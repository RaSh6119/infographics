"""The Health Icons database for setup 3.

Health Icons (healthicons.org, CC0) is cloned into data/icons/healthicons at a pinned commit.
build_index() turns its metadata and filled SVGs into one self-contained index file, so
retrieval and inlining never depend on the clone's layout.

Each icon draws with fill="currentColor", so a page recolours it with the CSS `color` property.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPO_DIR = ROOT / "data" / "icons" / "healthicons"
INDEX_PATH = ROOT / "data" / "icons" / "index.json"
REPO_URL = "https://github.com/resolvetosavelives/healthicons"
COMMIT = "2080c1b40e4829f2f4217e03bc22908b4e402f6b"
STYLE = "filled"  # solid shapes, like the reference PDF; the library also has "outline"

# Tags like "dhis2:war" are IDs for another system, not words describing the icon.
_MACHINE_TAG = re.compile(r"^[a-z0-9]+:")


@dataclass(frozen=True)
class Icon:
    id: str  # "<category>/<name>", e.g. "contraceptives/male-condom"
    title: str
    category: str
    tags: tuple[str, ...]
    svg: str  # the full <svg> element, 48 x 48 viewBox

    def description(self) -> str:
        """What retrieval matches against: the title plus its tags."""
        return ", ".join(dict.fromkeys([self.title, *self.tags]))


def clean_svg(markup: str) -> str:
    """Drop the fixed 48 px size so the page can size the icon; keep the viewBox."""
    markup = markup.strip()
    if not markup.startswith("<svg") or 'viewBox="' not in markup:
        raise ValueError("not a single <svg> element with a viewBox")
    head, rest = markup.split(">", 1)
    head = re.sub(r'\s(width|height)="[^"]*"', "", head)
    return re.sub(r"\s+", " ", f"{head}>{rest}").replace("> <", "><")


def build_index(repo_dir: Path = REPO_DIR) -> dict:
    icons_dir = repo_dir / "public" / "icons"
    metadata = json.loads((icons_dir / "meta-data.json").read_text(encoding="utf-8"))
    icons = []
    for entry in sorted(metadata, key=lambda e: e["path"]):
        svg_file = icons_dir / "svg" / STYLE / f"{entry['path']}.svg"
        tags = tuple(t for t in entry["tags"] if not _MACHINE_TAG.match(t))
        icons.append(Icon(
            id=entry["path"],
            title=entry["title"],
            category=entry["category"],
            tags=tags,
            svg=clean_svg(svg_file.read_text(encoding="utf-8")),
        ))
    ids = [icon.id for icon in icons]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate icon ids in the Health Icons metadata")
    return {
        "source": REPO_URL,
        "commit": COMMIT,
        "style": STYLE,
        "license": "CC0 1.0",
        "icons": [asdict(icon) for icon in icons],
    }


def load_icons(index_path: Path = INDEX_PATH) -> dict[str, Icon]:
    if not index_path.exists():
        raise FileNotFoundError(
            f"{index_path} is missing. Run: python scripts/build_icon_index.py"
        )
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        entry["id"]: Icon(**{**entry, "tags": tuple(entry["tags"])}) for entry in data["icons"]
    }
