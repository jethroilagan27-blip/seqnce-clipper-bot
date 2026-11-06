"""Runs one job through the processing stages.

Add new stages (transcribe, analyze, plan, edit, render) to PIPELINE as they
are built. Each stage is a function `(job: dict) -> None` that reads/writes the
job via `db` and raises `media.MediaError` (user-safe message) on failure.

A *revision* (chat message, hand edit, restore) re-uses everything computed for the
job and only runs revise (chat only) -> editor -> render. A failed revision never
destroys the version the user already has.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .. import db, stages
from ..errors import PipelineError
from ..plan.diff import diff_plans
from . import editor, planner, prepare, render, revise, transcribe, visual

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

RENDER_STAGES: list[Stage] = [(stages.EDITING, editor.run), (stages.RENDERING, render.run)]


def _run_stages(job_id: str, job: dict[str, Any], plan: list[Stage]) -> str:
    last_stage = stages.UPLOADED
    for stage_name, stage_fn in plan:
        last_stage = stage_name
        db.update_job(job_id, stage=stage_name, progress=stages.STAGE_PROGRESS[stage_name])
        stage_fn(db.get_job(job_id) or job)
    return last_stage


def record_initial_version(job_id: str) -> None:
    job = db.get_job(job_id) or {}
    if job.get("plan_json") and job.get("output_path") and db.latest_version_number(job_id) == 0:
        db.add_version(
            job_id, 1, plan=job["plan_json"], source="initial",
            message=(job.get("settings_json") or {}).get("instructions") or None,
            output_path=job["output_path"], output_metadata=job.get("output_metadata_json"),
        )
        db.update_job(job_id, current_version=1)


def run_job(job: dict[str, Any]) -> None:
    if job.get("revision_json"):
        _run_revision(job)
        return

    job_id = job["id"]
    log.info("job %s: started", job_id)
    last_stage = stages.UPLOADED
    try:
        last_stage = _run_stages(job_id, job, PIPELINE)

        # Stages that produce the final video set output_path; until the render
        # stage exists a job simply ends after its last implemented stage.
        finished = db.get_job(job_id) or {}
        if finished.get("output_path"):
            record_initial_version(job_id)
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


def _run_revision(job: dict[str, Any]) -> None:
    job_id = job["id"]
    revision = job["revision_json"]
    kind = revision["kind"]  # chat | manual | restore
    base_number = db.latest_version_number(job_id)
    if base_number == 0:  # job finished before versions existed
        record_initial_version(job_id)
        base_number = db.latest_version_number(job_id)
    base = db.get_version(job_id, int(job.get("current_version") or base_number)) or {}
    log.info("job %s: %s revision started (from v%s)", job_id, kind, base.get("version"))

    try:
        if not base.get("plan_json"):
            raise PipelineError("This video's earlier version is missing, so it can't be changed.")
        if kind == "restore":
            # Going back needs no render: the old version's file is still on disk.
            src = db.get_version(job_id, int(revision["from_version"])) or {}
            if src.get("output_path") and Path(src["output_path"]).is_file():
                _finish_revision(job_id, base, revision, kind, reuse_from=src)
                return
        if kind == "chat":
            _run_stages(job_id, job, [(stages.REVISING, revise.run)])
            revised = db.get_job(job_id) or job
            revision = revised["revision_json"]
            if diff_plans(base["plan_json"], revised["plan_json"])["unchanged"]:
                # The AI decided nothing needed changing: keep the same video, just record the answer.
                _finish_revision(job_id, base, revision, kind, reuse_from=base)
                return
        _run_stages(job_id, job, RENDER_STAGES)
        _finish_revision(job_id, base, revision, kind, reuse_from=None)
    except Exception as exc:
        if isinstance(exc, PipelineError):
            log.error("job %s: %s revision failed: %s", job_id, kind, exc)
            message = str(exc)
        else:
            log.exception("job %s: %s revision crashed", job_id, kind)
            message = "Something went wrong while applying that change. Your current version is untouched."
        # Put the job back exactly as it was: same plan, same output, just a note about what failed.
        restore = (
            {"plan_json": base["plan_json"], "output_path": base.get("output_path"),
             "output_metadata_json": base.get("output_metadata_json")}
            if base.get("plan_json") else {}
        )
        db.update_job(
            job_id, **restore,
            status=stages.COMPLETED, stage=stages.COMPLETED, progress=100,
            revision_json=None, error=message,
        )


def _finish_revision(
    job_id: str, base: dict[str, Any], revision: dict[str, Any], kind: str, *, reuse_from: dict[str, Any] | None
) -> None:
    done = db.get_job(job_id) or {}
    number = db.latest_version_number(job_id) + 1
    plan = done["plan_json"]
    if reuse_from is not None:  # nothing to re-render: the new version points at an existing file
        output_path, output_meta = reuse_from.get("output_path"), reuse_from.get("output_metadata_json")
    else:
        output_path, output_meta = done["output_path"], done.get("output_metadata_json")
    db.add_version(
        job_id, number, plan=plan, source=kind,
        message=revision.get("message"), reply=revision.get("reply"),
        changes=diff_plans(base["plan_json"], plan),
        output_path=output_path, output_metadata=output_meta,
    )
    db.update_job(
        job_id, status=stages.COMPLETED, stage=stages.COMPLETED, progress=100,
        current_version=number, revision_json=None, error=None,
        output_path=output_path, output_metadata_json=output_meta,
    )
    log.info("job %s: now at version %d", job_id, number)
