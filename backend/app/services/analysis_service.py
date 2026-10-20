"""Pipeline d'analyse documentaire structurée (API v2, interface « Analyse documentaire »).

Étapes suivies par l'écran de progression :
  1. Lecture des documents          (0 → 15 %)
  2. Découpage et indexation         (15 → 30 %)  — condensation si le corpus dépasse le contexte
  3. Identification des grands thèmes (30 → 60 %)  — aperçu en direct des thèmes
  4. Rédaction de la synthèse        (60 → 90 %)
  5. Mise en forme                   (90 → 100 %)

Deux formats de résultat :
  - "themes"  : synthèse globale, transcription, notes en vrac
  - "journey" : flux et parcours utilisateurs
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import litellm

from app.core.config import settings
from app.services.parser_service import AnchoredTextBlock, MultiFormatDocumentParser

Mode = Literal["global", "transcript", "notes", "flow"]
Level = Literal["synth", "detail", "deep"]

MODE_LABELS: dict[str, str] = {
    "global": "Synthèse globale",
    "transcript": "Synthèse de transcription",
    "notes": "Synthèse de notes en vrac",
    "flow": "Flux et parcours utilisateurs",
}
LEVEL_LABELS: dict[str, str] = {"synth": "Synthétique", "detail": "Détaillé", "deep": "Très détaillé"}

CHARS_PER_TOKEN = 3.2  # estimation prudente pour le français
RESERVED_TOKENS = 16_000
TEMPERATURE = 0.2


class AnalysisError(Exception):
    """Erreur métier remontée telle quelle à l'interface."""


# ---------------------------------------------------------------------------
# Catalogue des modèles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderConf:
    key: str  # préfixe des variables .env : CUSTOM_LLM, CUSTOM_LLM_2, GEMINI, ANTHROPIC
    kind: Literal["openai", "gemini", "anthropic"]
    name: str
    api_key: str
    api_base: str
    ca_bundle: str
    context_tokens: int
    models: tuple[str, ...]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    provider: ProviderConf
    description: str
    quality: int
    speed: int
    economy: int
    tier: Literal["deep", "balanced", "fast"]

    @property
    def context_tokens(self) -> int:
        return self.provider.context_tokens


def _names(raw: str) -> tuple[str, ...]:
    return tuple(m.strip() for m in (raw or "").split(",") if m.strip())


def providers() -> list[ProviderConf]:
    """Fournisseurs déclarés dans backend/.env (voir .env.example).

    - CUSTOM_LLM / CUSTOM_LLM_2 : endpoints compatibles OpenAI.
    - GEMINI / ANTHROPIC : clés de test, proposées seulement si la clé est renseignée.
    """
    out = [
        ProviderConf(
            key=key,
            kind="openai",
            name=(getattr(settings, f"{key}_PROVIDER_NAME") or key).strip(),
            api_key=(getattr(settings, f"{key}_API_KEY") or "").strip(),
            api_base=(getattr(settings, f"{key}_API_BASE") or "").strip().rstrip("/"),
            ca_bundle=(getattr(settings, f"{key}_CA_BUNDLE") or "").strip(),
            context_tokens=getattr(settings, f"{key}_CONTEXT_TOKENS"),
            models=_names(getattr(settings, f"{key}_AVAILABLE_MODELS")),
        )
        for key in ("CUSTOM_LLM", "CUSTOM_LLM_2")
    ]
    tests = [
        ("GEMINI", "gemini", "Google Gemini (test)", settings.GEMINI_API_KEY,
         settings.GEMINI_CA_BUNDLE, 1_000_000, settings.GEMINI_TEST_MODELS),
        ("ANTHROPIC", "anthropic", "Anthropic Claude (test)", settings.ANTHROPIC_API_KEY,
         settings.ANTHROPIC_CA_BUNDLE, 200_000, settings.ANTHROPIC_TEST_MODELS),
    ]
    for key, kind, name, api_key, ca, ctx, models in tests:
        if settings._is_key_set(api_key or ""):
            out.append(ProviderConf(key, kind, name, api_key.strip(), "", (ca or "").strip(), ctx, _names(models)))
    return out


