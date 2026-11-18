"""Embedding similarity, tested with synthetic images and a fake embedder (no downloads)."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from infographics.metrics.embedding import (
    EMBEDDERS,
    PLACEHOLDER,
    compare,
    hf_embedder,
    normalize,
    pad_to_square,
    paired,
)

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_embed(images):
    """Mean colour of each image: red, green and blue pages point in different directions."""
    return normalize(np.array([np.asarray(pad_to_square(i), np.float32).mean(axis=(0, 1)) + 1 for i in images]))


def solid(colour, size=(30, 20)):
    return Image.new("RGB", size, colour)


# --- preprocessing ---

def test_pad_to_square_keeps_whole_page_centred_on_white():
    image = solid((255, 0, 0), (40, 20))
    square = pad_to_square(image)
    assert square.size == (40, 40)
    assert square.getpixel((20, 20)) == (255, 0, 0)  # the page, not cropped
    assert square.getpixel((20, 2)) == (255, 255, 255)  # padding above
    assert square.getpixel((20, 37)) == (255, 255, 255)  # padding below


def test_pad_to_square_flattens_transparency_onto_white():
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    assert pad_to_square(image).getpixel((5, 5)) == (255, 255, 255)


def test_pad_to_square_leaves_square_images_alone():
    image = solid((0, 0, 255), (16, 16))
    assert list(pad_to_square(image).getdata()) == list(image.getdata())


# --- scoring ---

def test_compare_finds_closest_reference():
    refs = normalize(np.array([[1, 0], [0, 1]]))
    generated = normalize(np.array([[0.9, 0.1], [0, 1]]))
    first, second = compare(generated, refs, ["a.png", "b.png"])
    assert first.best_ref == "a.png" and second.best_ref == "b.png"
    assert second.best == pytest.approx(1.0)
    assert second.mean == pytest.approx(0.5)


def test_paired_compares_row_with_row():
    refs = normalize(np.array([[1, 0], [0, 1]]))
    assert paired(refs, refs) == pytest.approx([1, 1])
    assert paired(refs, refs[::-1]) == pytest.approx([0, 0])


def test_unpinned_model_refuses_to_load():
    spec = EMBEDDERS["siglip"]
    if spec.revision != PLACEHOLDER:
        pytest.skip("revision already pinned")
    with pytest.raises(ValueError, match="pinned revision"):
        hf_embedder(spec)


def test_pinned_revisions_are_full_commits_once_set():
    for spec in EMBEDDERS.values():
        assert spec.revision == PLACEHOLDER or len(spec.revision) == 40


# --- the script, end to end on fake runs ---

def make_run(root: Path, model: str, pages: dict[str, tuple[tuple, bool] | None]) -> Path:
    """A run folder with one sample per prompt. None = no screenshot."""
    run = root / "runs" / "dev_set" / f"s1_zero_shot__{model}__dev_set"
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"config": {"setup": "s1_zero_shot", "model": model}}))
    for prompt_id, page in pages.items():
        sample = run / prompt_id / "sample_1"
        sample.mkdir(parents=True)
        files = {}
        ok = False
        if page:
            colour, ok = page
            solid(colour).save(sample / "render.png")
            files["render"] = "render.png"
        failures = [] if ok else [{"kind": "broken_asset", "detail": "x"}]
        (sample / "record.json").write_text(json.dumps({
            "prompt": {"id": prompt_id, "type": "list"}, "sample": 1, "review_id": f"{model}-{prompt_id}",
            "render": {"ok": ok, "failures": failures}, "files": files,
        }))
    return run


def test_script_scores_official_and_as_rendered(tmp_path):
    script = load_script("embed_similarity")
    refs = tmp_path / "refs"
    refs.mkdir()
    solid((255, 0, 0)).save(refs / "red.png")
    solid((0, 255, 0)).save(refs / "green.png")
    run = make_run(tmp_path, "m", {
        "p_red": ((250, 5, 5), True),  # rendered fine, looks like the red reference
        "p_failed": ((250, 5, 5), False),  # same look, but the render failed
        "p_missing": None,  # no screenshot at all
    })
    pages = script.find_pages([run])
    ref_paths = sorted(refs.iterdir())
    pairs = {"p_red": "green.png"}
    columns = script.score(pages, ref_paths, {"fake": fake_embed}, pairs)
    by_id = {p["prompt_id"]: p for p in pages}

    good, failed, missing = by_id["p_red"], by_id["p_failed"], by_id["p_missing"]
    assert good["fake_best_ref"] == "red.png"
    assert good["fake_best"] == pytest.approx(good["as_rendered_fake_best"]) and good["fake_best"] > 0.99
    assert good["fake_paired"] < good["fake_best"]  # paired with green, a worse match
    assert failed["as_rendered_fake_best"] > 0.99 and failed["fake_best"] == 0.0  # official: 0
    assert failed["fake_paired"] == ""  # no pair listed for this prompt
    assert missing["as_rendered_fake_best"] == 0.0 and missing["fake_best"] == 0.0
    assert {"fake_best", "fake_mean", "fake_paired", "fake_best_ref", "as_rendered_fake_mean"} <= set(columns)


def test_pairs_file_must_name_known_references(tmp_path):
    script = load_script("embed_similarity")
    pairs = tmp_path / "pairs.csv"
    with pairs.open("w", newline="") as file:
        csv.writer(file).writerows([["prompt_id", "reference"], ["p1", "nope.png"]])
    with pytest.raises(SystemExit, match="nope.png"):
        script.load_pairs(pairs, ["red.png"])


# --- reference export: few-shot pages are recognised by pixels ---

def test_few_shot_page_matches_itself_not_others():
    script = load_script("export_reference_pages")
    page = Image.new("RGB", (60, 90), "white")
    page.paste(solid((0, 0, 128), (60, 30)), (0, 0))  # navy header
    other = Image.new("RGB", (60, 90), "white")
    other.paste(solid((200, 30, 30), (30, 90)), (0, 0))  # red side bar
    same = script.difference(script.thumbnail(page), script.thumbnail(page.resize((120, 180))))
    different = script.difference(script.thumbnail(page), script.thumbnail(other))
    assert same < script.MATCH_THRESHOLD < different
