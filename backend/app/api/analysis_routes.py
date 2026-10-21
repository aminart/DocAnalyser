from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services import analysis_service as svc
from app.services.export_service import markdown_to_docx, markdown_to_pdf
from app.services.source_lookup import passage

router = APIRouter(prefix="/api/v2", tags=["Analyse documentaire"])


class AnalysisCreate(BaseModel):
    document_ids: list[str] = Field(min_length=1)
    mode: Literal["global", "transcript", "notes", "flow"]
    level: Literal["synth", "detail", "deep"]
    model_id: str
    language: Literal["fr", "en"] = "fr"
    cite: bool = True


def _get(analysis_id: str) -> svc.Analysis:
    analysis = svc.ANALYSES.get(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse introuvable (le serveur a peut-être redémarré).")
    return analysis


@router.get("/models")
async def list_models() -> list[dict]:
    return svc.model_options()


@router.post("/documents")
async def upload_document(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    try:
        doc = svc.store_document(content, file.filename or "document.txt")
    except svc.AnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return doc.public()


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str) -> Response:
    svc.DOCUMENTS.pop(document_id, None)
    return Response(status_code=204)


@router.get("/analyses")
async def list_analyses() -> list[dict]:
    items = sorted(svc.ANALYSES.values(), key=lambda a: a.created_at, reverse=True)
    return [a.summary() for a in items]


@router.post("/analyses", status_code=202)
async def create_analysis(payload: AnalysisCreate) -> dict:
    try:
        analysis = svc.create_analysis(
            payload.document_ids, payload.mode, payload.level, payload.model_id, payload.language, payload.cite
        )
    except svc.AnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return analysis.public()


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    return _get(analysis_id).public()


@router.delete("/analyses/{analysis_id}")
async def cancel_analysis(analysis_id: str) -> dict:
    analysis = _get(analysis_id)
    svc.cancel_analysis(analysis)
    return analysis.public()


@router.get("/analyses/{analysis_id}/source")
async def get_source(analysis_id: str, document: str = "", location: str = "", text: str = "") -> dict:
    """Passage d'origine d'une source citée, pour la vérifier sans quitter la synthèse.

    Sans document (verbatim dont la source n'est pas précisée), on cherche dans tous les documents de l'analyse.
    """
    analysis = _get(analysis_id)
    text = text[:2000]
    if not document:
        candidates = [(d, passage(d, "", text)) for d in analysis.documents]
        doc, found = max(candidates, key=lambda c: (bool(c[1]["lines"]), c[1]["score"]))
        return {"document": doc.name, "location": "", **found}
    doc = next((d for d in analysis.documents if d.name == document), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Ce document ne fait pas partie de l'analyse.")
    return {"document": doc.name, "location": location, **passage(doc, location, text)}


def _plain(md_text: str) -> str:
    """Allège le Markdown pour les exports Word/PDF (citations, italiques)."""
    md_text = re.sub(r"```mermaid\n.*?```\n?", "", md_text, flags=re.S)  # schéma : utile en .md seulement
    out = []
    for line in md_text.splitlines():
        line = re.sub(r"^>\s?", "", line)
        line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", line)
        out.append(line)
    return "\n".join(out)


@router.get("/analyses/{analysis_id}/export")
async def export_analysis(analysis_id: str, format: Literal["md", "docx", "pdf"] = "md") -> Response:
    analysis = _get(analysis_id)
    if analysis.status != "done":
        raise HTTPException(status_code=400, detail="La synthèse n'est pas encore prête.")
    title = analysis.title or "Synthese"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:60] or "synthese"
    if format == "md":
        content, media = analysis.markdown.encode("utf-8"), "text/markdown; charset=utf-8"
    elif format == "docx":
        content = markdown_to_docx(title, _plain(analysis.markdown))
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        content, media = markdown_to_pdf(title, _plain(analysis.markdown)), "application/pdf"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{slug}.{format}"'},
    )
