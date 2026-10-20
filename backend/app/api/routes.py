from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.config import settings
from app.schemas.models import (
    DocumentMetadata,
    DocumentPreviewBlock,
    DocumentPreviewResponse,
    ExportFormat,
    JobCreateRequest,
    JobStage,
    JobStatusResponse,
    ModelOption,
    UploadInitRequest,
    UploadInitResponse,
)
from app.services.export_service import SynthesisExportService
from app.services.llm_service import MistralEnterpriseService
from app.services.parser_service import AnchoredTextBlock, MultiFormatDocumentParser

router = APIRouter(prefix="/api/v1", tags=["Document Intelligence"])

DOCUMENTS_STORE: dict[str, DocumentMetadata] = {}
PARSED_BLOCKS_CACHE: dict[str, list[AnchoredTextBlock]] = {}
JOBS_STORE: dict[str, JobStatusResponse] = {}

parser_service = MultiFormatDocumentParser()
llm_service = MistralEnterpriseService()
export_service = SynthesisExportService()


@router.get("/models", response_model=list[ModelOption])
async def list_available_models() -> list[ModelOption]:
    """Retourne les modèles LLM configurés dans le fichier .env (Mistral Small, Mistral Medium, etc.)."""
    return settings.get_model_options()


@router.post("/uploads/init", response_model=UploadInitResponse)
async def initialize_chunked_upload(payload: UploadInitRequest) -> UploadInitResponse:
    """Initialise un upload résilient par chunks pour les fichiers lourds (300+ pages PDF, Excel denses)."""
    doc_id = str(uuid.uuid4())
    safe_name = Path(payload.file_name).name
    storage_path = settings.STORAGE_DIR / f"{doc_id}_{safe_name}"
    storage_path.touch()

    DOCUMENTS_STORE[doc_id] = DocumentMetadata(
        document_id=doc_id,
        file_name=safe_name,
        mime_type=payload.mime_type or "application/octet-stream",
        total_size_bytes=payload.total_size_bytes,
        uploaded_chunks=0,
        total_chunks=payload.total_chunks,
        storage_key=str(storage_path),
        is_complete=False,
    )
    return UploadInitResponse(
        document_id=doc_id,
        upload_mode="chunked_api",
        chunk_size_bytes=5 * 1024 * 1024,
    )


@router.post("/uploads/{document_id}/chunk", response_model=DocumentMetadata)
async def upload_file_chunk(
    document_id: str,
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
) -> DocumentMetadata:
    """Reçoit et assemble séquentiellement chaque chunk binaire sans saturer la RAM."""
    doc_meta = DOCUMENTS_STORE.get(document_id)
    if not doc_meta:
        raise HTTPException(status_code=404, detail="Document introuvable.")

    target_path = Path(doc_meta.storage_key)
    data = await chunk.read()
    with target_path.open("ab") as f:
        f.write(data)

    doc_meta.uploaded_chunks += 1
    if doc_meta.uploaded_chunks >= doc_meta.total_chunks:
        doc_meta.is_complete = True

    DOCUMENTS_STORE[document_id] = doc_meta
    return doc_meta


@router.get("/documents/{document_id}/blocks", response_model=DocumentPreviewResponse)
async def get_document_parsed_blocks(document_id: str) -> DocumentPreviewResponse:
    """Permet de consulter les pages/slides/lignes exactes d'un document source pour la traçabilité."""
    doc_meta = DOCUMENTS_STORE.get(document_id)
    if not doc_meta:
        raise HTTPException(status_code=404, detail="Document introuvable.")

    blocks = PARSED_BLOCKS_CACHE.get(document_id)
    if blocks is None:
        blocks = list(parser_service.parse_file(Path(doc_meta.storage_key), doc_meta.file_name))
        PARSED_BLOCKS_CACHE[document_id] = blocks

    return DocumentPreviewResponse(
        document_id=document_id,
        file_name=doc_meta.file_name,
        total_blocks=len(blocks),
        blocks=[
            DocumentPreviewBlock(location=b.location, content=b.content)
            for b in blocks
        ],
    )


