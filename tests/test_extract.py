import pytest

from infographics.harness.extract import extract_html

PAGE = "<!doctype html>\n<html><body><p>Use condoms</p></body></html>"


@pytest.mark.parametrize(
    "reply",
    [
        PAGE,
        f"\n  {PAGE}\n",
        f"```html\n{PAGE}\n```",
        f"```HTML\n{PAGE}\n```",
        f"```\n{PAGE}\n```",
        f"```html\r\n{PAGE}\r\n```",
        f"Here is your infographic:\n\n```html\n{PAGE}\n```\n\nLet me know what you think!",
        f"Here is your infographic:\n{PAGE}\nI hope this helps.",
        f"<think>Maybe <html>draft</html>?</think>\n{PAGE}",
        f"<think>Maybe ```html\n<html>draft</html>\n```</think>\n```html\n{PAGE}\n```",
    ],
    ids=[
        "bare", "whitespace", "fence", "upper-label", "no-label", "crlf", "prose-and-fence",
        "prose-no-fence", "thinking", "thinking-with-fence",
    ],
)
def test_page_is_recovered_exactly(reply):
    assert extract_html(reply) == PAGE


def test_css_fence_is_ignored_in_favour_of_html():
    reply = f"```css\nbody {{ color: red; }}\n```\n```html\n{PAGE}\n```"
    assert extract_html(reply) == PAGE


def test_full_document_beats_a_longer_snippet():
    snippet = "<div>" + "x" * 500 + "</div>"
    assert extract_html(f"```html\n{snippet}\n```\n```html\n{PAGE}\n```") == PAGE


def test_output_cut_off_inside_a_fence_keeps_what_arrived():
    assert extract_html("```html\n<html><body><p>Use cond") == "<html><body><p>Use cond"


def test_output_cut_off_without_a_fence_keeps_what_arrived():
    assert extract_html("Sure!\n<html><body><p>Use cond") == "<html><body><p>Use cond"


def test_output_cut_off_while_thinking_has_no_html():
    assert extract_html("<think>I could use <html> and") is None


@pytest.mark.parametrize(
    "fragment", ['<svg width="10"></svg>', "<div>Use condoms</div>"], ids=["svg", "div"]
)
def test_bare_fragment_is_accepted(fragment):
    assert extract_html(fragment) == fragment


def test_svg_fence_is_accepted():
    assert extract_html('```svg\n<svg width="10"></svg>\n```') == '<svg width="10"></svg>'


@pytest.mark.parametrize(
    "reply",
    ["", "   ", "I can't help with that.", "```python\nprint(1)\n```", "```html\n\n```", "1 < 2"],
    ids=["empty", "whitespace", "refusal", "other-language", "empty-fence", "less-than"],
)
def test_reply_without_html_returns_none(reply):
    assert extract_html(reply) is None
