import json

import numpy as np
import pytest

from infographics.backends.base import Backend, Generation
from infographics.harness.prompts import Prompt
from infographics.harness.renderer import Renderer
from infographics.harness.run_logger import RunLogger
from infographics.harness.runner import run_setup
from infographics.rag.icons import Icon
from infographics.rag.inline import inline_icons
from infographics.rag.retrieve import (
    build_record,
    glossary_terms,
    labels_of,
    load_glossary,
    load_retrieved,
    per_label,
    retrieve,
)
from infographics.setups import builders

ICON_SVG = '<svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M0 0H48V48H0Z" fill="currentColor"/></svg>'
ICONS = {
    "devices/syringe": Icon("devices/syringe", "Syringe", "devices", ("Injection", "Needle"), ICON_SVG),
    "medications/pill-1": Icon("medications/pill-1", "Pill 1", "medications", ("Medicine", "Tablet"), ICON_SVG),
    "contraceptives/male-condom": Icon("contraceptives/male-condom", "Male Condom", "contraceptives", ("Condom",), ICON_SVG),
    "typography/letter-a": Icon("typography/letter-a", "Letter A", "typography", ("Pill",), ICON_SVG),
}
PROMPT = Prompt(
    "p_list", "list",
    "Create an HIV prevention infographic for patients.\n\nTitle: Stay Safe\n- Take PrEP\n- Use condoms",
    ("Stay Safe", "Take PrEP", "Use condoms"),
)
GLOSSARY = {"PrEP": ["pill", "medicine"], "PEP": ["pill", "emergency"], "U=U": ["HIV negative"],
            "condoms": ["condom"]}


def bag_of_words(texts):
    """A fake embedder: word counts over a tiny vocabulary, normalised."""
    vocab = ["pill", "medicine", "tablet", "syringe", "injection", "needle", "condom", "condoms"]
    rows = []
    for text in texts:
        words = text.lower().replace(",", " ").split()
        row = np.array([words.count(w) for w in vocab], dtype=float) + 1e-6
        rows.append(row / np.linalg.norm(row))
    return np.vstack(rows)


# --- glossary and labels ------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label, expected",
    [
        ("Take PrEP", ["pill", "medicine"]),
        ("PEP within 72 hours", ["pill", "emergency"]),
        ("U=U: Treatment is prevention", ["HIV negative"]),
        ("PrEPared", []),          # whole words only
        ("Use condoms", ["condom"]),
    ],
)
def test_glossary_matches_whole_terms(label, expected):
    assert glossary_terms(label, GLOSSARY) == expected


def test_project_glossary_loads():
    glossary = load_glossary()
    assert glossary["PrEP"][0] == "pill"
    assert "False" not in glossary and "True" not in glossary  # YAML yes/no read as booleans
    assert all(words for words in glossary.values())


def test_title_is_not_a_label():
    assert labels_of(PROMPT) == [(1, "Take PrEP"), (2, "Use condoms")]


@pytest.mark.parametrize("n, k", [(2, 3), (5, 3), (6, 2), (8, 1), (20, 1)])
def test_icons_per_label_keep_the_total_at_15(n, k):
    assert per_label(n) == k
    assert n * k <= 15 or k == 1


# --- retrieval ----------------------------------------------------------------------------------

def test_retrieval_finds_icons_by_meaning_and_skips_typography():
    results = retrieve([PROMPT], ICONS, bag_of_words, GLOSSARY)
    entries = results["p_list"]
    assert [e["label_index"] for e in entries] == [1, 2]
    assert entries[0]["icons"][0]["id"] == "medications/pill-1"   # via the glossary: PrEP -> pill
    assert entries[1]["icons"][0]["id"] == "contraceptives/male-condom"
    assert all(c["id"] != "typography/letter-a" for e in entries for c in e["icons"])


def test_negated_label_gets_the_object_plus_a_no_sign():
    icons = {**ICONS, "supplementary/no-sign": Icon("supplementary/no-sign", "No Sign", "supplementary",
                                                    ("No", "Not allowed"), ICON_SVG)}
    prompt = Prompt("p_neg", "list", "Title: T\n- Don't share needles\n- Use condoms",
                    ("T", "Don't share needles", "Use condoms"))
    needles, condoms = retrieve([prompt], icons, bag_of_words, {"needles": ["syringe"]})["p_neg"]
    assert needles["negated"] and not condoms["negated"]
    assert needles["icons"][0]["id"] == "devices/syringe"          # searched without "Don't"
    assert needles["icons"][-1] == {"id": "supplementary/no-sign", "score": None}
    assert all(c["id"] != "supplementary/no-sign" for c in condoms["icons"])
    total = sum(len(e["icons"]) for e in (needles, condoms))
    assert total <= 15