async def _run_synthesis_pipeline(job_id: str) -> None:
    """Worker asynchrone orchestrant le parsing multi-formats et l'analyse LLM Map-Reduce."""
    job = JOBS_STORE[job_id]

    def update_state(stage: JobStage, pct: int, detail: str) -> None:
        job.stage = stage
        job.progress_percent = max(0, min(100, pct))
        job.current_step_detail = detail
        job.updated_at = datetime.now(timezone.utc)
        JOBS_STORE[job_id] = job

    try:
        update_state(JobStage.PARSING, 10, "Extraction et indexation des ancres de traçabilité...")
        all_blocks: list[AnchoredTextBlock] = []
        total_docs = len(job.documents)

        for idx, doc_meta in enumerate(job.documents, start=1):
            file_path = Path(doc_meta.storage_key)
            update_state(
                JobStage.PARSING,
                10 + int((idx / total_docs) * 30),
                f"Parsing en flux de {doc_meta.file_name} ({idx}/{total_docs})...",
            )
            doc_blocks = list(parser_service.parse_file(file_path, doc_meta.file_name))
            PARSED_BLOCKS_CACHE[doc_meta.document_id] = doc_blocks
            all_blocks.extend(doc_blocks)

        if not all_blocks:
            raise ValueError("Aucun contenu textuel exploitable n'a pu être extrait des documents fournis.")

        update_state(
            JobStage.ANALYZING,
            42,
            f"Préparation de {len(all_blocks)} blocs sourcés pour {job.model_name}...",
        )

        result = await llm_service.synthesize_documents(
            blocks=all_blocks,
            mode=job.mode,
            model_name=job.model_name,
            on_progress=lambda pct, msg: update_state(JobStage.ANALYZING, pct, msg),
        )

        job.result = result
        update_state(JobStage.READY, 100, "Synthèse terminée et vérifiée avec succès.")

    except Exception as exc:
        job.stage = JobStage.FAILED
        job.error_message = str(exc)
        job.current_step_detail = "Échec lors du traitement."
        job.updated_at = datetime.now(timezone.utc)
        JOBS_STORE[job_id] = job


@router.post("/jobs", response_model=JobStatusResponse, status_code=202)
async def create_synthesis_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
) -> JobStatusResponse:
    """Lance un job d'analyse multi-fichiers asynchrone selon le mode et le modèle LLM choisis."""
    docs: list[DocumentMetadata] = []
    for doc_id in request.document_ids:
        meta = DOCUMENTS_STORE.get(doc_id)
        if not meta or not meta.is_complete:
            raise HTTPException(
                status_code=400,
                detail=f"Le document {doc_id} est introuvable ou son upload est incomplet.",
            )
        docs.append(meta)

    now = datetime.now(timezone.utc)
    job_id = str(uuid.uuid4())
    job_status = JobStatusResponse(
        job_id=job_id,
        stage=JobStage.PARSING,
        progress_percent=5,
        current_step_detail="Mise en file d'attente du job d'analyse...",
        mode=request.mode,
        model_name=request.model_name,
        documents=docs,
        created_at=now,
        updated_at=now,
    )
    JOBS_STORE[job_id] = job_status
    background_tasks.add_task(_run_synthesis_pipeline, job_id)
    return job_status


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    """Retourne la progression en temps réel et le résultat structuré dès que stage == 'ready'."""
    job = JOBS_STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job d'analyse introuvable.")
    return job


@router.get("/jobs/{job_id}/export")
async def export_synthesis_result(job_id: str, format: ExportFormat = ExportFormat.MARKDOWN) -> Response:
    """Exporte la synthèse finale en Markdown (.md), Word (.docx) ou PDF (.pdf)."""
    job = JOBS_STORE.get(job_id)
    if not job or job.stage != JobStage.READY or not job.result:
        raise HTTPException(status_code=400, detail="La synthèse n'est pas encore prête pour l'export.")

    content_bytes, media_type, filename = export_service.export(job.result, format)
    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
