from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import jobs, uploads

app = FastAPI(
    title="GoPro Telemetry Backend MVP",
    version="0.1.0",
    description="Backend MVP per upload video, parsing iniziale e preview dati overlay.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(uploads.router, prefix="/api", tags=["uploads"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])

app.mount("/files", StaticFiles(directory="data"), name="files")


@app.get("/")
def root() -> dict:
    return {
        "name": "GoPro Telemetry Backend MVP",
        "docs": "/docs",
        "health": "ok",
    }
