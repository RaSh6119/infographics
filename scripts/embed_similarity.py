"""Score rendered pages by embedding similarity to a folder of reference (ground-truth) images.

    python scripts/embed_similarity.py --refs data/ground_truth/pages --out results/embed_dev_set.csv runs/dev_set/*
    python scripts/embed_similarity.py --refs data/ground_truth/pages                  # every run in runs/<prompt set>/
    python scripts/embed_similarity.py --refs DIR --pairs data/ground_truth/pairs.csv   # also compare each page with its own reference
    python scripts/embed_similarity.py --refs DIR --prompt-ids clinic_list_001 runs/clinic_set/*  # one prompt only
    python scripts/embed_similarity.py --resolve-revisions                              # print the commits to pin (contacts Hugging Face)

For each page and each embedding model (SigLIP 2, DINOv2), three numbers:
    <model>_best      similarity to the closest reference
    <model>_mean      mean similarity to all references
    <model>_best_ref  which reference was closest
and, with --pairs, <model>_paired: similarity to the reference listed for the page's prompt_id.
The pairs file is a CSV with columns prompt_id,reference (a file name inside --refs).

Like OCR scoring, the plain columns are the official score: a page that failed to render scores 0.
The as_rendered_* columns score the screenshot anyway, as a diagnostic.

Reference images named in --exclude (or matching a setup 2 few-shot page, see
scripts/export_reference_pages.py) must not be in --refs: scoring setup 2 against the pages it was
shown would favour it.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographics.metrics.embedding import (  # noqa: E402
    EMBEDDERS,
    compare,
    hf_embedder,
    image_files,
    load_image,
    paired,
)

BASE_COLUMNS = ["run", "setup", "model", "prompt_id", "type", "sample", "review_id", "render_ok", "failures"]


def find_pages(run_dirs: list[Path]) -> list[dict]:
    """Every sample in the given runs, with its screenshot path (None if there is none)."""
    pages = []
    for run_dir in run_dirs:
        config = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["config"]
        for record_path in sorted(run_dir.glob("*/sample_*/record.json")):
            record = json.loads(record_path.read_text(encoding="utf-8"))
            render = record["files"].get("render")
            screenshot = record_path.parent / render if render else None
            pages.append({
                "run": run_dir.name, "setup": config["setup"], "model": config["model"],
                "prompt_id": record["prompt"]["id"], "type": record["prompt"]["type"],
                "sample": record["sample"], "review_id": record["review_id"],
                "render_ok": record["render"]["ok"],
                "failures": "; ".join(f"{f['kind']}: {f['detail']}" for f in record["render"]["failures"]),
                "_screenshot": screenshot if screenshot and screenshot.exists() else None,
            })
    return pages


def load_pairs(path: Path, ref_names: list[str]) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as file:
        pairs = {row["prompt_id"]: row["reference"] for row in csv.DictReader(file)}
    unknown = sorted(set(pairs.values()) - set(ref_names))
    if unknown:
        sys.exit(f"--pairs names references not in --refs: {', '.join(unknown)}")
    return pairs


def score(pages: list[dict], ref_paths: list[Path], embedders: dict, pairs: dict[str, str] | None) -> list[str]:
    """Add score columns to each page in place. Returns the score column names."""
    ref_names = [p.name for p in ref_paths]
    ref_images = [load_image(p) for p in ref_paths]
    shown = [page for page in pages if page["_screenshot"]]
    shown_images = [load_image(page["_screenshot"]) for page in shown]
    columns = []
    for name, embed in embedders.items():
        metrics = ["best", "mean"] + (["paired"] if pairs else [])
        columns += [f"{name}_{m}" for m in metrics] + [f"{name}_best_ref"]
        columns += [f"as_rendered_{name}_{m}" for m in metrics]
        refs = embed(ref_images)
        generated = embed(shown_images) if shown_images else refs[:0]
        for page, match, vector in zip(shown, compare(generated, refs, ref_names), generated):
            page[f"as_rendered_{name}_best"] = match.best
            page[f"as_rendered_{name}_mean"] = match.mean
            page[f"{name}_best_ref"] = match.best_ref
            if pairs:
                ref = pairs.get(page["prompt_id"])
                page[f"as_rendered_{name}_paired"] = (
                    float(paired(vector[None], refs[ref_names.index(ref)][None])[0]) if ref else ""
                )
        for page in pages:
            for m in metrics:
                key = f"as_rendered_{name}_{m}"
                page.setdefault(key, 0.0)  # no screenshot scores 0
                page.setdefault(f"{name}_best_ref", "")
                value = page[key]
                page[f"{name}_{m}"] = value if (page["render_ok"] or value == "") else 0.0
    return columns


def resolve_revisions() -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    for spec in EMBEDDERS.values():
        print(f"{spec.name}: {spec.repo} @ {api.model_info(spec.repo).sha}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path, help="run folders (default: all of runs/<prompt set>/)")
    parser.add_argument("--refs", type=Path, help="folder of reference images")
    parser.add_argument("--pairs", type=Path, help="CSV prompt_id,reference for paired scores")
    parser.add_argument("--prompt-ids", help="score only these prompts, comma-separated (default: all)")
    parser.add_argument("--models", default=",".join(EMBEDDERS), help="embedding models (default: all)")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "embed_similarity.csv")
    parser.add_argument("--resolve-revisions", action="store_true", help="print the commits to pin, then exit")
    args = parser.parse_args()

    if args.resolve_revisions:
        return resolve_revisions()
    if not args.refs:
        parser.error("--refs is required")
    ref_paths = image_files(args.refs)
    if not ref_paths:
        sys.exit(f"no images in {args.refs}")
    pairs = load_pairs(args.pairs, [p.name for p in ref_paths]) if args.pairs else None
    run_dirs = args.runs or sorted(p.parent for p in (ROOT / "runs").glob("*/*/run.json"))
    pages = find_pages([d for d in run_dirs if (d / "run.json").exists()])
    if args.prompt_ids:
        wanted = set(args.prompt_ids.split(","))
        pages = [p for p in pages if p["prompt_id"] in wanted]
    if not pages:
        sys.exit("no runs found")

    names = args.models.split(",")
    unknown = sorted(set(names) - set(EMBEDDERS))
    if unknown:
        sys.exit(f"unknown models: {', '.join(unknown)} (known: {', '.join(EMBEDDERS)})")
    embedders = {name: hf_embedder(EMBEDDERS[name]) for name in names}
    print(f"{len(pages)} pages, {len(ref_paths)} references, models: {', '.join(names)}")
    columns = score(pages, ref_paths, embedders, pairs)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=BASE_COLUMNS + columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pages)

    groups = defaultdict(list)
    for page in pages:
        groups[(page["setup"], page["model"])].append(page)
    print("\nMean best-match similarity. Official (failed renders = 0) | as rendered:")
    header = "".join(f"{n:>18}" for n in names)
    print(f"{'setup':<14}{'model':<18}{'n':>3}{'ok':>4}{header}   |{header}")
    for (setup, model), group in sorted(groups.items()):
        ok = sum(p["render_ok"] for p in group)
        official = "".join(f"{statistics.mean(p[f'{n}_best'] for p in group):>18.3f}" for n in names)
        rendered = "".join(f"{statistics.mean(p[f'as_rendered_{n}_best'] for p in group):>18.3f}" for n in names)
        print(f"{setup:<14}{model:<18}{len(group):>3}{ok:>4}{official}   |{rendered}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
