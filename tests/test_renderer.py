import json

import pytest
from PIL import Image

from infographics.harness.renderer import PAGE_WIDTH, Renderer

GOOD_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin: 0; width: 1080px; font-family: Arial, sans-serif; background: #f4f7fb; }
  h1 { padding: 40px; margin: 0; background: #12507a; color: white; font-size: 56px; }
  .tile { margin: 32px 40px; padding: 32px; background: white; font-size: 36px; }
</style></head><body>
  <h1>How Well PrEP Works</h1>
  <div class="tile">
    <svg width="64" height="64"><circle cx="32" cy="32" r="30" fill="#12507a"/></svg>
    Sex: about 99% lower risk
  </div>
  <div class="tile">Injection drug use: at least 74% lower risk</div>
</body></html>"""

DATA_URI_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E"
    "%3Ccircle cx='5' cy='5' r='5'/%3E%3C/svg%3E"
)


@pytest.fixture(scope="module")
def renderer():
    with Renderer(timeout_s=3) as instance:
        yield instance


@pytest.fixture
def png(tmp_path):
    return tmp_path / "render.png"


def kinds(result):
    return {failure.kind for failure in result.failures}


def test_good_page_renders_at_full_height_and_contract_width(renderer, png):
    result = renderer.render(GOOD_PAGE, png)
    assert result.ok, result.failures
    assert result.warnings == []
    with Image.open(png) as image:
        assert image.width == PAGE_WIDTH
        assert image.height == result.height


def test_page_taller_than_viewport_is_captured_in_full(renderer, png):
    result = renderer.render('<body style="margin:0"><div style="height:3000px">Tall</div>', png)
    assert result.ok, result.failures
    with Image.open(png) as image:
        assert image.height == 3000


def test_repeat_render_is_pixel_identical(renderer, tmp_path):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    renderer.render(GOOD_PAGE, first)
    renderer.render(GOOD_PAGE, second)
    assert first.read_bytes() == second.read_bytes()


def test_page_is_decoded_as_utf8(renderer, png):
    script = "<script>if (document.characterSet !== 'UTF-8') throw new Error('bad')</script>"
    assert renderer.render(f"<p>PrEP – café</p>{script}", png).ok


def test_svg_only_page_is_not_blank(renderer, png):
    page = '<svg width="500" height="500"><rect width="500" height="500" fill="teal"/></svg>'
    assert renderer.render(page, png).ok


def test_short_text_is_not_blank(renderer, png):
    assert renderer.render("<p>Hi</p>", png).ok


def test_valid_data_uri_image_passes(renderer, png):
    assert renderer.render(f'<img src="{DATA_URI_SVG}" width="200">', png).ok


def test_finite_fade_in_is_captured_at_its_end_state(renderer, png):
    page = """<style>
      @keyframes in { from { opacity: 0 } to { opacity: 1 } }
      h1 { animation: in 60s forwards }
    </style><h1>Visible</h1>"""
    assert renderer.render(page, png).ok


def test_uncaught_script_error_fails(renderer, png):
    result = renderer.render("<p>Text</p><script>missingFunction()</script>", png)
    assert kinds(result) == {"js_error"}
    assert "missingFunction" in result.failures[0].detail
    assert result.png_path == str(png)  # kept so the failure can be inspected


def test_caught_script_error_passes(renderer, png):
    page = "<p>Text</p><script>try { missingFunction() } catch (e) {}</script>"
    assert renderer.render(page, png).ok


@pytest.mark.parametrize(
    "page",
    [
        '<p>Text</p><img src="icons/missing.png">',
        '<p>Text</p><img loading="lazy" style="margin-top:9000px" src="icons/missing.png">',
        '<p>Text</p><img src="data:image/png;base64,notanimage">',
        "<p>Text</p><img>",
        '<p>Text</p><link rel="stylesheet" href="https://fonts.example.invalid/style.css">',
        '<p>Text</p><script src="https://cdn.example.invalid/chart.js"></script>',
        '<p style="background:url(https://example.invalid/bg.png)">Text</p>',
    ],
    ids=["relative", "lazy", "bad-data-uri", "no-src", "external-css", "external-js", "css-bg"],
)
def test_broken_or_external_asset_fails(renderer, png, page):
    assert "broken_asset" in kinds(renderer.render(page, png))


def test_broken_asset_is_reported_once(renderer, png):
    result = renderer.render('<p>Text</p><img src="https://example.invalid/a.png">', png)
    details = [failure.detail for failure in result.failures]
    assert details == ["https://example.invalid/a.png"]


@pytest.mark.parametrize(
    "page",
    [
        "",
        "   \n  ",
        "<html><body></body></html>",
        "<div></div>",
        '<body style="background:white"><p style="color:white">Hidden</p></body>',
        '<body style="background:linear-gradient(red,blue);height:900px"></body>',
        '<svg width="500" height="500"></svg>',
    ],
    ids=["empty", "whitespace", "empty-body", "empty-div", "white-on-white", "gradient", "empty-svg"],
)
def test_blank_page_fails(renderer, png, page):
    assert kinds(renderer.render(page, png)) == {"blank"}


def test_overflowing_width_warns_but_passes(renderer, png):
    result = renderer.render('<body style="margin:0"><div style="width:1500px">Wide</div>', png)
    assert result.ok, result.failures
    assert any("1500 px wide" in warning for warning in result.warnings)


def test_too_tall_page_fails_without_a_capture(renderer, png):
    result = renderer.render('<div style="height:20000px">Tall</div>', png)
    assert kinds(result) == {"too_tall"}
    assert result.png_path is None
    assert not png.exists()


@pytest.mark.parametrize(
    "script",
    ["while (true) {}", "setTimeout(() => { while (true) {} }, 50)"],
    ids=["during-load", "after-load"],
)
def test_hung_page_times_out_and_next_render_still_works(renderer, png, tmp_path, script):
    result = renderer.render(f"<p>Text</p><script>{script}</script>", png)
    assert "timeout" in kinds(result)
    assert result.png_path is None
    assert renderer.render(GOOD_PAGE, tmp_path / "next.png").ok


def test_failed_rerun_removes_the_previous_image(renderer, png):
    assert renderer.render(GOOD_PAGE, png).ok
    assert not renderer.render("<script>while (true) {}</script>", png).ok
    assert not png.exists()


def test_output_directory_is_created(renderer, tmp_path):
    target = tmp_path / "run" / "sample_1" / "render.png"
    assert renderer.render(GOOD_PAGE, target).ok
    assert target.exists()


def test_result_is_json_serializable(renderer, png):
    record = json.loads(json.dumps(renderer.render("<script>oops()</script><p>Hi</p>", png).to_dict()))
    assert record["ok"] is False
    assert record["failures"][0]["kind"] == "js_error"
