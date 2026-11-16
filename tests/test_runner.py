import json

import pytest

from infographics.backends.base import Backend, Generation
from infographics.harness.prompts import Prompt
from infographics.harness.renderer import Renderer
from infographics.harness.run_logger import RunLogger
from infographics.harness.runner import run_setup
from infographics.setups.builders import FEW_SHOT_DIR, FEW_SHOT_IMAGES, SETUPS, few_shot, zero_shot

PROMPTS = [
    Prompt("p_one", "list", "Title: Use condoms", ("Use condoms",)),
    Prompt("p_two", "list", "Title: Get tested", ("Get tested",)),
]
CONFIG = {"setup": "test", "model": "fake", "checkpoint": "x", "quantization": None, "temperature": 0.2}


class FakeBackend(Backend):
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, messages, temperature, seed=None):
        self.calls.append((messages, temperature, seed))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Generation(reply, latency_s=0.5, input_tokens=10, output_tokens=20, finish_reason="stop")


GOOD = "```html\n<!doctype html><html><body><h1>Use condoms</h1></body></html>\n```"


@pytest.fixture(scope="module")
def renderer():
    with Renderer(timeout_s=5) as instance:
        yield instance


def run(tmp_path, backend, renderer, prompts=PROMPTS, samples=2):
    logger = RunLogger(tmp_path / "run", CONFIG)
    summary = run_setup(prompts, zero_shot, backend, renderer, logger, samples, 0.2, report=lambda _: None)
    return summary, logger


def record(logger, prompt_id, sample):
    return json.loads((logger.sample_dir(prompt_id, sample) / "record.json").read_text(encoding="utf-8"))


def test_every_sample_is_generated_rendered_and_logged(tmp_path, renderer):
    backend = FakeBackend([GOOD] * 4)
    summary, logger = run(tmp_path, backend, renderer)
    assert (summary.logged, summary.rendered_ok, summary.errors) == (4, 4, 0)
    assert [seed for *_, seed in backend.calls] == [1, 2, 1, 2]
    assert {temperature for _, temperature, _ in backend.calls} == {0.2}

    saved = record(logger, "p_two", 2)
    assert saved["render"]["ok"] is True
    assert saved["files"]["render"] == "render.png"
    assert saved["messages"][0]["role"] == "system"
    assert saved["extra"] == {"finish_reason": "stop", "seed": 2}
    assert saved["usage"] == {"input_tokens": 10, "output_tokens": 20}


def test_reply_without_html_is_logged_as_a_failure(tmp_path, renderer):
    summary, logger = run(tmp_path, FakeBackend(["Sorry, I can't."]), renderer, PROMPTS[:1], 1)
    assert (summary.logged, summary.rendered_ok) == (1, 0)
    saved = record(logger, "p_one", 1)
    assert saved["render"]["failures"][0]["kind"] == "no_html"
    assert saved["files"] == {"raw_output": "raw_output.txt", "html": None, "render": None}


def test_failed_call_is_skipped_and_retried_on_rerun(tmp_path, renderer):
    summary, logger = run(tmp_path, FakeBackend([GOOD, TimeoutError("slow"), GOOD, GOOD]), renderer)
    assert (summary.logged, summary.errors) == (3, 1)
    assert not logger.is_done("p_one", 2)

    backend = FakeBackend([GOOD])
    summary, logger = run(tmp_path, backend, renderer)
    assert (summary.logged, summary.skipped) == (1, 3)
    assert logger.is_done("p_one", 2)


def test_run_stops_when_the_server_seems_down(tmp_path, renderer):
    backend = FakeBackend([ConnectionError("refused")] * 4)
    with pytest.raises(RuntimeError, match="server running"):
        run(tmp_path, backend, renderer)
    assert len(backend.calls) == 3


def test_zero_shot_sends_system_prompt_and_user_prompt():
    messages = zero_shot(PROMPTS[0])
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "1080 px wide" in messages[0]["content"]
    assert messages[1]["content"] == PROMPTS[0].prompt


@pytest.mark.skipif(
    not all((FEW_SHOT_DIR / name).exists() for name in FEW_SHOT_IMAGES),
    reason="reference images are not in git",
)
def test_few_shot_adds_three_reference_images_before_the_prompt():
    content = few_shot(PROMPTS[0])[1]["content"]
    assert [part["type"] for part in content] == ["text", "image", "image", "image", "text"]
    assert content[-1]["text"] == PROMPTS[0].prompt


def test_few_shot_explains_missing_images(monkeypatch, tmp_path):
    monkeypatch.setattr("infographics.setups.builders.FEW_SHOT_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="copy them over"):
        few_shot(PROMPTS[0])


def test_setups_registered():
    assert set(SETUPS) == {"s1_zero_shot", "s2_few_shot", "s3_rag_icons"}
