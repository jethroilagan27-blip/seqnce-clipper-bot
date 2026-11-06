"""Runs one job through the processing stages.

Add new stages (transcribe, analyze, plan, edit, render) to PIPELINE as they
are built. Each stage is a function `(job: dict) -> None` that reads/writes the
job via `db` and raises `media.MediaError` (user-safe message) on failure.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .. import db, stages
from ..errors import PipelineError
from . import editor, planner, prepare, render, transcribe, visual

log = logging.getLogger(__name__)

Stage = tuple[str, Callable[[dict[str, Any]], None]]

PIPELINE: list[Stage] = [
    (stages.PREPARING, prepare.run),
    (stages.TRANSCRIBING, transcribe.run),
    (stages.ANALYZING_VISUALS, visual.run),
    (stages.PLANNING, planner.run),
    (stages.EDITING, editor.run),
    (stages.RENDERING, render.run),
]


def run_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    log.info("job %s: started", job_id)
    last_stage = stages.UPLOADED
    try:
        for stage_name, stage_fn in PIPELINE:
            last_stage = stage_name
            db.update_job(
                job_id, stage=stage_name, progress=stages.STAGE_PROGRESS[stage_name]
            )
            stage_fn(db.get_job(job_id) or job)

        # Stages that produce the final video set output_path; until the render
        # stage exists a job simply ends after its last implemented stage.
        finished = db.get_job(job_id) or {}
        if finished.get("output_path"):
            db.update_job(
                job_id, status=stages.COMPLETED, stage=stages.COMPLETED, progress=100
            )
        else:
            db.update_job(job_id, status=stages.COMPLETED, stage=last_stage)
        log.info("job %s: finished", job_id)
    except PipelineError as exc:
        log.error("job %s failed in stage %s: %s", job_id, last_stage, exc)
        db.update_job(job_id, status=stages.FAILED, error=str(exc))
    except Exception:
        log.exception("job %s crashed in stage %s", job_id, last_stage)
        db.update_job(
            job_id,
            status=stages.FAILED,
            error="Something went wrong while processing this video. Check the server log.",
        )
