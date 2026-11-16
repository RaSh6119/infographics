"""Build data/icons/index.json, setup 3's icon database, from the Health Icons clone.

One-time setup (the clone is not in git):

    git clone https://github.com/resolvetosavelives/healthicons.git data/icons/healthicons
    git -C data/icons/healthicons checkout 2080c1b40e4829f2f4217e03bc22908b4e402f6b
    python scripts/build_icon_index.py
"""

from __future__ import annotations

import collections
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographics.rag.icons import COMMIT, INDEX_PATH, REPO_DIR, build_index  # noqa: E402


def main() -> None:
    head = subprocess.run(
        ["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if head != COMMIT:
        sys.exit(f"{REPO_DIR} is at {head or 'no commit'}, expected {COMMIT}. See this file's docstring.")

    index = build_index()
    INDEX_PATH.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = collections.Counter(icon["category"] for icon in index["icons"])
    print(f"Wrote {len(index['icons'])} icons to {INDEX_PATH.relative_to(ROOT)}")
    print(", ".join(f"{name} {n}" for name, n in counts.most_common()))


if __name__ == "__main__":
    main()
