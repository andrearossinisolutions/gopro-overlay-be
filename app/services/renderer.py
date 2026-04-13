from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.schemas.render import RenderConfig


def render_video_with_overlay(
    job_id: str,
    source_video_path: str,
    telemetry: dict[str, Any],
    config: RenderConfig,
    progress_callback=None,
) -> dict[str, str]:
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
    duration_seconds = float((telemetry.get("video") or {}).get("duration_seconds") or 0.0)

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
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    last_progress = -1

    if process.stdout:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("out_time_ms=") and duration_seconds > 0:
                try:
                    out_time_ms = int(line.split("=", 1)[1])
                    rendered_seconds = out_time_ms / 1_000_000
                    percent = min(99, max(70, int(70 + (rendered_seconds / duration_seconds) * 29)))
                    if progress_callback and percent != last_progress:
                        progress_callback(percent, "rendering_video")
                        last_progress = percent
                except ValueError:
                    pass

    stderr_output = process.stderr.read() if process.stderr else ""
    return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(stderr_output.strip() or "ffmpeg ha restituito un errore durante il render.")

    return {
        "rendered_video_path": str(output_path),
        "render_config_path": str(config_path),
        "overlay_ass_path": str(ass_path),
    }


def _build_ass_script(telemetry: dict[str, Any], config: RenderConfig) -> str:
    video = telemetry.get("video") or {}
    width = int(video.get("width") or 1920)
    height = int(video.get("height") or 1080)

    base_font_size = max(20, int(26 * config.fontScale))
    small_font_size = max(16, int(18 * config.fontScale))
    label_font_size = max(18, int(20 * config.fontScale))

    primary = "&H00FFFFFF" if config.theme == "minimal-dark" else "&H00111111"
    secondary = "&H00D0D7DE" if config.theme == "minimal-dark" else "&H004A5568"
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
        f"Style: GaugeValue,Arial,{base_font_size},{primary},{primary},{outline},{back},1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1",
        f"Style: GaugeLabel,Arial,{label_font_size},{secondary},{secondary},{outline},{back},1,0,0,0,100,100,0,0,1,1,0,5,0,0,0,1",
        f"Style: Meta,Arial,{small_font_size},{primary},{primary},{outline},{back},0,0,0,0,100,100,0,0,1,1,0,1,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    samples = telemetry.get("samples") or []
    if not samples:
        samples = [
            {
                "t": 0.0,
                "speed_kmh": 0.0,
                "gs_kmh": 0.0,
                "ias_kmh": 0.0,
                "alt": 0.0,
                "lat": 0.0,
                "lon": 0.0,
                "heading": 0.0,
            }
        ]

    metrics = _metric_specs(telemetry, config)

    margin = int(config.margin)
    radius = max(56, int(72 * config.fontScale))
    spacing = max(22, int(28 * config.fontScale))
    diameter = radius * 2

    enabled_metric_count = len(metrics)
    gauges_width = enabled_metric_count * diameter + max(0, enabled_metric_count - 1) * spacing

    start_x = margin + radius
    center_y = height - margin - radius

    meta_y = height - margin + max(10, int(18 * config.fontScale))

    for idx, sample in enumerate(samples):
        start = float(sample.get("t") or 0.0)
        if idx + 1 < len(samples):
            end = float(samples[idx + 1].get("t") or start + 0.5)
        else:
            end = start + 0.5

        if end <= start:
            end = start + 0.5

        ass_start = _format_ass_time(start)
        ass_end = _format_ass_time(end)

        # Gauge row bottom-left
        for gauge_idx, metric in enumerate(metrics):
            cx = start_x + gauge_idx * (diameter + spacing)
            cy = center_y
            lines.extend(_build_gauge_dialogues(sample, metric, cx, cy, radius, ass_start, ass_end, config))

        # Meta text under gauges
        meta_rows = _meta_rows(sample, config)
        for row_idx, row_text in enumerate(meta_rows):
            row_y = meta_y + row_idx * max(18, int(20 * config.fontScale))
            lines.append(
                f"Dialogue: 10,{ass_start},{ass_end},Meta,,0,0,0,,"
                f"{{\\an1\\pos({margin},{row_y})}}{_escape_ass_text(row_text)}"
            )

        # Mini-map placeholder top-right if requested
        if config.showMiniMap:
            placeholder_w = max(180, int(220 * config.fontScale))
            placeholder_h = max(100, int(130 * config.fontScale))
            x1 = width - margin - placeholder_w
            y1 = margin
            x2 = width - margin
            y2 = margin + placeholder_h

            box_path = _rect_path(x1, y1, x2, y2)
            lines.append(
                f"Dialogue: 2,{ass_start},{ass_end},Meta,,0,0,0,,"
                f"{{\\p1\\bord1\\shad0\\c{_shape_fill_color(config)}\\3c{_shape_outline_color(config)}}}"
                f"{box_path}"
            )
            lines.append(
                f"Dialogue: 11,{ass_start},{ass_end},Meta,,0,0,0,,"
                f"{{\\an7\\pos({x1 + 12},{y1 + 18})}}Mini-map: coming soon"
            )

    return "\n".join(lines) + "\n"


