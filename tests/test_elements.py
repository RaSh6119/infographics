"""Setup 3b: the project's elements as an icon set, elements-first retrieval, prompt and inlining."""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
import yaml
from PIL import Image

from infographics.harness.prompts import Prompt
from infographics.rag import elements as el
from infographics.rag.icons import Icon
from infographics.rag.inline import inline_icons
from infographics.rag.retrieve import (
    ELEMENTS_MIN_SCORE,
    build_elements_record,
    elements_retrieved_path,
    load_elements_retrieved,
    load_retrieved,
    retrieve_elements_first,
)
from infographics.setups import builders

HEALTH_SVG = '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path d="M0 0H48V48H0Z" fill="currentColor"/></svg>'


def png_bytes(size=(40, 20), colour=(200, 30, 30, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def keyword_embed(texts):
    """A fake embedder: one dimension per keyword, so a label matches icons sharing its keyword."""
    vocab = ["pill", "condom", "syringe", "clock"]
    rows = []
    for text in texts:
        low = text.lower()
        row = np.array([low.count(w) for w in vocab], dtype=float) + 1e-3
        rows.append(row / np.linalg.norm(row))
    return np.vstack(rows)


ELEMENTS = {
    "elements/pill": Icon("elements/pill", "Pill", "medication", ("Medicine",), el.png_svg(png_bytes()), el.SOURCE),
    "elements/alarm-clock": Icon("elements/alarm-clock", "Alarm Clock", "time", ("Reminder",), el.png_svg(png_bytes()), el.SOURCE),
    "elements/no-sign": Icon("elements/no-sign", "No Sign", "symbols", ("Avoid",), el.png_svg(png_bytes()), el.SOURCE),
}
HEALTH = {
    "contraceptives/male-condom": Icon("contraceptives/male-condom", "Male Condom", "contraceptives", ("Condom",), HEALTH_SVG),
    "devices/syringe": Icon("devices/syringe", "Syringe", "devices", ("Injection",), HEALTH_SVG),
    "medications/pill-1": Icon("medications/pill-1", "Pill 1", "medications", ("Tablet",), HEALTH_SVG),
    "supplementary/no-sign": Icon("supplementary/no-sign", "No Sign", "supplementary", ("Avoid",), HEALTH_SVG),
}
PROMPT = Prompt(
    "p_list", "list",
    "Create an HIV prevention infographic.\n\nTitle: Stay Safe\n- Take a pill daily\n- Use a condom\n- Don't share a syringe",
    ("Stay Safe", "Take a pill daily", "Use a condom", "Don't share a syringe"),
)


# --- ids, PNG wrapping, catalogue checks --------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("icon_pill-organizer.png", "elements/pill-organizer"),
    ("structure_speech_bubble.png", "elements/speech-bubble"),
    ("icon_boxer-CD4-side-labeled.png", "elements/boxer-cd4-side-labeled"),
])
def test_element_id(name, expected):
    assert el.element_id(name) == expected


def test_png_svg_keeps_aspect_ratio_and_embeds_image():
    svg = el.png_svg(png_bytes((40, 20)))
    assert svg.startswith('<svg viewBox="0 0 40 20"')
    assert 'href="data:image/png;base64,' in svg and 'width="40" height="20"' in svg


def test_check_catalog_rejects_unlisted_and_missing_files():
    catalog = {"elements": [{"file": "icon_a.png"}], "excluded": ["icon_b.png"]}
    el.check_catalog(catalog, ["icon_a.png", "icon_b.png", "text_Hello.png"])  # text_ files are skipped
    with pytest.raises(ValueError, match="not in the catalog"):
        el.check_catalog(catalog, ["icon_a.png", "icon_b.png", "icon_new.png"])
    with pytest.raises(ValueError, match="not in the folder"):
        el.check_catalog(catalog, ["icon_b.png"])


def test_build_index_from_a_folder(tmp_path):
    folder = tmp_path / "Elements"
    folder.mkdir()
    (folder / "icon_pill.png").write_bytes(png_bytes())
    (folder / "text_Take-your-pill.png").write_bytes(png_bytes())
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(yaml.safe_dump({
        "excluded": [],
        "elements": [{"file": "icon_pill.png", "title": "Pill", "category": "medication", "tags": ["Medicine"]}],
    }))
    index = el.build_elements_index(folder, catalog)
    assert [i["id"] for i in index["icons"]] == ["elements/pill"]  # the text image is not an icon
    assert index["icons"][0]["source"] == el.SOURCE
    assert len(index["elements_sha256"]) == 64


@pytest.mark.skipif(not el.ELEMENTS_DIR.exists(), reason="data/icons/Elements is local only (not in git)")
def test_real_catalog_covers_the_folder():
    index = el.build_elements_index()
    ids = [i["id"] for i in index["icons"]]
    assert len(ids) == 66
    assert el.NO_SIGN_ID in ids
    assert not any("tick-mark" in i or i.startswith("elements/text") for i in ids)


# --- retrieval ---------------------------------------------------------------------------------

def run_retrieval(min_score=ELEMENTS_MIN_SCORE):
    return retrieve_elements_first([PROMPT], ELEMENTS, HEALTH, keyword_embed, {}, el.NO_SIGN_ID, min_score)


