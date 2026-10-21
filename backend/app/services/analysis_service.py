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
import difflib
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
TEMPERATURE = 0  # fidélité : réponses les plus déterministes possibles
MAX_CONTINUATIONS = 3
CONTINUE_PROMPT = (
    "Ta réponse a été coupée faute de place. Reprends exactement au caractère où tu t'es arrêté, "
    "sans rien répéter ni ajouter de commentaire."
)


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
    max_output_tokens: int = 0  # 0 : valeur par défaut du serveur


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
            max_output_tokens=getattr(settings, f"{key}_MAX_OUTPUT_TOKENS"),
        )
        for key in ("CUSTOM_LLM", "CUSTOM_LLM_2")
    ]
    tests = [
        ("GEMINI", "gemini", "Google Gemini (test)", settings.GEMINI_API_KEY,
         settings.GEMINI_CA_BUNDLE, settings.GEMINI_CONTEXT_TOKENS, settings.GEMINI_TEST_MODELS),
        ("ANTHROPIC", "anthropic", "Anthropic Claude (test)", settings.ANTHROPIC_API_KEY,
         settings.ANTHROPIC_CA_BUNDLE, settings.ANTHROPIC_CONTEXT_TOKENS, settings.ANTHROPIC_TEST_MODELS),
    ]
    for key, kind, name, api_key, ca, ctx, models in tests:
        if settings._is_key_set(api_key or ""):
            out.append(ProviderConf(key, kind, name, api_key.strip(), "", (ca or "").strip(), ctx, _names(models),
                                    max_output_tokens=32_000))
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

    if prov.max_output_tokens:
        kwargs["max_tokens"] = prov.max_output_tokens

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    parts: list[str] = []
    for _ in range(1 + MAX_CONTINUATIONS):
        response = await litellm.acompletion(
            model=f"{prov.kind}/{spec.name}",
            temperature=TEMPERATURE,
            messages=messages,
            num_retries=2,
            timeout=600,
            **kwargs,
        )
        choice = response.choices[0]
        chunk = choice.message.content or ""
        parts.append(chunk)
        if choice.finish_reason != "length" or not chunk:
            break
        # Réponse coupée faute de place : on demande la suite pour ne rien perdre de la fin.
        messages += [
            {"role": "assistant", "content": chunk},
            {"role": "user", "content": CONTINUE_PROMPT},
        ]
        kwargs.pop("response_format", None)  # la suite n'est pas un objet JSON complet
    else:
        raise AnalysisError(
            f"La synthèse produite par {spec.name} dépasse sa longueur maximale de réponse, même en plusieurs parties. "
            "Essayez un modèle à plus grande capacité de sortie."
        )

    content = "".join(parts).strip()
    if not content:
        raise AnalysisError(f"Réponse vide du modèle {spec.name}.")
    return content


_RETRYABLE = (litellm.RateLimitError, litellm.ServiceUnavailableError, litellm.InternalServerError, litellm.Timeout)
RETRY_WAITS = (5, 15, 40)  # secondes, en cas de surcharge du fournisseur


def _friendly_error(spec: ModelSpec, exc: Exception) -> str:
    if isinstance(exc, litellm.RateLimitError):
        return (f"Quota du fournisseur dépassé pour {spec.name} (limite atteinte). "
                "Réessayez plus tard ou choisissez un autre modèle.")
    if isinstance(exc, litellm.AuthenticationError):
        return f"La clé API du fournisseur « {spec.provider.name} » a été refusée : vérifiez {spec.provider.key}_API_KEY dans backend/.env."
    if isinstance(exc, litellm.NotFoundError):
        return f"Le modèle {spec.name} n'est pas disponible chez le fournisseur."
    if isinstance(exc, (litellm.ServiceUnavailableError, litellm.InternalServerError)):
        return (f"Le fournisseur de {spec.name} est momentanément surchargé et n'a pas répondu malgré plusieurs essais. "
                "Relancez l'analyse dans quelques minutes.")
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
    pages: int  # équivalent en pages, pour l'estimation de durée
    blocks: list[AnchoredTextBlock]
    warnings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(b.content) for b in self.blocks)

    def plain_text(self) -> str:
        return "\n".join(b.plain_text() for b in self.blocks)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "ext": self.ext,
            "size_bytes": self.size_bytes,
            "units": self.units,
            "pages": self.pages,
            "warnings": self.warnings,
        }


DOCUMENTS: dict[str, StoredDocument] = {}
_parser = MultiFormatDocumentParser()


