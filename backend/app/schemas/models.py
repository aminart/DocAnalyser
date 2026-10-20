from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class SynthesisMode(str, Enum):
    GLOBAL = "global_summary"
    TRANSCRIPT = "transcript_summary"
    USER_JOURNEY = "user_journey"
    RAW_NOTES = "raw_notes"


class JobStage(str, Enum):
    UPLOADING = "uploading"
    PARSING = "parsing"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"


class ExportFormat(str, Enum):
    MARKDOWN = "md"
    DOCX = "docx"
    PDF = "pdf"


class SourceReference(BaseModel):
    file_name: str = Field(..., description="Nom du fichier source d'origine")
    location: str = Field(..., description="Page X, Slide Y, Feuille Z Lignes A-B, ou Timestamp")
    excerpt: str = Field(..., description="Extrait court verbatim justifiant le point")


# --- Mode 1 : Synthèse Documentaire Globale ---
class StructuredParagraph(BaseModel):
    heading: str = Field(..., description="Titre concis (3 à 6 mots) annonçant le sujet exact du paragraphe")
    body: str = Field(..., description="Paragraphe analytique approfondi et détaillé (80 à 160 mots)")
    sources: list[SourceReference] = Field(default_factory=list)


class ThemeItem(BaseModel):
    theme: str = Field(..., description="Titre concis du pilier thématique (3 à 6 mots max)")
    summary: str = Field(..., description="Développement analytique complet en plusieurs phrases (100 à 180 mots)")
    arguments: list[str] = Field(..., description="Liste d'arguments, preuves et mécanismes détaillés")
    sources: list[SourceReference]


class MetricItem(BaseModel):
    label: str
    value: str
    context: str
    trend: Literal["up", "down", "neutral"] = "neutral"
    sources: list[SourceReference]


class RecommendationItem(BaseModel):
    title: str
    description: str
    priority: Literal["Haute", "Moyenne", "Basse"] = "Haute"
    sources: list[SourceReference]


class GlobalSummaryResult(BaseModel):
    mode: Literal[SynthesisMode.GLOBAL] = SynthesisMode.GLOBAL
    title: str
    executive_summary: str
    executive_paragraphs: list[StructuredParagraph] = Field(default_factory=list)
    key_themes: list[ThemeItem]
    key_metrics: list[MetricItem]
    recommendations: list[RecommendationItem]


# --- Mode 2 : Synthèse de Transcription ---
class ParticipantItem(BaseModel):
    name: str
    role: str


class TranscriptClusterItem(BaseModel):
    tag: str
    consolidated_notes: str
    key_takeaways: list[str]
    sources: list[SourceReference]


class DecisionItem(BaseModel):
    decision: str
    rationale: str
    sources: list[SourceReference]


class ActionItem(BaseModel):
    task: str
    assignee: str
    due_date: str
    priority: Literal["Haute", "Moyenne", "Basse"] = "Haute"
    sources: list[SourceReference]


class TensionItem(BaseModel):
    topic: str
    description: str
    stakeholders: list[str]
    sources: list[SourceReference]


class TranscriptSummaryResult(BaseModel):
    mode: Literal[SynthesisMode.TRANSCRIPT] = SynthesisMode.TRANSCRIPT
    title: str
    context: str
    participants: list[ParticipantItem]
    agenda: list[str]
    thematic_clusters: list[TranscriptClusterItem]
    decisions_made: list[DecisionItem]
    action_items: list[ActionItem]
    open_questions_and_tensions: list[TensionItem]


# --- Mode 3 : Extraction des Parcours Utilisateurs ---
class PersonaItem(BaseModel):
    name: str
    profile: str
    goals: list[str]
    frustrations: list[str]
    sources: list[SourceReference]


class UserJourneyStep(BaseModel):
    step_number: int
    stage: str
    persona: str
    action: str
    user_goal: str
    touchpoint: str
    pain_points: list[str]
    opportunities: list[str]
    sources: list[SourceReference]


class UserJourneyResult(BaseModel):
    mode: Literal[SynthesisMode.USER_JOURNEY] = SynthesisMode.USER_JOURNEY
    title: str
    overview: str
    personas: list[PersonaItem]
    steps: list[UserJourneyStep]
    mermaid_diagram: str


# --- Mode 4 : Synthèse de Notes en Vrac ---
class ConsolidatedIdea(BaseModel):
    title: str
    structured_content: str
    merged_count: int = Field(default=1, ge=1)
    sources: list[SourceReference]


class NoteCluster(BaseModel):
    pillar: str
    tags: list[str]
    summary: str
    consolidated_ideas: list[ConsolidatedIdea]


class NextStepItem(BaseModel):
    action: str
    category: str
    impact: Literal["Élevé", "Moyen", "Faible"] = "Élevé"
    sources: list[SourceReference]


class RawNotesResult(BaseModel):
    mode: Literal[SynthesisMode.RAW_NOTES] = SynthesisMode.RAW_NOTES
    title: str
    deduplication_summary: str
    clusters: list[NoteCluster]
    suggested_next_steps: list[NextStepItem]


SynthesisPayload = Annotated[
    Union[
        GlobalSummaryResult,
        TranscriptSummaryResult,
        UserJourneyResult,
        RawNotesResult,
    ],
    Field(discriminator="mode"),
]


# --- Documents, Uploads & Jobs ---
class DocumentMetadata(BaseModel):
    document_id: str
    file_name: str
    mime_type: str
    total_size_bytes: int
    uploaded_chunks: int
    total_chunks: int
    storage_key: str
    is_complete: bool = False


class DocumentPreviewBlock(BaseModel):
    location: str
    content: str


class DocumentPreviewResponse(BaseModel):
    document_id: str
    file_name: str
    total_blocks: int
    blocks: list[DocumentPreviewBlock]


class UploadInitRequest(BaseModel):
    file_name: str
    mime_type: str
    total_size_bytes: int
    total_chunks: int = Field(..., ge=1)


class UploadInitResponse(BaseModel):
    document_id: str
    upload_mode: Literal["chunked_api", "presigned_s3"]
    presigned_url: Optional[str] = None
    chunk_size_bytes: int = 5 * 1024 * 1024


class JobCreateRequest(BaseModel):
    document_ids: list[str] = Field(..., min_length=1)
    mode: SynthesisMode
    model_name: str = Field(default="mistral-medium-latest")


class JobStatusResponse(BaseModel):
    job_id: str
    stage: JobStage
    progress_percent: int = Field(..., ge=0, le=100)
    current_step_detail: str
    mode: SynthesisMode
    model_name: str
    documents: list[DocumentMetadata]
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    result: Optional[SynthesisPayload] = None


class ModelOption(BaseModel):
    id: str
    provider: Literal["gemini", "mistral", "custom"] = "mistral"
    provider_label: str = "Mistral AI"
    label: str
    description: str
    context_window: int
    api_key_configured: bool = False
