from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.job_store import JobStore
from app.services.processor import process_job_sync

router = APIRouter()
store = JobStore()

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v"}
MAX_FILE_SIZE_BYTES = 1_500_000_000  # 1.5 GB


@router.post("/uploads")
async def upload_video(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome file mancante.")

    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Estensione non supportata: {extension}. Usa uno di {sorted(ALLOWED_EXTENSIONS)}",
        )

    job = store.create_job(original_filename=file.filename)
    output_path = Path("data/uploads") / f"{job.id}{extension}"

    size = 0
    with output_path.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE_BYTES:
                output_path.unlink(missing_ok=True)
                store.fail_job(job.id, "File troppo grande.")
                raise HTTPException(status_code=413, detail="File troppo grande.")
            buffer.write(chunk)

    store.attach_uploaded_file(job.id, str(output_path), size)
    process_job_sync(job.id)

    return {
        "jobId": job.id,
        "status": store.get_job(job.id).status,
        "fileUrl": f"/files/uploads/{output_path.name}",
    }