def store_document(content: bytes, file_name: str) -> StoredDocument:
    safe_name = Path(file_name).name or "document.txt"
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
    return doc


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MODE_GUIDANCE: dict[str, str] = {
    "global": (
        "Croise l'ensemble des documents pour dégager les grands thèmes, les convergences et les points "
        "de divergence. Les pistes d'action sont uniquement les recommandations, demandes, attentes ou décisions "
        "exprimées dans les documents : n'en propose aucune de ton cru. Liste vide si les documents n'en contiennent pas."
    ),
    "transcript": (
        "Il s'agit de transcriptions (entretien, réunion, atelier). Les thèmes sont les grands sujets abordés ; "
        "fais ressortir idées clés, décisions et verbatims marquants. Les pistes d'action sont les décisions prises "
        "et prochaines étapes annoncées (indique le responsable et l'échéance seulement s'ils sont cités)."
    ),
    "notes": (
        "Il s'agit de notes brutes (notes de terrain, post-its, comptes rendus épars). Dédoublonne, remets de l'ordre "
        "et regroupe les idées par thème. Les pistes d'action sont les prochaines étapes ou idées d'action "
        "notées dans les documents, sans en ajouter."
    ),
    "flow": (
        "Reconstitue le parcours utilisateur décrit dans les documents : ses étapes, ce que fait l'utilisateur, "
        "ses points de contact, son ressenti, les frictions et les points de sortie. Les opportunités sont "
        "uniquement les attentes, demandes ou idées d'amélioration exprimées dans les documents."
    ),
}

# Le niveau règle la profondeur de rédaction de chaque élément, jamais le nombre
# d'éléments : tous les thèmes, étapes et frictions présents dans le corpus sont traités.
COMPLETENESS_RULE = (
    "Exhaustivité : traite tous les thèmes (ou étapes) importants présents dans le corpus, y compris ceux qui "
    "apparaissent en fin de document. Leur nombre dépend uniquement du corpus, pas du niveau demandé. "
    "Ne supprime jamais un élément important pour raccourcir ; le niveau ne change que la profondeur de rédaction."
)

LEVEL_GUIDANCE: dict[str, str] = {
    "synth": (
        "Niveau synthétique : rédaction concise. Pour chaque thème, les points clés essentiels ; "
        "chaque point tient en une phrase courte. Résumé du thème en 1 à 2 phrases. "
        "Verbatim et nuance seulement s'ils sont marquants."
    ),
    "detail": (
        "Niveau détaillé : chaque point clé est développé en 2 à 3 phrases avec un exemple tiré du corpus. "
        "Un verbatim marquant par thème ; nuance ou divergence quand le corpus en montre une."
    ),
    "deep": (
        "Niveau très détaillé : chaque point clé est argumenté (3 à 5 phrases), avec exemples, chiffres et contexte ; "
        "décompose les thèmes en points fins. Pour chaque thème : verbatim, nuance ou point de divergence, "
        "sources précises pour chaque point."
    ),
}

FLOW_GRAPH_RULES: dict[str, str] = {
    level: (
        "« flow » est un graphe libre qui reflète fidèlement ce que décrivent les documents : "
        "il peut être linéaire, comporter des embranchements, des chemins alternatifs, des retours en arrière "
        "ou plusieurs points d'entrée. N'invente pas de branches absentes du corpus. "
        "Types de nœuds : « entry » point d'entrée, « step » action ou écran, « decision » choix ou condition "
        "(au moins 2 liens sortants, chacun avec un label), « exit » abandon ou sortie du parcours (aucun lien sortant), "
        "« goal » objectif atteint. Mets « friction » à true sur les nœuds où des utilisateurs bloquent ou décrochent. "
        "Types de liens : « main » chemin principal, « alt » chemin alternatif, « exit » vers un abandon, "
        "« loop » retour en arrière ou répétition. "
        f"Granularité : {grain} Le graphe compte autant de nœuds que le parcours en décrit réellement."
    )
    for level, grain in {
        "synth": "regroupe les micro-étapes en étapes clés, mais garde toutes les décisions, abandons et retours.",
        "detail": "une étape par action ou écran significatif.",
        "deep": "détaille chaque écran, choix, condition et cas particulier décrits dans le corpus.",
    }.items()
}

