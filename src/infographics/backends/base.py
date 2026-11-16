"""The interface every model backend implements, and the message format the setups produce.

Messages use one provider-neutral format, which is also what the run logger saves:

    {"role": "system" | "user" | "assistant", "content": "plain text"}
    {"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image", "path": "..."}]}

Images are referenced by path, so logs stay small. Each backend converts them to its own format.
"""

from __future__ import annotations

import base64
import mimetypes
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Message = dict[str, Any]


@dataclass
class Generation:
    text: str
    latency_s: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None  # "length" means the reply was cut off at max_tokens

    def usage(self) -> dict[str, int | None]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


class Backend(ABC):
    # False when the provider has no seed parameter, so logs don't claim a seed was used.
    sends_seed: bool = True

    @abstractmethod
    def generate(
        self, messages: list[Message], temperature: float | None, seed: int | None = None
    ) -> Generation:
        """Return the model's reply. Raise on errors; the runner decides whether to retry later.

        temperature None means the provider's default: some models reject any other value.
        """


def image_paths(messages: list[Message]) -> list[str]:
    return [
        part["path"]
        for message in messages
        if isinstance(message["content"], list)
        for part in message["content"]
        if part["type"] == "image"
    ]


def image_data_url(path: str | Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
