from __future__ import annotations

import json
import math
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


def _require_exiftool() -> str:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        raise TelemetryExtractionError(
            "ExifTool non trovato nel PATH. Installa 'libimage-exiftool-perl'."
        )
    return exiftool


def _run_json_command(cmd: list[str]) -> list[dict[str, Any]]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TelemetryExtractionError(
            result.stderr.strip() or f"Comando fallito: {' '.join(cmd)}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TelemetryExtractionError("Output JSON non valido da ExifTool.") from exc

    if not isinstance(payload, list):
        raise TelemetryExtractionError("ExifTool ha restituito un payload inatteso.")

    return payload


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    value = value.strip()

    candidates = [
        "%Y:%m:%d %H:%M:%S.%fZ",
        "%Y:%m:%d %H:%M:%SZ",
        "%Y:%m:%d %H:%M:%S.%f",
        "%Y:%m:%d %H:%M:%S",
    ]

    for fmt in candidates:
        try:
            dt = datetime.strptime(value, fmt)
            if value.endswith("Z"):
                return dt.replace(tzinfo=timezone.utc)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _get_tag(row: dict[str, Any], tag_name: str) -> Any:
    """
    ExifTool con -G3 restituisce spesso chiavi come:
    - Main:GPSLatitude
    - Doc1:GPSLatitude
    - Doc25:GPSSpeed

    Questa funzione cerca prima il tag puro, poi qualsiasi chiave che termini
    con :<tag_name>.
    """
    if tag_name in row:
        return row[tag_name]

    suffix = f":{tag_name}"
    for key, value in row.items():
        if key.endswith(suffix):
            return value

    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def probe_video(video_path: str | Path) -> VideoInfo:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return VideoInfo(
            duration_seconds=0.0,
            fps=0.0,
            width=0,
            height=0,
            codec="unknown",
        )

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,width,height,codec_name:format=duration",
        "-of",
        "json",
        str(video_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return VideoInfo(
            duration_seconds=0.0,
            fps=0.0,
            width=0,
            height=0,
            codec="unknown",
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return VideoInfo(
            duration_seconds=0.0,
            fps=0.0,
            width=0,
            height=0,
            codec="unknown",
        )

    stream = (payload.get("streams") or [{}])[0]
    fmt = payload.get("format") or {}

    fps_raw = str(stream.get("avg_frame_rate", "0/1"))
    fps = 0.0
    if "/" in fps_raw:
        n, d = fps_raw.split("/", 1)
        try:
            fps = float(n) / float(d) if float(d) else 0.0
        except ValueError:
            fps = 0.0

    return VideoInfo(
        duration_seconds=float(fmt.get("duration") or 0.0),
        fps=fps,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        codec=str(stream.get("codec_name") or "unknown"),
    )


def extract_gopro_telemetry(video_path: str | Path) -> dict[str, Any]:
    exiftool = _require_exiftool()
    video_path = Path(video_path)

    if not video_path.exists():
        raise TelemetryExtractionError(f"File video non trovato: {video_path}")

    video = probe_video(video_path)

    cmd = [
        exiftool,
        "-ee",
        "-api",
        "LargeFileSupport=1",
        "-G3",
        "-j",
        "-n",
        str(video_path),
    ]
    rows = _run_json_command(cmd)

    samples_raw: list[dict[str, Any]] = []
    for row in rows:
        lat = _to_float(_get_tag(row, "GPSLatitude"))
        lon = _to_float(_get_tag(row, "GPSLongitude"))
        if lat is None or lon is None:
            continue

        alt = _to_float(_get_tag(row, "GPSAltitude")) or 0.0

        speed = _to_float(_get_tag(row, "GPSSpeed"))
        speed_ref = str(_get_tag(row, "GPSSpeedRef") or "").upper()

        speed_kmh = 0.0
        if speed is not None:
            if speed_ref == "K":
                speed_kmh = speed
            elif speed_ref == "M":
                speed_kmh = speed * 1.609344
            elif speed_ref == "N":
                speed_kmh = speed * 1.852
            else:
                speed_kmh = speed

        heading = (
            _to_float(_get_tag(row, "GPSImgDirection"))
            or _to_float(_get_tag(row, "GPSDestBearing"))
            or 0.0
        )

        gps_dt = _parse_datetime(
            _get_tag(row, "GPSDateTime")
            or _get_tag(row, "GPSDateStamp")
            or _get_tag(row, "DateTimeOriginal")
            or _get_tag(row, "CreateDate")
        )

        samples_raw.append(
            {
                "gps_dt": gps_dt,
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "speed_kmh": speed_kmh,
                "heading": heading,
            }
        )

    if not samples_raw:
        raise TelemetryExtractionError(
            "Nessun punto GPS trovato nel video GoPro. "
            "Verifica che il GPS fosse attivo durante la registrazione e che il file contenga telemetria GPMF."
        )

    samples_raw.sort(
        key=lambda x: x["gps_dt"] or datetime.fromtimestamp(0, tz=timezone.utc)
    )
    t0 = samples_raw[0]["gps_dt"]

    normalized_samples: list[dict[str, Any]] = []
    total_distance_km = 0.0
    max_speed_kmh = 0.0
    elevation_gain_m = 0.0

    prev = None
    for index, item in enumerate(samples_raw):
        gps_dt = item["gps_dt"]
        if gps_dt and t0:
            t = max(0.0, (gps_dt - t0).total_seconds())
        else:
            t = float(index)

        sample = {
            "t": round(t, 3),
            "lat": round(item["lat"], 7),
            "lon": round(item["lon"], 7),
            "alt": round(item["alt"], 2),
            "speed_kmh": round(item["speed_kmh"], 2),
            "heading": round(item["heading"], 2),
        }

        if prev is not None:
            total_distance_km += _haversine_km(
                prev["lat"], prev["lon"], sample["lat"], sample["lon"]
            )
            alt_gain = sample["alt"] - prev["alt"]
            if alt_gain > 0:
                elevation_gain_m += alt_gain

        max_speed_kmh = max(max_speed_kmh, sample["speed_kmh"])
        normalized_samples.append(sample)
        prev = sample

    return {
        "video": {
            "duration_seconds": video.duration_seconds,
            "fps": video.fps,
            "width": video.width,
            "height": video.height,
            "codec": video.codec,
        },
        "samples": normalized_samples,
        "stats": {
            "has_gps": True,
            "points": len(normalized_samples),
            "distance_km": round(total_distance_km, 3),
            "max_speed_kmh": round(max_speed_kmh, 2),
            "elevation_gain_m": round(elevation_gain_m, 1),
        },
    }
    
def find_sample_for_time(telemetry: dict[str, Any], t: float) -> dict[str, Any] | None:
    samples = telemetry.get("samples") or []
    if not samples:
        return None

    try:
        target = float(t)
    except (TypeError, ValueError):
        return samples[0] if samples else None

    nearest = min(
        samples,
        key=lambda sample: abs(float(sample.get("t", 0.0)) - target),
    )
    return nearest