FLOW_LEVEL_GUIDANCE: dict[str, str] = {
    "synth": (
        "Niveau synthétique : textes courts (une phrase). Les étapes du parcours sont les grandes phases ; "
        "pour chacune, les frictions et opportunités principales."
    ),
    "detail": (
        "Niveau détaillé : chaque étape décrit précisément ce que fait l'utilisateur ; "
        "frictions et opportunités formulées avec leur contexte."
    ),
    "deep": (
        "Niveau très détaillé : phases fines, toutes les frictions et opportunités citées dans le corpus, "
        "frictions prioritaires argumentées avec verbatim et fréquence."
    ),
}

BASE_RULES = (
    "Tu es un analyste expert en recherche qualitative. Ta synthèse remplace la lecture des documents : "
    "elle doit être d'une fidélité absolue au corpus. Règles impératives :\n"
    "- N'invente rien : chaque affirmation, chiffre, nom, date ou fréquence doit figurer dans le corpus. "
    "Si une information n'y est pas, laisse le champ vide plutôt que de la deviner.\n"
    "- Ne déforme pas : conserve le sens, les nuances et les désaccords tels qu'ils sont exprimés, et reprends tels "
    "quels les chiffres, durées, montants, dates, lieux et noms utiles.\n"
    "- Les citations (verbatims) sont recopiées mot pour mot depuis le corpus, sans les reformuler ni les traduire.\n"
    "- Exploite chaque document fourni ; n'en ignore aucun.\n"
    "- Les noms de documents sont recopiés exactement tels qu'indiqués dans les balises [SOURCE: ...]. "
    "Comme emplacement, reprends le repère de la ligne citée tel qu'il apparaît dans le corpus "
    "(L12, §4, Page 3, Slide 2, 00:01:10).\n"
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
          "sources": [{"document": "nom exact du document", "location": "repère exact du passage (L12, §4, Page 3, Slide 2, 00:01:10)"}]
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
      "opportunities": ["attentes ou idées d'amélioration exprimées dans les documents (phrase courte)"]
    }
  ],
  "flow": {
    "nodes": [
      {
        "id": "identifiant court unique (ex. n1)",
        "label": "action, écran ou décision (2 à 8 mots)",
        "type": "entry | step | decision | exit | goal",
        "friction": false
      }
    ],
    "edges": [
      {
        "from": "id du nœud de départ",
        "to": "id du nœud d'arrivée",
        "label": "condition ou action déclenchante (chaîne vide si évident)",
        "kind": "main | alt | exit | loop"
      }
    ]
  },
  "priorities": [
    {
      "severity": "Bloquant | Majeur | Mineur",
      "title": "intitulé de la friction",
      "body": "explication en 1 à 2 phrases",
      "quote": "verbatim recopié mot pour mot",
      "phase": "nom de l'étape concernée",
      "frequency": "fréquence citée dans les documents (ex. 9 participants sur 12), sinon chaîne vide"
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
        COMPLETENESS_RULE,
        guidance,
        _language_rule(language),
        "Schéma JSON attendu :\n" + schema,
    ])


def _full_prompt(mode: str, level: str, language: str, cite: bool) -> str:
    if mode == "flow":
        parts = [
            BASE_RULES,
            MODE_GUIDANCE[mode],
            COMPLETENESS_RULE,
            FLOW_LEVEL_GUIDANCE[level],
            "« sentiment » est un entier de -2 (très négatif) à 2 (très positif).",
            FLOW_GRAPH_RULES[level],
            _language_rule(language),
            "Schéma JSON attendu :\n" + FLOW_SCHEMA,
        ]
    else:
        parts = [
            BASE_RULES,
            MODE_GUIDANCE[mode],
            COMPLETENESS_RULE,
            LEVEL_GUIDANCE[level],
            "« theme » dans actions est le numéro (1, 2, ...) du thème concerné. Autant de pistes d'action que le corpus en justifie.",
            "Indique les sources de chaque point." if cite else "Laisse « sources » vide ([]) pour chaque point.",
            _language_rule(language),
            "Schéma JSON attendu :\n" + THEMES_SCHEMA,
        ]
    return "\n\n".join(parts)


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
        for attempt, wait in enumerate((0, *RETRY_WAITS)):
            if wait:
                await asyncio.sleep(wait)  # surcharge passagère : on patiente avant de réessayer
            try:
                out = await _complete(spec, system_prompt, user, want_json)
                analysis.active_model_id = spec.id
                return out
            except litellm.RateLimitError as exc:
                last = exc
                if re.search(r"per ?day|PerDay|daily", str(exc), re.I):
                    break  # quota journalier épuisé : inutile d'insister, modèle suivant
                # limite par minute : elle se lève d'elle-même, on réessaie après une pause
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
    from app.services import batch_pipeline  # import local : le module dépend de celui-ci

    chain = fallback_chain(spec)
    try:
        # 1. Lecture
        _enter(analysis, 0)
        segments = [b.to_prompt_segment() for d in analysis.documents for b in d.blocks]
        corpus = "\n".join(segments)
        checker = QuoteChecker("\n".join(d.plain_text() for d in analysis.documents))
        await asyncio.sleep(0.6)  # laisse l'interface afficher l'étape

        if batch_pipeline.needs_batches(chain[0], corpus):
            # Corpus plus grand que la fenêtre du modèle : extraction par lots, puis rédaction thème par thème.
            analysis.batched = True
            run = batch_pipeline.run_flow if analysis.mode == "flow" else batch_pipeline.run_themes
            data = await run(analysis, chain, checker)
        else:
            data = await _run_single_pass(analysis, chain, corpus)

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


