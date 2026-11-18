"""Pipeline d'analyse documentaire structurée (API v2, interface DocAnalyser).

Étapes suivies par l'écran de progression :
  1. Lecture des documents          (0 → 15 %)
  2. Découpage et indexation         (15 → 30 %)  — condensation si le corpus dépasse le contexte
  3. Identification des grands thèmes (30 → 60 %)  — aperçu en direct des thèmes
  4. Rédaction de la synthèse        (60 → 90 %)
  5. Mise en forme                   (90 → 100 %)

Deux formats de résultat :
  - "themes"  : synthèse globale, transcription, notes en vrac
  - "journey" : flux et parcours utilisateurs

Ce module garde l'orchestration : documents, appels au modèle (essais, repli), déroulé d'une analyse.
Le reste vit à côté : models (catalogue), prompts (consignes), normalize (réponses du modèle),
report_markdown (export), errors ; batch_pipeline (gros corpus) et qa_service (questions).
Les noms déplacés restent importables depuis ce module.
"""
from __future__ import annotations

import asyncio
import logging
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal


from app.core.config import settings
from app.services import llm_client, store
from app.services.errors import AnalysisError, InvalidModelOutput, ProviderUnavailable
from app.services.models import (  # noqa: F401 : réexportés, utilisés via analysis_service ailleurs
    APP_ID, ENV_PROVIDERS, STUDIODOCK, ModelSpec, ProviderConf, all_models, connexions_studiodock, fallback_chain, get_model,
    is_configured, model_options, providers,
)
from app.services.normalize import (  # noqa: F401
    QuoteChecker, _match_doc, _s, _str_list, normalize_flow, normalize_journey, normalize_themes,
)
from app.services.parser_service import AnchoredTextBlock, MultiFormatDocumentParser, UnsupportedFormat, check_format
from app.services.prompts import (  # noqa: F401
    BASE_RULES, COMPLETENESS_RULE, LEVEL_GUIDANCE, LEVEL_LABELS, MODE_GUIDANCE, MODE_LABELS, _full_prompt,
    _language_rule, _outline_prompt,
)
from app.services.report_markdown import to_markdown, to_mermaid  # noqa: F401

Mode = Literal["global", "transcript", "notes", "flow"]
Level = Literal["synth", "detail", "deep"]


CHARS_PER_TOKEN = 3.2  # estimation prudente pour le français
RESERVED_TOKENS = 16_000
TEMPERATURE = 0  # fidélité : réponses les plus déterministes possibles
MAX_CONTINUATIONS = 3
# Au-delà, un échec d'envoi en un seul bloc déclenche le repli sur l'analyse par lots.
LARGE_REQUEST_TOKENS = 150_000
FALLBACK_REQUEST_TOKENS = 128_000
CONTINUE_PROMPT = (
    "Ta réponse a été coupée faute de place. Reprends exactement au caractère où tu t'es arrêté, "
    "sans rien répéter ni ajouter de commentaire."
)


logger = logging.getLogger("analyse")




async def _complete(
    spec: ModelSpec, system_prompt: str, user_content: str, want_json: bool = True,
    on_text: Callable[[str], None] | None = None,
) -> str:
    """Appel au modèle, réponse reçue en streaming ; on_text, s'il est fourni, reçoit le texte accumulé.

    Le streaming évite qu'une longue réponse soit coupée par le délai d'attente : celui-ci porte sur chaque morceau.
    """
    prov = spec.provider
    if not prov.api_base:
        raise AnalysisError(f"{prov.key}_API_BASE n'est pas renseignée dans backend/.env")
    # Claude ne gère pas la sortie JSON imposée : la consigne exige déjà un JSON strict.
    json_mode = want_json and prov.kind != "anthropic"

    extra, system_prompt = _thinking_off(spec, system_prompt)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    parts: list[str] = []
    timeout = request_timeout(spec, streaming=True)
    for _ in range(1 + MAX_CONTINUATIONS):
        chunk, finish = await llm_client.chat(
            base_url=prov.api_base, api_key=prov.api_key, model=spec.name, messages=messages,
            temperature=TEMPERATURE, max_tokens=prov.max_output_tokens, json_mode=json_mode,
            ca_bundle=prov.ca_bundle,
            on_delta=(lambda text, done="".join(parts): on_text(done + text)) if on_text else None,
            timeout=timeout, stream=True, extra=extra,
        )
        parts.append(chunk)
        if finish != "length" or not chunk:
            break
        # Réponse coupée faute de place : on demande la suite pour ne rien perdre de la fin.
        messages += [
            {"role": "assistant", "content": chunk},
            {"role": "user", "content": CONTINUE_PROMPT},
        ]
        json_mode = False  # la suite n'est pas un objet JSON complet
    else:
        raise AnalysisError(
            f"La synthèse produite par {spec.name} dépasse sa longueur maximale de réponse, même en plusieurs parties. "
            "Essayez un modèle à plus grande capacité de sortie."
        )

    content = _THINK.sub("", "".join(parts)).strip()
    if not content:
        raise AnalysisError(f"Réponse vide du modèle {spec.name}.")
    return content


