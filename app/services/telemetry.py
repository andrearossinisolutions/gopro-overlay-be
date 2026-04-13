from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TelemetryExtractionError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str


_DOC_KEY_RE = re.compile(r"^(Doc\d+):(.+)$")


def _require_exiftool() -> str:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        raise TelemetryExtractionError(
            "ExifTool non trovato nel PATH. Installa 'libimage-exiftool-perl'."
        )
    return exiftool


def _run_json_command(cmd: list[str]) -> list[dict[str, Any]]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TelemetryExtractionError(result.stderr.strip())

    return json.loads(result.stdout)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    for fmt in [
        "%Y:%m:%d %H:%M:%S.%fZ",
        "%Y:%m:%d %H:%M:%SZ",
        "%Y:%m:%d %H:%M:%S.%f",
        "%Y:%m:%d %H:%M:%S",
    ]:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _compute_heading(lat1, lon1, lat2, lon2):
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _group_doc_rows(rows):
    grouped = {}

    for row in rows:
        for key, value in row.items():
            match = _DOC_KEY_RE.match(key)
            if match:
                doc_id, tag = match.groups()
                grouped.setdefault(doc_id, {})
                grouped[doc_id][tag] = value

    return [grouped[k] for k in sorted(grouped.keys())]


def probe_video(video_path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return VideoInfo(0, 0, 0, 0, "unknown")

    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,width,height,codec_name:format=duration",
        "-of", "json",
        str(video_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    stream = data["streams"][0]
    fmt = data["format"]

    fps = eval(stream["avg_frame_rate"]) if "avg_frame_rate" in stream else 0

    return VideoInfo(
        duration_seconds=float(fmt.get("duration", 0)),
        fps=fps,
        width=stream.get("width", 0),
        height=stream.get("height", 0),
        codec=stream.get("codec_name", "unknown"),
    )


def extract_gopro_telemetry(video_path):
    exiftool = _require_exiftool()
    video_path = Path(video_path)

    if not video_path.exists():
        raise TelemetryExtractionError(f"File non trovato: {video_path}")

    video = probe_video(video_path)

    rows = _run_json_command([
        exiftool,
        "-ee",
        "-G3",
        "-j",
        "-n",
        str(video_path),
    ])

    doc_rows = _group_doc_rows(rows)

    samples_raw = []

    for row in doc_rows:
        lat = _to_float(row.get("GPSLatitude"))
        lon = _to_float(row.get("GPSLongitude"))
        if lat is None or lon is None:
            continue

        alt = _to_float(row.get("GPSAltitude")) or 0.0
        raw_speed = _to_float(row.get("GPSSpeed")) or 0.0
        speed_ref = str(row.get("GPSSpeedRef") or "").upper()

        if speed_ref == "K":
            speed_kmh = raw_speed
        elif speed_ref == "M":
            speed_kmh = raw_speed * 1.609344
        elif speed_ref == "N":
            speed_kmh = raw_speed * 1.852
        else:
            speed_kmh = raw_speed * 3.6

        heading = (
            _to_float(row.get("GPSImgDirection"))
            or _to_float(row.get("GPSDestBearing"))
            or None
        )

        gps_dt = _parse_datetime(row.get("GPSDateTime"))

        samples_raw.append({
            "gps_dt": gps_dt,
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "speed_kmh": speed_kmh,
            "heading": heading,
        })

    if len(samples_raw) < 2:
        raise TelemetryExtractionError("Telemetria insufficiente (meno di 2 punti).")

    samples_raw.sort(key=lambda x: x["gps_dt"] or datetime.now(timezone.utc))
    t0 = samples_raw[0]["gps_dt"]

    normalized = []
    prev = None

    total_distance = 0
    max_speed = 0
    elevation_gain = 0

    for i, item in enumerate(samples_raw):
        if item["gps_dt"] and t0:
            t = (item["gps_dt"] - t0).total_seconds()
        else:
            t = i

        if prev:
            computed_heading = _compute_heading(
                prev["lat"], prev["lon"],
                item["lat"], item["lon"]
            )
        else:
            computed_heading = 0.0

        heading = item["heading"] if item["heading"] is not None else computed_heading

        sample = {
            "t": round(t, 3),
            "gps_dt": item["gps_dt"].isoformat() if item["gps_dt"] else None,
            "lat": round(item["lat"], 7),
            "lon": round(item["lon"], 7),
            "alt": round(item["alt"], 2),
            "speed_kmh": round(item["speed_kmh"], 2),
            "heading": round(heading, 2),
        }

        if prev:
            total_distance += _haversine_km(prev["lat"], prev["lon"], sample["lat"], sample["lon"])
            gain = sample["alt"] - prev["alt"]
            if gain > 0:
                elevation_gain += gain

        max_speed = max(max_speed, sample["speed_kmh"])

        normalized.append(sample)
        prev = sample

    return {
        "video": {
            "duration_seconds": video.duration_seconds,
            "fps": video.fps,
            "width": video.width,
            "height": video.height,
            "codec": video.codec,
        },
        "samples": normalized,
        "stats": {
            "has_gps": True,
            "points": len(normalized),
            "distance_km": round(total_distance, 3),
            "max_speed_kmh": round(max_speed, 2),
            "elevation_gain_m": round(elevation_gain, 1),
        },
    }


def find_sample_for_time(telemetry, t):
    samples = telemetry.get("samples", [])
    if not samples:
        return None

    return min(samples, key=lambda s: abs(s["t"] - t))