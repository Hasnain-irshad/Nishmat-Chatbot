"""
Upload validation and file extraction.

Pure unit tests — no database, no network, no API key. They run in under a
second and cost nothing, which is the point: the expensive, budget-consuming
paths are exercised through the mock provider.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.services import file_validation as fv
from app.services.ingestion.base import has_hebrew, hebrew_ratio, normalise

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "Data"
AUDIO = ROOT / "Audios"

# A real vocalised phrase from the client's corpus.
VOCALISED = "הַמְנַהֵג עוֹלָמוֹ בְּחֶסֶד וּבְרִיּוֹתָיו בְּרַחֲמִים"


# ------------------------------------------------------------------ Hebrew


def test_normalise_preserves_nikud_exactly():
    """
    The single most destructive thing this pipeline could do is quietly strip
    vowel points. NFKD or naive accent-removal would; NFC does not.
    """
    assert normalise(VOCALISED) == VOCALISED
    assert len(normalise(VOCALISED)) == len(VOCALISED)


def test_normalise_collapses_word_artifacts():
    assert normalise("a\u00a0b") == "a b"
    assert normalise("a\u200bb") == "ab"


def test_hebrew_detection():
    assert has_hebrew(VOCALISED)
    assert not has_hebrew("Shavua tov, neshamot yekarot.")
    assert hebrew_ratio(VOCALISED) == 1.0
    assert hebrew_ratio("Hallel v'Zimrah") == 0.0
    # The common corpus shape: Hebrew plus an English gloss.
    mixed = f"{VOCALISED} - Who guides His world with kindness"
    assert 0.0 < hebrew_ratio(mixed) < 1.0


# -------------------------------------------------------------- validation


def _docx_bytes() -> bytes:
    return (DATA / "Nishmat #17.docx").read_bytes()


def test_sniffs_a_real_docx():
    kind, mime = fv.sniff(_docx_bytes())
    assert kind == "docx"
    assert "wordprocessingml" in mime


def test_sniffs_a_real_ogg_voice_note():
    files = sorted(AUDIO.glob("*.ogg"))
    if not files:
        pytest.skip("no audio samples present")
    kind, mime = fv.sniff(files[0].read_bytes())
    assert kind == "audio"
    assert mime == "audio/ogg"


def test_sniffs_pdf_png_jpeg_and_text():
    assert fv.sniff(b"%PDF-1.7\n" + b"x" * 32)[0] == "pdf"
    assert fv.sniff(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)[0] == "image"
    assert fv.sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 32)[0] == "image"
    assert fv.sniff("Shavua tov, neshamot.\n".encode() * 4)[0] == "text"


def test_a_zip_renamed_to_docx_is_refused():
    """
    A DOCX is a ZIP, so the container alone proves nothing. Without checking
    for word/document.xml, any archive would be accepted as a document.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "not a document")

    assert fv.sniff(buffer.getvalue()) is None

    with pytest.raises(fv.ValidationError):
        fv.validate("pretend.docx", buffer.getvalue())


def test_extension_cannot_override_content():
    """The extension is a hint from the client, and the client can lie."""
    with pytest.raises(fv.ValidationError) as exc:
        fv.validate("lesson.pdf", _docx_bytes())
    assert "check you picked the right file" in str(exc.value)


def test_empty_and_unknown_files_are_refused():
    with pytest.raises(fv.ValidationError):
        fv.validate("empty.txt", b"")
    with pytest.raises(fv.ValidationError):
        fv.validate("thing.bin", b"\x00\x01\x02\x03" * 64)


def test_oversized_upload_is_refused():
    from app.config import get_settings

    limit = get_settings().max_upload_bytes("image")
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (limit + 1024)
    with pytest.raises(fv.ValidationError) as exc:
        fv.validate("huge.png", oversized)
    assert "over the" in str(exc.value)


def test_validate_returns_a_stable_checksum():
    content = _docx_bytes()
    first = fv.validate("Nishmat #17.docx", content)
    second = fv.validate("renamed.docx", content)
    # Dedupe is by content, so a rename must not defeat it.
    assert first.checksum_sha256 == second.checksum_sha256
    assert first.kind == "docx"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\lesson.docx", "lesson.docx"),
        ("....docx", "docx"),
        ("", "upload"),
    ],
)
def test_filenames_are_sanitised(raw, expected):
    assert fv.sanitise_filename(raw) == expected


