"""Job status, versions and revision endpoints."""

from __future__ import annotations

from pathlib import Path as FsPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path

from .. import db, stages
from ..auth import User, can_access, current_user, spend_quota
from ..pipeline.runner import record_initial_version
from ..pipeline.transcribe import load_partial, load_transcript
from ..plan.manual import ManualEditError, apply_manual_edit
from ..plan.preview import build_spec
from ..plan.schema import EditingPlan
from ..plan.text import clean_instructions
from ..schemas import (
    EditSettings,
    JobOut,
    ResultOut,
    RevisionRequest,
    RevisionStarted,
    TimelineRequest,
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


def get_job_or_404(job_id: str, user: User) -> dict[str, Any]:
    """The job, if it exists AND the user may use it. Someone else's job looks exactly like a missing one."""
    job = db.get_job(job_id)
    if job is None or not can_access(user, job):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str = JOB_ID, user: User = Depends(current_user)) -> JobOut:
    return to_job_out(get_job_or_404(job_id, user))


@router.get("/{job_id}/analysis")
def get_analysis(job_id: str = JOB_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Transcript + visual analysis produced so far (for debugging/inspection)."""
    job = get_job_or_404(job_id, user)
    if not job.get("transcript_path"):
        # Still transcribing: hand out what has been recognised so far (text only) for the live view.
        partial = load_partial(job_id) if job["status"] in (stages.QUEUED, stages.RUNNING) else None
        if partial is None:
            raise HTTPException(status_code=409, detail="Analysis is not ready yet")
        return {"transcript": partial, "visual": None, "plan": None, "partial": True}
    return {
        "transcript": load_transcript(job),
        "visual": job.get("visual_json"),
        "plan": job.get("plan_json"),
        "partial": False,
    }


@router.get("/{job_id}/result", response_model=ResultOut)
def get_result(job_id: str = JOB_ID, user: User = Depends(current_user)) -> ResultOut:
    job = get_job_or_404(job_id, user)
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


def _finished_job_or_409(job_id: str, user: User) -> dict[str, Any]:
    job = get_job_or_404(job_id, user)
    if job["status"] != stages.COMPLETED or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="The edit isn't finished yet.")
    if db.latest_version_number(job_id) == 0:  # finished before versions existed
        record_initial_version(job_id)
        job = get_job_or_404(job_id, user)
    return job


@router.get("/{job_id}/versions")
def get_versions(job_id: str = JOB_ID, user: User = Depends(current_user)) -> dict[str, Any]:
    """Every render of this job, oldest first, with the chat message and the diff that made it."""
    job = get_job_or_404(job_id, user)
    if not job.get("output_path"):
        raise HTTPException(status_code=409, detail="The edit isn't finished yet.")
    if db.latest_version_number(job_id) == 0:  # finished before versions existed
        record_initial_version(job_id)
        job = get_job_or_404(job_id, user)
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
def create_revision(
    body: RevisionRequest, job_id: str = JOB_ID, user: User = Depends(current_user)
) -> RevisionStarted:
    """Ask for a change (chat message), edit by hand, or go back to an earlier version.

    Returns immediately; poll GET /api/jobs/{id} (status/stage/progress), then GET .../versions.
    Chat messages use the AI, so they count against the user's daily chat quota (hand edits don't).
    """
    job = _finished_job_or_409(job_id, user)
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
            plan, description = apply_manual_edit(
                job["plan_json"], body.edit, float(job["metadata_json"]["duration"])
            )
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

    if revision["kind"] == "chat":
        spend_quota(user, "chat")  # atomic; 429 when today's chat messages are used up
    if not db.start_revision(job_id, revision, stage, stages.STAGE_PROGRESS[stage], plan):
        raise HTTPException(status_code=409, detail="Another change is still being applied.")
    return RevisionStarted(version=new_number)


@router.post("/{job_id}/timeline")
def get_timeline(
    body: TimelineRequest | None = None, job_id: str = JOB_ID, user: User = Depends(current_user)
) -> dict[str, Any]:
    """What an edit looks like on the timeline, computed with the renderer's own cut/caption code.

    Available as soon as the plan exists (while the video is still rendering). Nothing is saved:
    pass `edit` to preview a draft (trimmed clips, other hook text, …) on top of the base plan,
    which is the job's current plan or the given `version`.
    """
    body = body or TimelineRequest()
    job = get_job_or_404(job_id, user)
    if not job.get("transcript_path") or not job.get("metadata_json"):
        raise HTTPException(status_code=409, detail="The transcript isn't ready yet.")
    if body.version is not None:
        row = db.get_version(job_id, body.version)
        if row is None:
            raise HTTPException(status_code=404, detail="That version doesn't exist.")
        base = row["plan_json"]
    else:
        base = job.get("plan_json")
    if not base:
        raise HTTPException(status_code=409, detail="The editing plan isn't ready yet.")

    meta = job["metadata_json"]
    if body.edit is not None:
        try:
            base, _ = apply_manual_edit(base, body.edit, float(meta["duration"]))
        except ManualEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_spec(EditingPlan.model_validate(base), load_transcript(job), meta)
