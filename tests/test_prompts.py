import json
from pathlib import Path

import pytest

from infographics.harness.prompts import INFOGRAPHIC_TYPES, load_prompts

DATA = Path(__file__).parent.parent / "data" / "prompts"
GOOD = {"id": "a_1", "type": "list", "prompt": "Title: Use condoms", "required_text": ["Use condoms"]}


def write(tmp_path, *records):
    path = tmp_path / "set.jsonl"
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_dev_set_loads_with_one_prompt_of_each_type():
    prompts = load_prompts(DATA / "dev_set.jsonl")
    assert len(prompts) == 5
    assert {prompt.type for prompt in prompts} == INFOGRAPHIC_TYPES


def test_students_prompts_are_not_accepted_as_a_test_set():
    with pytest.raises(ValueError, match="missing"):
        load_prompts(DATA / "prompts.jsonl")


def test_blank_lines_are_skipped(tmp_path):
    assert len(load_prompts(write(tmp_path, GOOD, "", "  "))) == 1


@pytest.mark.parametrize(
    "change, message",
    [
        ({"type": "poster"}, "unknown type"),
        ({"id": "../escape"}, "id must use"),
        ({"prompt": "  "}, "prompt is empty"),
        ({"required_text": []}, "non-empty list"),
        ({"required_text": ["Not in prompt"]}, "not in the prompt"),
    ],
    ids=["type", "unsafe-id", "empty-prompt", "no-required-text", "required-text-absent"],
)
def test_invalid_records_are_rejected_with_their_line_number(tmp_path, change, message):
    other = {**GOOD, "id": "b_2", **change}
    with pytest.raises(ValueError, match=rf"set\.jsonl:2: .*{message}"):
        load_prompts(write(tmp_path, GOOD, other))


def test_missing_field_is_rejected(tmp_path):
    record = {key: value for key, value in GOOD.items() if key != "required_text"}
    with pytest.raises(ValueError, match="missing"):
        load_prompts(write(tmp_path, record))


def test_duplicate_id_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate id"):
        load_prompts(write(tmp_path, GOOD, GOOD))


def test_invalid_json_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="not valid JSON"):
        load_prompts(write(tmp_path, "{oops"))


def test_empty_file_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no prompts"):
        load_prompts(write(tmp_path, ""))
