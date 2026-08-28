"""
Image understanding.

Not OCR. The client may upload a photograph of a printed page, a screenshot of
a WhatsApp message, or a picture that carries meaning beyond its text. So the
model is asked for a faithful transcription *and* a description of what else
is there — kept in clearly separated sections, so nothing the model observed
about the picture can later be mistaken for text the source actually contained.
"""

from __future__ import annotations

from app.logging import get_logger
from app.services.ingestion.base import ExtractionError, ExtractionResult, normalise

log = get_logger("ingestion.image")

INSTRUCTION = (
    "You are reading an image supplied as source material for a Torah lesson.\n\n"
    "Return exactly two sections, with these headings.\n\n"
    "TRANSCRIPTION:\n"
    "Every piece of text visible in the image, exactly as written. Preserve "
    "Hebrew in Hebrew script with all vowel points (nikud) intact. Preserve "
    "English exactly. Keep the original line breaks. Do not translate, correct, "
    "or tidy anything. Write [illegible] for anything you cannot read. "
    "If there is no text at all, write: (no text)\n\n"
    "DESCRIPTION:\n"
    "What the image shows, in two or three sentences — the kind of document or "
    "scene, and anything visually meaningful. Describe only what is actually "
    "visible. Do not speculate about context you cannot see."
)


# A photographed page of a printed book. Different from the general case in
# three ways that matter downstream: the running head and page number are the
# only evidence of where the text came from; footnotes carry the sources the
# body relies on; and a half-visible sentence at a page break must be marked as
# incomplete rather than silently finished, because a model completing it is
# indistinguishable from a model inventing it.
REFERENCE_PAGE_INSTRUCTION = (
    "You are transcribing a photograph of a page from a printed Jewish book, "
    "supplied by a teacher as reference material for a lesson.\n\n"
    "Return exactly two sections, with these headings.\n\n"
    "TRANSCRIPTION:\n"
    "Every word on the page, in reading order, exactly as printed. Preserve "
    "Hebrew in Hebrew script with all vowel points (nikud) intact. Keep the "
    "book title or running head and the page number if either is visible — "
    "write them on their own line at the top. Transcribe footnotes too, marked "
    "as FOOTNOTE. Where a sentence is cut off by the edge of the page or the "
    "photograph, transcribe what is there and write [cut off] — never complete "
    "it. Write [illegible] for anything you cannot read. Do not translate, "
    "correct, summarise or tidy.\n\n"
    "DESCRIPTION:\n"
    "In two or three sentences: which book and page this appears to be, if the "
    "page says so, and what the passage is about. Say plainly if the page does "
    "not identify itself. Do not infer the book from the content."
)


class ImageProcessor:
    kind = "image"

    async def extract(
        self, content: bytes, filename: str, *, purpose: str = "lesson_source"
    ) -> ExtractionResult:
        from app.llm.provider import get_provider
        from app.llm.types import LLMError

        payload, mime = prepare_for_vision(content)
        provider = get_provider()
        instruction = (
            REFERENCE_PAGE_INSTRUCTION if purpose == "reference" else INSTRUCTION
        )

        try:
            completion = await provider.describe_image(
                payload, mime_type=mime, instruction=instruction
            )
        except LLMError as exc:
            raise ExtractionError(f"We couldn't read that image: {exc}") from exc

        text = normalise(completion.text.strip())
        if not text:
            raise ExtractionError("We couldn't read anything from that image.")

        transcription, description = split_sections(text)

        return ExtractionResult(
            text=text,
            paragraphs=[line.strip() for line in text.split("\n")],
            metadata={
                "mime_type": mime,
                "transcription": transcription,
                "description": description,
                "vision_model": completion.usage.model,
                "word_count": len(text.split()),
                "purpose": purpose,
            },
            warnings=[
                "This text was read from an image. Please check the Hebrew and "
                "any quotations against the original before publishing."
            ],
        )


def split_sections(text: str) -> tuple[str, str]:
    """Separate the transcription from the description."""
    upper = text.upper()

    if "DESCRIPTION:" in upper:
        cut = upper.index("DESCRIPTION:")
        transcription = text[:cut]
        description = text[cut + len("DESCRIPTION:") :]
    else:
        transcription, description = text, ""

    # Drop a leading "TRANSCRIPTION:" heading if the model included one.
    stripped = transcription.strip()
    if stripped.upper().startswith("TRANSCRIPTION:"):
        stripped = stripped[len("TRANSCRIPTION:") :]

    return stripped.strip(), description.strip()


# The long edge, in pixels, that a page is reduced to before it is sent.
#
# 2000px keeps vocalised Hebrew comfortably legible — the marks are the fine
# detail that matters, and they survive this — while bounding what goes over
# the wire. The client photographs pages with a phone, and a modern phone photo
# is 3-8 MB, which becomes 4-11 MB once base64-encoded into a JSON body. That
# is what made a reference upload sit for six minutes and then fail on a read
# timeout, having cost three full attempts.
VISION_MAX_EDGE = 2000

# Below this, sending the original is cheaper than re-encoding it.
VISION_RECODE_ABOVE_BYTES = 400_000

JPEG_QUALITY = 85


def prepare_for_vision(content: bytes) -> tuple[bytes, str]:
    """
    Shrink a large photograph before sending it to the vision model.

    Returns the bytes to send and their mime type. Anything that cannot be
    decoded is passed through untouched: a format we cannot read here is not
    necessarily one the model cannot read, and refusing it would be a worse
    outcome than sending it as-is.
    """
    if len(content) <= VISION_RECODE_ABOVE_BYTES:
        return content, mime_for(content)

    try:
        import fitz  # PyMuPDF

        source = fitz.Pixmap(content)
        document = fitz.open(stream=content)
        page = document[0]

        longest = max(page.rect.width, page.rect.height)
        if not longest:
            return content, mime_for(content)

        # `get_pixmap` renders from the page rect, which is in points, so zoom
        # 1.0 is NOT the original pixel grid. Rendering at the image's own
        # density reproduces it exactly; anything above that would invent
        # detail, so it is the ceiling.
        native_zoom = source.width / page.rect.width
        zoom = min(native_zoom, VISION_MAX_EDGE / longest)

        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        if pixmap.alpha:
            # JPEG has no alpha channel, and leaving it makes the encode fail.
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)

        encoded = pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    except Exception:
        log.warning("vision_downscale_failed", original_bytes=len(content))
        return content, mime_for(content)

    if len(encoded) >= len(content):
        return content, mime_for(content)

    log.info(
        "vision_image_downscaled",
        before=len(content),
        after=len(encoded),
        pixels=f"{pixmap.width}x{pixmap.height}",
    )
    return encoded, "image/jpeg"


def mime_for(content: bytes) -> str:
    head = content[:16]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return "image/jpeg"
