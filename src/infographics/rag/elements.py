"""Setup 3b's icon set: the project's own illustration elements, in the reference pages' style.

The elements are PNG images in data/icons/Elements/ (made for this project; the folder is not in
git). configs/elements_catalog.yaml describes each one for retrieval and lists the files left out
(pictures of text, and two that are not icons).

Each PNG becomes an Icon whose `svg` wraps the image as an embedded data URI:

    <svg viewBox="0 0 W H" xmlns=...><image href="data:image/png;base64,..." width="W" height="H"/></svg>

so the setup 3 placeholder and inlining step (rag/inline.py) places elements exactly as it places
Health Icons, and the page stays self-contained. Unlike Health Icons, elements keep their own
colours: the CSS `color` property does not change them.
"""

from __future__ import annotations

import base64
import io
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import yaml
from PIL import Image

from .icons import ROOT, Icon

ELEMENTS_DIR = ROOT / "data" / "icons" / "Elements"
CATALOG_PATH = ROOT / "configs" / "elements_catalog.yaml"
ELEMENTS_INDEX_PATH = ROOT / "data" / "icons" / "elements_index.json"  # gitignored, like the PNGs
ID_PREFIX = "elements/"
SOURCE = "project-elements"
NO_SIGN_ID = "elements/no-sign"


def element_id(file_name: str) -> str:
    """icon_pill-organizer.png -> elements/pill-organizer; structure_drop.png -> elements/drop."""
    stem = Path(file_name).stem
    for prefix in ("icon_", "structure_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    return ID_PREFIX + stem.replace("_", "-").lower()


def load_catalog(path: Path = CATALOG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def png_svg(png: bytes) -> str:
    """An <svg> that shows the PNG at its own aspect ratio."""
    with Image.open(io.BytesIO(png)) as image:
        width, height = image.size
    data = base64.b64encode(png).decode("ascii")
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<image href="data:image/png;base64,{data}" width="{width}" height="{height}"/></svg>'
    )


def check_catalog(catalog: dict, files: list[str]) -> None:
    """Every PNG in the folder is either catalogued or excluded, and nothing listed is missing."""
    listed = [entry["file"] for entry in catalog["elements"]]
    excluded = list(catalog.get("excluded", []))
    text = [f for f in files if f.startswith("text_")]
    problems = []
    if len(listed) != len(set(listed)):
        problems.append("a file is listed twice")
    missing = sorted(set(listed + excluded) - set(files))
    if missing:
        problems.append(f"listed but not in the folder: {missing}")
    unlisted = sorted(set(files) - set(listed) - set(excluded) - set(text))
    if unlisted:
        problems.append(f"in the folder but not in the catalog (add or exclude them): {unlisted}")
    ids = [element_id(f) for f in listed]
    if len(ids) != len(set(ids)):
        problems.append("two files map to the same element id")
    if problems:
        raise ValueError("configs/elements_catalog.yaml: " + "; ".join(problems))


def build_elements_index(directory: Path = ELEMENTS_DIR, catalog_path: Path = CATALOG_PATH) -> dict:
    catalog = load_catalog(catalog_path)
    files = sorted(p.name for p in directory.glob("*.png"))
    check_catalog(catalog, files)
    icons, digests = [], {}
    for entry in catalog["elements"]:
        png = (directory / entry["file"]).read_bytes()
        digests[entry["file"]] = hashlib.sha256(png).hexdigest()
        icons.append(Icon(
            id=element_id(entry["file"]),
            title=entry["title"],
            category=entry["category"],
            tags=tuple(entry.get("tags", [])),
            svg=png_svg(png),
            source=SOURCE,
        ))
    # One hash over every file's hash: changes if any element image changes.
    folder_hash = hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    return {
        "source": "data/icons/Elements (made for this project)",
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "elements_sha256": folder_hash,
        "files": digests,
        "icons": [asdict(icon) for icon in icons],
    }


def load_elements(index_path: Path = ELEMENTS_INDEX_PATH) -> dict[str, Icon]:
    if not index_path.exists():
        raise FileNotFoundError(f"{index_path} is missing. Run: python scripts/build_elements_index.py")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return {e["id"]: Icon(**{**e, "tags": tuple(e["tags"])}) for e in data["icons"]}


def elements_hash(index_path: Path = ELEMENTS_INDEX_PATH) -> str:
    return json.loads(index_path.read_text(encoding="utf-8"))["elements_sha256"]
