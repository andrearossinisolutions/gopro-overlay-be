from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.schemas.render import RenderConfig


def render_video_with_overlay(job_id: str, source_video_path: str, telemetry: dict[str, Any], config: RenderConfig) -> dict[str, str]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg non trovato nel PATH. Installa ffmpeg per generare il video finale.")

    jobs_dir = Path("data/jobs")
    jobs_dir.mkdir(parents=True, exist_ok=True)
    ass_path = jobs_dir / f"{job_id}.overlay.ass"
    config_path = jobs_dir / f"{job_id}.render-config.json"
    output_path = jobs_dir / f"{job_id}.rendered.mp4"

    ass_path.write_text(_build_ass_script(telemetry, config), encoding="utf-8")
    config_path.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")

    subtitles_path = _ffmpeg_escape_path(str(ass_path.resolve()))
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        source_video_path,
        "-vf",
        f"subtitles={subtitles_path}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(output_path),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg ha restituito un errore durante il render.")

    return {
        "rendered_video_path": str(output_path),
        "render_config_path": str(config_path),
        "overlay_ass_path": str(ass_path),
    }


def _build_ass_script(telemetry: dict[str, Any], config: RenderConfig) -> str:
    video = telemetry.get("video") or {}
    width = int(video.get("width") or 1920)
    height = int(video.get("height") or 1080)
    font_size = max(22, int(28 * config.fontScale))
    alignment, margin_l, margin_r, margin_v = _style_for_position(config.position, config.margin)
    primary = "&H00FFFFFF" if config.theme == "minimal-dark" else "&H00111111"
    outline = "&H00111111" if config.theme == "minimal-dark" else "&H00FFFFFF"
    back = "&H66000000" if config.theme == "minimal-dark" else "&H66FFFFFF"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Overlay,Arial,{font_size},{primary},{primary},{outline},{back},1,0,0,0,100,100,0,0,3,1,0,{alignment},{margin_l},{margin_r},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    samples = telemetry.get("samples") or []
    if not samples:
        samples = [{"t": 0.0, "speed_kmh": 0.0, "alt": 0.0, "lat": 0.0, "lon": 0.0, "heading": 0.0}]

    for idx, sample in enumerate(samples):
        start = float(sample.get("t") or 0.0)
        if idx + 1 < len(samples):
            end = float(samples[idx + 1].get("t") or start + 0.5)
        else:
            end = start + 0.5
        if end <= start:
            end = start + 0.5
        text = _overlay_text(sample, config)
        lines.append(
            f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},Overlay,,0,0,0,,{_escape_ass_text(text)}"
        )

    return "\n".join(lines) + "\n"


def _overlay_text(sample: dict[str, Any], config: RenderConfig) -> str:
    rows: list[str] = []
    if config.showSpeed:
        speed = float(sample.get("speed_kmh") or 0.0)
        if config.units == "imperial":
            rows.append(f"Speed: {speed * 0.621371:.1f} mph")
        else:
            rows.append(f"Speed: {speed:.1f} km/h")
    if config.showAltitude:
        alt = float(sample.get("alt") or 0.0)
        if config.units == "imperial":
            rows.append(f"Altitude: {alt * 3.28084:.0f} ft")
        else:
            rows.append(f"Altitude: {alt:.1f} m")
    if config.showCoordinates:
        rows.append(f"GPS: {float(sample.get('lat') or 0.0):.6f}, {float(sample.get('lon') or 0.0):.6f}")
    if config.showTimestamp:
        rows.append(f"Time: {_format_hms(float(sample.get('t') or 0.0))}")
    if config.showMiniMap:
        rows.append("Mini-map: placeholder")
    rows.append(f"Heading: {float(sample.get('heading') or 0.0):.0f}°")
    return r"\N".join(rows)


def _format_hms(value: float) -> str:
    total = int(value)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_ass_time(value: float) -> str:
    centiseconds = int(round(value * 100))
    hours = centiseconds // 360000
    remainder = centiseconds % 360000
    minutes = remainder // 6000
    remainder %= 6000
    seconds = remainder // 100
    cs = remainder % 100
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _style_for_position(position: str, margin: int) -> tuple[int, int, int, int]:
    mapping = {
        "top-left": (7, margin, 0, margin),
        "top-right": (9, 0, margin, margin),
        "bottom-left": (1, margin, 0, margin),
        "bottom-right": (3, 0, margin, margin),
    }
    return mapping.get(position, (1, margin, 0, margin))


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _ffmpeg_escape_path(value: str) -> str:
    escaped = value.replace('\\', r'\\').replace(':', r'\:')
    return escaped.replace(',', r'\,')
