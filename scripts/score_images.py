"""Score a folder of finished images on metric 4 (OCR text fidelity), for images made outside the
harness, such as ones generated through chat apps.

    python scripts/score_images.py data/images_test --required-file data/images_test/required.txt \
        --out results/images_test_ocr.csv

The required-text file holds one phrase per line. Images are found in all subfolders.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from infographics.metrics.ocr_text import OcrReader, score_image  # noqa: E402

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--required-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    required = [line.strip() for line in args.required_file.read_text(encoding="utf-8").splitlines()]
    required = [line for line in required if line]
    images = sorted(p for p in args.folder.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        sys.exit(f"no images found in {args.folder}")

    reader = OcrReader()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["image", "text_fidelity", "word_recall", "phrase_recall", "missing", "misread", "ocr_text"]
        )
        for image in images:
            score, lines = score_image(image, required, reader)
            misread = [
                f"{m.word}->{m.matched or '(none)'}" for p in score.phrases for m in p.words if m.distance
            ]
            name = image.relative_to(args.folder).as_posix()
            writer.writerow(
                [
                    name,
                    score.text_fidelity,
                    score.word_recall,
                    score.phrase_recall,
                    "; ".join(score.missing),
                    "; ".join(misread),
                    " | ".join(line.text for line in lines),
                ]
            )
            print(f"{score.phrase_recall:5.2f}  {name}  {'; '.join(misread)}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
