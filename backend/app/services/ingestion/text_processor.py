"""Plain text and Markdown."""

from __future__ import annotations

from app.services.ingestion.base import ExtractionError, ExtractionResult, normalise


class TextProcessor:
    kind = "text"

    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        text = None
        used = None

        # UTF-8 first — everything the client produces is UTF-8. The fallbacks
        # exist for files that have been through an older Windows editor, where
        # cp1255 is the Hebrew codepage.
        for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1255", "cp1252"):
            try:
                text = content.decode(encoding)
                used = encoding
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if text is None:
            raise ExtractionError("We couldn't read the text in that file.")

        text = normalise(text)

        warnings = []
        if used not in ("utf-8", "utf-8-sig"):
            warnings.append(
                f"This file was not UTF-8 (read as {used}). "
                f"Please check any Hebrew reads correctly."
            )

        return ExtractionResult(
            text=text,
            paragraphs=[line.strip() for line in text.split("\n")],
            metadata={"encoding": used, "word_count": len(text.split())},
            warnings=warnings,
        )
