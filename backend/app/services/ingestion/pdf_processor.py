"""
PDF extraction.

PyMuPDF for text, page by page, preserving reading order. Pages that yield
almost nothing are nearly always scans — those get rendered and read by the
vision model instead, and the admin is told exactly which pages needed it, so
they can check those rather than trusting them blindly.
"""

from __future__ import annotations

import io

from app.logging import get_logger
from app.services.ingestion.base import ExtractionError, ExtractionResult, normalise

log = get_logger("ingestion.pdf")

# Below this many characters a page is treated as scanned rather than digital.
MIN_CHARS_PER_PAGE = 20

# A scanned page costs a vision call. Cap the damage a single upload can do to
# a fixed budget — a 200-page scan would otherwise drain it in one go.
MAX_VISION_PAGES = 15

VISION_INSTRUCTION = (
    "This is a page from a Torah lesson document. Transcribe ALL text you can "
    "see, exactly as written.\n"
    "- Preserve Hebrew in Hebrew script, including every vowel point (nikud).\n"
    "- Preserve English exactly as written.\n"
    "- Keep the reading order and line breaks of the original.\n"
    "- Do not translate, summarise, correct, or comment. Transcribe only.\n"
    "- Write [illegible] for anything you cannot read, rather than guessing."
)


class PDFProcessor:
    kind = "pdf"

    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:  # pragma: no cover
            raise ExtractionError("PDF support is not installed on the server.") from exc

        try:
            document = fitz.open(stream=io.BytesIO(content), filetype="pdf")
        except Exception as exc:
            raise ExtractionError(
                "We couldn't open that PDF. It may be corrupted or password-protected."
            ) from exc

        pages: list[str] = []
        scanned: list[int] = []
        warnings: list[str] = []

        try:
            if document.needs_pass:
                raise ExtractionError("That PDF is password-protected.")

            for index in range(document.page_count):
                page = document.load_page(index)
                # "text" preserves reading order; "blocks"/"raw" do not.
                page_text = normalise(page.get_text("text") or "").strip()
                if len(page_text) < MIN_CHARS_PER_PAGE:
                    scanned.append(index)
                pages.append(page_text)

            if scanned:
                rendered = await self._read_scanned_pages(fitz, document, scanned)
                for index, text in rendered.items():
                    if text:
                        pages[index] = text

                shown = ", ".join(str(i + 1) for i in scanned[:10])
                warnings.append(
                    f"{len(scanned)} page(s) had no selectable text and were read "
                    f"with image understanding ({shown}"
                    f"{'…' if len(scanned) > 10 else ''}). "
                    f"Please check these pages carefully before publishing."
                )
                if len(scanned) > MAX_VISION_PAGES:
                    warnings.append(
                        f"Only the first {MAX_VISION_PAGES} scanned pages were read, "
                        f"to stay within the AI budget. "
                        f"{len(scanned) - MAX_VISION_PAGES} page(s) were skipped."
                    )

            page_count = document.page_count
        finally:
            document.close()

        text = "\n\n".join(p for p in pages if p.strip())
        if not text.strip():
            raise ExtractionError(
                "We couldn't find any text in that PDF, even by reading it as images."
            )

        return ExtractionResult(
            text=text,
            paragraphs=[line.strip() for line in text.split("\n")],
            metadata={
                "page_count": page_count,
                "scanned_pages": [i + 1 for i in scanned],
                "word_count": len(text.split()),
            },
            warnings=warnings,
        )

    async def _read_scanned_pages(self, fitz, document, indices: list[int]) -> dict[int, str]:
        """Render scanned pages to images and read them with the vision model."""
        from app.llm.provider import get_provider
        from app.llm.types import LLMError

        provider = get_provider()
        results: dict[int, str] = {}

        for index in indices[:MAX_VISION_PAGES]:
            try:
                page = document.load_page(index)
                # 2x scale: enough resolution for nikud to survive, without
                # sending an enormous payload.
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                image_bytes = pixmap.tobytes("png")

                completion = await provider.describe_image(
                    image_bytes,
                    mime_type="image/png",
                    instruction=VISION_INSTRUCTION,
                )
                results[index] = normalise(completion.text.strip())

            except LLMError as exc:
                # One unreadable page must not fail the whole document.
                log.warning("pdf_vision_failed", page=index + 1, error=str(exc))
                results[index] = ""
            except Exception:
                log.exception("pdf_page_render_failed", page=index + 1)
                results[index] = ""

        return results
