"""Load and validate a prompt set stored as JSON Lines.

Each line holds: id, type, prompt, required_text. A bad file stops the run here, with the line
number, rather than producing results that have to be thrown away later.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

INFOGRAPHIC_TYPES = {"statistical", "timeline", "process", "comparison", "list"}
REQUIRED_FIELDS = {"id", "type", "prompt", "required_text"}
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")  # ids become folder names


@dataclass(frozen=True)
class Prompt:
    id: str
    type: str
    prompt: str
    required_text: tuple[str, ...]


def _parse_line(line: str, where: str) -> Prompt:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(f"{where}: not valid JSON ({error})") from error
    if not isinstance(record, dict):
        raise ValueError(f"{where}: expected an object")

    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ValueError(f"{where}: missing {sorted(missing)}")
    if not isinstance(record["id"], str) or not SAFE_ID.fullmatch(record["id"]):
        raise ValueError(f"{where}: id must use only letters, digits, _ and -")
    if record["type"] not in INFOGRAPHIC_TYPES:
        raise ValueError(f"{where}: unknown type {record['type']!r}")
    if not isinstance(record["prompt"], str) or not record["prompt"].strip():
        raise ValueError(f"{where}: prompt is empty")

    required = record["required_text"]
    if not isinstance(required, list) or not required:
        raise ValueError(f"{where}: required_text must be a non-empty list")
    for text in required:
        # Text a model was never given can't fairly be required of it.
        if not isinstance(text, str) or not text or text not in record["prompt"]:
            raise ValueError(f"{where}: required_text {text!r} is not in the prompt")

    return Prompt(record["id"], record["type"], record["prompt"], tuple(required))


def load_prompts(path: str | Path) -> list[Prompt]:
    path = Path(path)
    prompts: list[Prompt] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name}:{number}"
        prompt = _parse_line(line, where)
        if prompt.id in seen:
            raise ValueError(f"{where}: duplicate id {prompt.id!r}")
        seen.add(prompt.id)
        prompts.append(prompt)
    if not prompts:
        raise ValueError(f"{path.name}: no prompts found")
    return prompts
