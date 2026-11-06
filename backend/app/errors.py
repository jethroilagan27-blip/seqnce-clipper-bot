"""Shared exception types.

`PipelineError` messages are written for end users and are shown in the UI.
Anything that is *not* a PipelineError is treated as a bug: logged with a
traceback and replaced by a generic message.
"""

from __future__ import annotations


class PipelineError(Exception):
    """A processing step failed in an expected way (safe to show to the user)."""
