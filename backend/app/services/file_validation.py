"""
Upload validation.

The file's real type is decided by its **content**, never by its extension or
the `Content-Type` the browser claims. Both of those are attacker-controlled;
the magic bytes are not.

A dependency-free sniffer rather than python-magic: we only need to recognise
a known, small set of formats, and libmagic is an awkward native dependency to
carry onto a Linux container from a Windows dev machine.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from io import BytesIO

from app.config import get_settings

# The only kinds the pipeline understands. Anything else is refused.
SourceKind = str  # "pdf" | "docx" | "audio" | "image" | "text"

EXTENSION_KIND: dict[str, SourceKind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".txt": "text",
    ".md": "text",
    ".rtf": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".heic": "image",
    ".mp3": "audio",
    ".m4a": "audio",
    ".wav": "audio",
    ".ogg": "audio",
    ".oga": "audio",
    ".opus": "audio",
    ".mp4": "audio",
    ".mpeg": "audio",
    ".mpga": "audio",
    ".webm": "audio",
}


class ValidationError(Exception):
    """The upload was refused. The message is safe to show a person."""


@dataclass(frozen=True)
class ValidatedFile:
    filename: str
    kind: SourceKind
    mime_type: str
    size_bytes: int
    checksum_sha256: str


def _extension(filename: str) -> str:
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext and ext != filename else ""


def sniff(content: bytes) -> tuple[SourceKind, str] | None:
    """
    Identify a file from its leading bytes. Returns (kind, mime) or None.
    """
    if len(content) < 12:
        return None

    head = content[:16]

    # ---- documents ----
    if head.startswith(b"%PDF-"):
        return "pdf", "application/pdf"

    if head.startswith(b"PK\x03\x04"):
        # A DOCX is a ZIP. Confirm it actually contains a Word document rather
        # than trusting the container — a .zip renamed to .docx is not a docx.
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return "docx", (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            )
        return None

    # ---- images ----
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif"
    if head.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image", "image/webp"
    if content[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image", "image/heic"

    # ---- audio ----
    if head.startswith(b"OggS"):
        # WhatsApp voice notes are Ogg/Opus — the client's actual format.
        return "audio", "audio/ogg"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio", "audio/mpeg"
    if head.startswith(b"RIFF") and content[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if head.startswith(b"fLaC"):
        return "audio", "audio/flac"
    if content[4:8] == b"ftyp":
        # M4A/MP4 container. Audio-only in practice for this product.
        return "audio", "audio/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "audio", "audio/webm"

    # ---- text ----
    if _looks_like_text(content):
        return "text", "text/plain"

    return None


def _looks_like_text(content: bytes) -> bool:
    """UTF-8 decodable with no control characters beyond normal whitespace."""
    sample = content[:4096]
    if b"\x00" in sample:
        return False
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            decoded = sample.decode("utf-16")
        except UnicodeDecodeError:
            return False
    control = sum(
        1 for ch in decoded if ord(ch) < 32 and ch not in "\n\r\t\f\v"
    )
    return control / max(len(decoded), 1) < 0.02


def validate(filename: str, content: bytes) -> ValidatedFile:
    """
    Validate an upload, or raise ValidationError with a message a person can act on.
    """
    settings = get_settings()

    if not content:
        raise ValidationError("That file is empty.")

    sniffed = sniff(content)
    if sniffed is None:
        raise ValidationError(
            "We couldn't read that file. Supported formats are PDF, Word (.docx), "
            "images, audio recordings, and plain text."
        )

    kind, mime = sniffed

    # The extension does not decide the type, but a mismatch is worth catching:
    # it usually means the person picked the wrong file.
    extension = _extension(filename)
    claimed = EXTENSION_KIND.get(extension)
    if claimed and claimed != kind:
        raise ValidationError(
            f"That file is named like a {claimed} file but its contents are "
            f"{kind}. Please check you picked the right file."
        )

    limit = settings.max_upload_bytes(kind)
    if len(content) > limit:
        raise ValidationError(
            f"That file is {len(content) / 1_048_576:.1f} MB, which is over the "
            f"{limit // 1_048_576} MB limit for {kind} files."
        )

    safe_name = sanitise_filename(filename)

    return ValidatedFile(
        filename=safe_name,
        kind=kind,
        mime_type=mime,
        size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
    )


def sanitise_filename(filename: str) -> str:
    """
    Strip any path components and control characters.

    The original name is only ever shown back to the admin — it never becomes
    the storage key, which is a generated UUID path — but a filename carrying
    `../` or a newline still has no business in our database or our logs.
    """
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    name = name.lstrip(".") or "upload"
    return name[:200]
