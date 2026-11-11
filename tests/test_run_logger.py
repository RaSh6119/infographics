import json

import pytest

from infographics.harness.prompts import Prompt
from infographics.harness.renderer import Failure, RenderResult
from infographics.harness.run_logger import RunLogger

CONFIG = {
    "setup": "s1_zero_shot",
    "model": "example-model",
    "checkpoint": "abc123",
    "quantization": None,
    "temperature": 0.2,
}
PROMPT = Prompt("dev_list_001", "list", "Title: Use condoms", ("Use condoms",))
MESSAGES = [{"role": "user", "content": PROMPT.prompt}]
USAGE = {"input_tokens": 10, "output_tokens": 20}


@pytest.fixture
def logger(tmp_path):
    return RunLogger(tmp_path / "run", CONFIG)


def log(logger, sample=1, **overrides):
    arguments = {
        "raw_output": "```html\n<p>Café</p>\n```\n",
        "html": "<p>Café</p>",
        "render": RenderResult(png_path="anywhere.png", width=1080, height=800),
        "latency_s": 1.5,
        "usage": USAGE,
        **overrides,
    }
    return logger.log_sample(PROMPT, sample, MESSAGES, **arguments)


def read_record(directory):
    return json.loads((directory / "record.json").read_text(encoding="utf-8"))


def test_sample_is_saved_with_everything_the_plan_requires(logger):
    logger.render_path(PROMPT.id, 1).parent.mkdir(parents=True)
    logger.render_path(PROMPT.id, 1).write_bytes(b"png")
    directory = log(logger, gpu_seconds=1.2)
    record = read_record(directory)

    assert record["prompt"]["text"] == PROMPT.prompt
    assert record["prompt"]["type"] == "list"
    assert record["messages"] == MESSAGES
    assert record["latency_s"] == 1.5
    assert record["gpu_seconds"] == 1.2
    assert record["usage"] == USAGE
    assert record["render"]["ok"] is True
    assert record["files"] == {
        "raw_output": "raw_output.txt",
        "html": "output.html",
        "render": "render.png",
    }
    assert (directory / "output.html").read_text(encoding="utf-8") == "<p>Café</p>"


def test_raw_output_is_kept_byte_for_byte(logger):
    raw = "line one\r\nline two\n"
    directory = log(logger, raw_output=raw)
    assert (directory / "raw_output.txt").read_bytes() == raw.encode("utf-8")


def test_failed_render_is_recorded_without_files_that_do_not_exist(logger):
    failed = RenderResult(failures=[Failure("no_html", "reply had no HTML")])
    record = read_record(log(logger, html=None, render=failed))
    assert record["render"]["ok"] is False
    assert record["render"]["failures"][0]["kind"] == "no_html"
    assert record["files"]["html"] is None
    assert record["files"]["render"] is None


def test_image_only_output_is_supported(logger):
    logger.render_path(PROMPT.id, 1).parent.mkdir(parents=True)
    logger.render_path(PROMPT.id, 1).write_bytes(b"png")
    record = read_record(log(logger, raw_output=None, html=None, render=None))
    assert record["render"] is None
    assert record["files"] == {"raw_output": None, "html": None, "render": "render.png"}


def test_reference_images_are_identified_by_content(logger, tmp_path):
    image = tmp_path / "reference.png"
    image.write_bytes(b"reference")
    record = read_record(log(logger, reference_images=[image]))
    assert record["reference_images"][0]["path"] == str(image)
    assert len(record["reference_images"][0]["sha256"]) == 64


def test_hybrid_cost_fields_are_recorded(logger):
    record = read_record(log(logger, patch_rounds=2, extra_tokens=900))
    assert (record["patch_rounds"], record["extra_tokens"]) == (2, 900)


def test_review_ids_are_unique_and_reveal_nothing(logger):
    first = read_record(log(logger, sample=1))["review_id"]
    second = read_record(log(logger, sample=2))["review_id"]
    assert first != second
    for term in (CONFIG["setup"], CONFIG["model"], PROMPT.id):
        assert term not in first


def test_finished_sample_is_not_overwritten(logger):
    log(logger)
    with pytest.raises(FileExistsError):
        log(logger)


def test_is_done_only_after_record_is_written(logger):
    assert not logger.is_done(PROMPT.id, 1)
    logger.render_path(PROMPT.id, 1).parent.mkdir(parents=True)
    logger.render_path(PROMPT.id, 1).write_bytes(b"png")  # rendered, then interrupted
    assert not logger.is_done(PROMPT.id, 1)
    log(logger)
    assert logger.is_done(PROMPT.id, 1)


def test_interrupted_sample_can_be_logged_again(logger):
    directory = logger.sample_dir(PROMPT.id, 1)
    directory.mkdir(parents=True)
    (directory / "raw_output.txt").write_text("partial", encoding="utf-8")
    log(logger, raw_output="complete")
    assert (directory / "raw_output.txt").read_text(encoding="utf-8") == "complete"


def test_run_file_records_config_and_environment(logger):
    saved = json.loads((logger.run_dir / "run.json").read_text(encoding="utf-8"))
    assert saved["config"] == CONFIG
    assert {"git", "python", "platform"} <= saved["environment"].keys()


def test_resuming_with_same_config_keeps_finished_samples(tmp_path):
    log(RunLogger(tmp_path / "run", CONFIG))
    assert RunLogger(tmp_path / "run", dict(CONFIG)).is_done(PROMPT.id, 1)


def test_resuming_with_different_config_is_refused(tmp_path):
    RunLogger(tmp_path / "run", CONFIG)
    with pytest.raises(ValueError, match="different config"):
        RunLogger(tmp_path / "run", {**CONFIG, "temperature": 0.7})


@pytest.mark.parametrize("key", sorted(CONFIG))
def test_config_must_pin_every_required_key(tmp_path, key):
    config = {k: v for k, v in CONFIG.items() if k != key}
    with pytest.raises(ValueError, match=key):
        RunLogger(tmp_path / "run", config)


def test_unserializable_messages_fail_and_leave_sample_unfinished(logger):
    with pytest.raises(TypeError):
        logger.log_sample(PROMPT, 1, [{"content": b"bytes"}], "raw", "<p>x</p>", None, 1.0, USAGE)
    assert not logger.is_done(PROMPT.id, 1)
