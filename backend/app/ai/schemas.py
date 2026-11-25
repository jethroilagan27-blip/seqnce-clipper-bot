"""Structured outputs we ask the AI for. Constraints are enforced in Python
(clamping/validation), not via JSON-schema keywords, to stay provider-neutral."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProposedClip(BaseModel):
    start: float = Field(description="Start time in seconds, taken from a transcript segment start")
    end: float = Field(description="End time in seconds, taken from a transcript segment end")
    purpose: Literal["hook", "main_content", "example", "conclusion"]
    reason: str = Field(description="One short sentence: why this part is worth keeping")


class PlanProposal(BaseModel):
    """What we ask the AI for when planning the edit."""

    main_subject: str
    main_message: str = Field(description="The one-sentence takeaway of the video")
    clips: list[ProposedClip]
    hook_text: str = Field(
        default="",
        description="A punchy on-screen title of at most 7 words that makes people keep watching",
    )
    hook_color: Literal["yellow", "white", "red", "cyan", "green", "pink", "orange"] = Field(
        default="yellow", description="Title colour that suits the mood of the video"
    )


class RevisionProposal(BaseModel):
    """What we ask the AI for when the user requests a change to an existing edit."""

    reply: str = Field(
        description="One or two friendly sentences telling the user what you changed (or why you could not)"
    )
    clips: list[ProposedClip] = Field(
        description="The COMPLETE new list of clips to keep. Clips the user did not ask to change keep their exact start/end"
    )
    hook_enabled: bool = Field(description="Whether the title at the top is shown")
    hook_text: str = Field(description="Title of at most 7 words (the current one unless the user wants it changed)")
    hook_color: Literal["yellow", "white", "red", "cyan", "green", "pink", "orange"]
    captions_enabled: bool
    target_duration: int = Field(
        description="Aimed-for total length in seconds (15-90). Keep the current value unless the user asks for another length"
    )


class RankedMoment(BaseModel):
    """The AI's opinion of one candidate moment of a highlight video. Every field is required, so none is skipped."""

    id: int = Field(description="The moment's number, exactly as labelled")
    score: int = Field(description="0 = boring or unusable, 10 = a must-have highlight")
    label: str = Field(description="What happens, in at most 6 words")
    focus_x: float = Field(description="Where the action is horizontally: 0 = left edge, 0.5 = middle, 1 = right edge")


class HighlightProposal(BaseModel):
    """What we ask the AI for when making a highlight video."""

    main_subject: str = Field(description="What the footage is, one short phrase")
    moments: list[RankedMoment] = Field(description="One entry for EVERY moment shown")
    hook_text: str = Field(description="A punchy on-screen title of at most 7 words, true to what is shown")
    hook_color: Literal["yellow", "white", "red", "cyan", "green", "pink", "orange"]


class HighlightRevision(HighlightProposal):
    """The same, when the user asks to change an existing highlight video."""

    reply: str = Field(description="One or two friendly sentences telling the user what you changed (or why you could not)")
    target_duration: int = Field(description="Wanted total length in seconds (15-90). Keep the current value unless asked for another")
    hook_enabled: bool = Field(description="Whether the title at the top is shown")


class VisualMoment(BaseModel):
    time_s: float
    description: str


class VisualAnalysis(BaseModel):
    main_subject: str = Field(description="Who/what the footage is about, one short phrase")
    speaker_visible: bool
    framing: Literal["close_up", "medium", "wide", "no_person"]
    speaker_focus_x: float = Field(
        description="Horizontal centre of the main speaker as a fraction of frame width (0=left, 1=right)"
    )
    suitable_for_vertical: bool = Field(
        description="True if a centred 9:16 crop keeps the speaker fully in frame"
    )
    notable_moments: list[VisualMoment] = Field(default_factory=list)
