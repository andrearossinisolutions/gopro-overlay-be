from __future__ import annotations

import math
from typing import Any

from app.models.job import TelemetryStats, VideoInfo


# Nota: questa è telemetria mock ma strutturata come sarà utile al frontend.
# In un secondo step si sostituirà generate_mock_telemetry con un parser reale GoPro.

def generate_mock_telemetry(video: VideoInfo) -> tuple[dict[str, Any], TelemetryStats]:
    duration = max(video.duration_seconds, 20.0)
    sample_step = 0.5
    num_samples = int(duration / sample_step) + 1

    base_lat = 45.4642
    base_lon = 9.19
    samples: list[dict[str, Any]] = []

    distance_km = 0.0
    max_speed = 0.0
    prev_lat = base_lat
    prev_lon = base_lon
    prev_alt = 120.0

    for index in range(num_samples):
        t = round(index * sample_step, 3)
        phase = index / max(num_samples - 1, 1)
        lat = base_lat + 0.01 * phase
        lon = base_lon + 0.015 * math.sin(phase * math.pi)
        alt = 120.0 + 18.0 * math.sin(phase * math.pi * 2)
        speed_kmh = max(0.0, 20.0 + 12.0 * math.sin(phase * math.pi * 4))
        heading = (90.0 + phase * 180.0) % 360

        samples.append(
            {
                "t": t,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "alt": round(alt, 1),
                "speed_kmh": round(speed_kmh, 1),
                "heading": round(heading, 1),
            }
        )

        distance_km += _approx_distance_km(prev_lat, prev_lon, lat, lon)
        max_speed = max(max_speed, speed_kmh)
        prev_lat = lat
        prev_lon = lon
        prev_alt = alt

    payload = {
        "video": video.model_dump(),
        "samples": samples,
    }
    stats = TelemetryStats(
        has_gps=True,
        points=len(samples),
        distance_km=round(distance_km, 3),
        max_speed_kmh=round(max_speed, 1),
        elevation_gain_m=round(_compute_elevation_gain(samples), 1),
    )
    return payload, stats



def find_sample_for_time(payload: dict[str, Any], t: float) -> dict[str, Any] | None:
    samples = payload.get("samples") or []
    if not samples:
        return None
    nearest = min(samples, key=lambda sample: abs(sample["t"] - t))
    return nearest



def _compute_elevation_gain(samples: list[dict[str, Any]]) -> float:
    gain = 0.0
    previous_alt = None
    for sample in samples:
        current = float(sample["alt"])
        if previous_alt is not None and current > previous_alt:
            gain += current - previous_alt
        previous_alt = current
    return gain



def _approx_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * 85.0
    dy = (lat2 - lat1) * 111.0
    return (dx * dx + dy * dy) ** 0.5
