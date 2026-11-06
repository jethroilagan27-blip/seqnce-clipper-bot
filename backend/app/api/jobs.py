"""Job status, versions and revision endpoints."""

from __future__ import annotations

from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, HTTPException, Path

from .. import db, stages
from ..pipeline.runner import record_initial_version
from ..pipeline.transcribe import load_transcript
from ..plan.manual import ManualEditError, apply_manual_edit
from ..plan.text import clean_instructions
from ..schemas import (
    EditSettings,
    JobOut,
    ResultOut,
    RevisionRequest,
    RevisionStarted,
    VideoInfo,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

JOB_ID = Path(pattern=r"^[0-9a-f]{32}$", description="Job id returned by the upload")


def _video_info(meta: dict[str, Any] | None) -> VideoInfo | None:
    return VideoInfo(**{k: meta[k] for k in VideoInfo.model_fields if k in meta}) if meta else None


def to_job_out(job: dict[str, Any]) -> JobOut:
    return JobOut(
        id=job["id"],
        status=job["status"],
        stage=job["stage"],
        progress=job["progress"],
        original_filename=job["original_filename"],
        settings=EditSettings(**job["settings_json"]),
        original=_video_info(job.get("metadata_json")),
        has_output=bool(job.get("output_path")),
        current_version=int(job.get("current_version") or 1),
        revising=bool(job.get("revision_json")),
        error=job.get("error"),
        created_at=job["created_at"],
        updated_at=job["updated_at"],
    )


def get_job_or_404(job_id: str) -> dict[str, Any]:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str = JOB_ID) -> JobOut:
    return to_job_out(get_job_or_404(job_id))


@router.get("/{job_id}/analysis")
def get_analysis(job_id: str = JOB_ID) -> dict[str, Any]:
    """Transcript + visual analysis produced so far (for debugging/inspection)."""
    job = get_job_or_404(job_id)
    if not job.get("transcript_path"):
        raise HTTPException(status_code=409, detail="Analysis is not ready yet")
    return {
        "transcript": load_transcript(job),
        "visual": job.get("visual_json"),
        "plan": job.get("plan_json"),
    }


@router.get("/{job_id}/result", response_model=ResultOut)
def get_result(job_id: str = JOB_ID) -> ResultOut:
    job = get_job_or_404(job_id)
    if job["status"] == stages.FAILED:
        raise HTTPException(status_code=409, detail=job.get("error") or "Job failed")
    revising = bool(job.get("revision_json")) and bool(job.get("output_path"))  # previous version stays viewable
    if (job["status"] != stages.COMPLETED and not revising) or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="Result is not ready yet")
    return ResultOut(
        job_id=job_id,
        version=int(job.get("current_version") or 1),
        original=_video_info(job.get("metadata_json")),
        rendered=_video_info(job.get("output_metadata_json")),
        plan=job.get("plan_json"),
        preview_url=f"/api/videos/{job_id}/preview",
        download_url=f"/api/videos/{job_id}/download",
    )


def _finished_job_or_409(job_id: str) -> dict[str, Any]:
    job = get_job_or_404(job_id)
    if job["status"] != stages.COMPLETED or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="The edit isn't finished yet.")
    if db.latest_version_number(job_id) == 0:  # finished before versions existed
        record_initial_version(job_id)
        job = get_job_or_404(job_id)
    return job


@router.get("/{job_id}/versions")
def get_versions(job_id: str = JOB_ID) -> dict[str, Any]:
    """Every render of this job, oldest first, with the chat message and the diff that made it."""
    job = get_job_or_404(job_id)
    if not job.get("output_path"):
        raise HTTPException(status_code=409, detail="The edit isn't finished yet.")
    if db.latest_version_number(job_id) == 0:  # finished before versions existed
        record_initial_version(job_id)
        job = get_job_or_404(job_id)
    current = int(job.get("current_version") or 1)
    versions = []
    for v in db.list_versions(job_id):
        has_output = bool(v.get("output_path")) and FsPath(v["output_path"]).is_file()
        n = v["version"]
        versions.append({
            "version": n,
            "source": v["source"],
            "message": v.get("message"),
            "reply": v.get("reply"),
            "created_at": v["created_at"],
            "plan": v["plan_json"],
            "changes": v.get("changes_json"),
            "has_output": has_output,
            "preview_url": f"/api/videos/{job_id}/preview?version={n}" if has_output else None,
            "download_url": f"/api/videos/{job_id}/download?version={n}" if has_output else None,
        })
    return {"current": current, "versions": versions}


@router.post("/{job_id}/revisions", response_model=RevisionStarted, status_code=202)
def create_revision(body: RevisionRequest, job_id: str = JOB_ID) -> RevisionStarted:
    """Ask for a change (chat message), edit by hand, or go back to an earlier version.

    Returns immediately; poll GET /api/jobs/{id} (status/stage/progress), then GET .../versions.
    """
    job = _finished_job_or_409(job_id)
    if job.get("revision_json"):
        raise HTTPException(status_code=409, detail="Another change is still being applied.")
    new_number = db.latest_version_number(job_id) + 1
    plan: dict[str, Any] | None = None

    if body.message is not None:
        text = clean_instructions(body.message)
        if not text:
            raise HTTPException(status_code=422, detail="Type what you'd like changed.")
        revision = {"kind": "chat", "message": text}
        stage = stages.REVISING
    elif body.edit is not None:
        try:
            plan, description = apply_manual_edit(job["plan_json"], body.edit)
        except ManualEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if description == "No changes":
            raise HTTPException(status_code=422, detail="That doesn't change anything.")
        revision = {"kind": "manual", "message": description}
        stage = stages.EDITING
    else:
        assert body.restore_version is not None
        target = db.get_version(job_id, body.restore_version)
        if target is None:
            raise HTTPException(status_code=404, detail="That version doesn't exist.")
        if body.restore_version == int(job.get("current_version") or 1):
            raise HTTPException(status_code=422, detail="That's already the current version.")
        plan = {**target["plan_json"], "warnings": []}
        revision = {
            "kind": "restore",
            "message": f"Went back to version {body.restore_version}",
            "from_version": body.restore_version,
        }
        stage = stages.EDITING

    if not db.start_revision(job_id, revision, stage, stages.STAGE_PROGRESS[stage], plan):
        raise HTTPException(status_code=409, detail="Another change is still being applied.")
    return RevisionStarted(version=new_number)
