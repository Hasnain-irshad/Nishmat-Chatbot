"""File ingestion: turning uploaded source material into extracted text."""

from .base import ExtractionError, ExtractionResult, has_hebrew, normalise
from .corpus_parser import ParsedLesson, parse_corpus_directory, parse_corpus_file
from .docx_processor import DocxProcessor, extract_docx, logical_lines
from .registry import extract, get_processor, requires_llm, supported_kinds

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "has_hebrew",
    "normalise",
    "extract_docx",
    "logical_lines",
    "DocxProcessor",
    "ParsedLesson",
    "parse_corpus_file",
    "parse_corpus_directory",
    "extract",
    "get_processor",
    "requires_llm",
    "supported_kinds",
]
