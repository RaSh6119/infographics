"""Save everything the plan requires for each run, in a form that can be resumed and reviewed.

    runs/<run_name>/
        run.json                    config and environment, written once
        <prompt_id>/sample_<n>/
            record.json             written last, so its presence means the sample is complete
            raw_output.txt          the model's reply, unchanged
            output.html             the extracted HTML, if any
            render.png              the render or generated image, if any

Each record has a random review_id. Human reviews refer to outputs by that id, so reviewers don't
see which setup or model produced what.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .prompts import Prompt
    from .renderer import RenderResult

# The plan requires exact checkpoints and quantization to be pinned for reproducibility.
REQUIRED_CONFIG_KEYS = {"setup", "model", "checkpoint", "quantization", "temperature"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()

    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _describe_image(path: str | Path) -> dict[str, str]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }


class RunLogger:
    def __init__(self, run_dir: str | Path, config: dict[str, Any]):
        missing = REQUIRED_CONFIG_KEYS - config.keys()
        if missing:
            raise ValueError(f"run config is missing {sorted(missing)}")
        config = json.loads(json.dumps(config))

        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        run_file = self.run_dir / "run.json"
        if run_file.exists():
            saved = json.loads(run_file.read_text(encoding="utf-8"))["config"]
            if saved != config:
                raise ValueError(
                    f"{self.run_dir} was started with a different config, so resuming it would "
                    "mix results. Use a new run name."
                )
        else:
            _write_json(
                run_file,
                {
                    "config": config,
                    "started_at": _now(),
                    "environment": {
                        "git": _git_state(),
                        "python": sys.version.split()[0],
                        "platform": platform.platform(),  # renders differ between machines
                    },
                },
            )

    def sample_dir(self, prompt_id: str, sample: int) -> Path:
        return self.run_dir / prompt_id / f"sample_{sample}"

    def render_path(self, prompt_id: str, sample: int) -> Path:
        return self.sample_dir(prompt_id, sample) / "render.png"

    def is_done(self, prompt_id: str, sample: int) -> bool:
        return (self.sample_dir(prompt_id, sample) / "record.json").exists()

    def log_sample(
        self,
        prompt: "Prompt",
        sample: int,
        messages: list[dict[str, Any]],
        raw_output: str | None,
        html: str | None,
        render: "RenderResult | None",
        latency_s: float,
        usage: dict[str, Any],
        reference_images: list[str | Path] = (),
        patch_rounds: int = 0,
        extra_tokens: int = 0,
        gpu_seconds: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Save one sample. Refuses to overwrite a finished one, since reruns must be deliberate."""
        if self.is_done(prompt.id, sample):
            raise FileExistsError(f"{prompt.id} sample {sample} is already logged")

        directory = self.sample_dir(prompt.id, sample)
        directory.mkdir(parents=True, exist_ok=True)
        if raw_output is not None:
            (directory / "raw_output.txt").write_text(raw_output, encoding="utf-8", newline="")
        if html is not None:
            (directory / "output.html").write_text(html, encoding="utf-8", newline="")

        render_record = None
        if render is not None:
            render_record = render.to_dict()
            render_record.pop("png_path")  # the file's location is given under "files"

        record = {
            "review_id": uuid.uuid4().hex,
            "logged_at": _now(),
            "prompt": {
                "id": prompt.id,
                "type": prompt.type,
                "text": prompt.prompt,
                "required_text": list(prompt.required_text),
            },
            "sample": sample,
            "messages": messages,
            "reference_images": [_describe_image(path) for path in reference_images],
            "render": render_record,
            "latency_s": latency_s,
            "gpu_seconds": gpu_seconds,
            "usage": usage,
            "patch_rounds": patch_rounds,
            "extra_tokens": extra_tokens,
            "extra": extra or {},
            "files": {
                "raw_output": "raw_output.txt" if raw_output is not None else None,
                "html": "output.html" if html is not None else None,
                "render": "render.png" if (directory / "render.png").exists() else None,
            },
        }
        _write_json(directory / "record.json", record)
        return directory
