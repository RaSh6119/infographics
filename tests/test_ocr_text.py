import pytest
from PIL import Image

from infographics.metrics.ocr_text import OcrReader, normalize_word, score_image, score_text

REQUIRED = ["Condom Use", "Not Sharing Needles", "PEP (72 hours)"]


def test_exact_text_scores_one():
    score = score_text(REQUIRED, REQUIRED)
    assert (score.text_fidelity, score.word_recall, score.phrase_recall) == (1, 1, 1)
    assert score.missing == []


def test_split_and_jumbled_lines_still_match():
    lines = ["Condom", "Not Sharing", "PEP", "Use", "(72 hours)", "Needles"]
    assert score_text(REQUIRED, lines).phrase_recall == 1


def test_case_and_surrounding_punctuation_are_ignored():
    assert score_text(REQUIRED, ["CONDOM USE", "NOT SHARING NEEDLES", "PEP 72 HOURS"]).word_recall == 1


@pytest.mark.parametrize(
    "word, normalized",
    [("(72", "72"), ("hours)", "hours"), ("99%", "99%"), ("U=U:", "u=u"), ("Don't", "don't"), ("—", "")],
)
def test_normalize_word(word, normalized):
    assert normalize_word(word) == normalized


def test_misspelling_lowers_fidelity_and_fails_the_phrase():
    score = score_text(["Regular Testing"], ["Regukg Testing"])
    assert score.word_recall == 0.5
    assert score.phrase_recall == 0
    assert 0.5 < score.text_fidelity < 1
    assert score.phrases[0].words[0].matched == "regukg"


def test_missing_phrase_is_reported():
    score = score_text(REQUIRED, ["Condom Use", "PEP (72 hours)"])
    assert score.missing == ["Not Sharing Needles"]
    assert score.phrase_recall == pytest.approx(2 / 3, abs=1e-3)


def test_extra_text_does_not_lower_the_score():
    assert score_text(REQUIRED, REQUIRED + ["Talk to your provider", "01", "02"]).text_fidelity == 1


def test_one_ocr_word_cannot_satisfy_two_required_words():
    score = score_text(["PrEP", "PrEP daily"], ["PrEP daily"])
    assert score.word_recall == pytest.approx(2 / 3, abs=1e-3)


def test_similar_words_go_to_their_best_match():
    score = score_text(["PEP", "PrEP"], ["PrEP", "PEP"])
    assert score.phrase_recall == 1


def test_no_ocr_text_scores_zero():
    score = score_text(REQUIRED, [])
    assert (score.text_fidelity, score.word_recall, score.phrase_recall) == (0, 0, 0)


@pytest.mark.parametrize("required", [[], ["Condom Use", "  "], ["—"]])
def test_required_text_without_words_is_rejected(required):
    with pytest.raises(ValueError):
        score_text(required, ["anything"])


def test_result_is_json_serializable():
    import json

    record = json.loads(json.dumps(score_text(REQUIRED, REQUIRED).to_dict()))
    assert record["phrases"][0]["words"][0]["word"] == "condom"


@pytest.fixture(scope="module")
def reader():
    pytest.importorskip("easyocr")
    return OcrReader()


@pytest.mark.parametrize("width", [1080, 3200], ids=["small", "large"])
def test_rendered_page_is_read_at_any_size(reader, tmp_path, width):
    from infographics.harness.renderer import Renderer

    page = """<body style="margin:0;font-family:Arial;padding:40px">
      <h1 style="font-size:56px">HIV Prevention Strategies</h1>
      <div style="display:flex;gap:80px;font-size:30px">
        <p>Condom<br>Use</p><p>Not Sharing<br>Needles</p><p>PEP<br>(72 hours)</p>
      </div></body>"""
    png = tmp_path / "page.png"
    with Renderer() as renderer:
        assert renderer.render(page, png).ok
    with Image.open(png) as image:
        resized = image.resize((width, round(image.height * width / image.width)))

    score, lines = score_image(resized, ["HIV Prevention Strategies", *REQUIRED], reader)
    assert score.phrase_recall == 1, [line.text for line in lines]
    assert all(0 <= x <= width for line in lines for x, _ in line.box)
