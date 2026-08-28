"""
Structured understanding of a source document.

This is stage one of generation, and it exists to keep *understanding* separate
from *writing*. A single prompt that reads a transcript and produces a finished
lesson is impossible to debug: when the output is wrong you cannot tell whether
the model misread the source or just wrote it badly. Splitting them means every
failure has an address.

The anti-fabrication rule lives here rather than in a prompt instruction. Every
quotation and statistic carries `verbatim_from_source`, and the generator is
only permitted to present something as a quotation when that flag is true. In a
Torah-learning context an invented source is not a bug to fix next sprint — it
is a reputational injury to the teacher whose name is on the lesson.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Quote(BaseModel):
    """A quotation found in the source. Never one the model recalled."""

    text: str = Field(description="The quotation, exactly as it appears in the source.")
    attribution: str | None = Field(
        default=None,
        description=(
            "Who or what the source credits — 'Rashi', 'Tehillim 20', "
            "'the Gemara'. Null if the source does not say."
        ),
    )
    verbatim_from_source: bool = Field(
        description=(
            "True ONLY if this text appears in the source material. False if you "
            "are supplying it from your own knowledge. Never guess: if unsure, false."
        )
    )


class Story(BaseModel):
    summary: str = Field(description="What happens, in one or two sentences.")
    from_source: bool = Field(
        description="True only if this story appears in the source material."
    )


class StructuredAnalysis(BaseModel):
    """What the source is about, before anything is written."""

    detected_lesson_number: int | None = Field(
        default=None,
        description="A lesson number stated in the source, or null. Never invent one.",
    )
    central_theme: str = Field(
        description="The single idea this lesson is built around, in one sentence."
    )
    hebrew_phrase: str | None = Field(
        default=None,
        description=(
            "The Hebrew phrase the lesson explores, copied character for character "
            "from the source INCLUDING every vowel point. Null if the source has none."
        ),
    )
    transliteration: str | None = Field(
        default=None,
        description="Romanised form of that phrase, if the source gives one.",
    )
    translation: str | None = Field(
        default=None, description="English meaning of that phrase, if the source gives one."
    )

    key_concepts: list[str] = Field(
        default_factory=list, description="The ideas the lesson turns on. Two to five."
    )
    main_points: list[str] = Field(
        default_factory=list,
        description="The substantive points the source actually makes, in order.",
    )
    stories: list[Story] = Field(
        default_factory=list, description="Anecdotes, images or scenes in the source."
    )
    examples: list[str] = Field(
        default_factory=list, description="Everyday examples the source uses."
    )

    torah_sources: list[Quote] = Field(
        default_factory=list,
        description=(
            "Pesukim, Gemara, midrashim or teachings cited in the source. "
            "Include ONLY what the source itself cites."
        ),
    )
    research_claims: list[Quote] = Field(
        default_factory=list,
        description="Statistics or research findings the source states.",
    )

    reflection_questions: list[str] = Field(default_factory=list)
    practical_takeaway: str | None = Field(
        default=None, description="The concrete thing the source asks the reader to do."
    )
    closing_message: str | None = Field(default=None)

    emotional_arc: str = Field(
        description=(
            "How the source moves emotionally from beginning to end — the shape the "
            "finished lesson should follow."
        )
    )
    seasonal_context: str | None = Field(
        default=None,
        description=(
            "Any time of year, festival or parashah the source refers to. "
            "Null unless the source mentions it."
        ),
    )

    source_coverage_notes: str = Field(
        description=(
            "Honest assessment: is there enough here for a full lesson? Say plainly "
            "what is thin or missing. Do not paper over a thin source."
        )
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Anything the admin should check — no Hebrew found, source very short, "
            "transcript appears garbled, contradictory statements."
        ),
    )

    # ------------------------------------------------------------------ #

    @property
    def has_usable_content(self) -> bool:
        """Enough substance to be worth generating from."""
        return bool(self.central_theme) and (
            len(self.main_points) >= 2 or len(self.stories) >= 1
        )

    def citable_sources(self) -> list[Quote]:
        """Only quotes actually present in the source may be presented as quotes."""
        return [q for q in self.torah_sources if q.verbatim_from_source]

    def citable_research(self) -> list[Quote]:
        return [q for q in self.research_claims if q.verbatim_from_source]

    def fabrication_risks(self) -> list[str]:
        """Anything the model supplied from memory rather than reading."""
        risks = []
        for quote in self.torah_sources:
            if not quote.verbatim_from_source:
                risks.append(f"Torah source not in the material: {quote.text[:80]}")
        for claim in self.research_claims:
            if not claim.verbatim_from_source:
                risks.append(f"Research claim not in the material: {claim.text[:80]}")
        for story in self.stories:
            if not story.from_source:
                risks.append(f"Story not in the material: {story.summary[:80]}")
        return risks


def analysis_json_schema() -> dict:
    """
    Strict JSON schema for OpenAI Structured Outputs.

    `strict` mode requires every property to appear in `required` and forbids
    additional properties, so optional fields are expressed as nullable rather
    than omitted.
    """
    schema = StructuredAnalysis.model_json_schema()
    _make_strict(schema)
    return {
        "name": "structured_analysis",
        "strict": True,
        "schema": schema,
    }


def _make_strict(node: dict) -> None:
    """Walk the schema making it acceptable to strict Structured Outputs."""
    if not isinstance(node, dict):
        return

    if node.get("type") == "object" or "properties" in node:
        node["additionalProperties"] = False
        properties = node.get("properties", {})
        node["required"] = list(properties.keys())
        for child in properties.values():
            _make_strict(child)

    for key in ("items", "$defs", "definitions"):
        value = node.get(key)
        if isinstance(value, dict):
            if key in ("$defs", "definitions"):
                for child in value.values():
                    _make_strict(child)
            else:
                _make_strict(value)

    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key, []) or []:
            _make_strict(child)