def _flag_sources(result: dict[str, Any], documents: list[StoredDocument]) -> None:
    """Marque chaque source dont le repère n'existe pas dans le document (« found » à False)."""
    from app.services.source_lookup import location_exists

    by_name = {d.name: d for d in documents}
    for t in result.get("themes") or []:
        for p in t["points"]:
            for src in p["sources"]:
                doc = by_name.get(src["document"])
                src["found"] = bool(doc and src["location"] and location_exists(doc, src["location"]))


async def _run_single_pass(analysis: Analysis, chain: list[ModelSpec], corpus: str) -> dict[str, Any]:
    """Le corpus tient dans la fenêtre du modèle : repérage des thèmes puis rédaction, sur le texte intégral."""
    _enter(analysis, 1)
    analysis.progress = 30

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
    user = f"{plan_label} lors de la première passe (traite-les tous ; ajoutes-en si le corpus l'exige) :\n" + \
        "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names)) + "\n\nCorpus :\n\n" + corpus
    full_raw = await _with_creep(
        analysis, 90,
        _call(analysis, chain, _full_prompt(analysis.mode, analysis.level, analysis.language, analysis.cite), user),
    )
    return _parse_json(full_raw)


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


class QuoteChecker:
    """Retrouve un verbatim dans le texte réel des documents (casse, ponctuation et guillemets ignorés).

    « exact » : présent mot pour mot ; « close » : passage retrouvé mais légèrement reformulé
    (≥ 70 % des mots dans le même ordre) ; « absent » : aucun passage comparable.
    """

    CLOSE = 0.7

    def __init__(self, corpus: str) -> None:
        self.text = self._norm(corpus)
        self.words = self.text.split()
        self.positions: dict[str, list[int]] = {}
        for i, w in enumerate(self.words):
            self.positions.setdefault(w, []).append(i)

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())

    def check(self, quote: str) -> Literal["exact", "close", "absent", ""]:
        q = self._norm(quote)
        if not q:
            return ""
        if f" {q} " in f" {self.text} ":
            return "exact"
        qw = q.split()
        # Les mots les plus rares de la citation servent d'ancres pour localiser le passage d'origine.
        anchors = sorted({w for w in qw if w in self.positions}, key=lambda w: len(self.positions[w]))[:3]
        best = 0.0
        for w in anchors:
            for pos in self.positions[w][:50]:
                window = self.words[max(0, pos - len(qw)):pos + len(qw)]
                matched = sum(bl.size for bl in difflib.SequenceMatcher(None, qw, window, autojunk=False).get_matching_blocks())
                best = max(best, matched / len(qw))
        return "close" if best >= self.CLOSE else "absent"


def normalize_themes(data: dict[str, Any], doc_names: list[str], checker: QuoteChecker) -> dict[str, Any]:
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
            "quote_check": checker.check(_s(raw.get("quote"))),
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
            "quotes_exact": sum(1 for t in themes if t["quote_check"] == "exact"),
            "actions": len(actions),
        },
    }


def normalize_journey(data: dict[str, Any], doc_names: list[str], checker: QuoteChecker) -> dict[str, Any]:
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

    flow = normalize_flow(data.get("flow"))

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
            "quote_check": checker.check(_s(p.get("quote"))),
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
        # Éléments extraits (analyse par lots) que le parcours n'a pas repris : affichés tels quels.
        "extra": [
            {"text": _s(e.get("text")), "document": _match_doc(_s(e.get("document")), doc_names) or "",
             "location": _s(e.get("location"))}
            for e in data.get("extra") or [] if isinstance(e, dict) and _s(e.get("text"))
        ],
        "sources": [{"document": d, "citations": 0} for d in doc_names],
    }