# Profil déduit du nom du modèle : la liste elle-même vient uniquement du .env.
_DEEP = re.compile(r"large|opus|pro\b|ultra|argon|70b|72b|405b|-max", re.I)
_FAST = re.compile(r"small|\bmini\b|haiku|lite|nano|tiny|\b[1-9]b\b", re.I)
_TIER_SCORES = {"deep": (5, 2, 2), "balanced": (4, 4, 4), "fast": (3, 5, 5)}
_TIER_DESC = {
    "deep": "Raisonnement approfondi, pour les analyses très détaillées et les corpus complexes.",
    "balanced": "Équilibre entre profondeur d'analyse et rapidité.",
    "fast": "Rapide et économique, idéal pour des synthèses courtes.",
}


def _tier(model: str) -> Literal["deep", "balanced", "fast"]:
    if _DEEP.search(model):
        return "deep"
    if _FAST.search(model):
        return "fast"
    return "balanced"


def all_models() -> list[ModelSpec]:
    """Modèles listés dans *_AVAILABLE_MODELS, dans l'ordre du .env."""
    models = []
    for prov in providers():
        for n in prov.models:
            tier = _tier(n)
            q, v, c = _TIER_SCORES[tier]
            models.append(ModelSpec(f"{prov.key}:{n}", n, prov, _TIER_DESC[tier], q, v, c, tier))
    return models


def is_configured(spec: ModelSpec) -> bool:
    if spec.provider.kind != "openai":
        return True  # les fournisseurs de test ne sont listés que si leur clé est renseignée
    # La clé est facultative : un endpoint interne (vLLM, Ollama) peut ne pas en exiger.
    return bool(spec.provider.api_base)


def model_options() -> list[dict[str, Any]]:
    return [
        {
            "id": m.id,
            "name": m.name,
            "provider": m.provider.key,
            "provider_label": m.provider.name,
            "description": m.description,
            "quality": m.quality,
            "speed": m.speed,
            "economy": m.economy,
            "tier": m.tier,
            "configured": is_configured(m),
        }
        for m in all_models()
    ]


def get_model(model_id: str) -> ModelSpec:
    for m in all_models():
        if m.id == model_id:
            return m
    raise AnalysisError(f"Modèle inconnu : {model_id} (vérifiez *_AVAILABLE_MODELS dans backend/.env)")


_CLIENTS: dict[tuple[str, str], Any] = {}


def _openai_client(prov: ProviderConf) -> Any:
    """Client dédié quand un certificat d'entreprise (CA bundle) est requis pour ce fournisseur."""
    if not prov.ca_bundle:
        return None
    cache_key = (prov.api_base, prov.ca_bundle)
    if cache_key not in _CLIENTS:
        import httpx
        from openai import AsyncOpenAI

        _CLIENTS[cache_key] = AsyncOpenAI(
            api_key=prov.api_key or "not-needed",
            base_url=prov.api_base,
            http_client=httpx.AsyncClient(verify=prov.ca_bundle, timeout=600),
        )
    return _CLIENTS[cache_key]


async def _complete(spec: ModelSpec, system_prompt: str, user_content: str, want_json: bool = True) -> str:
    prov = spec.provider
    if prov.kind == "openai":
        if not prov.api_base:
            raise AnalysisError(f"{prov.key}_API_BASE n'est pas renseignée dans backend/.env")
        kwargs: dict[str, Any] = {"api_base": prov.api_base, "api_key": prov.api_key or "not-needed"}
        client = _openai_client(prov)
        if client is not None:
            kwargs["client"] = client
    else:
        kwargs = {"api_key": prov.api_key}
        if prov.ca_bundle:
            kwargs["ssl_verify"] = prov.ca_bundle
    # Claude ne gère pas response_format : le prompt impose déjà un JSON strict.
    if want_json and prov.kind != "anthropic":
        kwargs["response_format"] = {"type": "json_object"}

    response = await litellm.acompletion(
        model=f"{prov.kind}/{spec.name}",
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        num_retries=2,
        timeout=600,
        **kwargs,
    )
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise AnalysisError(f"Réponse vide du modèle {spec.name}.")
    return content


_RETRYABLE = (litellm.RateLimitError, litellm.ServiceUnavailableError, litellm.InternalServerError, litellm.Timeout)


