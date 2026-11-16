"""Build the messages each setup sends to a model. Only these inputs differ between setups;
the system prompt, the prompts and everything after generation are shared.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from infographics.backends.base import Message
from infographics.harness.prompts import Prompt
from infographics.harness.renderer import Failure

ROOT = Path(__file__).resolve().parents[3]
SYSTEM_PROMPT_PATH = ROOT / "configs" / "system_prompt.md"
FEW_SHOT_DIR = ROOT / "data" / "few_shot"

# One reference page per type, as the plan asks: statistical, process and comparison.
FEW_SHOT_IMAGES = ["statistical_14E.png", "process_5E.png", "comparison_10E.png"]

FEW_SHOT_INTRO = (
    "These three reference infographics show the visual style to follow: how people, objects and "
    "symbols are drawn, and which colours are used for what. They are about HIV treatment, not "
    "prevention, so do not copy their text, topics or layouts."
)

Builder = Callable[[Prompt], list[Message]]


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def zero_shot(prompt: Prompt) -> list[Message]:
    return [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": prompt.prompt},
    ]


def few_shot(prompt: Prompt) -> list[Message]:
    paths = [FEW_SHOT_DIR / name for name in FEW_SHOT_IMAGES]
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"few-shot reference images missing from {FEW_SHOT_DIR}: {missing}. They are not in git; "
            "copy them over from the laptop."
        )
    content = [{"type": "text", "text": FEW_SHOT_INTRO}]
    content += [{"type": "image", "path": str(path)} for path in paths]
    content += [{"type": "text", "text": prompt.prompt}]
    return [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": content},
    ]


RAG_ICONS_INTRO = (
    "Icons you can use. These come from the Health Icons library. For each label below, choose the "
    "icon that fits it best; if none fits, draw your own symbol instead.\n"
    'To place an icon, write an empty element such as <svg data-icon="ICON_ID" width="96" height="96" '
    'style="color:#6283bb"></svg>: set its size and position as for any SVG, and its colour with the '
    "CSS color property. The icon's shapes are filled in automatically. Use only the icon IDs listed "
    "here."
)


@lru_cache(maxsize=1)
def _icons():
    from infographics.rag.icons import load_icons

    return load_icons()


@lru_cache(maxsize=1)
def _retrieved():
    from infographics.rag.retrieve import load_retrieved

    return load_retrieved()


def _candidates(prompt: Prompt) -> list[dict]:
    entries = _retrieved().get(prompt.id)
    if entries is None:
        raise FileNotFoundError(
            f"no icon retrieval for {prompt.id!r} in data/icons/retrieved_*.json. Run: "
            "python scripts/retrieve_icons.py --prompts <its prompt file>"
        )
    return entries


def rag_icons(prompt: Prompt) -> list[Message]:
    icons = _icons()
    lines = [RAG_ICONS_INTRO, ""]
    for entry in _candidates(prompt):
        label = prompt.required_text[entry["label_index"]]
        options = ", ".join(f"{c['id']} ({icons[c['id']].title})" for c in entry["icons"])
        lines.append(f"- {label}: {options}")
    return [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": f"{prompt.prompt}\n\n" + "\n".join(lines)},
    ]


def offered_icons(prompt: Prompt) -> list[str]:
    return list(dict.fromkeys(c["id"] for e in _candidates(prompt) for c in e["icons"]))


def rag_icons_postprocess(prompt: Prompt, html: str) -> tuple[str, dict[str, Any], list[Failure]]:
    """Swap icon placeholders for the real SVGs before rendering; log which icons were used."""
    from infographics.rag.inline import inline_icons

    result = inline_icons(html, _icons())
    return result.html, result.log(offered_icons(prompt)), result.failures


SETUPS: dict[str, Builder] = {
    "s1_zero_shot": zero_shot,
    "s2_few_shot": few_shot,
    "s3_rag_icons": rag_icons,
}

# Steps applied to the extracted HTML before rendering, for setups that need one.
Postprocessor = Callable[[Prompt, str], tuple[str, dict[str, Any], list[Failure]]]
POSTPROCESSORS: dict[str, Postprocessor] = {
    "s3_rag_icons": rag_icons_postprocess,
}
