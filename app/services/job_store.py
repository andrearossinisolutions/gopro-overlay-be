from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.job import Job


class JobStore:
    def __init__(self) -> None:
        self.jobs_dir = Path("data/jobs")
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def create_job(self, original_filename: str) -> Job:
        job = Job(id=f"job_{uuid.uuid4().hex[:10]}", original_filename=original_filename)
        self.save_job(job)
        return job

    def save_job(self, job: Job) -> None:
        job.updated_at = datetime.now(timezone.utc)
        self._job_path(job.id).write_text(job.model_dump_json(indent=2), encoding="utf-8")

    def get_job(self, job_id: str) -> Job | None:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        return Job.model_validate_json(path.read_text(encoding="utf-8"))

    def list_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        for path in sorted(self.jobs_dir.glob("*.json"), reverse=True):
            try:
                jobs.append(Job.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def update_job(self, job_id: str, **updates: Any) -> Job:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job {job_id} non trovato")
        for key, value in updates.items():
            setattr(job, key, value)
        self.save_job(job)
        return job

    def attach_uploaded_file(self, job_id: str, path: str, size: int) -> Job:
        return self.update_job(
            job_id,
            uploaded_path=path,
            uploaded_size_bytes=size,
            status="uploaded",
            progress=10,
            step="upload_completed",
        )

    def fail_job(self, job_id: str, message: str) -> Job:
        return self.update_job(
            job_id,
            status="error",
            progress=100,
            step="failed",
            error_message=message,
        )

    def save_telemetry(self, job_id: str, payload: dict[str, Any]) -> str:
        telemetry_path = self.jobs_dir / f"{job_id}.telemetry.json"
        telemetry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.update_job(job_id, telemetry_path=str(telemetry_path))
        return str(telemetry_path)

    def load_telemetry(self, job_id: str) -> dict[str, Any] | None:
        telemetry_path = self.jobs_dir / f"{job_id}.telemetry.json"
        if not telemetry_path.exists():
            return None
        return json.loads(telemetry_path.read_text(encoding="utf-8"))