_THINK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)  # réflexion écrite dans la réponse


def _thinking_off(spec: ModelSpec, system_prompt: str) -> tuple[dict[str, Any], str]:
    """Désactive la réflexion préalable : champ « think » d'Ollama (modèle local), consigne /no_think de Qwen 3.

    Le champ « think » n'est envoyé qu'à un modèle local : un champ inconnu peut être refusé par une passerelle
    d'entreprise. La consigne /no_think ne s'adresse qu'aux modèles Qwen. Une réflexion écrite malgré tout dans
    la réponse (<think>…</think>) en est retirée.
    """
    if not settings.DISABLE_THINKING:
        return {}, system_prompt
    extra: dict[str, Any] = {"think": False} if spec.provider.local else {}
    if re.search(r"qwen", spec.name, re.I) and "/no_think" not in system_prompt:
        system_prompt += "\n\n/no_think"
    return extra, system_prompt


def request_timeout(spec: ModelSpec, streaming: bool = False) -> float:
    """Attente maximale sans rien recevoir : plus longue pour un modèle sur ce poste (lent sur un gros lot).

    En streaming, le délai porte sur chaque morceau : un modèle qui écrit encore n'est jamais coupé. Un modèle
    local garde un délai plus long, car il lit tout le lot avant d'écrire le premier mot.
    """
    if spec.provider.local:
        return float(settings.LOCAL_STREAM_TIMEOUT_SECONDS if streaming else settings.LOCAL_LLM_TIMEOUT_SECONDS)
    return llm_client.STREAM_READ_TIMEOUT if streaming else float(settings.LLM_TIMEOUT_SECONDS)


def concurrency(spec: ModelSpec) -> int:
    """Appels simultanés au modèle : un seul à la fois, par défaut, pour un modèle sur ce poste."""
    limit = settings.LOCAL_CONCURRENT_LLM_REQUESTS if spec.provider.local else settings.MAX_CONCURRENT_LLM_REQUESTS
    return max(1, limit)


def _minutes(seconds: float) -> str:
    return f"{round(seconds / 60)} min" if seconds >= 120 else f"{round(seconds)} s"


_RETRYABLE = llm_client.RETRYABLE
RETRY_WAITS = (5, 15, 40)  # secondes, en cas de surcharge du fournisseur


def _friendly_error(spec: ModelSpec, exc: Exception) -> str:
    reason = str(exc)[:300]
    if isinstance(exc, llm_client.RateLimitError):
        return (f"Quota du fournisseur dépassé pour {spec.name} (limite atteinte). "
                "Réessayez plus tard ou choisissez un autre modèle.")
    if isinstance(exc, llm_client.AuthenticationError):
        return f"La clé API du fournisseur « {spec.provider.name} » a été refusée : vérifiez {spec.provider.key}_API_KEY dans backend/.env."
    if isinstance(exc, llm_client.NotFoundError):
        return f"Le modèle {spec.name} n'est pas disponible chez le fournisseur ({reason})."
    if isinstance(exc, llm_client.ServiceUnavailableError):
        return (f"Le fournisseur de {spec.name} est momentanément indisponible et n'a pas répondu malgré plusieurs "
                f"essais ({reason}). Relancez l'analyse dans quelques minutes.")
    if isinstance(exc, llm_client.TimeoutError):
        wait = _minutes(request_timeout(spec, streaming=True))
        if spec.provider.local:
            return (f"Le modèle {spec.name}, sur ce poste, n'a rien envoyé pendant {wait}. Il est peut-être surchargé ou "
                    "a manqué de mémoire (voir la fenêtre d'Ollama). Allongez LOCAL_STREAM_TIMEOUT_SECONDS ou réduisez "
                    "LOCAL_MAX_REQUEST_TOKENS dans backend/.env, ou choisissez un modèle plus léger.")
        return (f"Le modèle {spec.name} n'a rien envoyé pendant {wait}. Réessayez dans quelques minutes, ou avec "
                "un niveau moins détaillé.")
    if isinstance(exc, llm_client.ContextWindowExceededError):
        return f"Le corpus dépasse la fenêtre de contexte de {spec.name} : réduisez MAX_REQUEST_TOKENS ou CONTEXT_TOKENS."
    if isinstance(exc, llm_client.BadRequestError):
        return f"Le fournisseur de {spec.name} a refusé une requête : {reason}"
    return f"Échec de l'appel au modèle {spec.name} : {reason}"



