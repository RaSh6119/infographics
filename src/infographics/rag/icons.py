"""The Health Icons database for setup 3.

Health Icons (healthicons.org, CC0) is cloned into data/icons/healthicons at a pinned commit.
build_index() turns its metadata and filled SVGs into one self-contained index file, so
retrieval and inlining never depend on the clone's layout.

Each icon draws with fill="currentColor", so a page recolours it with the CSS `color` property.

Health Icons has no general symbols such as clocks, arrows or a "no" sign, so 10 supplementary
icons from Google's Material Symbols (Apache 2.0, rounded, filled) are added in their own category,
"supplementary". They are generic, not chosen for particular prompts; their SVGs, licence and
notice are in data/icons/supplementary/.
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

SUPPLEMENTARY_DIR = ROOT / "data" / "icons" / "supplementary"
SUPPLEMENTARY_SOURCE = "https://github.com/google/material-design-icons"
SUPPLEMENTARY_COMMIT = "10ecc14790612ca8fd164e3f4ffe9c16fc50d5b7"
# (file in SUPPLEMENTARY_DIR, our id, title, tags). Material Symbols names in the file names.
SUPPLEMENTARY = [
    ("schedule.svg", "supplementary/clock", "Clock", ("Time", "Hours", "Clock", "Schedule")),
    ("hourglass_bottom.svg", "supplementary/hourglass", "Hourglass", ("Time", "Waiting", "Duration", "Timer")),
    ("alarm.svg", "supplementary/alarm-clock", "Alarm Clock", ("Urgent", "Reminder", "Time", "Alarm")),
    ("arrow_downward.svg", "supplementary/arrow-down", "Arrow Down", ("Decrease", "Lower", "Reduce", "Down")),
    ("arrow_upward.svg", "supplementary/arrow-up", "Arrow Up", ("Increase", "Higher", "Up")),
    ("arrow_forward.svg", "supplementary/arrow-right", "Arrow Right", ("Next", "Step", "Forward", "Then")),
    ("percent.svg", "supplementary/percent", "Percent", ("Percentage", "Rate", "Statistic")),
    ("block.svg", "supplementary/no-sign", "No Sign", ("No", "Not allowed", "Prohibited", "Avoid")),
    ("verified_user.svg", "supplementary/shield-check", "Shield with Checkmark", ("Protection", "Protected", "Safe")),
    ("event_available.svg", "supplementary/calendar-check", "Calendar with Checkmark", ("Appointment", "Scheduled", "Completed")),
]

# Tags like "dhis2:war" are IDs for another system, not words describing the icon.
_MACHINE_TAG = re.compile(r"^[a-z0-9]+:")


@dataclass(frozen=True)
class Icon:
    id: str  # "<category>/<name>", e.g. "contraceptives/male-condom"
    title: str
    category: str
    tags: tuple[str, ...]
    svg: str  # the full <svg> element with its viewBox
    source: str = "healthicons"  # or "material-symbols" for the supplementary icons

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


def supplementary_icons(directory: Path = SUPPLEMENTARY_DIR) -> list[Icon]:
    """The Material Symbols icons, made to draw in currentColor like Health Icons."""
    icons = []
    for file, icon_id, title, tags in SUPPLEMENTARY:
        markup = (directory / file).read_text(encoding="utf-8")
        markup = re.sub(r"<path\b(?![^>]*\bfill=)", '<path fill="currentColor"', markup)
        icons.append(Icon(id=icon_id, title=title, category="supplementary", tags=tags,
                          svg=clean_svg(markup), source="material-symbols"))
    return icons


def build_index(repo_dir: Path = REPO_DIR, supplementary_dir: Path | None = SUPPLEMENTARY_DIR) -> dict:
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
    if supplementary_dir is not None:
        icons += supplementary_icons(supplementary_dir)
    ids = [icon.id for icon in icons]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate icon ids in the icon index")
    return {
        "source": REPO_URL,
        "commit": COMMIT,
        "style": STYLE,
        "license": "CC0 1.0",
        "supplementary": None if supplementary_dir is None else {
            "source": SUPPLEMENTARY_SOURCE,
            "commit": SUPPLEMENTARY_COMMIT,
            "style": "Material Symbols Rounded, filled, 48px",
            "license": "Apache 2.0 (data/icons/supplementary/LICENSE)",
            "count": len(SUPPLEMENTARY),
        },
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
