"""Moteur de synthèse analytique unifié (Gemini / Mistral) via litellm.

- Extraction PDF propre avec PyMuPDF (balises de page conservées).
- Stuffing : le texte intégral est injecté dans le contexte. Un découpage
  "map-reduce" n'est utilisé qu'en dernier recours si le document dépasse
  la fenêtre de contexte du modèle.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF
import litellm

from app.core.config import settings
from app.services.parser_service import MultiFormatDocumentParser

Provider = Literal["gemini", "mistral"]

SYSTEM_PROMPT = """Tu es un analyste expert. Ton rôle est de rédiger une synthèse opérationnelle et structurée du document fourni.
Règles impératives :
- Zéro phrase d'introduction creuse ou de transition inutile.
- Ne déduis rien hors du texte fourni, conserve rigoureusement les chiffres clés, dates, acteurs et arbitrages.
Format attendu en Markdown :
## Synthèse exécutive (3-4 phrases percutantes)
## Enjeux et constats majeurs (points à puces avec données chiffrées)
## Décisions et recommandations clés
## Points de vigilance et limites identifiés"""

MODE_INSTRUCTIONS: dict[str, str] = {
    "global_summary": "Mode : synthèse documentaire globale. Respecte exactement les 4 sections ci-dessus.",
    "transcript_summary": (
        "Mode : compte-rendu de réunion / transcription. Remplace les sections par : "
        "## Synthèse exécutive, ## Décisions prises, ## Actions à mener (tableau : Action | Responsable | Échéance), "
        "## Points ouverts et tensions. Ne cite que des participants et échéances présents dans le texte."
    ),
    "user_journey": (
        "Mode : parcours utilisateur. Remplace les sections par : ## Synthèse exécutive, ## Personas, "
        "## Étapes du parcours (tableau : Étape | Objectif | Irritants | Opportunités), ## Points de vigilance et limites identifiés."
    ),
    "raw_notes": (
        "Mode : notes en vrac. Dédoublonne et regroupe les idées par thèmes. Remplace les sections par : "
        "## Synthèse exécutive, ## Thèmes regroupés (un sous-titre ### par thème), ## Prochaines étapes suggérées, "
        "## Points de vigilance et limites identifiés."
    ),
}

LEVEL_INSTRUCTIONS: dict[str, str] = {
    "flash": "Niveau : flash. Maximum ~150 mots au total, 3 à 5 puces, un seul tableau si indispensable.",
    "standard": "Niveau : standard. Environ 400 à 600 mots, puces concises avec chiffres clés.",
    "detaille": (
        "Niveau : détaillé. Couvre exhaustivement le contenu (800 à 1500 mots), "
        "sous-titres ### par thème, tous les chiffres, dates, acteurs et arbitrages."
    ),
}

FORMAT_INSTRUCTIONS = (
    "Mise en forme : titres courts et explicites (2 à 6 mots), puces plutôt que paragraphes longs, "
    "tableaux Markdown dès que tu compares des éléments ou présentes des données chiffrées. "
    "Si plusieurs documents sont fournis, indique le document source entre parenthèses pour chaque fait important."
)


def build_system_prompt(mode: str, level: str) -> str:
    return "\n\n".join(
        [
            SYSTEM_PROMPT,
            MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["global_summary"]),
            LEVEL_INSTRUCTIONS.get(level, LEVEL_INSTRUCTIONS["standard"]),
            FORMAT_INSTRUCTIONS,
        ]
    )


# NB : gemini-1.5-* est retiré de l'API (404). Modèle surchargeable via .env.
MODELS: dict[str, str] = {
    "gemini": os.getenv("SUMMARY_GEMINI_MODEL", "gemini/gemini-3.8-flash"),
    "mistral": os.getenv("SUMMARY_MISTRAL_MODEL", "mistral/mistral-large-latest"),
}

# Modèles de repli essayés dans l'ordre si le principal échoue (quota 429, surcharge 503...).
FALLBACKS: dict[str, list[str]] = {
    "gemini": [m for m in os.getenv("SUMMARY_GEMINI_FALLBACKS", "gemini/gemini-3.5-flash").split(",") if m],
    "mistral": [m for m in os.getenv("SUMMARY_MISTRAL_FALLBACKS", "mistral/mistral-medium-latest").split(",") if m],
}

# Fenêtre de contexte (tokens) et marge de sécurité pour la réponse/prompt.
CONTEXT_TOKENS: dict[str, int] = {"gemini": 1_000_000, "mistral": 128_000}
CHARS_PER_TOKEN = 3.2  # estimation prudente pour le français
RESERVED_TOKENS = 12_000
TEMPERATURE = 0.2


class SummarizerError(Exception):
    """Erreur métier (clé manquante, document vide, provider inconnu...)."""