# ---------------------------------------------------------------------------
# Graphe de flux (structure libre) et rendu Mermaid
# ---------------------------------------------------------------------------

NODE_TYPES = {"entry", "step", "decision", "exit", "goal"}
EDGE_KINDS = {"main", "alt", "exit", "loop"}
MAX_NODES, MAX_EDGES = 150, 300  # garde-fou d'affichage uniquement


def _linear_to_graph(items: list[Any]) -> dict[str, Any]:
    """Ancien format (liste d'étapes avec points de sortie) converti en graphe."""
    nodes, edges = [], []
    steps = [f for f in items if isinstance(f, dict) and _s(f.get("label"))]
    for i, f in enumerate(steps):
        nid = f"s{i + 1}"
        kind = _s(f.get("kind")).lower()
        nodes.append({"id": nid, "label": _s(f.get("label")),
                      "type": kind if kind in {"entry", "goal"} else "step",
                      "friction": bool(f.get("breaking"))})
        if i:
            edges.append({"from": f"s{i}", "to": nid, "label": "", "kind": "main"})
        if _s(f.get("exit")):
            nodes.append({"id": f"x{i + 1}", "label": _s(f.get("exit")), "type": "exit", "friction": False})
            edges.append({"from": nid, "to": f"x{i + 1}", "label": "", "kind": "exit"})
    return {"nodes": nodes, "edges": edges}


def normalize_flow(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list):
        raw = _linear_to_graph(raw)
    if not isinstance(raw, dict):
        return {"nodes": [], "edges": [], "mermaid": ""}

    nodes: list[dict[str, Any]] = []
    ids: dict[str, str] = {}  # id fourni par le modèle -> id sûr pour Mermaid
    for n in raw.get("nodes") or []:
        if not isinstance(n, dict) or not _s(n.get("label")) or len(nodes) >= MAX_NODES:
            continue
        original = _s(str(n.get("id") or "")) or f"auto{len(nodes) + 1}"
        if original in ids:
            continue
        safe = f"n{len(nodes) + 1}"
        ids[original] = safe
        ntype = _s(n.get("type")).lower()
        nodes.append({
            "id": safe,
            "label": _s(n.get("label")),
            "type": ntype if ntype in NODE_TYPES else "step",
            "friction": bool(n.get("friction")),
        })

    by_id = {n["id"]: n for n in nodes}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in raw.get("edges") or []:
        if not isinstance(e, dict) or len(edges) >= MAX_EDGES:
            continue
        a, b = ids.get(_s(str(e.get("from") or ""))), ids.get(_s(str(e.get("to") or "")))
        if not a or not b or a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        kind = _s(e.get("kind")).lower()
        if kind not in EDGE_KINDS:
            kind = "exit" if by_id[b]["type"] == "exit" else "main"
        edges.append({"from": a, "to": b, "label": _s(e.get("label")), "kind": kind})

    # Graphe sans liens exploitables : on enchaîne les nœuds dans l'ordre.
    if not edges and len(nodes) > 1:
        edges = [{"from": x["id"], "to": y["id"], "label": "", "kind": "main"} for x, y in zip(nodes, nodes[1:])]

    graph = {"nodes": nodes, "edges": edges}
    graph["mermaid"] = to_mermaid(graph) if nodes else ""
    return graph


def _mermaid_text(text: str, width: int = 24) -> str:
    """Échappe un libellé pour Mermaid et le coupe en lignes courtes."""
    words, lines, current = text.split(), [], ""
    for w in words:
        if current and len(current) + 1 + len(w) > width:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    safe = [
        ln.replace("#", "#35;").replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;").replace("|", "#124;")
        for ln in lines[:4]
    ]
    return "<br/>".join(safe)


_SHAPES = {
    "entry": ('(["', '"])'),
    "goal": ('(["', '"])'),
    "step": ('["', '"]'),
    "decision": ('{"', '"}'),
    "exit": ('{{"', '"}}'),
}

