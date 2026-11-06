import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.analysis_routes import router as analysis_router
from app.api.connection_routes import router as connection_router
from app.core.config import BACKEND_DIR
from app.info import APP_ID, APP_NAME, VERSION
from app.services.analysis_service import load_history

app = FastAPI(
    title="DocAnalyser API",
    description="Import de documents multi-formats et synthèses structurées par thèmes ou par parcours",
    version=VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis_router)
app.include_router(connection_router)


@app.on_event("startup")
async def restore_history() -> None:
    load_history()


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Contrat du portail : répond dès que le serveur tourne, quels que soient les modèles configurés."""
    return {"status": "ok", "app": APP_ID, "name": APP_NAME, "version": VERSION}


def frontend_dist_dir() -> Path:
    """Interface compilée (npm run build) : à côté du backend, ou dans l'exécutable empaqueté."""
    override = os.getenv("FRONTEND_DIST")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "frontend_dist"
    return BACKEND_DIR.parent / "frontend" / "dist"


FRONTEND_DIST = frontend_dist_dir()

if (FRONTEND_DIST / "index.html").is_file():
    # Le backend sert l'interface : un seul processus, une seule adresse (http://127.0.0.1:8020).
    if (FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Route d'API inconnue")
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
