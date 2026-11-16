"""Backend for Claude through the official Anthropic SDK.

Claude Opus 5.5 always thinks before answering and rejects temperature, so the model config sets
temperature: null and controls depth with effort instead. Replies are streamed, which keeps long
pages from hitting HTTP timeouts.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

from .base import Backend, Generation, Message

# Claude's stop reasons, mapped to the runner's: "length" means cut off at max_tokens.
STOP_REASONS = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}


def to_anthropic(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """Split out the system prompt and convert images to base64 blocks."""
    system = None
    converted = []
    for message in messages:
        content = message["content"]
        if message["role"] == "system":
            if not isinstance(content, str):
                raise ValueError("the system message must be plain text")
            system = content
            continue
        if isinstance(content, list):
            blocks = []
            for part in content:
                if part["type"] == "text":
                    blocks.append({"type": "text", "text": part["text"]})
                elif part["type"] == "image":
                    path = Path(part["path"])
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mimetypes.guess_type(str(path))[0] or "image/png",
                            "data": base64.standard_b64encode(path.read_bytes()).decode("ascii"),
                        },
                    })
                else:
                    raise ValueError(f"unknown message part type {part['type']!r}")
            content = blocks
        converted.append({"role": message["role"], "content": content})
    return system, converted


class AnthropicBackend(Backend):
    sends_seed = False  # the Messages API has no seed parameter

    def __init__(
        self,
        model: str,
        api_key_env: str = "ANTHROPIC_API_KEY",
        max_tokens: int = 32000,
        effort: str | None = None,
        timeout_s: float = 900.0,
    ):
        import anthropic

        if not os.environ.get(api_key_env):
            raise ValueError(f"{api_key_env} is not set. Add it to .env.")
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self._client = anthropic.Anthropic(
            api_key=os.environ[api_key_env], timeout=timeout_s, max_retries=2
        )

    def generate(
        self, messages: list[Message], temperature: float | None, seed: int | None = None
    ) -> Generation:
        system, converted = to_anthropic(messages)
        options: dict[str, Any] = {}
        if system is not None:
            options["system"] = system
        if temperature is not None:
            options["temperature"] = temperature
        if self.effort:
            options["output_config"] = {"effort": self.effort}

        start = time.perf_counter()
        with self._client.messages.stream(
            model=self.model, max_tokens=self.max_tokens, messages=converted, **options
        ) as stream:
            response = stream.get_final_message()
        latency = time.perf_counter() - start

        text = "".join(block.text for block in response.content if block.type == "text")
        return Generation(
            text=text,
            latency_s=round(latency, 3),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            # A refusal is kept as "refusal": the reply then has no HTML and is logged as no_html.
            finish_reason=STOP_REASONS.get(response.stop_reason, response.stop_reason),
        )