def _friendly_error(spec: ModelSpec, exc: Exception) -> str:
    if isinstance(exc, litellm.RateLimitError):
        return (f"Quota du fournisseur dépassé pour {spec.name} (limite atteinte). "
                "Réessayez plus tard ou choisissez un autre modèle.")
    if isinstance(exc, litellm.AuthenticationError):
        return f"La clé API du fournisseur « {spec.provider.name} » a été refusée : vérifiez {spec.provider.key}_API_KEY dans backend/.env."
    if isinstance(exc, litellm.NotFoundError):
        return f"Le modèle {spec.name} n'est pas disponible chez le fournisseur."
    if isinstance(exc, litellm.Timeout):
        return f"Le modèle {spec.name} n'a pas répondu à temps. Réessayez avec un niveau moins détaillé."
    if isinstance(exc, litellm.ContextWindowExceededError):
        return f"Le corpus dépasse la fenêtre de contexte de {spec.name}."
    return f"Échec de l'appel au modèle {spec.name} : {str(exc)[:300]}"


def fallback_chain(spec: ModelSpec) -> list[ModelSpec]:
    """Modèle choisi puis, en cas de quota ou surcharge, les autres modèles configurés du même fournisseur."""
    order = {"deep": 0, "balanced": 1, "fast": 2}
    others = [m for m in all_models() if m.provider.key == spec.provider.key and m.id != spec.id and is_configured(m)]
    others.sort(key=lambda m: abs(order[m.tier] - order[spec.tier]))
    return [spec, *others]


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AnalysisError("Le modèle n'a pas renvoyé de JSON exploitable.")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AnalysisError("Le modèle a renvoyé un JSON invalide.") from exc
    if not isinstance(data, dict):
        raise AnalysisError("Le modèle a renvoyé une structure inattendue.")
    return data


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
    pages: int
    blocks: list[AnchoredTextBlock]

    @property
    def chars(self) -> int:
        return sum(len(b.content) for b in self.blocks)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "ext": self.ext,
            "size_bytes": self.size_bytes,
            "units": self.units,
            "pages": self.pages,
        }


DOCUMENTS: dict[str, StoredDocument] = {}
_parser = MultiFormatDocumentParser()


def _describe_units(ext: str, blocks: list[AnchoredTextBlock], chars: int) -> tuple[str, int]:
    """Résumé lisible du volume (pages, slides, lignes) et équivalent en pages."""
    if ext == "pdf":
        n = len(blocks)
        return f"{n} page{'s' if n > 1 else ''}", n
    if ext in {"pptx", "ppt"}:
        n = len(blocks)
        return f"{n} slide{'s' if n > 1 else ''}", n
    pages = max(1, round(chars / 2500))
    if ext in {"csv", "xlsx", "xls"}:
        last = 0
        for b in blocks:
            nums = re.findall(r"(\d+)", b.location)
            if nums:
                last = max(last, int(nums[-1]))
        if last:
            return f"{last} lignes", pages
    if ext in {"docx", "doc"}:
        return f"{pages} page{'s' if pages > 1 else ''}", pages
    return "", pages


def store_document(content: bytes, file_name: str) -> StoredDocument:
    safe_name = Path(file_name).name or "document.txt"
    doc_id = str(uuid.uuid4())
    path = settings.STORAGE_DIR / f"v2_{doc_id}_{safe_name}"
    path.write_bytes(content)
    try:
        blocks = [b for b in _parser.parse_file(path, safe_name) if b.content.strip()]
    except Exception as exc:  # fichier corrompu, format non lisible
        raise AnalysisError(f"Impossible de lire {safe_name} : {exc}") from exc
    if not blocks:
        raise AnalysisError(f"Aucun texte exploitable dans {safe_name} (document scanné ?).")
    ext = Path(safe_name).suffix.lower().lstrip(".") or "txt"
    chars = sum(len(b.content) for b in blocks)
    units, pages = _describe_units(ext, blocks, chars)
    doc = StoredDocument(doc_id, safe_name, ext, len(content), units, pages, blocks)
    DOCUMENTS[doc_id] = doc
    return doc


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MODE_GUIDANCE: dict[str, str] = {
    "global": (
        "Croise l'ensemble des documents pour dégager les grands thèmes, les convergences et les points "
        "de divergence. Les pistes d'action sont des recommandations concrètes découlant des constats."
    ),
    "transcript": (
        "Il s'agit de transcriptions (entretien, réunion, atelier). Les thèmes sont les grands sujets abordés ; "
        "fais ressortir idées clés, décisions et verbatims marquants. Les pistes d'action sont les décisions prises "
        "et prochaines étapes (indique le responsable dans le texte si il est cité)."
    ),
    "notes": (
        "Il s'agit de notes brutes (notes de terrain, post-its, comptes rendus épars). Dédoublonne, remets de l'ordre "
        "et regroupe les idées par thème. Les pistes d'action sont les prochaines étapes suggérées."
    ),
    "flow": (
        "Reconstitue le parcours utilisateur décrit dans les documents : ses étapes, ce que fait l'utilisateur, "
        "ses points de contact, son ressenti, les frictions, les points de sortie et les opportunités."
    ),
}

