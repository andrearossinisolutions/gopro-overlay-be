from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

JobStatus = Literal["uploaded", "parsing", "ready", "rendering", "done", "error"]


class VideoInfo(BaseModel):
    duration_seconds: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = "unknown"


class TelemetryStats(BaseModel):
    has_gps: bool = False
    points: int = 0
    distance_km: float = 0.0
    max_speed_kmh: float = 0.0
    elevation_gain_m: float = 0.0


class Job(BaseModel):
    id: str
    original_filename: str
    uploaded_path: Optional[str] = None
    uploaded_size_bytes: int = 0
    status: JobStatus = "uploaded"
    progress: int = 0
    step: str = "created"
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    video: VideoInfo = Field(default_factory=VideoInfo)
    telemetry: TelemetryStats = Field(default_factory=TelemetryStats)
    telemetry_path: Optional[str] = None
    render_output_path: Optional[str] = None
