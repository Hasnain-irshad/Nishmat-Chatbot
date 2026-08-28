"""
Processor registry.

One lookup, one place to add a format. Nothing downstream branches on file
type — it asks the registry for a processor and gets text back.
"""

from __future__ import annotations

from app.services.ingestion.audio_processor import AudioProcessor
from app.services.ingestion.base import ExtractionError, ExtractionResult, FileProcessor
from app.services.ingestion.docx_processor import DocxProcessor
from app.services.ingestion.image_processor import ImageProcessor
from app.services.ingestion.pdf_processor import PDFProcessor
from app.services.ingestion.text_processor import TextProcessor

_PROCESSORS: dict[str, FileProcessor] = {
    "pdf": PDFProcessor(),
    "docx": DocxProcessor(),
    "text": TextProcessor(),
    "image": ImageProcessor(),
    "audio": AudioProcessor(),
}

# Which formats need a model call, and are therefore unavailable until the
# OpenAI key is configured. Used to fail early with a useful message rather
# than partway through a job.
_REQUIRES_LLM = {"image", "audio"}


def get_processor(kind: str) -> FileProcessor:
    processor = _PROCESSORS.get(kind)
    if processor is None:
        raise ExtractionError(f"We don't support {kind} files yet.")
    return processor


def requires_llm(kind: str) -> bool:
    return kind in _REQUIRES_LLM


def supported_kinds() -> list[str]:
    return sorted(_PROCESSORS)


async def extract(
    kind: str, content: bytes, filename: str, *, purpose: str = "lesson_source"
) -> ExtractionResult:
    """
    Extract text from an uploaded file of a known kind.

    `purpose` says what the file IS, so a processor that can read differently
    does. A photograph of a book page wants its running head, its page number
    and its footnotes kept; the same photograph attached as a lesson's own
    material does not. Processors that cannot use the distinction ignore it,
    which is why it is passed only where it is accepted rather than added to
    the protocol.
    """
    processor = get_processor(kind)
    if purpose != "lesson_source" and _accepts_purpose(processor):
        return await processor.extract(content, filename, purpose=purpose)
    return await processor.extract(content, filename)


def _accepts_purpose(processor: FileProcessor) -> bool:
    import inspect

    try:
        return "purpose" in inspect.signature(processor.extract).parameters
    except (TypeError, ValueError):  # pragma: no cover — builtins, C callables
        return False
