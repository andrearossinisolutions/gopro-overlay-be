from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.render import RenderConfig
from app.services.job_store import JobStore
from app.services.renderer import render_video_with_overlay
from app.services.telemetry import extract_gopro_telemetry, find_sample_for_time
from app.services.video_info import VideoProbeError, probe_video

store = JobStore()


def process_job_sync(job_id: str) -> None:
    job = store.get_job(job_id)
    if not job:
        return

    try:
        store.update_job(job_id, status="parsing", progress=15, step="probing_video")
        video = probe_video(job.uploaded_path or "")
        store.update_job(job_id, video=video, progress=45, step="extracting_telemetry")

        telemetry_result = extract_gopro_telemetry(job.uploaded_path or "")

        telemetry_payload = {
            "video": telemetry_result["video"],
            "samples": telemetry_result["samples"],
        }
        telemetry_stats = telemetry_result["stats"]

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
    except Exception as exc:
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
    if not job or not telemetry or not job.uploaded_path or job.status not in {"ready", "done"}:
        return None

    telemetry_mode = "real" if job.telemetry.has_gps else "mock"

    store.update_job(
        job_id,
        status="rendering",
        progress=70,
        step="rendering_video",
        error_message=None,
    )

    manifest_path = Path("data/jobs") / f"{job_id}.render.json"
    render_payload = {
        "jobId": job_id,
        "sourceVideo": job.uploaded_path,
        "video": job.video.model_dump(),
        "telemetryStats": job.telemetry.model_dump(),
        "config": config.model_dump(),
        "telemetryMode": telemetry_mode,
        "note": (
            "Il video finale viene renderizzato davvero da ffmpeg. "
            "La telemetria usata per l’overlay proviene dal file GoPro."
            if telemetry_mode == "real"
            else "Il video finale viene renderizzato davvero da ffmpeg, "
            "ma il file non contiene dati GPS utilizzabili."
        ),
    }
    manifest_path.write_text(json.dumps(render_payload, indent=2), encoding="utf-8")

    try:
        artifacts = render_video_with_overlay(job_id, job.uploaded_path, telemetry, config)
    except Exception as exc:
        store.fail_job(job_id, f"Render fallito: {exc}")
        raise

    store.update_job(
        job_id,
        render_output_path=artifacts["rendered_video_path"],
        render_config_path=artifacts["render_config_path"],
        status="done",
        progress=100,
        step="render_ready",
    )

    rendered_name = Path(artifacts["rendered_video_path"]).name
    config_name = Path(artifacts["render_config_path"]).name
    manifest_name = manifest_path.name

    return {
        "jobId": job_id,
        "status": "done",
        "message": "Render completato.",
        "telemetryMode": telemetry_mode,
        "renderedVideoUrl": f"/files/jobs/{rendered_name}",
        "renderConfigUrl": f"/files/jobs/{config_name}",
        "renderManifestUrl": f"/files/jobs/{manifest_name}",
        "config": config.model_dump(),
    }


def _format_seconds(value: float) -> str:
    total = int(value)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"