def _parse_json(raw: str) -> dict[str, Any]:
    """Lecture tolérante : bloc ```json, texte autour, retours à la ligne non échappés, virgules en trop."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise InvalidModelOutput("Le modèle n'a pas renvoyé de JSON exploitable.")
    body = text[start : end + 1]
    for candidate in (body, re.sub(r",\s*([}\]])", r"\1", body)):
        try:
            data = json.loads(candidate, strict=False)  # strict=False : caractères de contrôle dans les chaînes
            break
        except json.JSONDecodeError:
            continue
    else:
        raise InvalidModelOutput("Le modèle a renvoyé un JSON invalide.")
    if not isinstance(data, dict):
        raise InvalidModelOutput("Le modèle a renvoyé une structure inattendue.")
    return data


async def _call_json(analysis: "Analysis", chain: list[ModelSpec], system_prompt: str, user: str, **kwargs) -> dict[str, Any]:
    """Appel au modèle dont la réponse doit être un objet JSON ; un nouvel essai si elle est illisible."""
    for attempt in range(2):
        raw = await _call(analysis, chain, system_prompt, user, **kwargs)
        try:
            return _parse_json(raw)
        except InvalidModelOutput:
            if attempt:
                raise
            user += ("\n\n(Ta réponse précédente n'était pas un JSON valide. Réponds uniquement avec un objet JSON "
                     "valide et complet, en échappant les guillemets dans les textes.)")
    raise AssertionError("inatteignable")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@dataclass
class StoredDocument:
    id: str
    name: str
    ext: str
    size_bytes: int
    units: str  # « 18 pages », « 412 lignes », « 12 slides »...
    pages: int  # équivalent en pages, pour l'estimation de durée
    blocks: list[AnchoredTextBlock]
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(b.content) for b in self.blocks)

    def plain_text(self) -> str:
        return "\n".join(b.plain_text() for b in self.blocks)

    def numbered(self) -> tuple[str, int] | None:
        """(« pages » ou « slides », dernier numéro) si le document se découpe en pages ou slides numérotées."""
        nums, kinds = [], set()
        for b in self.blocks:
            m = _NUMBERED.match(b.location)
            if not m:
                return None
            kinds.add(m.group(1))
            nums.append(int(m.group(2)))
        if len(kinds) != 1 or not nums:
            return None
        return ("pages" if kinds == {"Page"} else "slides"), max(nums)

    def public(self) -> dict[str, Any]:
        numbered = self.numbered()
        return {
            "id": self.id,
            "name": self.name,
            "ext": self.ext,
            "size_bytes": self.size_bytes,
            "units": self.units,
            "pages": self.pages,
            "warnings": self.warnings,
            "sections": numbered[0] if numbered else None,  # pages ou slides qu'on peut choisir d'analyser
            "last_section": numbered[1] if numbered else 0,
        }


_NUMBERED = re.compile(r"^(Page|Slide) (\d+)$")


def parse_selection(text: str, last: int, word: str = "page") -> list[tuple[int, int]]:
    """« 12-45, 80, 100- » → [(12, 45), (80, 80), (100, last)] ; message clair si la saisie est illisible."""
    ranges = []
    text = re.sub(r"\s*(?:-|–|à)\s*", "-", text.strip())  # « 12 à 45 », « 12 – 45 » → « 12-45 »
    for part in re.split(r"[,;\s]+", text):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not m or part == "-":
            raise AnalysisError(f"« {part} » n'est pas une sélection de {word}s lisible : écrivez par exemple 12-45, 80.")
        start, end = (int(m.group(3)), int(m.group(3))) if m.group(3) else (int(m.group(1) or 1), int(m.group(2) or last))
        if start > end:
            start, end = end, start
        if start < 1 or start > last:
            raise AnalysisError(f"La {word} {start} n'existe pas : le document va de 1 à {last}.")
        ranges.append((start, min(end, last)))
    return ranges


def select_sections(doc: StoredDocument, text: str) -> StoredDocument:
    """Copie du document réduite aux pages (ou slides) choisies, enregistrée comme un document à part.

    Le nom reste le même : les sources citées (« Page 12 ») renvoient toujours au bon passage.
    """
    numbered = doc.numbered()
    if not numbered:
        raise AnalysisError(f"{doc.name} ne se découpe pas en pages : il est analysé en entier.")
    kind, last = numbered
    word = kind[:-1]
    ranges = parse_selection(text, last, word)
    if not ranges:
        return doc
    keep = lambda n: any(a <= n <= b for a, b in ranges)  # noqa: E731
    blocks = [b for b in doc.blocks if keep(int(_NUMBERED.match(b.location).group(2)))]
    if not blocks:
        raise AnalysisError(f"Aucune {word} avec du texte dans la sélection « {text} » de {doc.name}.")
    label = ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in ranges)
    unit = "p." if kind == "pages" else "slides"
    plural = "s" if len(blocks) > 1 else ""
    selected = StoredDocument(
        str(uuid.uuid4()), doc.name, doc.ext, doc.size_bytes,
        f"{len(blocks)} {word}{plural} sur {doc.units} ({unit} {label})",
        len(blocks) if kind == "pages" else max(1, round(sum(len(b.content) for b in blocks) / 2500)),
        blocks, doc.warnings,
    )
    DOCUMENTS[selected.id] = selected
    store.save_document(selected)
    return selected


DOCUMENTS: dict[str, StoredDocument] = {}
_parser = MultiFormatDocumentParser()


# Anciens formats binaires d'Office : aucune des bibliothèques de lecture ne les ouvre.
LEGACY_FORMATS = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}


def store_document(content: bytes, file_name: str) -> StoredDocument:
    safe_name = Path(file_name).name or "document.txt"
    suffix = Path(safe_name).suffix.lower()
    if suffix in LEGACY_FORMATS:
        modern = LEGACY_FORMATS[suffix]
        raise AnalysisError(
            f"{safe_name} est à l'ancien format {suffix}, que DocAnalyser ne sait pas lire. Ouvrez-le dans "
            f"Office et enregistrez-le au format {modern} (Fichier › Enregistrer sous), puis importez-le à nouveau."
        )
    try:
        check_format(safe_name, content)
    except UnsupportedFormat as exc:
        raise AnalysisError(str(exc)) from exc
    doc_id = str(uuid.uuid4())
    path = settings.STORAGE_DIR / f"v2_{doc_id}_{safe_name}"
    path.write_bytes(content)
    try:
        parsed = _parser.parse(path, safe_name)
    except Exception as exc:  # fichier corrompu, format non lisible
        raise AnalysisError(f"Impossible de lire {safe_name} : {exc}") from exc
    blocks = [b for b in parsed.blocks if b.content.strip()]
    if not blocks:
        detail = f" ({parsed.warnings[0]})" if parsed.warnings else ""
        raise AnalysisError(f"Aucun texte lisible dans {safe_name}{detail}. Les documents scannés doivent être océrisés.")
    ext = Path(safe_name).suffix.lower().lstrip(".") or "txt"
    chars = sum(len(b.plain_text()) for b in blocks)
    pages = len(blocks) if ext == "pdf" else max(1, round(chars / 2500))
    doc = StoredDocument(doc_id, safe_name, ext, len(content), parsed.units, pages, blocks, parsed.warnings)
    DOCUMENTS[doc_id] = doc
    store.save_document(doc)
    return doc


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

STEP_DEFS = [
    ("read", "Lecture des documents", 0, 15),
    ("index", "Découpage et indexation du contenu", 15, 30),
    ("themes", "Identification des grands thèmes", 30, 60),
    ("write", "Rédaction de la synthèse", 60, 90),
    ("format", "Mise en forme", 90, 100),
]


@dataclass
class Analysis:
    id: str
    mode: str
    level: str
    model_id: str
    language: str
    cite: bool
    documents: list[StoredDocument]
    created_at: datetime
    status: Literal["running", "done", "failed", "cancelled"] = "running"
    progress: float = 0.0
    step: int = 0
    preview: list[str] = field(default_factory=list)
    title: str = ""
    result: dict[str, Any] | None = None
    markdown: str = ""
    error: str | None = None
    task: asyncio.Task | None = None
    active_model_id: str = ""
    batched: bool = False  # corpus trop grand pour le modèle : analyse par lots
    step_notes: dict[int, str] = field(default_factory=dict)  # précisions d'étape (« lot 3/6 »)
    context_cap: int = 0  # plafond de taille de requête après un échec d'envoi en un seul bloc
    questions: list[dict[str, Any]] = field(default_factory=list)  # questions posées sur les documents (qa_service)
    markdown_edited: bool = False  # texte exporté modifié à la main après l'analyse
    eta_at: float = 0.0  # fin estimée (horodatage time.time()), mesurée sur les premiers lots ; 0 = inconnue

    def step_details(self) -> list[str]:
        total_pages = sum(d.pages for d in self.documents)
        n = len(self.documents)
        cite = ", avec citations des sources" if self.cite else ""
        return [
            f"{n} fichier{'s' if n > 1 else ''} · {total_pages} page{'s' if total_pages > 1 else ''}",
            "Repérage des passages, intervenants et citations",
            "Reconstitution des étapes du parcours" if self.mode == "flow"
            else "Regroupement des idées récurrentes entre documents",
            f"Niveau {LEVEL_LABELS[self.level].lower()}{cite}",
            "Structuration par étapes, frictions et opportunités" if self.mode == "flow"
            else "Structuration par thèmes et points clés",
        ]

    def public(self) -> dict[str, Any]:
        details = self.step_details()
        steps = []
        for i, (key, label, start, end) in enumerate(STEP_DEFS):
            if key == "themes" and self.mode == "flow":
                label = "Identification des étapes du parcours"
            if key == "index" and self.batched:
                label = "Découpage et extraction par lots"
            if self.status == "done" or i < self.step:
                state, local = "done", 100
            elif i == self.step and self.status == "running":
                state = "active"
                local = round(max(0.0, min(1.0, (self.progress - start) / (end - start))) * 100)
            else:
                state, local = "pending", 0
            detail = self.step_notes.get(i, details[i])
            steps.append({"key": key, "label": label, "detail": detail, "state": state, "progress": local})
        spec = next((m for m in all_models() if m.id == (self.active_model_id or self.model_id)), None)
        return {
            "id": self.id,
            "status": self.status,
            "progress": 100 if self.status == "done" else int(self.progress),
            "steps": steps,
            "preview": self.preview,
            "title": self.title,
            "mode": self.mode,
            "mode_label": MODE_LABELS[self.mode],
            "level": self.level,
            "level_label": LEVEL_LABELS[self.level],
            "model_id": self.model_id,
            "model_name": spec.name if spec else self.model_id.split(":", 1)[-1],
            "model_fallback": bool(self.active_model_id and self.active_model_id != self.model_id),
            "language": self.language,
            "cite": self.cite,
            "documents": [d.public() for d in self.documents],
            "created_at": self.created_at.isoformat(),
            "result": self.result,
            "markdown": self.markdown,
            "error": self.error,
            "questions": self.questions,
            "markdown_edited": self.markdown_edited,
            "eta_seconds": max(0, round(self.eta_at - time.time())) if self.status == "running" and self.eta_at else None,
        }

    def summary(self) -> dict[str, Any]:
        spec = next((m for m in all_models() if m.id == (self.active_model_id or self.model_id)), None)
        return {
            "id": self.id,
            "title": self.title or MODE_LABELS[self.mode],
            "status": self.status,
            "mode": self.mode,
            "mode_label": MODE_LABELS[self.mode],
            "level_label": LEVEL_LABELS[self.level],
            "model_name": spec.name if spec else self.model_id.split(":", 1)[-1],
            "documents": [d.name for d in self.documents],
            "created_at": self.created_at.isoformat(),
        }


ANALYSES: dict[str, Analysis] = {}


def create_analysis(
    document_ids: list[str], mode: str, level: str, model_id: str, language: str, cite: bool,
    sections: dict[str, str] | None = None,
) -> Analysis:
    """sections : pages (ou slides) à analyser par document, par exemple {id: "12-45, 80"} ; absent = tout."""
    if mode not in MODE_LABELS:
        raise AnalysisError(f"Mode inconnu : {mode}")
    if level not in LEVEL_LABELS:
        raise AnalysisError(f"Niveau inconnu : {level}")
    spec = get_model(model_id)
    if not is_configured(spec):
        raise AnalysisError(f"{spec.provider.key}_API_BASE n'est pas renseignée dans backend/.env pour {spec.name}.")
    docs = []
    for doc_id in document_ids:
        doc = DOCUMENTS.get(doc_id)
        if not doc:
            raise AnalysisError("Un des documents est introuvable : importez-le à nouveau.")
        wanted = (sections or {}).get(doc_id, "").strip()
        docs.append(select_sections(doc, wanted) if wanted else doc)
    if not docs:
        raise AnalysisError("Importez au moins un document.")

    analysis = Analysis(
        id=str(uuid.uuid4()), mode=mode, level=level, model_id=model_id,
        language=language, cite=cite, documents=docs, created_at=datetime.now(timezone.utc),
    )
    ANALYSES[analysis.id] = analysis
    store.save_analysis(analysis)
    analysis.task = asyncio.create_task(_run(analysis, spec))
    return analysis


def retry_analysis(old: Analysis) -> Analysis:
    """Relance une analyse échouée ou annulée, avec les mêmes documents et réglages, à la place de l'ancienne.

    Les lots déjà extraits (gardés sur le disque) sont repris : l'analyse repart là où elle s'était arrêtée.
    """
    if old.status not in ("failed", "cancelled"):
        raise AnalysisError("Seule une analyse échouée ou annulée peut être reprise.")
    new = create_analysis([d.id for d in old.documents], old.mode, old.level, old.model_id, old.language, old.cite)
    delete_analysis(old)  # ses documents servent à la nouvelle : ils sont gardés
    return new


def set_markdown(analysis: Analysis, markdown: str | None) -> None:
    """Texte exporté (Markdown, Word, PDF) modifié à la main ; None revient au texte produit par l'analyse."""
    if analysis.status != "done":
        raise AnalysisError("La synthèse n'est pas encore prête.")
    if markdown is None or not markdown.strip():
        analysis.markdown, analysis.markdown_edited = to_markdown(analysis), False
    else:
        analysis.markdown, analysis.markdown_edited = markdown, True
    store.save_analysis(analysis)


