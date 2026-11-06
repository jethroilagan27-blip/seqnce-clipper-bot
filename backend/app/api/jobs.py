"""Job status endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path

from .. import db, stages
from ..pipeline.transcribe import load_transcript
from ..schemas import EditSettings, JobOut, ResultOut, VideoInfo

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
    if job["status"] != stages.COMPLETED or not job.get("output_path"):
        raise HTTPException(status_code=409, detail="Result is not ready yet")
    return ResultOut(
        job_id=job_id,
        original=_video_info(job.get("metadata_json")),
        rendered=_video_info(job.get("output_metadata_json")),
        plan=job.get("plan_json"),
        preview_url=f"/api/videos/{job_id}/preview",
        download_url=f"/api/videos/{job_id}/download",
    )
