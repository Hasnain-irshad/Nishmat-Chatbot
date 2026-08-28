"""
DOCX text extraction.

Deliberately built on the standard library's zipfile + ElementTree rather than
python-docx. The client's corpus proved that real-world DOCX is messy, and a
raw XML walk cannot be tripped up by an unusual style definition or a
content-control wrapper the way a higher-level parser can. It also keeps this
module dependency-free, so scripts can run before anything is pip-installed.

What matters for this project specifically:

  * `<w:br/>` becomes a real newline. The client's writing style uses line
    breaks as punctuation — "Maybe for weeks. / Maybe for months." is three
    lines, not one paragraph — so collapsing them would destroy the pacing
    that defines her voice.
  * Text is normalised to NFC and nothing else. Hebrew in this corpus is fully
    vocalised, and NFKD or naive accent-stripping would silently destroy the
    nikud.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from app.services.ingestion.base import (
    ExtractionError,
    ExtractionResult,
    has_hebrew,
    hebrew_ratio,
    normalise,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

HEBREW_RANGE = re.compile(r"[֐-׿]")


def _paragraph_text(node: ET.Element) -> str:
    parts: list[str] = []
    for child in node.iter():
        tag = child.tag.split("}")[-1]
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
    return "".join(parts)


def extract_docx(source: Path | bytes) -> ExtractionResult:
    """
    Extract a DOCX into paragraphs, preserving intentional line breaks.

    Accepts a path (the corpus importer reads from disk) or raw bytes (an
    upload never touches the filesystem).
    """
    warnings: list[str] = []
    label = source.name if isinstance(source, Path) else "That file"

    try:
        archive = zipfile.ZipFile(
            BytesIO(source) if isinstance(source, bytes) else source
        )
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"{label} is not a readable .docx file") from exc

    try:
        document_xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ExtractionError(
            f"{label} does not look like a Word document."
        ) from exc

    root = ET.fromstring(document_xml)

    paragraphs: list[str] = []
    for para in root.iter(W + "p"):
        text = normalise(_paragraph_text(para))
        # Trailing whitespace only; leading space is sometimes meaningful
        # indentation in this corpus.
        paragraphs.append(text.rstrip())

    media = [n for n in archive.namelist() if n.startswith("word/media/")]
    if media:
        warnings.append(
            f"{len(media)} embedded image(s) present — text extraction ignores them"
        )

    body = "\n".join(paragraphs)
    if not body.strip():
        warnings.append("no text content found")

    return ExtractionResult(
        text=body,
        paragraphs=paragraphs,
        metadata={
            "paragraph_count": len(paragraphs),
            "embedded_media": len(media),
            "has_hebrew": has_hebrew(body),
            "word_count": len(body.split()),
        },
        warnings=warnings,
    )


def logical_lines(paragraphs: list[str]) -> list[str]:
    """
    Flatten paragraphs into logical lines, splitting on the newlines that came
    from `<w:br/>`. Blank entries are preserved — they carry the paragraph
    spacing that the reader renders as breathing room.
    """
    lines: list[str] = []
    for para in paragraphs:
        for line in para.split("\n"):
            lines.append(line.strip())
    return lines


class DocxProcessor:
    """Registry adapter — the upload path hands us bytes."""

    kind = "docx"

    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        return extract_docx(content)
