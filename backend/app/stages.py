"""Processing stages shared by the worker and (mirrored in) the frontend.

`progress` is the percentage shown once a job *enters* that stage.
"""

from __future__ import annotations

UPLOADED = "uploaded"
PREPARING = "preparing"
TRANSCRIBING = "transcribing"
ANALYZING_VISUALS = "analyzing_visuals"
PLANNING = "planning"
EDITING = "editing"
RENDERING = "rendering"
COMPLETED = "completed"

STAGE_PROGRESS: dict[str, int] = {
    UPLOADED: 5,
    PREPARING: 10,
    TRANSCRIBING: 25,
    ANALYZING_VISUALS: 45,
    PLANNING: 60,
    EDITING: 75,
    RENDERING: 90,
    COMPLETED: 100,
}

QUEUED = "queued"
RUNNING = "running"
FAILED = "failed"
# status values: queued | running | completed | failed
