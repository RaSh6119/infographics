"""Build the messages each setup sends to a model. Only these inputs differ between setups;
the system prompt, the prompts and everything after generation are shared.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from infographics.backends.base import Message
from infographics.harness.prompts import Prompt

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


SETUPS: dict[str, Builder] = {
    "s1_zero_shot": zero_shot,
    "s2_few_shot": few_shot,
}