LEVEL_GUIDANCE: dict[str, str] = {
    "synth": "Niveau synthétique : 3 à 4 thèmes, 2 à 3 points clés par thème, corps de point en 1 phrase.",
    "detail": "Niveau détaillé : 3 à 6 thèmes, 3 à 4 points clés par thème, corps de point en 2 à 3 phrases avec exemples.",
    "deep": (
        "Niveau très détaillé : 4 à 8 thèmes, 4 à 6 points clés par thème, corps de point argumenté (3 à 5 phrases), "
        "nuances systématiques et sources précises pour chaque point."
    ),
}

FLOW_LEVEL_GUIDANCE: dict[str, str] = {
    "synth": "Niveau synthétique : 4 à 5 étapes, 1 friction et 1 opportunité par étape, 2 à 3 frictions prioritaires.",
    "detail": "Niveau détaillé : 4 à 6 étapes, 1 à 2 frictions et opportunités par étape, 3 à 4 frictions prioritaires.",
    "deep": "Niveau très détaillé : 5 à 7 étapes, 1 à 3 frictions et opportunités par étape, 4 à 6 frictions prioritaires.",
}

BASE_RULES = (
    "Tu es un analyste expert en recherche qualitative. Règles impératives :\n"
    "- N'invente rien : chaque affirmation doit être étayée par le corpus fourni.\n"
    "- Les citations (verbatims) sont recopiées mot pour mot depuis le corpus.\n"
    "- Les noms de documents sont recopiés exactement tels qu'indiqués dans les balises [SOURCE: ...].\n"
    "- Réponds uniquement avec un objet JSON valide, sans texte autour."
)


def _language_rule(language: str) -> str:
    target = "anglais" if language == "en" else "français"
    return f"Rédige tout le contenu textuel en {target} (les verbatims restent dans leur langue d'origine)."


THEMES_OUTLINE_SCHEMA = """{
  "title": "titre court et explicite de l'étude (max 8 mots)",
  "themes": [{"title": "intitulé du thème (3 à 6 mots)"}]
}"""

FLOW_OUTLINE_SCHEMA = """{
  "title": "titre court et explicite du parcours (max 8 mots)",
  "phases": [{"name": "nom de l'étape (1 à 3 mots)"}]
}"""

THEMES_SCHEMA = """{
  "title": "titre court et explicite de l'étude",
  "brief": "2 à 3 phrases qui résument l'essentiel ; entoure de *astérisques* un seul mot ou groupe de 2 à 4 mots, le plus important",
  "themes": [
    {
      "title": "intitulé du thème",
      "summary": "2 à 3 phrases de synthèse du thème",
      "documents": ["noms exacts des documents où le thème est présent"],
      "points": [
        {
          "lead": "le point clé en une phrase courte",
          "body": "développement argumenté avec exemples",
          "sources": [{"document": "nom exact du document", "location": "p. 4 / Lignes 10-20 / Slide 3 ..."}]
        }
      ],
      "quote": "verbatim marquant recopié mot pour mot (chaîne vide si aucun)",
      "quote_by": "qui parle et dans quel contexte (ex. Participante 7 — entretien individuel)",
      "nuance": "nuance ou point de divergence observé (chaîne vide si aucun)"
    }
  ],
  "actions": [
    {"title": "piste d'action concrète", "body": "1 à 2 phrases de justification", "theme": 1}
  ]
}"""

