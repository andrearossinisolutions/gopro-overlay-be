from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.render import RenderConfig
from app.services.job_store import JobStore
from app.services.telemetry import find_sample_for_time, generate_mock_telemetry
from app.services.video_info import VideoProbeError, probe_video

store = JobStore()


def process_job_sync(job_id: str) -> None:
    job = store.get_job(job_id)
    if not job:
        return

    try:
        store.update_job(job_id, status="parsing", progress=25, step="probing_video")
        video = probe_video(job.uploaded_path or "")
        store.update_job(job_id, video=video, progress=55, step="extracting_telemetry")

        telemetry_payload, telemetry_stats = generate_mock_telemetry(video)
        store.save_telemetry(job_id, telemetry_payload)

        store.update_job(
            job_id,
            telemetry=telemetry_stats,
            status="ready",
            progress=100,
            step="ready",
        )
    except VideoProbeError as exc:
        store.fail_job(job_id, f"Probe video fallito: {exc}")
    except Exception as exc:  # pragma: no cover - MVP pragmatico
        store.fail_job(job_id, f"Errore durante il processing: {exc}")



def build_preview_payload(job_id: str, t: float) -> dict[str, Any] | None:
    job = store.get_job(job_id)
    telemetry = store.load_telemetry(job_id)
    if not job or not telemetry:
        return None

    sample = find_sample_for_time(telemetry, t)
    if not sample:
        return None

    return {
        "jobId": job_id,
        "time": round(t, 3),
        "overlay": {
            "speedLabel": f"{sample['speed_kmh']:.1f} km/h",
            "altitudeLabel": f"{sample['alt']:.1f} m",
            "coordinatesLabel": f"{sample['lat']:.6f}, {sample['lon']:.6f}",
            "timestampLabel": _format_seconds(t),
        },
        "sample": sample,
    }



def create_render_output(job_id: str, config: RenderConfig) -> dict[str, Any] | None:
    job = store.get_job(job_id)
    telemetry = store.load_telemetry(job_id)
    if not job or not telemetry or job.status not in {"ready", "done"}:
        return None

    store.update_job(job_id, status="rendering", progress=75, step="writing_render_manifest")
    manifest_path = Path("data/jobs") / f"{job_id}.render.json"
    render_payload = {
        "jobId": job_id,
        "sourceVideo": job.uploaded_path,
        "video": job.video.model_dump(),
        "telemetryStats": job.telemetry.model_dump(),
        "config": config.model_dump(),
        "note": "MVP: qui c'è il manifest usato dal frontend per simulare l'overlay. Nel passo successivo si aggancerà ffmpeg.",
    }
    manifest_path.write_text(json.dumps(render_payload, indent=2), encoding="utf-8")

    store.update_job(
        job_id,
        render_output_path=str(manifest_path),
        status="done",
        progress=100,
        step="render_manifest_ready",
    )

    return {
        "jobId": job_id,
        "status": "done",
        "renderManifestUrl": f"/files/jobs/{manifest_path.name}",
        "config": config.model_dump(),
    }



def _format_seconds(value: float) -> str:
    total = int(value)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
