"""Run one setup with one model over a prompt set: generate, extract, render and log each sample.

Samples that are already logged are skipped, so an interrupted run continues where it stopped.
A failed model call is reported and skipped without being logged, so rerunning retries it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from infographics.backends.base import Backend, Message, image_paths
from infographics.harness.extract import extract_html
from infographics.harness.prompts import Prompt
from infographics.harness.renderer import Failure, Renderer, RenderResult
from infographics.harness.run_logger import RunLogger

# Several model errors in a row usually mean the server is down, so stop instead of skipping all.
MAX_CONSECUTIVE_ERRORS = 3


@dataclass
class RunSummary:
    logged: int = 0
    skipped: int = 0
    rendered_ok: int = 0
    errors: int = 0


def run_setup(
    prompts: list[Prompt],
    build_messages: Callable[[Prompt], list[Message]],
    backend: Backend,
    renderer: Renderer,
    logger: RunLogger,
    samples: int,
    temperature: float | None,
    report: Callable[[str], None] = print,
) -> RunSummary:
    summary = RunSummary()
    consecutive_errors = 0
    total = len(prompts) * samples

    for prompt in prompts:
        messages = build_messages(prompt)
        for sample in range(1, samples + 1):
            done = summary.logged + summary.skipped + summary.errors + 1
            label = f"[{done}/{total}] {prompt.id} sample {sample}"
            if logger.is_done(prompt.id, sample):
                summary.skipped += 1
                continue

            try:
                generation = backend.generate(messages, temperature, seed=sample)
            except Exception as error:  # noqa: BLE001 - any provider error; retried on rerun
                summary.errors += 1
                consecutive_errors += 1
                report(f"{label}: model call failed: {type(error).__name__}: {error}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    raise RuntimeError(
                        f"{consecutive_errors} model calls failed in a row; is the server running?"
                    ) from error
                continue
            consecutive_errors = 0

            html = extract_html(generation.text)
            if html is None:
                render = RenderResult(failures=[Failure("no_html", "the reply contained no HTML")])
            else:
                render = renderer.render(html, logger.render_path(prompt.id, sample))

            logger.log_sample(
                prompt,
                sample,
                messages,
                raw_output=generation.text,
                html=html,
                render=render,
                latency_s=generation.latency_s,
                usage=generation.usage(),
                reference_images=image_paths(messages),
                extra={
                    "finish_reason": generation.finish_reason,
                    "seed": sample if backend.sends_seed else None,
                },
            )
            summary.logged += 1
            summary.rendered_ok += render.ok
            status = "ok" if render.ok else ", ".join(f.kind for f in render.failures)
            cut = " (cut off at max_tokens)" if generation.finish_reason == "length" else ""
            report(f"{label}: {status}, {generation.latency_s:.0f} s, "
                   f"{generation.output_tokens} tokens{cut}")

    return summary