FLOW_SCHEMA = """{
  "title": "titre court et explicite du parcours",
  "brief": "2 à 3 phrases qui résument le parcours ; entoure de *astérisques* un seul groupe de 2 à 6 mots, le plus important",
  "phases": [
    {
      "name": "nom de l'étape",
      "mood": "ressenti dominant en un mot (ex. Curieux, Hésitant, Perdu, Confiant, Frustré)",
      "sentiment": 0,
      "does": "ce que fait l'utilisateur à cette étape (1 phrase)",
      "touchpoints": ["points de contact (2 à 4 mots chacun)"],
      "frictions": ["frictions ou points de rupture (phrase courte)"],
      "opportunities": ["opportunités d'amélioration (phrase courte)"]
    }
  ],
  "flow": [
    {"label": "action ou écran du flux principal", "kind": "entry | step | goal", "breaking": false, "exit": "point de sortie / abandon à ce niveau (chaîne vide si aucun)"}
  ],
  "priorities": [
    {
      "severity": "Bloquant | Majeur | Mineur",
      "title": "intitulé de la friction",
      "body": "explication en 1 à 2 phrases",
      "quote": "verbatim recopié mot pour mot",
      "phase": "nom de l'étape concernée",
      "frequency": "fréquence observée (ex. 9 participants sur 12) ou chaîne vide"
    }
  ]
}"""


def _outline_prompt(mode: str, level: str, language: str) -> str:
    schema = FLOW_OUTLINE_SCHEMA if mode == "flow" else THEMES_OUTLINE_SCHEMA
    guidance = FLOW_LEVEL_GUIDANCE[level] if mode == "flow" else LEVEL_GUIDANCE[level]
    target = "les étapes du parcours, dans l'ordre chronologique" if mode == "flow" else "les grands thèmes, du plus au moins présent"
    return "\n\n".join([
        BASE_RULES,
        MODE_GUIDANCE[mode],
        f"Première passe : identifie uniquement {target}.",
        guidance,
        _language_rule(language),
        "Schéma JSON attendu :\n" + schema,
    ])


def _full_prompt(mode: str, level: str, language: str, cite: bool) -> str:
    if mode == "flow":
        parts = [
            BASE_RULES,
            MODE_GUIDANCE[mode],
            FLOW_LEVEL_GUIDANCE[level],
            "« sentiment » est un entier de -2 (très négatif) à 2 (très positif). "
            "Dans « flow », le premier élément est de kind « entry », le dernier de kind « goal » ; "
            "mets « breaking » à true pour les étapes où des utilisateurs décrochent. 5 à 7 éléments.",
            _language_rule(language),
            "Schéma JSON attendu :\n" + FLOW_SCHEMA,
        ]
    else:
        parts = [
            BASE_RULES,
            MODE_GUIDANCE[mode],
            LEVEL_GUIDANCE[level],
            "« theme » dans actions est le numéro (1, 2, ...) du thème concerné. 3 à 6 pistes d'action.",
            "Indique les sources de chaque point." if cite else "Laisse « sources » vide ([]) pour chaque point.",
            _language_rule(language),
            "Schéma JSON attendu :\n" + THEMES_SCHEMA,
        ]
    return "\n\n".join(parts)


CONDENSE_PROMPT = (
    "Tu prépares un corpus pour une analyse qualitative. Condense l'extrait ci-dessous en notes factuelles "
    "denses : idées, constats, chiffres, décisions, frictions et 2 à 4 verbatims marquants recopiés mot pour mot. "
    "Conserve pour chaque note la balise [SOURCE: document | LOC: emplacement] d'origine. "
    "Réponds en texte brut, sans introduction."
)


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
            if self.status == "done" or i < self.step:
                state, local = "done", 100
            elif i == self.step and self.status == "running":
                state = "active"
                local = round(max(0.0, min(1.0, (self.progress - start) / (end - start))) * 100)
            else:
                state, local = "pending", 0
            steps.append({"key": key, "label": label, "detail": details[i], "state": state, "progress": local})
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
            "model_name": spec.name if spec else self.model_id,
            "model_fallback": bool(self.active_model_id and self.active_model_id != self.model_id),
            "language": self.language,
            "cite": self.cite,
            "documents": [d.public() for d in self.documents],
            "created_at": self.created_at.isoformat(),
            "result": self.result,
            "markdown": self.markdown,
            "error": self.error,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title or MODE_LABELS[self.mode],
            "status": self.status,
            "mode": self.mode,
            "created_at": self.created_at.isoformat(),
        }


ANALYSES: dict[str, Analysis] = {}


