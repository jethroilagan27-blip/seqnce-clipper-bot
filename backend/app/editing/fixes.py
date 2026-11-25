"""A correction to the captions: "between these two moments of the ORIGINAL video, the words are these".

Kept apart from the transcript, so what Whisper heard is never overwritten, and tied to source times, so a correction
survives trimming and re-ordering of the cuts. Empty text hides the captions for that stretch.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_FIXES = 200
MAX_FIX_CHARS = 600


class CaptionFix(BaseModel):
    start: float = Field(ge=0, le=100_000)
    end: float = Field(gt=0, le=100_000)
    text: str = Field(default="", max_length=MAX_FIX_CHARS)

    @field_validator("text")
    @classmethod
    def _plain_one_line(cls, value: str) -> str:
        return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())

    @model_validator(mode="after")
    def _in_order(self) -> "CaptionFix":
        if self.end <= self.start:
            raise ValueError("a correction must end after it starts")
        return self