def cancel_analysis(analysis: Analysis) -> None:
    if analysis.status == "running" and analysis.task:
        analysis.task.cancel()
    if analysis.status == "running":
        analysis.status = "cancelled"
    store.save_analysis(analysis)


def delete_analysis(analysis: Analysis) -> None:
    """Supprime une analyse, et ses documents s'ils ne servent à aucune autre analyse."""
    cancel_analysis(analysis)
    ANALYSES.pop(analysis.id, None)
    store.delete_analysis(analysis.id)
    still_used = {d.id for a in ANALYSES.values() for d in a.documents}
    for doc in analysis.documents:
        if doc.id not in still_used:
            DOCUMENTS.pop(doc.id, None)
            store.delete_document(doc.id)


def load_history() -> None:
    """Recharge documents et analyses enregistrés (appelé au démarrage du serveur)."""
    documents, analyses = store.load_all()
    DOCUMENTS.update(documents)
    ANALYSES.update(analyses)


async def _creep(analysis: Analysis, target: float) -> None:
    """Fait avancer doucement la barre pendant un appel LLM dont on ne connaît pas la durée."""
    while True:
        await asyncio.sleep(0.5)
        analysis.progress += max(0.05, (target - analysis.progress) * 0.03)
        analysis.progress = min(analysis.progress, target)