def create_analysis(
    document_ids: list[str], mode: str, level: str, model_id: str, language: str, cite: bool
) -> Analysis:
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
        docs.append(doc)
    if not docs:
        raise AnalysisError("Importez au moins un document.")

    analysis = Analysis(
        id=str(uuid.uuid4()), mode=mode, level=level, model_id=model_id,
        language=language, cite=cite, documents=docs, created_at=datetime.now(timezone.utc),
    )
    ANALYSES[analysis.id] = analysis
    analysis.task = asyncio.create_task(_run(analysis, spec))
    return analysis


def cancel_analysis(analysis: Analysis) -> None:
    if analysis.status == "running" and analysis.task:
        analysis.task.cancel()
    if analysis.status == "running":
        analysis.status = "cancelled"


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


async def _call(analysis: Analysis, chain: list[ModelSpec], system_prompt: str, user: str, want_json: bool = True) -> str:
    """Appelle le modèle actif ; bascule sur le suivant de la chaîne en cas de quota ou de surcharge."""
    start = next((i for i, m in enumerate(chain) if m.id == analysis.active_model_id), 0)
    last: Exception | None = None
    for spec in chain[start:]:
        try:
            out = await _complete(spec, system_prompt, user, want_json)
            analysis.active_model_id = spec.id
            return out
        except _RETRYABLE as exc:
            last = exc
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(_friendly_error(spec, exc)) from exc
    raise AnalysisError(_friendly_error(chain[-1] if len(chain) > 1 else chain[0], last or Exception()))


def _enter(analysis: Analysis, step: int) -> None:
    analysis.step = step
    analysis.progress = max(analysis.progress, STEP_DEFS[step][2])


async def _run(analysis: Analysis, spec: ModelSpec) -> None:
    chain = fallback_chain(spec)
    try:
        # 1. Lecture
        _enter(analysis, 0)
        segments = [b.to_prompt_segment() for d in analysis.documents for b in d.blocks]
        await asyncio.sleep(0.6)  # laisse l'interface afficher l'étape

        # 2. Découpage / indexation (condensation si dépassement de contexte)
        _enter(analysis, 1)
        corpus = await _build_corpus(analysis, chain, segments)

        # 3. Thèmes / étapes
        _enter(analysis, 2)
        outline_raw = await _with_creep(
            analysis, 60,
            _call(analysis, chain, _outline_prompt(analysis.mode, analysis.level, analysis.language), corpus),
        )
        outline = _parse_json(outline_raw)
        analysis.title = str(outline.get("title") or "").strip()
        items = outline.get("phases" if analysis.mode == "flow" else "themes") or []
        names = [str(i.get("name") or i.get("title") or "").strip() for i in items if isinstance(i, dict)]
        for name in [n for n in names if n]:
            analysis.preview.append(name)
            await asyncio.sleep(0.35)

        # 4. Rédaction
        _enter(analysis, 3)
        plan_label = "Étapes identifiées" if analysis.mode == "flow" else "Thèmes identifiés"
        user = f"{plan_label} lors de la première passe (à suivre, ajustables si le corpus l'exige) :\n" + \
            "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names)) + "\n\nCorpus :\n\n" + corpus
        full_raw = await _with_creep(
            analysis, 90,
            _call(analysis, chain, _full_prompt(analysis.mode, analysis.level, analysis.language, analysis.cite), user),
        )

        # 5. Mise en forme
        _enter(analysis, 4)
        data = _parse_json(full_raw)
        doc_names = [d.name for d in analysis.documents]
        result = normalize_journey(data, doc_names) if analysis.mode == "flow" else normalize_themes(data, doc_names)
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


async def _build_corpus(analysis: Analysis, chain: list[ModelSpec], segments: list[str]) -> str:
    spec = chain[0]
    corpus = "\n".join(segments)
    max_chars = int((spec.context_tokens - RESERVED_TOKENS) * CHARS_PER_TOKEN)
    if len(corpus) <= max_chars:
        analysis.progress = 30
        return corpus

    # Dépassement : découpage en lots puis condensation fidèle de chaque lot.
    batch_chars = max_chars // 2
    batches, current, size = [], [], 0
    for seg in segments:
        if size + len(seg) > batch_chars and current:
            batches.append("\n".join(current))
            current, size = [], 0
        current.append(seg)
        size += len(seg)
    if current:
        batches.append("\n".join(current))

    sem = asyncio.Semaphore(settings.MAX_CONCURRENT_LLM_REQUESTS)
    done = 0

    async def condense(batch: str) -> str:
        nonlocal done
        async with sem:
            out = await _call(analysis, chain, CONDENSE_PROMPT, batch, want_json=False)
        done += 1
        analysis.progress = 15 + 15 * done / len(batches)
        return out

    return "\n\n".join(await asyncio.gather(*(condense(b) for b in batches)))


