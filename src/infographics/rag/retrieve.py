"""Setup 3 retrieval: candidate Health Icons for each label of a prompt.

Each label (a required phrase other than the title) becomes a search query: the label's own words
plus any glossary expansions (configs/icon_glossary.yaml). A small text-embedding model compares
the query with every icon's title and tags, and the label keeps its best few icons. With 15 icons
in total, a prompt with 5 labels gets 3 per label, one with 8 labels gets 1 per label, and so on.

Retrieval runs once per prompt set, before any model is called, and is saved to a file
(scripts/retrieve_icons.py), so every model gets exactly the same candidates. The saved file holds
label positions, glossary terms and icon IDs only, never the label text, so a file for a private
prompt set holds none of its text.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from infographics.harness.prompts import Prompt

from .icons import COMMIT as ICON_INDEX_COMMIT
from .icons import ROOT, Icon

ELEMENTS_CATALOG_PATH = ROOT / "configs" / "elements_catalog.yaml"

GLOSSARY_PATH = ROOT / "configs" / "icon_glossary.yaml"
RETRIEVED_DIR = ROOT / "data" / "icons"
TOTAL_ICONS = 15
MAX_PER_LABEL = 3
# Typography icons are letters and digits; the page's text already covers those.
EXCLUDED_CATEGORIES = {"typography"}

# A negated label ("Don't share needles", "No daily pills") needs both the object and a "no" sign,
# so the object is searched for without the negating word and the "no" sign is added on top.
NEGATIONS = re.compile(r"\b(no|not|don't|do not|never|avoid)\b\s*", flags=re.IGNORECASE)
NO_SIGN_ID = "supplementary/no-sign"

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"  # pinned, so retrieval is reproducible

# Takes texts, returns one unit-length vector per text (rows of a 2-D array).
Embedder = Callable[[Sequence[str]], np.ndarray]


@dataclass(frozen=True)
class Candidate:
    icon_id: str
    score: float


def load_glossary(path: Path = GLOSSARY_PATH) -> dict[str, list[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(term): [w.strip() for w in str(words).split(",") if w.strip()] for term, words in raw.items()}


def glossary_terms(label: str, glossary: dict[str, list[str]]) -> list[str]:
    """Expansion words for every glossary term that appears in the label as a whole word."""
    terms: list[str] = []
    for term, words in glossary.items():
        if re.search(rf"(?<![\w=]){re.escape(term)}(?![\w=])", label, flags=re.IGNORECASE):
            terms += [w for w in words if w not in terms]
    return terms


def title_of(prompt: Prompt) -> str | None:
    match = re.search(r"^Title: (.*)$", prompt.prompt, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def labels_of(prompt: Prompt) -> list[tuple[int, str]]:
    """(position in required_text, phrase) for every required phrase except the title."""
    title = title_of(prompt)
    return [(i, text) for i, text in enumerate(prompt.required_text) if text != title]


def per_label(n_labels: int, total: int = TOTAL_ICONS, cap: int = MAX_PER_LABEL) -> int:
    return max(1, min(cap, total // max(n_labels, 1)))


def sentence_transformer_embedder(
    model_name: str = EMBEDDING_MODEL, revision: str = EMBEDDING_REVISION
) -> tuple[Embedder, dict]:
    """The real embedder, plus what to record about it (model, exact revision, library version)."""
    import sentence_transformers
    from huggingface_hub import snapshot_download

    path = Path(snapshot_download(model_name, revision=revision))
    model = sentence_transformers.SentenceTransformer(str(path), device="cpu")

    def embed(texts: Sequence[str]) -> np.ndarray:
        return model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)

    info = {"model": model_name, "revision": path.name,
            "sentence_transformers": sentence_transformers.__version__}
    return embed, info


def retrieve(
    prompts: Sequence[Prompt],
    icons: dict[str, Icon],
    embed: Embedder,
    glossary: dict[str, list[str]],
) -> dict[str, list[dict]]:
    """For each prompt: one entry per label with its glossary terms and candidate icons."""
    pool = [icon for icon in icons.values() if icon.category not in EXCLUDED_CATEGORIES]
    # The category helps icons with thin titles, e.g. "Pill 1" becomes "Pill 1, ..., medications".
    icon_vectors = embed([f"{icon.description()}, {icon.category}" for icon in pool])
    has_no_sign = any(icon.id == NO_SIGN_ID for icon in pool)
    results: dict[str, list[dict]] = {}
    for prompt in prompts:
        labels = labels_of(prompt)
        negated = {position for position, label in labels if has_no_sign and NEGATIONS.search(label)}
        # Each negated label's extra "no" sign counts toward the total of 15.
        k = per_label(len(labels) + len(negated))
        entries = []
        for position, label in labels:
            searched = NEGATIONS.sub("", label).strip() if position in negated else label
            terms = glossary_terms(searched, glossary)
            query = ", ".join([searched, *terms])
            scores = icon_vectors @ embed([query])[0]
            best = [i for i in np.argsort(-scores) if pool[i].id != NO_SIGN_ID][:k]
            icons_for_label = [{"id": pool[i].id, "score": round(float(scores[i]), 4)} for i in best]
            if position in negated:
                icons_for_label.append({"id": NO_SIGN_ID, "score": None})
            entries.append({
                "label_index": position,
                "negated": position in negated,
                "glossary_terms": terms,
                "icons": icons_for_label,
            })
        results[prompt.id] = entries
    return results


def retrieved_path(prompts_file: str | Path) -> Path:
    return RETRIEVED_DIR / f"retrieved_{Path(prompts_file).stem}.json"


def build_record(prompts_file: str | Path, results: dict, embedder_info: dict) -> dict:
    return {
        "prompts_file": Path(prompts_file).name,
        "embedding": embedder_info,
        "icon_index_commit": ICON_INDEX_COMMIT,
        "glossary_sha256": hashlib.sha256(GLOSSARY_PATH.read_bytes()).hexdigest(),
        "total_icons": TOTAL_ICONS,
        "max_per_label": MAX_PER_LABEL,
        "excluded_categories": sorted(EXCLUDED_CATEGORIES),
        "prompts": results,
    }


def load_retrieved(directory: Path = RETRIEVED_DIR) -> dict[str, list[dict]]:
    """Candidates for every prompt with saved retrieval, keyed by prompt id."""
    merged: dict[str, list[dict]] = {}
    for path in sorted(directory.glob("retrieved_*.json")):
        merged.update(json.loads(path.read_text(encoding="utf-8"))["prompts"])
    return merged


# --- Setup 3b: the project's elements first, Health Icons for what they don't cover -------------

# An element is offered for a label only if it matches at least ELEMENTS_MIN_SCORE (cosine
# similarity, same embedding model) AND comes within ELEMENTS_MARGIN of the label's best Health
# Icon. Elements win ties and near-ties, but never displace a clearly better Health Icon: on the dev
# set a fixed cut-off alone let a virus (0.76) beat the condom (0.85) for "Sex", because wrong
# elements scored 0.72-0.81, about the same as good ones. Both values were set on the dev set only
# and FROZEN 2026-11-18, with configs/elements_catalog.yaml, before any clinic retrieval. Do not
# tune them on other prompt sets; a change is a new version and means rerunning setup 3b.
# Known weak dev retrievals, left as they are rather than fitted to single phrases: "Injectable
# PrEP" gets the empty pill bottle (the glossary adds pill words to any PrEP label), and "Given
# in clinic" gets the plain person figure.
ELEMENTS_MIN_SCORE = 0.70
ELEMENTS_MARGIN = 0.02


def _query(label: str, negated: bool, glossary: dict[str, list[str]]) -> tuple[str, list[str]]:
    searched = NEGATIONS.sub("", label).strip() if negated else label
    terms = glossary_terms(searched, glossary)
    return ", ".join([searched, *terms]), terms


def retrieve_elements_first(
    prompts: Sequence[Prompt],
    elements: dict[str, Icon],
    fallback: dict[str, Icon],
    embed: Embedder,
    glossary: dict[str, list[str]],
    no_sign_id: str,
    min_score: float = ELEMENTS_MIN_SCORE,
    margin: float = ELEMENTS_MARGIN,
) -> dict[str, list[dict]]:
    """Like retrieve(), but each label's slots go first to elements scoring at least `min_score`
    and within `margin` of the label's best Health Icon, best first; slots left over go to the best
    Health Icons. A negated label gets the elements' "no" sign on top, as in setup 3."""
    element_pool = [icon for icon in elements.values() if icon.id != no_sign_id]
    fallback_pool = [icon for icon in fallback.values()
                     if icon.category not in EXCLUDED_CATEGORIES and icon.id != NO_SIGN_ID]
    describe = lambda icon: f"{icon.description()}, {icon.category}"  # noqa: E731
    element_vectors = embed([describe(icon) for icon in element_pool])
    fallback_vectors = embed([describe(icon) for icon in fallback_pool])
    has_no_sign = no_sign_id in elements
    results: dict[str, list[dict]] = {}
    for prompt in prompts:
        labels = labels_of(prompt)
        negated = {position for position, label in labels if has_no_sign and NEGATIONS.search(label)}
        k = per_label(len(labels) + len(negated))
        entries = []
        for position, label in labels:
            query, terms = _query(label, position in negated, glossary)
            vector = embed([query])[0]
            element_scores = element_vectors @ vector
            fallback_scores = fallback_vectors @ vector
            floor = max(min_score, float(fallback_scores.max()) - margin)
            chosen = [{"id": element_pool[i].id, "score": round(float(element_scores[i]), 4)}
                      for i in np.argsort(-element_scores) if element_scores[i] >= floor][:k]
            chosen += [{"id": fallback_pool[i].id, "score": round(float(fallback_scores[i]), 4)}
                       for i in np.argsort(-fallback_scores)[: k - len(chosen)]]
            if position in negated:
                chosen.append({"id": no_sign_id, "score": None})
            entries.append({
                "label_index": position,
                "negated": position in negated,
                "glossary_terms": terms,
                "icons": chosen,
            })
        results[prompt.id] = entries
    return results


def elements_retrieved_path(prompts_file: str | Path) -> Path:
    # Not "retrieved_*.json": load_retrieved() must not pick these up for setup 3.
    return RETRIEVED_DIR / f"elements_retrieved_{Path(prompts_file).stem}.json"


def build_elements_record(prompts_file: str | Path, results: dict, embedder_info: dict,
                          elements_sha256: str, min_score: float = ELEMENTS_MIN_SCORE,
                          margin: float = ELEMENTS_MARGIN) -> dict:
    record = build_record(prompts_file, results, embedder_info)
    record.update(setup="s3b_rag_elements", elements_sha256=elements_sha256,
                  elements_min_score=min_score, elements_margin=margin,
                  elements_catalog_sha256=hashlib.sha256(ELEMENTS_CATALOG_PATH.read_bytes()).hexdigest())
    return record


def load_elements_retrieved(directory: Path = RETRIEVED_DIR) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    for path in sorted(directory.glob("elements_retrieved_*.json")):
        merged.update(json.loads(path.read_text(encoding="utf-8"))["prompts"])
    return merged
