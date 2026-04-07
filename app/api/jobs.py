from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.schemas.render import RenderConfig
from app.services.job_store import JobStore
from app.services.processor import build_preview_payload, create_render_output

router = APIRouter()
store = JobStore()


@router.get("/jobs")
def list_jobs() -> dict:
    return {"items": [job.model_dump() for job in store.list_jobs()]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato.")
    return job.model_dump()


@router.get("/jobs/{job_id}/status")
def get_job_status(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato.")
    return {
        "jobId": job.id,
        "status": job.status,
        "progress": job.progress,
        "step": job.step,
        "errorMessage": job.error_message,
    }


@router.get("/jobs/{job_id}/telemetry")
def get_job_telemetry(job_id: str) -> dict:
    payload = store.load_telemetry(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Telemetria non trovata.")
    return payload


@router.get("/jobs/{job_id}/preview")
def get_preview(job_id: str, t: float = Query(default=0.0, ge=0.0)) -> dict:
    payload = build_preview_payload(job_id, t)
    if payload is None:
        raise HTTPException(status_code=404, detail="Preview non disponibile.")
    return payload


@router.get("/jobs/{job_id}/artifacts")
def get_artifacts(job_id: str) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato.")

    def url_for(path: str | None) -> str | None:
        if not path:
            return None
        return f"/files/jobs/{Path(path).name}"

    return {
        "jobId": job.id,
        "telemetryUrl": url_for(job.telemetry_path),
        "renderedVideoUrl": url_for(job.render_output_path),
        "renderConfigUrl": url_for(job.render_config_path),
    }


@router.post("/jobs/{job_id}/render")
def render_job(job_id: str, config: RenderConfig) -> dict:
    try:
        result = create_render_output(job_id, config)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Job non trovato o non pronto.")
    return result