# ---------------------------------------------------------------------------
# Normalisation des résultats
# ---------------------------------------------------------------------------

def _s(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _str_list(value: Any) -> list[str]:
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _match_doc(name: str, doc_names: list[str]) -> str | None:
    """Rattache un nom de document approximatif à un document réel."""
    if not name:
        return None
    low = name.lower()
    for d in doc_names:
        if d.lower() == low:
            return d
    stem = Path(low).stem
    for d in doc_names:
        if Path(d.lower()).stem == stem or stem in d.lower() or Path(d.lower()).stem in low:
            return d
    return None


def normalize_themes(data: dict[str, Any], doc_names: list[str]) -> dict[str, Any]:
    themes = []
    citations = {d: 0 for d in doc_names}
    for raw in data.get("themes") or []:
        if not isinstance(raw, dict) or not _s(raw.get("title")):
            continue
        present = {m for m in (_match_doc(n, doc_names) for n in _str_list(raw.get("documents"))) if m}
        points = []
        for p in raw.get("points") or []:
            if not isinstance(p, dict) or not _s(p.get("lead")):
                continue
            sources = []
            for src in p.get("sources") or []:
                if not isinstance(src, dict):
                    continue
                doc = _match_doc(_s(src.get("document")), doc_names)
                if not doc:
                    continue
                sources.append({"document": doc, "location": _s(src.get("location"))})
                citations[doc] += 1
                present.add(doc)
            points.append({"lead": _s(p.get("lead")), "body": _s(p.get("body")), "sources": sources})
        themes.append({
            "title": _s(raw.get("title")),
            "summary": _s(raw.get("summary")),
            "documents": [d for d in doc_names if d in present],
            "points": points,
            "quote": _s(raw.get("quote")).strip("«»\"“” "),
            "quote_by": _s(raw.get("quote_by")),
            "nuance": _s(raw.get("nuance")),
        })
    if not themes:
        raise AnalysisError("Le modèle n'a identifié aucun thème exploitable.")

    actions = []
    for a in data.get("actions") or []:
        if not isinstance(a, dict) or not _s(a.get("title")):
            continue
        try:
            theme = int(a.get("theme") or 0)
        except (TypeError, ValueError):
            theme = 0
        actions.append({
            "title": _s(a.get("title")),
            "body": _s(a.get("body")),
            "theme": theme if 1 <= theme <= len(themes) else None,
        })

    return {
        "kind": "themes",
        "title": _s(data.get("title")),
        "brief": _s(data.get("brief")),
        "themes": themes,
        "actions": actions,
        "sources": [{"document": d, "citations": citations[d]} for d in doc_names],
        "stats": {
            "themes": len(themes),
            "points": sum(len(t["points"]) for t in themes),
            "quotes": sum(1 for t in themes if t["quote"]),
            "actions": len(actions),
        },
    }


def normalize_journey(data: dict[str, Any], doc_names: list[str]) -> dict[str, Any]:
    phases = []
    for raw in data.get("phases") or []:
        if not isinstance(raw, dict) or not _s(raw.get("name")):
            continue
        try:
            sentiment = max(-2, min(2, int(round(float(raw.get("sentiment") or 0)))))
        except (TypeError, ValueError):
            sentiment = 0
        phases.append({
            "name": _s(raw.get("name")),
            "mood": _s(raw.get("mood")),
            "sentiment": sentiment,
            "does": _s(raw.get("does")),
            "touchpoints": _str_list(raw.get("touchpoints")),
            "frictions": _str_list(raw.get("frictions")),
            "opportunities": _str_list(raw.get("opportunities")),
        })
    if not phases:
        raise AnalysisError("Le modèle n'a reconstitué aucune étape de parcours.")

    flow = []
    raw_flow = [f for f in data.get("flow") or [] if isinstance(f, dict) and _s(f.get("label"))]
    for i, f in enumerate(raw_flow):
        kind = _s(f.get("kind")).lower()
        if kind not in {"entry", "step", "goal"}:
            kind = "entry" if i == 0 else ("goal" if i == len(raw_flow) - 1 else "step")
        flow.append({"label": _s(f.get("label")), "kind": kind,
                     "breaking": bool(f.get("breaking")), "exit": _s(f.get("exit"))})

    priorities = []
    for p in data.get("priorities") or []:
        if not isinstance(p, dict) or not _s(p.get("title")):
            continue
        sev = _s(p.get("severity")).capitalize()
        priorities.append({
            "severity": sev if sev in {"Bloquant", "Majeur", "Mineur"} else "Majeur",
            "title": _s(p.get("title")),
            "body": _s(p.get("body")),
            "quote": _s(p.get("quote")).strip("«»\"“” "),
            "phase": _s(p.get("phase")),
            "frequency": _s(p.get("frequency")),
        })
    order = {"Bloquant": 0, "Majeur": 1, "Mineur": 2}
    priorities.sort(key=lambda p: order[p["severity"]])

    return {
        "kind": "journey",
        "title": _s(data.get("title")),
        "brief": _s(data.get("brief")),
        "phases": phases,
        "flow": flow,
        "priorities": priorities,
        "sources": [{"document": d, "citations": 0} for d in doc_names],
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def to_markdown(analysis: Analysis) -> str:
    r = analysis.result or {}
    spec = next((m for m in all_models() if m.id == (analysis.active_model_id or analysis.model_id)), None)
    lines = [
        f"# {r.get('title') or MODE_LABELS[analysis.mode]}",
        "",
        f"_{MODE_LABELS[analysis.mode]} · {LEVEL_LABELS[analysis.level]} · "
        f"{len(analysis.documents)} document(s) · {spec.name if spec else analysis.model_id}_",
        "",
        "## En bref",
        "",
        r.get("brief", "").replace("*", "**") if r.get("brief") else "",
        "",
    ]
    if r.get("kind") == "themes":
        for i, t in enumerate(r["themes"], start=1):
            lines += [f"## {i}. {t['title']}", "", t["summary"], ""]
            for p in t["points"]:
                src = "; ".join(f"{s['document']} {s['location']}".strip() for s in p["sources"])
                lines.append(f"- **{p['lead']}** {p['body']}" + (f" _(Sources : {src})_" if src else ""))
            lines.append("")
            if t["quote"]:
                lines += [f"> « {t['quote']} » — {t['quote_by']}", ""]
            if t["nuance"]:
                lines += [f"**Nuance / point de divergence :** {t['nuance']}", ""]
        if r["actions"]:
            lines += ["## Pistes d'action", ""]
            for i, a in enumerate(r["actions"], start=1):
                tag = f" _(Thème {a['theme']})_" if a.get("theme") else ""
                lines.append(f"{i}. **{a['title']}** {a['body']}{tag}")
            lines.append("")
    else:
        lines += ["## Carte du parcours", ""]
        for i, ph in enumerate(r.get("phases", []), start=1):
            lines += [f"### Étape {i} — {ph['name']} ({ph['mood']})", "", ph["does"], ""]
            if ph["touchpoints"]:
                lines.append(f"- **Points de contact :** {', '.join(ph['touchpoints'])}")
            for f in ph["frictions"]:
                lines.append(f"- **Friction :** {f}")
            for o in ph["opportunities"]:
                lines.append(f"- **Opportunité :** {o}")
            lines.append("")
        if r.get("flow"):
            lines += ["## Flux principal et points de sortie", ""]
            for f in r["flow"]:
                exit_ = f" — sortie : {f['exit']}" if f["exit"] else ""
                lines.append(f"- {f['label']}{exit_}")
            lines.append("")
        if r.get("priorities"):
            lines += ["## Frictions prioritaires", ""]
            for p in r["priorities"]:
                lines += [
                    f"### [{p['severity']}] {p['title']}",
                    "",
                    p["body"],
                    "",
                    f"> « {p['quote']} »" if p["quote"] else "",
                    "",
                    f"Étape : {p['phase']}" + (f" · Cité par {p['frequency']}" if p["frequency"] else ""),
                    "",
                ]
    lines.append("_Synthèse générée par un modèle de langage : vérifiez les points importants dans les sources citées._")
    return "\n".join(lines)