def test_storage_keys_never_contain_the_filename():
    """
    Keys are opaque UUID paths. That removes traversal, collisions, and the
    question of what to do with a Hebrew filename, in one decision.
    """
    from app.services import storage

    key = storage.build_key("audio", "רחל שיעור.ogg")
    assert key.startswith("audio/")
    assert "רחל" not in key
    assert ".." not in key
    assert storage.build_key("audio", "a.ogg") != storage.build_key("audio", "a.ogg")


# -------------------------------------------------------------- extraction


@pytest.mark.asyncio
async def test_docx_processor_reads_a_real_lesson():
    from app.services.ingestion import registry

    result = await registry.extract("docx", _docx_bytes(), "Nishmat #17.docx")

    assert result.word_count > 400
    assert result.has_hebrew
    # The lesson's actual phrase must survive extraction with nikud intact.
    assert "הַמְנַהֵג" in result.text


@pytest.mark.asyncio
async def test_text_processor_handles_utf8_and_flags_other_encodings():
    from app.services.ingestion import registry

    result = await registry.extract("text", VOCALISED.encode("utf-8"), "a.txt")
    assert result.text == VOCALISED
    assert not result.warnings

    latin = await registry.extract("text", "Shavua tov".encode("cp1252"), "b.txt")
    assert "Shavua tov" in latin.text


@pytest.mark.asyncio
async def test_audio_extraction_runs_on_the_mock_provider():
    """
    Proves the audio path is wired end to end without spending anything.

    `conftest.force_mock_llm` pins LLM_MODE to mock for the whole session, so
    this exercises the real code path against fixtures no matter what
    backend/.env is currently set to.
    """
    from app.config import get_settings
    from app.services.ingestion import registry

    assert get_settings().llm_mode == "mock"

    files = sorted(AUDIO.glob("*.ogg"))
    if not files:
        pytest.skip("no audio samples present")

    result = await registry.extract("audio", files[0].read_bytes(), files[0].name)

    assert result.text
    assert result.metadata["transcript"] is True
    assert any("transcribed from audio" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_oversized_audio_is_refused_before_any_api_call():
    from app.services.ingestion.audio_processor import MAX_TRANSCRIPTION_BYTES
    from app.services.ingestion.base import ExtractionError
    from app.services.ingestion import registry

    too_big = b"OggS" + b"\x00" * MAX_TRANSCRIPTION_BYTES
    with pytest.raises(ExtractionError) as exc:
        await registry.extract("audio", too_big, "long.ogg")
    assert "split it" in str(exc.value)


def test_registry_covers_every_supported_kind():
    from app.services.ingestion import registry

    assert set(registry.supported_kinds()) == {"pdf", "docx", "text", "image", "audio"}
    # These need a model call, so they must be declared as such.
    assert registry.requires_llm("audio")
    assert registry.requires_llm("image")
    assert not registry.requires_llm("docx")


# ------------------------------------------------------------------ budget


@pytest.mark.asyncio
async def test_mock_provider_costs_nothing():
    """
    Development must be incapable of spending the client's budget. Every mock
    usage record has to be exactly zero.
    """
    from app.llm.mock_provider import MockProvider
    from app.llm.types import Message

    provider = MockProvider()
    completion = await provider.complete(
        [Message(role="user", content="hello")], operation="generation"
    )
    embeddings = await provider.embed(["hello"])

    assert completion.usage.estimated_cost == 0.0
    assert embeddings.usage.estimated_cost == 0.0


def test_unknown_models_are_priced_pessimistically():
    """
    Pricing an unrecognised model at zero would silently disable the budget
    cap — the worst possible failure for a fixed budget.
    """
    from app.llm import pricing

    assert pricing.chat_cost("some-future-model", 1_000_000, 1_000_000) > 0
    assert pricing.audio_cost("some-future-transcriber", 600) > 0
    assert not pricing.is_known("some-future-model")


def test_dated_model_suffixes_resolve_to_a_known_rate():
    from app.llm import pricing

    exact = pricing.chat_cost("gpt-4.1-mini", 1000, 1000)
    dated = pricing.chat_cost("gpt-4.1-mini-2025-04-14", 1000, 1000)
    assert exact == dated
