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