async def _with_creep(analysis: Analysis, end: float, coro):
    creeper = asyncio.create_task(_creep(analysis, end - 1))
    try:
        return await coro
    finally:
        creeper.cancel()


async def _call(
    analysis: Analysis, chain: list[ModelSpec], system_prompt: str, user: str, want_json: bool = True,
    on_text: Callable[[str], None] | None = None, patient: bool = True,
) -> str:
    """Appelle le modèle actif ; bascule sur le suivant de la chaîne en cas de quota ou de surcharge.

    patient=False : un seul essai par modèle (inutile de renvoyer plusieurs fois une requête démesurée).
    """
    start = next((i for i, m in enumerate(chain) if m.id == analysis.active_model_id), 0)
    last: Exception | None = None
    for spec in chain[start:]:
        for attempt, wait in enumerate((0, *RETRY_WAITS) if patient else (0,)):
            if wait:
                await asyncio.sleep(wait)  # surcharge passagère : on patiente avant de réessayer
            try:
                out = await _complete(spec, system_prompt, user, want_json, on_text)
                analysis.active_model_id = spec.id
                return out
            except llm_client.RateLimitError as exc:
                last = exc
                if re.search(r"per ?day|PerDay|daily", str(exc), re.I):
                    break  # quota journalier épuisé : inutile d'insister, modèle suivant
                # limite par minute : elle se lève d'elle-même, on réessaie après une pause
            except llm_client.TimeoutError as exc:
                last = exc
                logger.warning("%s n'a pas répondu en %s", spec.name, _minutes(request_timeout(spec, streaming=True)))
                break  # modèle bloqué : on passe directement au suivant plutôt que de l'attendre à nouveau
            except _RETRYABLE as exc:
                last = exc
            except AnalysisError:
                raise
            except Exception as exc:
                logger.warning("Appel à %s refusé : %s", spec.name, exc)  # détail complet dans la console du backend
                raise AnalysisError(_friendly_error(spec, exc)) from exc
    raise ProviderUnavailable(_friendly_error(chain[-1] if len(chain) > 1 else chain[0], last or Exception()),
                              timed_out=isinstance(last, llm_client.TimeoutError))


