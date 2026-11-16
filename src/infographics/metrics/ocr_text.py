"""Metric 4: OCR text fidelity. Is the required text present and spelled correctly?

Text is read from the image with OCR, for HTML renders as well as generated images, so every setup
is scored the same way. Words are matched without regard to order (as in LeX-Bench), because OCR
splits multi-line labels and jumbles the reading order of tiled layouts.

Scores, all from 0 to 1, higher is better:
    text_fidelity  1 - mean normalized edit distance of each required word to its matched OCR word
    word_recall    share of required words found spelled exactly
    phrase_recall  share of required phrases whose words were all found spelled exactly

Matching ignores case and surrounding punctuation, so "PEP (72 HOURS)" matches "PEP (72 hours)".
It does not check that a label sits next to the right icon, and OCR misreadings count as errors,
so a perfect page can score slightly below 1.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from rapidfuzz.distance import Levenshtein
from scipy.optimize import linear_sum_assignment

# Every image is resized to this width before OCR, so small images aren't penalised for small text.
OCR_WIDTH = 2560

_EDGE_PUNCTUATION = re.compile(r"^[^\w%]+|[^\w%]+$")


def normalize_word(word: str) -> str:
    word = unicodedata.normalize("NFKC", word).casefold()
    return _EDGE_PUNCTUATION.sub("", word)


def words_of(text: str) -> list[str]:
    return [word for word in map(normalize_word, text.split()) if word]


@dataclass
class WordMatch:
    word: str
    matched: str | None
    distance: float


@dataclass
class PhraseResult:
    phrase: str
    found: bool
    words: list[WordMatch]


@dataclass
class TextScore:
    text_fidelity: float
    word_recall: float
    phrase_recall: float
    phrases: list[PhraseResult]

    @property
    def missing(self) -> list[str]:
        return [result.phrase for result in self.phrases if not result.found]

    def to_dict(self) -> dict:
        return asdict(self)


def score_text(required: Sequence[str], ocr_lines: Sequence[str]) -> TextScore:
    phrase_words = [words_of(phrase) for phrase in required]
    if not phrase_words or not all(phrase_words):
        raise ValueError("every required phrase must contain at least one word")

    wanted = [word for words in phrase_words for word in words]
    found = [word for line in ocr_lines for word in words_of(line)]

    matches = [WordMatch(word, None, 1.0) for word in wanted]
    if found:
        cost = np.array([[Levenshtein.normalized_distance(w, f) for f in found] for w in wanted])
        # Each OCR word can match one required word only, so a repeated word must appear twice.
        for row, column in zip(*linear_sum_assignment(cost)):
            matches[row] = WordMatch(wanted[row], found[column], round(float(cost[row, column]), 4))

    phrases, start = [], 0
    for phrase, words in zip(required, phrase_words):
        own = matches[start : start + len(words)]
        start += len(words)
        phrases.append(PhraseResult(phrase, all(m.distance == 0 for m in own), own))

    return TextScore(
        text_fidelity=round(1 - sum(m.distance for m in matches) / len(matches), 4),
        word_recall=round(sum(m.distance == 0 for m in matches) / len(matches), 4),
        phrase_recall=round(sum(p.found for p in phrases) / len(phrases), 4),
        phrases=phrases,
    )


@dataclass
class OcrLine:
    text: str
    confidence: float
    box: list[list[int]]  # four corners, in the original image's pixels


class OcrReader:
    """Wraps EasyOCR. The model loads on first use, which takes a few seconds."""

    def __init__(self, gpu: bool | None = None):
        self._gpu = gpu
        self._reader = None

    def read(self, image: str | Path | Image.Image) -> list[OcrLine]:
        if self._reader is None:
            import easyocr
            import torch

            gpu = torch.cuda.is_available() if self._gpu is None else self._gpu
            self._reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)

        if isinstance(image, Image.Image):
            rgb = image.convert("RGB")
        else:
            with Image.open(image) as opened:
                rgb = opened.convert("RGB")
        scale = OCR_WIDTH / rgb.width
        resized = rgb.resize((OCR_WIDTH, round(rgb.height * scale)), Image.LANCZOS)

        return [
            OcrLine(text, round(float(confidence), 3), [[round(x / scale), round(y / scale)] for x, y in box])
            for box, text, confidence in self._reader.readtext(np.asarray(resized))
        ]


def score_image(
    image: str | Path | Image.Image, required: Sequence[str], reader: OcrReader
) -> tuple[TextScore, list[OcrLine]]:
    lines = reader.read(image)
    return score_text(required, [line.text for line in lines]), lines
