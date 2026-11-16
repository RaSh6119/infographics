"""Backend for any server that speaks the OpenAI chat completions API.

That covers vLLM serving a local model such as Qwen3.5-9B (base_url http://localhost:8000/v1, no
real API key), Ollama, OpenAI itself, and Gemini through Google's OpenAI-compatible endpoint.
Providers differ in what they accept, so the model config can say:
  max_tokens_param: max_completion_tokens   (OpenAI's GPT-5 models reject max_tokens)
  send_seed: false                          (Gemini rejects seed)
"""

from __future__ import annotations

import os
import time
from typing import Any

from .base import Backend, Generation, Message, image_data_url


def to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    converted = []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            parts = []
            for part in content:
                if part["type"] == "text":
                    parts.append({"type": "text", "text": part["text"]})
                elif part["type"] == "image":
                    parts.append(
                        {"type": "image_url", "image_url": {"url": image_data_url(part["path"])}}
                    )
                else:
                    raise ValueError(f"unknown message part type {part['type']!r}")
            content = parts
        converted.append({"role": message["role"], "content": content})
    return converted


class OpenAICompatibleBackend(Backend):
    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key_env: str | None = None,
        max_tokens: int = 16384,
        extra_body: dict[str, Any] | None = None,
        timeout_s: float = 900.0,
        max_tokens_param: str = "max_tokens",
        send_seed: bool = True,
    ):
        from openai import OpenAI

        if max_tokens_param not in ("max_tokens", "max_completion_tokens"):
            raise ValueError(f"unknown max_tokens_param {max_tokens_param!r}")
        api_key = os.environ.get(api_key_env, "") if api_key_env else "not-needed"
        if not api_key:
            raise ValueError(f"{api_key_env} is not set. Add it to .env.")
        self.model = model
        self.max_tokens = max_tokens
        self.max_tokens_param = max_tokens_param
        self.sends_seed = send_seed
        self.extra_body = extra_body or {}
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=2)

    def generate(
        self, messages: list[Message], temperature: float | None, seed: int | None = None
    ) -> Generation:
        options: dict[str, Any] = {self.max_tokens_param: self.max_tokens}
        if temperature is not None:
            options["temperature"] = temperature
        if self.sends_seed and seed is not None:
            options["seed"] = seed
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=to_openai_messages(messages),
            extra_body=self.extra_body or None,
            **options,
        )
        latency = time.perf_counter() - start
        choice = response.choices[0]
        usage = response.usage
        return Generation(
            text=choice.message.content or "",
            latency_s=round(latency, 3),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            finish_reason=choice.finish_reason,
        )
