from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis_routes import router as analysis_router

app = FastAPI(
    title="Analyse documentaire API",
    description="Import de documents multi-formats et synthèses structurées par thèmes ou par parcours",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