def _enter(analysis: Analysis, step: int) -> None:
    analysis.step = step
    analysis.progress = max(analysis.progress, STEP_DEFS[step][2])


async def _run(analysis: Analysis, spec: ModelSpec) -> None:
    from app.services import batch_pipeline  # import local : le module dépend de celui-ci

    chain = fallback_chain(spec)
    try:
        # 1. Lecture
        _enter(analysis, 0)
        segments = [b.to_prompt_segment() for d in analysis.documents for b in d.blocks]
        corpus = "\n".join(segments)
        checker = QuoteChecker("\n".join(d.plain_text() for d in analysis.documents))
        await asyncio.sleep(0.6)  # laisse l'interface afficher l'étape
        if spec.provider.local:
            await _fit_local_context(analysis, chain[0])

        run_batches = batch_pipeline.run_flow if analysis.mode == "flow" else batch_pipeline.run_themes
        if batch_pipeline.needs_batches(chain[0], corpus, analysis.context_cap):
            # Corpus plus grand que la fenêtre du modèle : extraction par lots, puis rédaction thème par thème.
            analysis.batched = True
            data = await run_batches(analysis, chain, checker)
        else:
            large = len(corpus) / CHARS_PER_TOKEN > LARGE_REQUEST_TOKENS
            try:
                data = await _run_single_pass(analysis, chain, corpus, patient=not large)
            except ProviderUnavailable:
                if not large:
                    raise
                # Le fournisseur n'a pas traité le corpus d'un bloc (souvent une limite de volume par minute) :
                # on repart en analyse par lots, avec des requêtes de taille raisonnable.
                analysis.batched, analysis.context_cap = True, FALLBACK_REQUEST_TOKENS
                analysis.active_model_id, analysis.preview, analysis.title = "", [], ""
                analysis.progress, analysis.step = 15, 1
                tokens_k = round(len(corpus) / CHARS_PER_TOKEN / 1000)
                analysis.step_notes[1] = (
                    f"Le modèle n'a pas pu traiter les ≈ {tokens_k} 000 tokens d'un seul bloc : passage à l'analyse par lots"
                )
                data = await run_batches(analysis, chain, checker)

        # 5. Mise en forme
        _enter(analysis, 4)
        doc_names = [d.name for d in analysis.documents]
        normalize = normalize_journey if analysis.mode == "flow" else normalize_themes
        result = normalize(data, doc_names, checker)
        result["coverage"] = data.get("coverage")
        _flag_sources(result, analysis.documents)
        analysis.title = result["title"] or analysis.title or MODE_LABELS[analysis.mode]
        result["title"] = analysis.title
        analysis.result = result
        analysis.markdown = to_markdown(analysis)
        analysis.progress = 100
        analysis.status = "done"
    except asyncio.CancelledError:
        analysis.status = "cancelled"
    except AnalysisError as exc:
        analysis.status, analysis.error = "failed", str(exc)
    except Exception as exc:  # erreur inattendue
        analysis.status, analysis.error = "failed", f"Erreur inattendue : {str(exc)[:300]}"
    finally:
        analysis.eta_at = 0.0
        if analysis.id in ANALYSES:  # pas d'enregistrement si l'analyse vient d'être supprimée
            store.save_analysis(analysis)