def _metric_specs(telemetry: dict[str, Any], config: RenderConfig) -> list[dict[str, Any]]:
    samples = telemetry.get("samples") or []

    max_gs = max((float(s.get("gs_kmh", s.get("speed_kmh") or 0.0)) for s in samples), default=160.0)
    max_ias = max((float(s.get("ias_kmh") or 0.0) for s in samples), default=160.0)
    max_alt_m = max((float(s.get("alt") or 0.0) for s in samples), default=500.0)

    gs_max = max(180.0, _round_up(max_gs * 1.15, 20.0))
    ias_max = max(180.0, _round_up(max_ias * 1.15, 20.0))
    alt_max_m = max(500.0, _round_up(max_alt_m * 1.10, 100.0))

    specs: list[dict[str, Any]] = []

    if config.showSpeed:
        specs.append(
            {
                "key": "gs",
                "label": "GS",
                "max_value": gs_max,
                "value_getter": lambda s: float(s.get("gs_kmh", s.get("speed_kmh") or 0.0)),
                "formatter": lambda v: _format_speed(v, config.units),
            }
        )

    if config.showIAS:
        specs.append(
            {
                "key": "ias",
                "label": "IAS",
                "max_value": ias_max,
                "value_getter": lambda s: float(s.get("ias_kmh") or 0.0),
                "formatter": lambda v: _format_speed(v, config.units),
            }
        )

    if config.showAltitude:
        specs.append(
            {
                "key": "alt",
                "label": "ALT",
                "max_value": alt_max_m,
                "value_getter": lambda s: float(s.get("alt") or 0.0),
                "formatter": lambda v: _format_altitude(v, config.units),
            }
        )

    return specs


def _build_gauge_dialogues(
    sample: dict[str, Any],
    metric: dict[str, Any],
    cx: int,
    cy: int,
    radius: int,
    ass_start: str,
    ass_end: str,
    config: RenderConfig,
) -> list[str]:
    lines: list[str] = []

    value = metric["value_getter"](sample)
    max_value = float(metric["max_value"] or 1.0)
    value_ratio = _clamp(value / max_value, 0.0, 1.0)

    start_angle = -210.0
    sweep = 240.0
    angle = start_angle + sweep * value_ratio

    outer_r = radius
    ring_thickness = max(12, int(radius * 0.16))
    inner_r = outer_r - ring_thickness

    # Background disc
    lines.append(
        f"Dialogue: 1,{ass_start},{ass_end},Meta,,0,0,0,,"
        f"{{\\p1\\bord0\\shad0\\c{_disc_fill_color(config)}}}"
        f"{_circle_path(cx, cy, outer_r, 48)}"
    )

    # Outer ring
    lines.append(
        f"Dialogue: 2,{ass_start},{ass_end},Meta,,0,0,0,,"
        f"{{\\p1\\bord0\\shad0\\c{_ring_color(metric['key'], config)}}}"
        f"{_ring_path(cx, cy, outer_r, inner_r, 64)}"
    )

    # Needle
    needle_len = int(radius * 0.80)
    needle_width = max(6, int(radius * 0.10))
    lines.append(
        f"Dialogue: 3,{ass_start},{ass_end},Meta,,0,0,0,,"
        f"{{\\p1\\bord0\\shad0\\c{_needle_color(metric['key'], config)}}}"
        f"{_needle_path(cx, cy, needle_len, needle_width, angle)}"
    )

    # Center hub
    lines.append(
        f"Dialogue: 4,{ass_start},{ass_end},Meta,,0,0,0,,"
        f"{{\\p1\\bord0\\shad0\\c{_hub_color(config)}}}"
        f"{_circle_path(cx, cy, max(6, int(radius * 0.10)), 24)}"
    )

    # Label
    lines.append(
        f"Dialogue: 5,{ass_start},{ass_end},GaugeLabel,,0,0,0,,"
        f"{{\\an5\\pos({cx},{cy - int(radius * 0.38)})}}{metric['label']}"
    )

    # Value
    lines.append(
        f"Dialogue: 6,{ass_start},{ass_end},GaugeValue,,0,0,0,,"
        f"{{\\an5\\pos({cx},{cy + int(radius * 0.15)})}}{_escape_ass_text(metric['formatter'](value))}"
    )

    return lines