_CLASS_DEFS = [
    "classDef entry fill:#FFFFFF,stroke:#15171C,stroke-width:1.5px,color:#15171C",
    "classDef step fill:#FFFFFF,stroke:#D5D9E2,stroke-width:1.5px,color:#15171C",
    "classDef decision fill:#F4F5F8,stroke:#5A6070,stroke-width:1.5px,color:#15171C",
    "classDef friction fill:#FFF8F3,stroke:#C2560F,stroke-width:2px,color:#7E3A0A",
    "classDef exit fill:#FFFFFF,stroke:#C2560F,stroke-width:1.5px,stroke-dasharray:4 3,color:#7E3A0A",
    "classDef goal fill:#EEF0FD,stroke:#3346D3,stroke-width:2px,color:#2433A8",
]

_LINK_STYLES = {
    "main": "stroke:#5A6070,stroke-width:2px",
    "alt": "stroke:#9AA1B0,stroke-width:1.5px",
    "exit": "stroke:#C2560F,stroke-width:1.5px,stroke-dasharray:4 3",
    "loop": "stroke:#3346D3,stroke-width:1.5px,stroke-dasharray:2 3",
}


def to_mermaid(graph: dict[str, Any]) -> str:
    direction = "LR" if len(graph["nodes"]) <= 10 else "TB"
    lines = [f"flowchart {direction}"]
    for n in graph["nodes"]:
        start, end = _SHAPES[n["type"]]
        cls = "friction" if n["friction"] and n["type"] in {"step", "decision", "entry"} else n["type"]
        lines.append(f"  {n['id']}{start}{_mermaid_text(n['label'])}{end}:::{cls}")
    for e in graph["edges"]:
        arrow = "-->" if e["kind"] in {"main", "alt"} else "-.->"
        label = f'|"{_mermaid_text(e["label"], 20)}"|' if e["label"] else ""
        lines.append(f"  {e['from']} {arrow}{label} {e['to']}")
    lines += [f"  {c}" for c in _CLASS_DEFS]
    for i, e in enumerate(graph["edges"]):
        lines.append(f"  linkStyle {i} {_LINK_STYLES[e['kind']]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

QUOTE_NOTES = {
    "close": " _(citation légèrement reformulée par rapport au document)_",
    "absent": " _(citation introuvable dans les documents : à vérifier)_",
}


def to_markdown(analysis: Analysis) -> str:
    r = analysis.result or {}
    spec = next((m for m in all_models() if m.id == (analysis.active_model_id or analysis.model_id)), None)
    lines = [
        f"# {r.get('title') or MODE_LABELS[analysis.mode]}",
        "",
        f"_{MODE_LABELS[analysis.mode]} · {LEVEL_LABELS[analysis.level]} · "
        f"{len(analysis.documents)} document(s) · {spec.name if spec else analysis.model_id}_",
        "",
        *([f"_Corpus volumineux analysé en {cov['batches']} lots ({cov['items']} éléments extraits)._", ""]
          if (cov := r.get("coverage")) else []),
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
                lines += [f"> « {t['quote']} » — {t['quote_by']}{QUOTE_NOTES.get(t['quote_check'], '')}", ""]
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
        flow = r.get("flow") or {}
        if flow.get("nodes"):
            labels = {n["id"]: n["label"] for n in flow["nodes"]}
            kinds = {"main": "", "alt": " (alternatif)", "exit": " (abandon)", "loop": " (retour)"}
            lines += ["## Flux et points de sortie", "", "```mermaid", flow["mermaid"], "```", ""]
            for e in flow["edges"]:
                cond = f" — {e['label']}" if e["label"] else ""
                lines.append(f"- {labels[e['from']]} → {labels[e['to']]}{kinds[e['kind']]}{cond}")
            lines.append("")
        if r.get("extra"):
            lines += ["## Autres éléments des documents", ""]
            lines += [f"- {e['text']}" + (f" _({e['document']} {e['location']})_" if e["document"] else "") for e in r["extra"]]
            lines.append("")
        if r.get("priorities"):
            lines += ["## Frictions prioritaires", ""]
            for p in r["priorities"]:
                lines += [
                    f"### [{p['severity']}] {p['title']}",
                    "",
                    p["body"],
                    "",
                    f"> « {p['quote']} »{QUOTE_NOTES.get(p['quote_check'], '')}" if p["quote"] else "",
                    "",
                    f"Étape : {p['phase']}" + (f" · Cité par {p['frequency']}" if p["frequency"] else ""),
                    "",
                ]
    lines.append("_Synthèse générée par un modèle de langage : vérifiez les points importants dans les sources citées._")
    return "\n".join(lines)