LOCAL_MIN_CONTEXT = RESERVED_TOKENS + 8_000  # en dessous, un lot ne laisse presque plus de place au texte


async def _fit_local_context(analysis: Analysis, spec: ModelSpec) -> None:
    """Modèle Ollama : vérifie la fenêtre réellement ouverte, que l'adresse compatible OpenAI ne laisse pas choisir.

    Une fenêtre plus petite que les requêtes prévues ferait couper chaque lot sans prévenir : les requêtes sont
    alors réduites à cette fenêtre, ou l'analyse s'arrête tout de suite avec la marche à suivre.
    """
    from app.services import batch_pipeline

    try:
        # Petite requête : charge le modèle (ce qui serait fait de toute façon) pour lire sa fenêtre.
        await llm_client.chat(base_url=spec.provider.api_base, api_key=spec.provider.api_key, model=spec.name,
                              messages=[{"role": "user", "content": "OK"}], max_tokens=1,
                              ca_bundle=spec.provider.ca_bundle, timeout=request_timeout(spec))
        ctx = await llm_client.ollama_context_length(spec.provider.api_base, spec.name, spec.provider.ca_bundle)
    except llm_client.LLMError:
        return  # le vrai appel donnera l'erreur, avec son message
    planned = batch_pipeline.window_tokens(spec, analysis.context_cap)
    if not ctx or ctx >= planned:
        return
    if ctx < LOCAL_MIN_CONTEXT:
        raise AnalysisError(
            f"Ollama n'ouvre que {ctx:,} tokens de contexte pour {spec.name}, alors que DocAnalyser a besoin d'au "
            f"moins {LOCAL_MIN_CONTEXT:,} (ici {planned:,}) : la fin de chaque lot serait ignorée sans prévenir. "
            f"Dans Ollama, réglez « Context length » (ou la variable OLLAMA_CONTEXT_LENGTH) à {planned:,} ou plus, "
            "redémarrez Ollama, puis relancez l'analyse.".replace(",", " ")
        )
    analysis.context_cap = ctx
    logger.warning("Fenêtre d'Ollama pour %s : %s tokens (au lieu de %s prévus)", spec.name, ctx, planned)


