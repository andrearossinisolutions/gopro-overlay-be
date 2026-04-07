from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.models.job import VideoInfo


class VideoProbeError(RuntimeError):
    pass


def probe_video(path: str) -> VideoInfo:
    file_path = Path(path)
    if not file_path.exists():
        raise VideoProbeError(f"File non trovato: {path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
        format_info = payload.get("format") or {}

        fps = _parse_frame_rate(stream.get("r_frame_rate", "0/1"))
        return VideoInfo(
            duration_seconds=round(float(format_info.get("duration") or 0.0), 3),
            fps=fps,
            width=int(stream.get("width") or 0),
            height=int(stream.get("height") or 0),
            codec=str(stream.get("codec_name") or "unknown"),
        )
    except FileNotFoundError:
        return VideoInfo(codec="ffprobe_not_installed")
    except Exception as exc:  # pragma: no cover - fallback pragmatico
        raise VideoProbeError(str(exc)) from exc


def _parse_frame_rate(raw: str) -> float:
    if "/" not in raw:
        return float(raw or 0.0)
    numerator, denominator = raw.split("/", 1)
    if denominator == "0":
        return 0.0
    return round(float(numerator) / float(denominator), 3)
