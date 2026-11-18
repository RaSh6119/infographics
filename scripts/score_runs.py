"""Score harness runs on metric 4 (OCR text fidelity): one row per sample, plus a summary.

    python scripts/score_runs.py                       # every run in runs/<prompt set>/
    python scripts/score_runs.py runs/dev_set/s1_zero_shot__gpt-5.5__dev_set --out results/x.csv

Each sample is scored against the required text saved in its own record. A sample that did not
render (no HTML, render error, blank page, broken asset...) scores 0, as the plan specifies: that
is the official score.

The `as_rendered_*` columns are a diagnostic, not the official score: they OCR the screenshot even
when the render failed, if a screenshot exists. They show what a page's text looks like when the
only failure is, say, a font loaded from the web. No screenshot means 0 there too.
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

from infographics.metrics.ocr_text import OcrReader, score_image  # noqa: E402

COLUMNS = [
    "run", "setup", "model", "prompt_id", "type", "sample", "review_id", "render_ok", "failures",
    "text_fidelity", "word_recall", "phrase_recall",
    "as_rendered_text_fidelity", "as_rendered_word_recall", "as_rendered_phrase_recall",
    "missing", "misread", "ocr_text",
]
METRICS = ["text_fidelity", "word_recall", "phrase_recall"]


def score_run(run_dir: Path, reader: OcrReader) -> list[dict]:
    config = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["config"]
    rows = []
    for record_path in sorted(run_dir.glob("*/sample_*/record.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        prompt = record["prompt"]
        row = {
            "run": run_dir.name, "setup": config["setup"], "model": config["model"],
            "prompt_id": prompt["id"], "type": prompt["type"], "sample": record["sample"],
            "review_id": record["review_id"], "render_ok": record["render"]["ok"],
            "failures": "; ".join(f"{f['kind']}: {f['detail']}" for f in record["render"]["failures"]),
        }
        render = record["files"].get("render")
        screenshot = record_path.parent / render if render else None
        if screenshot and screenshot.exists():
            score, lines = score_image(screenshot, prompt["required_text"], reader)
            misread = [
                f"{m.word}->{m.matched or '(none)'}" for p in score.phrases for m in p.words if m.distance
            ]
            for key in METRICS:
                row[f"as_rendered_{key}"] = getattr(score, key)
            row.update(missing="; ".join(score.missing), misread="; ".join(misread),
                       ocr_text=" | ".join(line.text for line in lines))
        else:
            for key in METRICS:
                row[f"as_rendered_{key}"] = 0.0
            row.update(missing="(no screenshot)", misread="", ocr_text="")
        for key in METRICS:  # the official score: a failed render scores 0
            row[key] = row[f"as_rendered_{key}"] if row["render_ok"] else 0.0
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path, help="run folders (default: all of runs/<prompt set>/)")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "ocr_runs.csv")
    args = parser.parse_args()

    run_dirs = args.runs or sorted(p.parent for p in (ROOT / "runs").glob("*/*/run.json"))
    if not run_dirs:
        sys.exit("no runs found")

    reader = OcrReader()
    rows = []
    for run_dir in run_dirs:
        run_rows = score_run(run_dir, reader)
        rows += run_rows
        for row in run_rows:
            note = f"  missing: {row['missing']}" if row["missing"] else ""
            print(f"{row['phrase_recall']:5.2f}  {run_dir.name}/{row['prompt_id']}{note}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    groups = defaultdict(list)
    for row in rows:
        groups[(row["setup"], row["model"])].append(row)
    print("\nOfficial score (failed renders = 0), then the as-rendered diagnostic:")
    print(f"{'setup':<14}{'model':<18}{'n':>3}{'ok':>4}{'fidelity':>10}{'phrases':>9}{'all text':>10}"
          f"   |{'fidelity':>10}{'phrases':>9}{'all text':>10}")
    for (setup, model), group in sorted(groups.items()):
        mean = lambda key: statistics.mean(r[key] for r in group)  # noqa: E731
        complete = lambda key: sum(r[key] == 1.0 for r in group)  # noqa: E731
        ok = sum(r["render_ok"] for r in group)
        print(f"{setup:<14}{model:<18}{len(group):>3}{ok:>4}{mean('text_fidelity'):>10.3f}"
              f"{mean('phrase_recall'):>9.3f}{complete('phrase_recall'):>6}/{len(group)}"
              f"   |{mean('as_rendered_text_fidelity'):>10.3f}{mean('as_rendered_phrase_recall'):>9.3f}"
              f"{complete('as_rendered_phrase_recall'):>6}/{len(group)}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