def test_elements_come_first_and_health_icons_fill_the_gaps():
    entries = {e["label_index"]: e for e in run_retrieval()["p_list"]}
    pill = [c["id"] for c in entries[1]["icons"]]
    condom = [c["id"] for c in entries[2]["icons"]]
    assert pill[0] == "elements/pill"  # a good element match is offered first
    assert "medications/pill-1" in pill  # leftover slots go to Health Icons
    assert condom[0] == "contraceptives/male-condom"  # no element fits: Health Icons only
    assert not any(c.startswith("elements/") for c in condom)


def test_negated_label_gets_the_elements_no_sign():
    entry = [e for e in run_retrieval()["p_list"] if e["negated"]][0]
    ids = [c["id"] for c in entry["icons"]]
    assert ids[0] == "devices/syringe"
    assert ids[-1] == el.NO_SIGN_ID and entry["icons"][-1]["score"] is None
    assert "supplementary/no-sign" not in ids


def test_threshold_keeps_weak_elements_out():
    entries = run_retrieval(min_score=1.01)["p_list"]  # nothing can match this well
    offered = [c["id"] for e in entries for c in e["icons"] if c["id"] != el.NO_SIGN_ID]
    assert not any(i.startswith("elements/") for i in offered)


def test_record_holds_no_label_text_and_has_its_own_file_name(tmp_path):
    record = build_elements_record("data/prompts/dev_set.jsonl", run_retrieval(), {"model": "fake"}, "abc")
    text = json.dumps(record)
    assert "condom" not in text.lower().replace("contraceptives/male-condom", "")
    assert record["setup"] == "s3b_rag_elements" and record["elements_min_score"] == ELEMENTS_MIN_SCORE
    path = elements_retrieved_path("data/prompts/dev_set.jsonl")
    assert path.name == "elements_retrieved_dev_set.json"
    # setup 3's loader must not read setup 3b's files, and the reverse
    (tmp_path / path.name).write_text(json.dumps({"prompts": {"x": []}}))
    (tmp_path / "retrieved_dev_set.json").write_text(json.dumps({"prompts": {"y": []}}))
    assert set(load_retrieved(tmp_path)) == {"y"}
    assert set(load_elements_retrieved(tmp_path)) == {"x"}


# --- prompt and inlining ------------------------------------------------------------------------

@pytest.fixture
def setup_3b(monkeypatch):
    entries = run_retrieval()
    monkeypatch.setattr(builders, "_elements_and_icons", lambda: {**HEALTH, **ELEMENTS})
    monkeypatch.setattr(builders, "_elements_retrieved", lambda: entries)


def test_setup_3b_is_registered():
    assert builders.SETUPS["s3b_rag_elements"] is builders.rag_elements
    assert builders.POSTPROCESSORS["s3b_rag_elements"] is builders.rag_elements_postprocess


def test_prompt_lists_elements_with_titles(setup_3b):
    user = builders.rag_elements(PROMPT)[1]["content"]
    assert "elements/" in user and "keep their own colours" in user
    assert "- Take a pill daily: elements/pill (Pill)" in user


def test_postprocess_inlines_png_elements_and_logs_them(setup_3b):
    html = '<body><svg data-icon="elements/pill" width="80" height="40" style="color:red"></svg>' \
           '<svg data-icon="contraceptives/male-condom" width="48" height="48"></svg></body>'
    out, log, failures = builders.rag_elements_postprocess(PROMPT, html)
    assert failures == []
    assert 'data-icon="elements/pill"' in out and "data:image/png;base64," in out
    assert 'viewBox="0 0 40 20"' in out and 'width="80"' in out
    assert log["elements_used"] == ["elements/pill"]
    assert log["icons_used"] == ["elements/pill", "contraceptives/male-condom"]


def test_unknown_element_id_is_a_broken_asset():
    result = inline_icons('<svg data-icon="elements/pil"></svg>', ELEMENTS)
    assert result.unknown == ["elements/pil"]
    assert result.failures[0].kind == "broken_asset"


def test_clearly_better_health_icon_beats_an_element():
    """An element passing the floor is still dropped when a Health Icon fits clearly better."""
    def embed(texts):  # the element half-matches "condom"; the Health Icon matches it fully
        rows = []
        for text in texts:
            low = text.lower()
            if "condom" in low:
                rows.append([1.0, 0.0])
            elif "bed" in low:
                rows.append([0.8, 0.6])
            else:
                rows.append([0.0, 1.0])
        return np.array(rows)
    elements = {"elements/bed": Icon("elements/bed", "Bed", "daily life", (), el.png_svg(png_bytes()), el.SOURCE)}
    health = {"contraceptives/male-condom": HEALTH["contraceptives/male-condom"]}
    prompt = Prompt("p", "list", "Title: T\n- Use a condom", ("T", "Use a condom"))
    ids = [c["id"] for c in retrieve_elements_first([prompt], elements, health, embed, {}, el.NO_SIGN_ID,
                                                    min_score=0.7, margin=0.02)["p"][0]["icons"]]
    assert ids[0] == "contraceptives/male-condom" and "elements/bed" not in ids  # 0.80 < 1.00 - 0.02
    near = retrieve_elements_first([prompt], elements, health, embed, {}, el.NO_SIGN_ID,
                                   min_score=0.7, margin=0.25)["p"][0]["icons"]
    assert near[0]["id"] == "elements/bed"  # within the margin: the element goes first
