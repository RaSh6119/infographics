"""Setup 3 post-processing: replace icon placeholders with the real Health Icons SVGs.

Models place an icon by writing an empty element such as

    <svg data-icon="contraceptives/male-condom" width="96" height="96" style="color:#3576bc"></svg>

and this step swaps in the icon's paths and viewBox while keeping the model's own attributes (size,
position, class, style). Icons draw with fill="currentColor", so their colour comes from the CSS
`color` property; a `fill` attribute on the placeholder is turned into `color`, since that is what
models often write.

A placeholder naming an icon that does not exist is a broken asset, like a missing image, so the
page fails. Which icons were used, and which offered icons were not, is logged per page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from infographics.harness.renderer import Failure

from .icons import Icon

# <svg ... data-icon="ID" ...> ... </svg>, or the self-closing form <svg ... data-icon="ID" ... />
_PLACEHOLDER = re.compile(
    r"<svg\b(?P<attrs>[^>]*?\bdata-icon\s*=\s*(?P<q>[\"'])(?P<id>[^\"']*)(?P=q)[^>]*?)"
    r"(?:/>|>(?P<body>.*?)</svg\s*>)",
    flags=re.IGNORECASE | re.DOTALL,
)
_ATTR = re.compile(r"([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*')", flags=re.DOTALL)
_ICON_SVG = re.compile(r"<svg\b(?P<attrs>[^>]*)>(?P<body>.*)</svg>\s*$", flags=re.DOTALL)
# Attributes the icon itself defines; the model's values for these are dropped.
_ICON_OWNED = {"viewbox", "xmlns", "data-icon"}


@dataclass
class InlineResult:
    html: str
    used: list[str] = field(default_factory=list)  # in order of appearance, repeats kept
    unknown: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)

    def log(self, offered: list[str]) -> dict:
        used = list(dict.fromkeys(self.used))
        return {
            "icons_offered": len(offered),
            "icons_placed": len(self.used),
            "icons_used": used,
            "icons_offered_not_used": [i for i in offered if i not in used],
            "icons_used_not_offered": [i for i in used if i not in offered],
            "unknown_icon_ids": self.unknown,
        }


def _attrs(text: str) -> dict[str, str]:
    return {name: value[1:-1] for name, value in _ATTR.findall(text)}


def _with_color(attrs: dict[str, str]) -> dict[str, str]:
    """Move a fill colour to `color`, which is what currentColor icons follow."""
    fill = attrs.pop("fill", None)
    style = attrs.get("style", "")
    if fill and fill.lower() not in ("none", "currentcolor") and not re.search(r"(^|;)\s*color\s*:", style):
        attrs["style"] = f"color:{fill};{style}" if style else f"color:{fill}"
    return attrs


def _render_icon(icon: Icon, placeholder_attrs: dict[str, str]) -> str:
    match = _ICON_SVG.match(icon.svg)
    icon_attrs = _attrs(match.group("attrs"))
    merged = {k: v for k, v in placeholder_attrs.items() if k.lower() not in _ICON_OWNED}
    merged = _with_color(merged)
    merged["viewBox"] = icon_attrs["viewBox"]
    merged["xmlns"] = "http://www.w3.org/2000/svg"
    merged["data-icon"] = icon.id
    attr_text = " ".join(f'{k}="{v}"' for k, v in merged.items())
    return f"<svg {attr_text}>{match.group('body')}</svg>"


def inline_icons(html: str, icons: dict[str, Icon]) -> InlineResult:
    result = InlineResult(html=html)

    def replace(match: re.Match) -> str:
        icon_id = match.group("id").strip()
        icon = icons.get(icon_id)
        if icon is None:
            result.unknown.append(icon_id)
            return match.group(0)  # left empty: draws nothing
        result.used.append(icon_id)
        return _render_icon(icon, _attrs(match.group("attrs")))

    result.html = _PLACEHOLDER.sub(replace, html)
    for icon_id in dict.fromkeys(result.unknown):
        result.failures.append(Failure("broken_asset", f"unknown icon id {icon_id!r}"))
    return result
