"""Embedding similarity: how close is a generated page to the reference (ground-truth) pages?

Each image becomes a vector from a pretrained image model; similarity is the cosine of two vectors
(1 = same direction). Two models, because they notice different things:

    siglip   SigLIP 2, trained on images with captions: overall content and look
    dinov2   DINOv2, trained on images alone: layout, shapes and visual style

Nothing is trained here. Both models are pinned to exact Hugging Face revisions, so the scores are
reproducible.

Every image is padded to a white square before embedding, never cropped or stretched. Pages come in
different shapes (the renders are 1536 x 1024 or taller when text overflows; references may be
portrait), and the models' own preprocessing would otherwise cut off the page edges or distort it.

Scores are cosine similarities, not percentages. They are only meaningful relative to each other,
within one embedding model: a SigLIP score of 0.8 and a DINOv2 score of 0.8 do not mean the same.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PLACEHOLDER = "FILL_IN"


@dataclass(frozen=True)
class EmbedderSpec:
    name: str
    repo: str
    revision: str
    size: int  # square input side in pixels


# Pinned 2026-11-18 (from scripts/embed_similarity.py --resolve-revisions). Never change them
# mid-experiment: scores from different revisions are not comparable.
EMBEDDERS = {
    "siglip": EmbedderSpec("siglip", "google/siglip2-base-patch16-512", "a89f5c5093f902bf39d3cd4d81d2c09867f0724b", 512),
    "dinov2": EmbedderSpec("dinov2", "facebook/dinov2-base", "f9e44c814b77203eaa57a6bdbbd535f21ede1415", 448),
}

# A function from a list of images to an (n, d) array. Tests pass a fake one.
Embedder = Callable[[Sequence[Image.Image]], np.ndarray]


def pad_to_square(image: Image.Image, fill=(255, 255, 255)) -> Image.Image:
    """The image centred on a white square, with transparency flattened onto white."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, fill)
        flat.paste(rgba, mask=rgba.split()[-1])
        image = flat
    else:
        image = image.convert("RGB")
    side = max(image.size)
    square = Image.new("RGB", (side, side), fill)
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return square


def normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def hf_embedder(spec: EmbedderSpec, device: str | None = None, batch_size: int = 8) -> Embedder:
    """Load a pinned model from Hugging Face. Downloads it on first use (SigLIP ~1.5 GB, DINOv2 ~350 MB)."""
    if spec.revision == PLACEHOLDER:
        raise ValueError(
            f"{spec.name}: no pinned revision yet. Run scripts/embed_similarity.py --resolve-revisions "
            f"and copy the commit into EMBEDDERS in {Path(__file__).name}."
        )
    import torch
    from transformers import AutoImageProcessor, AutoModel

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model = AutoModel.from_pretrained(spec.repo, revision=spec.revision).to(device).eval()
    processor = AutoImageProcessor.from_pretrained(spec.repo, revision=spec.revision)
    # Images arrive square, so resize straight to the model's size; no centre crop.
    options = {"size": {"height": spec.size, "width": spec.size}}
    if spec.name == "dinov2":
        options["do_center_crop"] = False

    @torch.no_grad()
    def embed(images: Sequence[Image.Image]) -> np.ndarray:
        out = []
        for start in range(0, len(images), batch_size):
            batch = [pad_to_square(image) for image in images[start : start + batch_size]]
            pixels = processor(images=batch, return_tensors="pt", **options)["pixel_values"].to(device)
            if spec.name == "siglip":
                features = model.get_image_features(pixel_values=pixels)
                features = getattr(features, "pooler_output", features)
            else:  # DINOv2: the layer-normed CLS token
                features = model(pixel_values=pixels).pooler_output
            out.append(features.float().cpu().numpy())
        return normalize(np.concatenate(out)) if out else np.zeros((0, 0), np.float32)

    return embed


def image_files(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        image.load()
        return image


@dataclass
class Match:
    best: float  # similarity to the closest reference
    mean: float  # mean similarity to all references
    best_ref: str  # name of the closest reference


def compare(generated: np.ndarray, references: np.ndarray, ref_names: Sequence[str]) -> list[Match]:
    """One Match per generated vector. Both inputs must already be normalized."""
    sims = generated @ references.T
    return [
        Match(best=float(row.max()), mean=float(row.mean()), best_ref=ref_names[int(row.argmax())])
        for row in sims
    ]


def paired(generated: np.ndarray, references: np.ndarray) -> np.ndarray:
    """Similarity of each generated vector to its own reference (row i with row i)."""
    return np.sum(generated * references, axis=1)
