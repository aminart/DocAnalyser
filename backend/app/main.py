from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.analysis_routes import router as analysis_router
from app.api.routes import router as api_router
from app.services.summarizer import SummarizerError, provider_config, summarize_files

app = FastAPI(
    title="DocIntel Studio API",
    description="Plateforme d'analyse documentaire multi-formats et multi-modes avec sourçage granulaire",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(analysis_router)


@app.get("/api/summarize/config")
async def summarize_config() -> list[dict]:
    return provider_config()


@app.post("/api/summarize")
async def summarize(
    files: list[UploadFile] = File(...),
    provider: Literal["gemini", "mistral"] = Form("gemini"),
    mode: Literal["global_summary", "transcript_summary", "user_journey", "raw_notes"] = Form("global_summary"),
    level: Literal["flash", "standard", "detaille"] = Form("standard"),
) -> dict[str, str]:
    """Synthèse analytique Markdown d'un ou plusieurs documents via Gemini ou Mistral (litellm)."""
    payload = [(await f.read(), f.filename or "document.txt") for f in files]
    if not payload or not any(c for c, _ in payload):
        raise HTTPException(status_code=400, detail="Aucun fichier exploitable.")
    try:
        summary, model = await summarize_files(payload, provider, mode, level)
    except SummarizerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"summary": summary, "provider": provider, "model": model, "mode": mode, "level": level}


STATIC_INDEX = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
async def serve_spa() -> FileResponse:
    return FileResponse(STATIC_INDEX)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
