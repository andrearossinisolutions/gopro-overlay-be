from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.render import RenderConfig
from app.services.job_store import JobStore
from app.services.renderer import render_video_with_overlay
from app.services.telemetry import extract_gopro_telemetry, find_sample_for_time
from app.services.video_info import VideoProbeError, probe_video

# 🆕 weather
from app.services.weather import (
    fetch_weather_timeseries,
    interpolate_weather,
    compute_headwind,
    estimate_ias,
)

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

        samples = telemetry_result["samples"]

        # 🚀 --- WEATHER + IAS ---
        try:
            if samples:
                start_dt = samples[0].get("t")
                end_dt = samples[-1].get("t")

                # ⚠️ non abbiamo datetime reale nei samples → fallback UTC now-based
                # meglio: usare gps_dt lato telemetry se lo vuoi migliorare
                from datetime import datetime, timedelta, timezone

                now = datetime.now(timezone.utc)
                start_time = now
                end_time = now + timedelta(hours=1)

                lat = samples[0]["lat"]
                lon = samples[0]["lon"]

                weather_series = fetch_weather_timeseries(lat, lon, start_time, end_time)

                for s in samples:
                    # tempo fittizio distribuito
                    ratio = s["t"] / samples[-1]["t"] if samples[-1]["t"] > 0 else 0
                    current_time = start_time + (end_time - start_time) * ratio

                    weather = interpolate_weather(weather_series, current_time)

                    wind_speed = weather["wind_speed_kmh"]
                    wind_dir = weather["wind_dir_deg"]

                    heading = s.get("heading", 0.0)
                    gs = s["speed_kmh"]  # GS reale

                    headwind = compute_headwind(wind_speed, wind_dir, heading)

                    ias = estimate_ias(gs, s["alt"], headwind)

                    # aggiorniamo sample
                    s["gs_kmh"] = round(gs, 2)
                    s["ias_kmh"] = round(ias, 2)
                    s["wind_speed_kmh"] = round(wind_speed, 1)
                    s["wind_dir_deg"] = round(wind_dir, 0)

        except Exception as e:
            # fallback safe → niente crash job
            print("Weather enrichment failed:", e)

        telemetry_payload = {
            "video": telemetry_result["video"],
            "samples": samples,
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
            # 🆕 GS + IAS
            "groundSpeedLabel": f"{sample.get('gs_kmh', sample['speed_kmh']):.1f} km/h",
            "iasLabel": f"{sample.get('ias_kmh', 0):.1f} km/h",

            "altitudeLabel": f"{sample['alt']:.1f} m",
            "coordinatesLabel": f"{sample['lat']:.6f}, {sample['lon']:.6f}",
            "headingLabel": f"{sample['heading']:.0f}°",
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