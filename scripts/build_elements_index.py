"""Setup 3b: build data/icons/elements_index.json from the PNGs in data/icons/Elements/.

    python scripts/build_elements_index.py

Reads configs/elements_catalog.yaml for each element's title, tags and category, and fails if a PNG
in the folder is neither catalogued nor excluded there. The index embeds the images, so it is
gitignored like the folder; it records a hash of every image so runs can be traced to the exact set.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographics.rag.elements import ELEMENTS_INDEX_PATH, build_elements_index  # noqa: E402


def main() -> None:
    index = build_elements_index()
    ELEMENTS_INDEX_PATH.write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    categories = Counter(icon["category"] for icon in index["icons"])
    print(f"{len(index['icons'])} elements: " + ", ".join(f"{c} {n}" for c, n in sorted(categories.items())))
    print(f"elements hash {index['elements_sha256'][:12]}")
    print(f"wrote {ELEMENTS_INDEX_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
