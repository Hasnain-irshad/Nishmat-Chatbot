"""
The file-processor contract.

Every source format reduces to the same thing: text, plus metadata about how
we got it, plus warnings the admin should see. Downstream — analysis,
generation, chunking — never needs to know whether a lesson began as a PDF or
a voice note.

Adding a format is one new module and one line in `registry.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

HEBREW_RANGE = re.compile(r"[֐-׿]")


@dataclass
class ExtractionResult:
    """Unified output of every file processor."""

    text: str
    paragraphs: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def has_hebrew(self) -> bool:
        return has_hebrew(self.text)


class ExtractionError(Exception):
    """Extraction failed. The message is safe to show a person."""


@runtime_checkable
class FileProcessor(Protocol):
    kind: str

    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        ...


# --------------------------------------------------------------------- text


def has_hebrew(text: str) -> bool:
    return bool(HEBREW_RANGE.search(text))


def hebrew_ratio(text: str) -> float:
    """Share of the letters in `text` that are Hebrew."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if HEBREW_RANGE.match(c)) / len(letters)


def normalise(text: str) -> str:
    """
    NFC only.

    Never NFKD, and never "strip accents": Hebrew in this corpus is fully
    vocalised, and decomposition silently destroys the nikud. There is a test
    asserting a real vocalised string survives this untouched.
    """
    text = unicodedata.normalize("NFC", text)
    # NBSP and zero-width space, spelled as escapes so they are visible
    # to the next person reading this file.
    return text.replace(" ", " ").replace("​", "")