def test_saved_retrieval_holds_no_label_text(tmp_path):
    results = retrieve([PROMPT], ICONS, bag_of_words, GLOSSARY)
    record = build_record("secret_set.jsonl", results, {"model": "fake", "revision": "x"})
    text = json.dumps(record)
    assert "Take PrEP" not in text and "Use condoms" not in text
    (tmp_path / "retrieved_secret_set.json").write_text(text)
    assert load_retrieved(tmp_path)["p_list"] == results["p_list"]


# --- inlining -----------------------------------------------------------------------------------

def test_placeholder_becomes_the_icon_keeping_size_and_colour():
    html = '<body><svg data-icon="devices/syringe" width="96" height="80" fill="#3576bc" class="i"></svg></body>'
    result = inline_icons(html, ICONS)
    assert result.used == ["devices/syringe"] and not result.failures
    assert 'width="96"' in result.html and 'height="80"' in result.html and 'class="i"' in result.html
    assert 'viewBox="0 0 48 48"' in result.html and "<path" in result.html
    assert "color:#3576bc" in result.html and 'fill="#3576bc"' not in result.html


def test_self_closing_placeholder_and_single_quotes():
    result = inline_icons("<svg data-icon='medications/pill-1' style='color:red'/>", ICONS)
    assert result.used == ["medications/pill-1"]
    assert "<path" in result.html and "color:red" in result.html


def test_unknown_icon_is_a_broken_asset():
    result = inline_icons('<svg data-icon="made/up"></svg>', ICONS)
    assert result.unknown == ["made/up"]
    assert [f.kind for f in result.failures] == ["broken_asset"]


def test_pages_without_placeholders_are_unchanged():
    html = "<svg width='10'><circle r='4'/></svg>"
    assert inline_icons(html, ICONS).html == html


def test_icon_use_is_logged_against_what_was_offered():
    html = '<svg data-icon="devices/syringe"></svg><svg data-icon="devices/syringe"></svg>'
    log = inline_icons(html, ICONS).log(["devices/syringe", "medications/pill-1"])
    assert log["icons_placed"] == 2
    assert log["icons_used"] == ["devices/syringe"]
    assert log["icons_offered_not_used"] == ["medications/pill-1"]


# --- the setup 3 prompt and the runner hook -----------------------------------------------------

@pytest.fixture
def setup3(monkeypatch):
    retrieved = retrieve([PROMPT], ICONS, bag_of_words, GLOSSARY)
    monkeypatch.setattr(builders, "_icons", lambda: ICONS)
    monkeypatch.setattr(builders, "_retrieved", lambda: retrieved)


def test_rag_prompt_lists_candidates_per_label(setup3):
    system, user = builders.rag_icons(PROMPT)
    assert system["role"] == "system"
    assert user["content"].startswith(PROMPT.prompt)
    assert "- Take PrEP: medications/pill-1 (Pill 1)" in user["content"]
    assert "draw your own symbol" in user["content"]


def test_missing_retrieval_says_how_to_make_it(monkeypatch):
    monkeypatch.setattr(builders, "_retrieved", lambda: {})
    with pytest.raises(FileNotFoundError, match="retrieve_icons.py"):
        builders.rag_icons(PROMPT)


class OneReply(Backend):
    def __init__(self, text):
        self.text = text

    def generate(self, messages, temperature, seed=None):
        return Generation(self.text, latency_s=0.1, input_tokens=1, output_tokens=1, finish_reason="stop")


@pytest.mark.parametrize(
    "placeholder, ok",
    [('<svg data-icon="medications/pill-1" width="80" height="80"></svg>', True),
     ('<svg data-icon="made/up" width="80" height="80"></svg>', False)],
)
def test_runner_inlines_icons_before_rendering(tmp_path, setup3, placeholder, ok):
    reply = f"```html\n<!doctype html><html><body><h1>Stay Safe</h1>{placeholder}</body></html>\n```"
    logger = RunLogger(tmp_path / "run", {"setup": "s3", "model": "fake", "checkpoint": "x",
                                          "quantization": None, "temperature": 0.2})
    with Renderer(timeout_s=10) as renderer:
        run_setup([PROMPT], builders.rag_icons, OneReply(reply), renderer, logger, 1, 0.2,
                  report=lambda _: None, postprocess=builders.rag_icons_postprocess)
    sample = logger.sample_dir("p_list", 1)
    record = json.loads((sample / "record.json").read_text(encoding="utf-8"))
    assert record["render"]["ok"] is ok
    assert record["extra"]["icons_offered"] >= 2
    if ok:
        assert record["extra"]["icons_used"] == ["medications/pill-1"]
        assert "<path" in (sample / "output.html").read_text(encoding="utf-8")
    else:
        assert record["extra"]["unknown_icon_ids"] == ["made/up"]
