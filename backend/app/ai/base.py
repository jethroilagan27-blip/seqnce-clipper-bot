"""Provider-agnostic AI interface.

Everything outside `app/ai/` talks to `AIProvider` only, so Gemini can be
swapped for another vision/LLM provider by adding one class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..errors import PipelineError

T = TypeVar("T", bound=BaseModel)


class AIError(PipelineError):
    """AI call failed (quota, network, malformed output...). Message is user-safe."""


@dataclass
class LabeledImage:
    label: str  # e.g. "Frame at 12.0s" - shown to the model before the image
    jpeg: bytes


class AIProvider(Protocol):
    name: str

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        images: list[LabeledImage] | None = None,
    ) -> T:
        """Return `response_model` parsed from the model's JSON output, or raise AIError."""
        ...