def _meta_rows(sample: dict[str, Any], config: RenderConfig) -> list[str]:
    rows: list[str] = []

    meta_parts: list[str] = []

    if config.showTimestamp:
        meta_parts.append(f"Time {_format_hms(float(sample.get('t') or 0.0))}")

    if config.showHeading:
        meta_parts.append(f"HDG {float(sample.get('heading') or 0.0):.0f}°")

    if meta_parts:
        rows.append("   ".join(meta_parts))

    if config.showCoordinates:
        rows.append(
            f"GPS {float(sample.get('lat') or 0.0):.6f}, {float(sample.get('lon') or 0.0):.6f}"
        )

    return rows


def _format_speed(value_kmh: float, units: str) -> str:
    if units == "imperial":
        return f"{value_kmh * 0.621371:.0f} mph"
    return f"{value_kmh:.0f} km/h"


def _format_altitude(value_m: float, units: str) -> str:
    if units == "metric":
        return f"{value_m:.0f} m"
    return f"{value_m * 3.28084:.0f} ft"


def _round_up(value: float, step: float) -> float:
    return math.ceil(value / step) * step


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _circle_path(cx: int, cy: int, r: int, steps: int = 40) -> str:
    points: list[tuple[int, int]] = []
    for i in range(steps):
        theta = 2 * math.pi * i / steps
        x = int(round(cx + r * math.cos(theta)))
        y = int(round(cy + r * math.sin(theta)))
        points.append((x, y))

    return _polygon_path(points)


def _ring_path(cx: int, cy: int, outer_r: int, inner_r: int, steps: int = 56) -> str:
    outer: list[tuple[int, int]] = []
    inner: list[tuple[int, int]] = []

    for i in range(steps):
        theta = 2 * math.pi * i / steps
        outer.append((
            int(round(cx + outer_r * math.cos(theta))),
            int(round(cy + outer_r * math.sin(theta))),
        ))

    for i in range(steps - 1, -1, -1):
        theta = 2 * math.pi * i / steps
        inner.append((
            int(round(cx + inner_r * math.cos(theta))),
            int(round(cy + inner_r * math.sin(theta))),
        ))

    return _polygon_path(outer + inner)


def _needle_path(cx: int, cy: int, length: int, width: int, angle_deg: float) -> str:
    angle = math.radians(angle_deg)
    dx = math.cos(angle)
    dy = math.sin(angle)

    px = -dy
    py = dx

    x1 = cx + px * width / 2
    y1 = cy + py * width / 2
    x2 = cx - px * width / 2
    y2 = cy - py * width / 2

    tip_x = cx + dx * length
    tip_y = cy + dy * length

    x3 = tip_x - px * width
    y3 = tip_y - py * width
    x4 = tip_x + px * width
    y4 = tip_y + py * width

    points = [
        (int(round(x1)), int(round(y1))),
        (int(round(x2)), int(round(y2))),
        (int(round(x3)), int(round(y3))),
        (int(round(x4)), int(round(y4))),
    ]
    return _polygon_path(points)


def _rect_path(x1: int, y1: int, x2: int, y2: int) -> str:
    return _polygon_path([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])


def _polygon_path(points: list[tuple[int, int]]) -> str:
    if not points:
        return ""
    first = points[0]
    rest = points[1:]
    path = [f"m {first[0]} {first[1]}"]
    for x, y in rest:
        path.append(f" l {x} {y}")
    path.append(" l")
    path.append(f" {first[0]} {first[1]}")
    return "".join(path)


def _disc_fill_color(config: RenderConfig) -> str:
    return "&H44000000" if config.theme == "minimal-dark" else "&H44FFFFFF"


def _hub_color(config: RenderConfig) -> str:
    return "&H00FFFFFF" if config.theme == "minimal-dark" else "&H00111111"


def _shape_outline_color(config: RenderConfig) -> str:
    return "&H00FFFFFF" if config.theme == "minimal-dark" else "&H00111111"


def _shape_fill_color(config: RenderConfig) -> str:
    return "&H44000000" if config.theme == "minimal-dark" else "&H44FFFFFF"


def _ring_color(metric_key: str, config: RenderConfig) -> str:
    if config.theme == "minimal-light":
        return {
            "gs": "&H00B45309",
            "ias": "&H000089D1",
            "alt": "&H002A9D8F",
        }.get(metric_key, "&H00111111")

    return {
        "gs": "&H0000C8FF",
        "ias": "&H00FFAA00",
        "alt": "&H0077DD77",
    }.get(metric_key, "&H00FFFFFF")


def _needle_color(metric_key: str, config: RenderConfig) -> str:
    if config.theme == "minimal-light":
        return {
            "gs": "&H00924A00",
            "ias": "&H00006BA8",
            "alt": "&H001F6F65",
        }.get(metric_key, "&H00111111")

    return {
        "gs": "&H0000FFFF",
        "ias": "&H00FFD060",
        "alt": "&H0090FF90",
    }.get(metric_key, "&H00FFFFFF")


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


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _ffmpeg_escape_path(value: str) -> str:
    escaped = value.replace("\\", r"\\").replace(":", r"\:")
    return escaped.replace(",", r"\,")