def _flag_sources(result: dict[str, Any], documents: list[StoredDocument]) -> None:
    """Marque chaque source dont le repère n'existe pas dans le document (« found » à False)."""
    from app.services.source_lookup import location_exists

    by_name = {d.name: d for d in documents}
    for t in result.get("themes") or []:
        for p in t["points"]:
            for src in p["sources"]:
                doc = by_name.get(src["document"])
                src["found"] = bool(doc and src["location"] and location_exists(doc, src["location"]))


_JSON_STR = r'"((?:[^"\\]|\\.)*)"'


def _streamed_names(text: str, mode: str) -> tuple[str, list[str]]:
    """Titre de l'étude et noms des thèmes (ou étapes) déjà complets dans une réponse JSON en cours d'écriture."""
    def decode(raw: str) -> str:
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw

    title_match = re.search(r'"title"\s*:\s*' + _JSON_STR, text)
    title = decode(title_match.group(1)) if title_match else ""
    key, field_name = ('"phases"', "name") if mode == "flow" else ('"themes"', "title")
    start = text.find(key)
    if start < 0:
        return title, []
    segment = text[start:]
    end = segment.find('"actions"' if mode != "flow" else '"flow"')
    if end > 0:
        segment = segment[:end]
    names = [decode(n) for n in re.findall(rf'"{field_name}"\s*:\s*' + _JSON_STR, segment)]
    return title, [n.strip() for n in names if n.strip()]


async def _run_single_pass(analysis: Analysis, chain: list[ModelSpec], corpus: str, patient: bool = True) -> dict[str, Any]:
    """Le corpus tient dans la fenêtre du modèle : un seul appel sur le texte intégral.

    La réponse arrive en streaming : les thèmes s'affichent dans l'aperçu dès que le modèle les écrit,
    et l'étape « Rédaction » commence au premier thème.
    """
    _enter(analysis, 1)
    analysis.progress = 30
    _enter(analysis, 2)

    def on_text(text: str) -> None:
        title, names = _streamed_names(text, analysis.mode)
        if title and not analysis.title:
            analysis.title = title
        if names:
            if analysis.step < 3:
                _enter(analysis, 3)
            analysis.preview = names

    async def creep() -> None:
        while True:
            await asyncio.sleep(0.5)
            target = 59 if analysis.step < 3 else 89
            analysis.progress = min(target, analysis.progress + max(0.05, (target - analysis.progress) * 0.03))

    creeper = asyncio.create_task(creep())
    try:
        data = await _call_json(
            analysis, chain, _full_prompt(analysis.mode, analysis.level, analysis.language, analysis.cite),
            "Corpus :\n\n" + corpus, on_text=on_text, patient=patient,
        )
    finally:
        creeper.cancel()
    _enter(analysis, 3)
    return data