def _api_key(provider: Provider) -> str:
    key = (settings.GEMINI_API_KEY if provider == "gemini" else settings.MISTRAL_API_KEY).strip()
    if not settings._is_key_set(key):
        var = "GEMINI_API_KEY" if provider == "gemini" else "MISTRAL_API_KEY"
        raise SummarizerError(f"{var} n'est pas configurée dans backend/.env")
    return key


def extract_text(file_path: Path, file_name: str) -> str:
    """Extrait le texte intégral. PDF : texte structuré par page via PyMuPDF."""
    if Path(file_name).suffix.lower() == ".pdf":
        parts: list[str] = []
        with fitz.open(file_path) as doc:
            for index, page in enumerate(doc, start=1):
                # "blocks" conserve l'ordre de lecture et les paragraphes
                blocks = page.get_text("blocks", sort=True)
                text = "\n\n".join(b[4].strip() for b in blocks if b[6] == 0 and b[4].strip())
                if text:
                    parts.append(f"[Page {index}]\n{text}")
        return "\n\n".join(parts)

    blocks = MultiFormatDocumentParser().parse_file(file_path, file_name)
    return "\n\n".join(f"[{b.location}]\n{b.content.strip()}" for b in blocks if b.content.strip())


def _split_for_context(text: str, max_chars: int) -> list[str]:
    """Découpe sur des frontières de paragraphes (dernier recours uniquement)."""
    segments, current, size = [], [], 0
    for para in text.split("\n\n"):
        if size + len(para) > max_chars and current:
            segments.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        segments.append("\n\n".join(current))
    return segments


async def _complete(provider: Provider, system_prompt: str, user_content: str) -> tuple[str, str]:
    """Retourne (texte, modèle effectivement utilisé), avec repli sur les modèles de secours."""
    api_key = _api_key(provider)
    last_error: Exception | None = None
    for model in [MODELS[provider], *FALLBACKS[provider]]:
        try:
            response = await litellm.acompletion(
                model=model,
                api_key=api_key,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                num_retries=2,
                timeout=300,
            )
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip(), model.split("/", 1)[1]
            last_error = SummarizerError(f"Réponse vide du modèle {model}.")
        except Exception as exc:  # quota, surcharge, auth... -> modèle suivant
            last_error = exc
    raise SummarizerError(f"Appel {provider} en échec : {last_error}") from last_error


async def summarize_text(
    text: str, provider: Provider, mode: str = "global_summary", level: str = "standard"
) -> tuple[str, str]:
    if provider not in MODELS:
        raise SummarizerError(f"Provider inconnu : {provider}")
    if not text.strip():
        raise SummarizerError("Aucun texte exploitable dans le document (PDF scanné ?).")

    system_prompt = build_system_prompt(mode, level)
    max_chars = int((CONTEXT_TOKENS[provider] - RESERVED_TOKENS) * CHARS_PER_TOKEN)
    prompt = "Document à synthétiser :\n\n{}"

    if len(text) <= max_chars:  # cas nominal : stuffing intégral
        return await _complete(provider, system_prompt, prompt.format(text))

    # Dépassement : synthèse par segments puis fusion, sans perdre les chiffres.
    segments = _split_for_context(text, max_chars)
    results = await asyncio.gather(
        *(_complete(provider, system_prompt, prompt.format(seg)) for seg in segments)
    )
    merged = "\n\n".join(f"### Partie {i + 1}/{len(results)}\n{p}" for i, (p, _) in enumerate(results))
    return await _complete(
        provider,
        system_prompt,
        "Les synthèses partielles suivantes proviennent des segments successifs d'un même document. "
        "Fusionne-les en une seule synthèse, sans perdre aucun chiffre clé, date, acteur ni arbitrage :\n\n"
        + merged,
    )


async def _extract_upload(content: bytes, file_name: str) -> str:
    suffix = Path(file_name).suffix or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        return await asyncio.to_thread(extract_text, tmp_path, file_name)
    finally:
        tmp_path.unlink(missing_ok=True)


async def summarize_files(
    files: list[tuple[bytes, str]],
    provider: Provider,
    mode: str = "global_summary",
    level: str = "standard",
) -> tuple[str, str]:
    """Concatène les documents (balisés par nom) puis synthétise l'ensemble."""
    parts = []
    for content, name in files:
        text = await _extract_upload(content, name)
        if text.strip():
            parts.append(f"=== DOCUMENT : {name} ===\n{text}")
    return await summarize_text("\n\n".join(parts), provider, mode, level)


def provider_config() -> list[dict]:
    """Modèles configurés et disponibilité des clés (pour l'affichage UI)."""
    return [
        {
            "id": p,
            "model": MODELS[p].split("/", 1)[1],
            "fallbacks": [m.split("/", 1)[1] for m in FALLBACKS[p]],
            "configured": settings._is_key_set(
                settings.GEMINI_API_KEY if p == "gemini" else settings.MISTRAL_API_KEY
            ),
        }
        for p in MODELS
    ]
