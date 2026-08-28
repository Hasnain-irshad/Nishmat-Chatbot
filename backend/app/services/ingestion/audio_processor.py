"""
Audio transcription.

This is the client's real workflow: she records a lesson as a WhatsApp voice
note, and that recording is the source material.

The single biggest quality lever here is the vocabulary prompt. Speech models
have never seen most of this vocabulary and will confidently produce
"shiduch", "hakaras hatov", "Elul" as "a lull". Seeding the decoder with the
terms that actually recur in this series fixes the majority of those errors
for no extra cost.
"""

from __future__ import annotations

from app.logging import get_logger
from app.services.ingestion.base import ExtractionError, ExtractionResult, normalise

log = get_logger("ingestion.audio")

# OpenAI's transcription endpoint rejects files above 25 MB. At the ~19 kbps
# of a WhatsApp voice note that is roughly three hours, so in practice this is
# a guard against the wrong file being uploaded, not a real ceiling.
MAX_TRANSCRIPTION_BYTES = 24 * 1024 * 1024

# Terms drawn from the client's own corpus. Order matters little; coverage does.
GLOSSARY = (
    "Nishmat Kol Chai, Shavua tov, Motzaei Shabbat, neshamot yekarot, neshama, "
    "l'iluy nishmat, Hashem, tefillah, davening, brachot, bracha, siddur, "
    "hakarat hatov, emunah, bitachon, chesed, rachamim, gevurah, netzach, "
    "shidduch, parnassah, shalom bayit, refuah shleimah, yeshuah, yeshuot, "
    "geulah, Mashiach, Klal Yisrael, Am Yisrael, Beit Hamikdash, Kotel, "
    "zechut, segulah, simcha, mitzvah, mitzvot, Torah, Gemara, Rashi, Chazal, "
    "Tehillim, pasuk, pesukim, midrash, parashah, Elul, Adar, Purim, Pesach, "
    "Rosh Hashanah, Yom Kippur, Sukkot, Shabbat, Rebbetzin, Rav, Harav, "
    "zt\"l, a\"h, b'ezrat Hashem, baruch Hashem, Elokeinu, Melech, Go'el, Moshia"
)

PROMPT = (
    "A warm, personal Torah lesson for a women's learning group, in English "
    "with Hebrew and Yiddish terms throughout. Recurring vocabulary: "
    f"{GLOSSARY}."
)


class AudioProcessor:
    kind = "audio"

    async def extract(self, content: bytes, filename: str) -> ExtractionResult:
        from app.llm.provider import get_provider
        from app.llm.types import LLMError

        if len(content) > MAX_TRANSCRIPTION_BYTES:
            raise ExtractionError(
                f"That recording is {len(content) / 1_048_576:.0f} MB, which is over "
                f"the {MAX_TRANSCRIPTION_BYTES // 1_048_576} MB transcription limit. "
                f"Please split it into shorter recordings and upload them separately."
            )

        provider = get_provider()

        try:
            transcription = await provider.transcribe(
                content,
                filename=filename,
                language="en",  # English-led, with Hebrew terms inside it
                prompt=PROMPT,
            )
        except LLMError as exc:
            raise ExtractionError(
                f"We couldn't transcribe that recording: {exc}"
            ) from exc

        text = normalise(transcription.text.strip())
        if not text:
            raise ExtractionError(
                "The recording produced no text. It may be silent or corrupted."
            )

        # Spoken transcripts arrive as one long run of prose. Break on sentence
        # ends so the admin can actually read and correct it, and so the lesson
        # generator receives something with structure rather than a wall.
        paragraphs = _split_for_reading(text)

        warnings = [
            "This text was transcribed from audio. Please read it through and "
            "correct any Hebrew terms before generating the lesson."
        ]
        duration = transcription.duration_seconds
        if duration and len(text.split()) / max(duration / 60, 0.1) < 60:
            # Under ~60 words per minute suggests long silences or a failed
            # section, rather than natural speech.
            warnings.append(
                "The transcript looks short for the length of the recording — "
                "please check nothing is missing."
            )

        return ExtractionResult(
            text=text,
            paragraphs=paragraphs,
            metadata={
                "transcript": True,
                "language": transcription.language,
                "duration_seconds": round(duration, 1),
                "segments": transcription.segments[:500],
                "transcription_model": transcription.usage.model,
                "word_count": len(text.split()),
            },
            warnings=warnings,
        )


def _split_for_reading(text: str, sentences_per_paragraph: int = 3) -> list[str]:
    """Group a continuous transcript into readable paragraphs."""
    import re

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return [text]

    return [
        " ".join(sentences[i : i + sentences_per_paragraph])
        for i in range(0, len(sentences), sentences_per_paragraph)
    ]
