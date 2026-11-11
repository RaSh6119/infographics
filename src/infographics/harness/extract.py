"""Pull the HTML out of a model's reply, which may also contain prose or Markdown code fences.

Returns None when the reply has no HTML, and the caller should count that as a failed render.
"""

from __future__ import annotations

import re

_THINKING = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)
# An unclosed fence runs to the end of the reply, as happens when output hits the token limit.
_FENCE = re.compile(r"```([\w-]*)[ \t]*\r?\n(.*?)(?:```|\Z)", re.DOTALL)
_DOCUMENT_START = re.compile(r"<!doctype\s+html|<html[\s>]", re.IGNORECASE)
_DOCUMENT_END = re.compile(r"</html\s*>", re.IGNORECASE)
_HTML_FENCE_LABELS = {"html", "htm", "svg", "xml"}


def _is_html_fence(label: str, body: str) -> bool:
    label = label.lower()
    if label:
        return label in _HTML_FENCE_LABELS
    return body.lstrip().startswith("<")


def extract_html(reply: str) -> str | None:
    text = _THINKING.sub("", reply)

    fences = [
        match.group(2).strip()
        for match in _FENCE.finditer(text)
        if _is_html_fence(match.group(1), match.group(2))
    ]
    fences = [fence for fence in fences if fence]
    if fences:
        # A reply can also include a short snippet, so prefer full documents, then the longest.
        return max(fences, key=lambda fence: (bool(_DOCUMENT_START.search(fence)), len(fence)))

    start = _DOCUMENT_START.search(text)
    if start:
        ends = list(_DOCUMENT_END.finditer(text, start.start()))
        end = ends[-1].end() if ends else len(text)
        return text[start.start() : end].strip()

    stripped = text.strip()
    if re.match(r"<[a-zA-Z]", stripped):  # a bare fragment such as <svg> or <div>
        return stripped
    return None
