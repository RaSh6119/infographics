"""Export the pages of a reference PDF as PNGs, leaving out the pages setup 2 shows the models.

    python scripts/export_reference_pages.py "data/ground_truth/R00 Infographics_English_CO.pdf" --out data/ground_truth/pages

Setup 2 includes three reference pages in every request (data/few_shot/). Scoring setup 2 against
those same pages would favour it, so any page that looks like one of them is skipped. The match is
by pixels (both shrunk to 64 x 64 greyscale), not by page number, so it doesn't depend on how the
PDF numbers its pages. Skipped pages are listed so they can be checked.

Needs pypdfium2. data/ground_truth/ is gitignored: the PDF and its pages aren't ours to publish.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographics.metrics.embedding import image_files, load_image, pad_to_square  # noqa: E402

THUMB = 64
MATCH_THRESHOLD = 0.06  # mean absolute difference (0-1) below which two pages count as the same


def thumbnail(image: Image.Image) -> np.ndarray:
    small = pad_to_square(image).convert("L").resize((THUMB, THUMB), Image.Resampling.LANCZOS)
    return np.asarray(small, dtype=np.float32) / 255


def difference(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exclude-like", type=Path, default=ROOT / "data" / "few_shot",
                        help="skip pages matching any image here (default: data/few_shot)")
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args()

    import pypdfium2 as pdfium

    excluded = {p.name: thumbnail(load_image(p)) for p in image_files(args.exclude_like)}
    args.out.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(args.pdf)
    kept, skipped = 0, []
    for index in range(len(pdf)):
        image = pdf[index].render(scale=args.dpi / 72).to_pil().convert("RGB")
        name = f"page_{index + 1:02d}.png"
        thumb = thumbnail(image)
        closest = min(((difference(thumb, t), n) for n, t in excluded.items()), default=(1.0, ""))
        if closest[0] < MATCH_THRESHOLD:
            skipped.append(f"{name} (matches {closest[1]}, difference {closest[0]:.3f})")
            continue
        image.save(args.out / name)
        kept += 1
        print(f"{name}  {image.width} x {image.height}  closest few-shot difference {closest[0]:.3f}")
    print(f"\nkept {kept} of {len(pdf)} pages in {args.out}")
    print("skipped:" if skipped else "skipped: none")
    for line in skipped:
        print(f"  {line}")
    if len(skipped) != len(excluded):
        print(f"WARNING: expected to skip {len(excluded)} pages, one per few-shot image. Check by eye.")


if __name__ == "__main__":
    main()
