from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
from typing import Callable, Optional

import httpx
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)

from app.core.config import ProviderCredentials, settings
from app.schemas.models import (
    ActionItem,
    ConsolidatedIdea,
    DecisionItem,
    GlobalSummaryResult,
    MetricItem,
    NextStepItem,
    NoteCluster,
    ParticipantItem,
    PersonaItem,
    RawNotesResult,
    RecommendationItem,
    SourceReference,
    StructuredParagraph,
    SynthesisMode,
    SynthesisPayload,
    TensionItem,
    ThemeItem,
    TranscriptClusterItem,
    TranscriptSummaryResult,
    UserJourneyResult,
    UserJourneyStep,
)
from app.services.parser_service import AnchoredTextBlock
from app.services.prompts import MAP_EXTRACTION_SYSTEM_PROMPT, SYSTEM_PROMPTS

DEPRECATED_GEMINI_PREFIXES = ("gemini-1.5", "gemini-2.0", "gemini-2.5")

STOPWORDS_FR = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "en", "au", "aux",
    "dans", "sur", "par", "pour", "avec", "sans", "sous", "vers", "chez", "entre",
    "ce", "cet", "cette", "ces", "son", "sa", "ses", "leur", "leurs", "notre", "nos",
    "votre", "vos", "qui", "que", "quoi", "dont", "où", "est", "sont", "été", "être",
    "avoir", "fait", "faire", "plus", "moins", "très", "bien", "tout", "tous", "toute",
    "toutes", "comme", "mais", "donc", "car", "ni", "ne", "pas", "plus", "aussi",
    "ainsi", "alors", "après", "avant", "depuis", "pendant", "contre", "selon",
    "nous", "vous", "ils", "elles", "on", "se", "y", "a", "ont", "avait", "sera",
}


class MistralEnterpriseService:
    """Routeur LLM Multi-Fournisseurs (Google Gemini Interactions API, Mistral AI, Custom OpenAI/vLLM) avec support CA Bundle par fournisseur."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_LLM_REQUESTS)
        self._payload_adapter = TypeAdapter(SynthesisPayload)

    @staticmethod
    def _build_ssl_context(ca_bundle: Optional[str]) -> ssl.SSLContext | bool:
        if ca_bundle and ca_bundle.strip():
            return ssl.create_default_context(cafile=ca_bundle.strip())
        return True

    @staticmethod
    def _normalize_model_id(model_name: str, provider: str) -> str:
        clean = model_name.split(":", 1)[-1].strip()
        if provider == "gemini" and clean.startswith(DEPRECATED_GEMINI_PREFIXES):
            return "gemini-3.8-flash"
        return clean

    async def _chat_completion(
        self,
        model_name: str,
        system_prompt: str,
        user_content: str,
        json_mode: bool = True,
    ) -> str:
        creds: ProviderCredentials = settings.resolve_provider(model_name)
        target_model = self._normalize_model_id(model_name, creds.provider)

        if creds.provider == "gemini":
            return await self._call_gemini_api(
                creds=creds,
                model_name=target_model,
                system_prompt=system_prompt,
                user_content=user_content,
                json_mode=json_mode,
            )

        return await self._call_openai_compatible_api(
            creds=creds,
            model_name=target_model,
            system_prompt=system_prompt,
            user_content=user_content,
            json_mode=json_mode,
        )

    async def _call_gemini_api(
        self,
        creds: ProviderCredentials,
        model_name: str,
        system_prompt: str,
        user_content: str,
        json_mode: bool = True,
    ) -> str:
        ssl_verify = self._build_ssl_context(creds.ca_bundle)
        target_model = model_name.removeprefix("models/")

        api_base = creds.api_base.rstrip("/")
        if not ("/v1" in api_base or "/v1beta" in api_base):
            api_base = f"{api_base}/v1beta"

        generate_url = f"{api_base}/models/{target_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": creds.api_key,
        }

        payload: dict = {
            "contents": [
                {"parts": [{"text": user_content}]}
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }
        if system_prompt and system_prompt.strip():
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        max_retries = 3
        backoff_delay = 2.0

        async with self._semaphore:
            async with httpx.AsyncClient(
                verify=ssl_verify,
                timeout=httpx.Timeout(180.0, connect=15.0),
            ) as client:
                for attempt in range(max_retries):
                    resp = await client.post(
                        generate_url,
                        headers=headers,
                        json=payload,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates") or []
                        if candidates:
                            content = candidates[0].get("content") or {}
                            parts = content.get("parts") or []
                            texts = [p.get("text", "") for p in parts if "text" in p]
                            if any(texts):
                                return "".join(texts)
                        raise ValueError(f"Réponse Gemini sans texte exploitable : {resp.text[:300]}")

                    logger.warning(
                        "Appel Gemini (%s) - statut HTTP %s (tentative %d/%d) : %s",
                        target_model,
                        resp.status_code,
                        attempt + 1,
                        max_retries,
                        resp.text[:250],
                    )

                    if resp.status_code in (429, 503) and attempt < max_retries - 1:
                        await asyncio.sleep(backoff_delay)
                        backoff_delay *= 2.0
                        continue

                    resp.raise_for_status()

                raise RuntimeError("Échec de l'appel Gemini après plusieurs tentatives.")

    async def _call_openai_compatible_api(
        self,
        creds: ProviderCredentials,
        model_name: str,
        system_prompt: str,
        user_content: str,
        json_mode: bool = True,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {creds.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": model_name,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with self._semaphore:
            async with httpx.AsyncClient(
                verify=self._build_ssl_context(creds.ca_bundle),
                timeout=httpx.Timeout(180.0, connect=15.0),
            ) as client:
                response = await client.post(
                    f"{creds.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

    def _group_blocks_into_chunks(
        self, blocks: list[AnchoredTextBlock], max_chars: int = 42000
    ) -> list[str]:
        chunks: list[str] = []
        current_segments: list[str] = []
        current_len = 0

        for block in blocks:
            segment = block.to_prompt_segment()
            if current_len + len(segment) > max_chars and current_segments:
                chunks.append("\n".join(current_segments))
                overlap = current_segments[-1] if current_segments else ""
                current_segments = [overlap, segment] if overlap else [segment]
                current_len = sum(len(s) for s in current_segments)
            else:
                current_segments.append(segment)
                current_len += len(segment)

        if current_segments:
            chunks.append("\n".join(current_segments))
        return chunks

    async def synthesize_documents(
        self,
        blocks: list[AnchoredTextBlock],
        mode: SynthesisMode,
        model_name: str,
        on_progress: Callable[[int, str], None],
    ) -> SynthesisPayload:
        creds = settings.resolve_provider(model_name)

        if not creds.has_valid_key and settings.ENABLE_FALLBACK_SIMULATION:
            on_progress(
                60,
                f"Analyse sémantique locale approfondie ({model_name} [{creds.provider.upper()}])...",
            )
            await asyncio.sleep(0.8)
            on_progress(88, "Structuration des paragraphes thématiques et ancrage des citations...")
            await asyncio.sleep(0.5)
            return self._build_extractive_fallback(blocks, mode, model_name)

        max_chars_per_chunk = 450000 if creds.provider == "gemini" else 42000
        chunks = self._group_blocks_into_chunks(blocks, max_chars=max_chars_per_chunk)
        system_prompt = SYSTEM_PROMPTS[mode]

        try:
            if len(chunks) == 1:
                on_progress(
                    65,
                    f"Analyse approfondie via {model_name} ({creds.provider.upper()} - contexte unifié)...",
                )
                raw_json = await self._chat_completion(
                    model_name=model_name,
                    system_prompt=system_prompt,
                    user_content=f"Voici le corpus documentaire balisé à analyser en profondeur :\n\n{chunks[0]}",
                    json_mode=True,
                )
                return self._parse_and_validate(raw_json, mode)

            total_chunks = len(chunks)
            completed_maps = 0

            async def map_chunk(idx: int, chunk_text: str) -> str:
                nonlocal completed_maps
                extracted = await self._chat_completion(
                    model_name=model_name,
                    system_prompt=MAP_EXTRACTION_SYSTEM_PROMPT,
                    user_content=(
                        f"Segment {idx + 1}/{total_chunks} pour une analyse approfondie de type '{mode.value}'.\n"
                        f"Extrais tous les développements, arguments, chiffres et conserve scrupuleusement chaque balise [SOURCE: ... | LOC: ...] :\n\n{chunk_text}"
                    ),
                    json_mode=False,
                )
                completed_maps += 1
                pct = 45 + int((completed_maps / total_chunks) * 35)
                on_progress(
                    pct,
                    f"Analyse Map-Reduce ({creds.provider.upper()}) : segment {completed_maps}/{total_chunks} traité ({model_name})...",
                )
                return f"=== SYNTHÈSE DÉTAILLÉE DU SEGMENT {idx + 1}/{total_chunks} ===\n{extracted}"

            on_progress(45, f"Démarrage de l'analyse distribuée sur {total_chunks} segments...")
            mapped_summaries = await asyncio.gather(
                *(map_chunk(i, chunk) for i, chunk in enumerate(chunks))
            )

            on_progress(85, "Consolidation finale multi-paragraphes et vérification du sourçage...")
            combined_notes = "\n\n".join(mapped_summaries)
            raw_json = await self._chat_completion(
                model_name=model_name,
                system_prompt=system_prompt,
                user_content=(
                    "Voici les extractions détaillées et sourcées issues de l'ensemble des segments du corpus.\n"
                    "Produis la synthèse finale approfondie, rédigée en paragraphes complets avec des titres concis, au format JSON strict :\n\n"
                    f"{combined_notes}"
                ),
                json_mode=True,
            )
            return self._parse_and_validate(raw_json, mode)

        except Exception as exc:
            logger.exception("Erreur lors de la synthèse LLM (%s): %s", model_name, exc)
            if settings.ENABLE_FALLBACK_SIMULATION:
                on_progress(
                    70,
                    f"Fournisseur {creds.provider.upper()} temporairement indisponible (quota ou réseau). Basculement automatique sur l'analyse sémantique locale...",
                )
                await asyncio.sleep(0.5)
                on_progress(90, "Génération de la synthèse locale avec traçabilité granulaire...")
                await asyncio.sleep(0.4)
                return self._build_extractive_fallback(blocks, mode, model_name)
            raise

    @staticmethod
    def _clean_sources(sources: list) -> list[dict]:
        clean = []
        for s in sources:
            if isinstance(s, dict):
                clean.append({
                    "file_name": str(s.get("file_name") or "Document").strip(),
                    "location": str(s.get("location") or "Page").strip(),
                    "excerpt": str(s.get("excerpt") or "").strip()[:300],
                })
            elif isinstance(s, str) and s.strip():
                clean.append({
                    "file_name": "Document",
                    "location": "Passage",
                    "excerpt": s.strip()[:300],
                })
        return clean

    def _sanitize_payload_dict(self, data: dict, mode: SynthesisMode) -> dict:
        data["mode"] = mode.value

        if not data.get("title") or not str(data.get("title")).strip():
            data["title"] = "Synthèse Analytique du Document"

        if mode == SynthesisMode.GLOBAL:
            if not data.get("executive_summary") or not str(data.get("executive_summary")).strip():
                data["executive_summary"] = "Synthèse analytique et stratégique consolidée du corpus documentaire."

            paragraphs = data.get("executive_paragraphs") or []
            sanitized_p = []
            for p in paragraphs:
                if isinstance(p, dict):
                    h = (p.get("heading") or "Point Clé").strip()
                    b = (p.get("body") or "").strip()
                    if b:
                        sanitized_p.append({
                            "heading": h,
                            "body": b,
                            "sources": self._clean_sources(p.get("sources") or []),
                        })
            data["executive_paragraphs"] = sanitized_p

            themes = data.get("key_themes") or []
            sanitized_t = []
            for t in themes:
                if isinstance(t, dict):
                    th = (t.get("theme") or "Axe Majeur").strip()
                    sm = (t.get("summary") or "").strip()
                    args = t.get("arguments") or []
                    clean_args = [str(a).strip() for a in args if str(a).strip()]
                    if not clean_args and sm:
                        clean_args = [f"**Constat clé :** {sm}"]
                    sanitized_t.append({
                        "theme": th,
                        "summary": sm or "Analyse approfondie de cet axe thématique.",
                        "arguments": clean_args,
                        "sources": self._clean_sources(t.get("sources") or []),
                    })
            data["key_themes"] = sanitized_t

            metrics = data.get("key_metrics") or []
            sanitized_m = []
            for m in metrics:
                if isinstance(m, dict):
                    raw_trend = str(m.get("trend", "")).lower().strip()
                    if raw_trend in ("up", "croissance", "hausse", "increase", "positif", "+"):
                        trend = "up"
                    elif raw_trend in ("down", "baisse", "decrease", "négatif", "-"):
                        trend = "down"
                    else:
                        trend = "neutral"
                    sanitized_m.append({
                        "label": str(m.get("label") or "Indicateur").strip(),
                        "value": str(m.get("value") or "-").strip(),
                        "context": str(m.get("context") or "").strip(),
                        "trend": trend,
                        "sources": self._clean_sources(m.get("sources") or []),
                    })
            data["key_metrics"] = sanitized_m

            recs = data.get("recommendations") or []
            sanitized_r = []
            for r in recs:
                if isinstance(r, dict):
                    raw_p = str(r.get("priority", "")).lower().strip()
                    if "haut" in raw_p or "high" in raw_p or "urg" in raw_p:
                        priority = "Haute"
                    elif "bas" in raw_p or "low" in raw_p or "faibl" in raw_p:
                        priority = "Basse"
                    else:
                        priority = "Moyenne"
                    sanitized_r.append({
                        "title": str(r.get("title") or "Action Recommandée").strip(),
                        "description": str(r.get("description") or "").strip(),
                        "priority": priority,
                        "sources": self._clean_sources(r.get("sources") or []),
                    })
            data["recommendations"] = sanitized_r

        elif mode == SynthesisMode.TRANSCRIPT:
            if not data.get("context"):
                data["context"] = "Synthèse et compte-rendu des échanges de la réunion."
            data["participants"] = [
                {"name": str(p.get("name") or "Participant"), "role": str(p.get("role") or "Intervenant")}
                for p in (data.get("participants") or []) if isinstance(p, dict)
            ]
            data["agenda"] = [str(a) for a in (data.get("agenda") or []) if str(a).strip()]
            clusters = data.get("thematic_clusters") or []
            data["thematic_clusters"] = [
                {
                    "tag": str(c.get("tag") or "Point de Discussion"),
                    "consolidated_notes": str(c.get("consolidated_notes") or ""),
                    "key_takeaways": [str(k) for k in (c.get("key_takeaways") or [])],
                    "sources": self._clean_sources(c.get("sources") or []),
                }
                for c in clusters if isinstance(c, dict)
            ]
            data["decisions_made"] = [
                {
                    "decision": str(d.get("decision") or "Décision adoptée"),
                    "rationale": str(d.get("rationale") or ""),
                    "sources": self._clean_sources(d.get("sources") or []),
                }
                for d in (data.get("decisions_made") or []) if isinstance(d, dict)
            ]
            action_items = data.get("action_items") or []
            sanitized_ai = []
            for a in action_items:
                if isinstance(a, dict):
                    raw_p = str(a.get("priority", "")).lower()
                    if "haut" in raw_p or "high" in raw_p:
                        priority = "Haute"
                    elif "bas" in raw_p or "low" in raw_p:
                        priority = "Basse"
                    else:
                        priority = "Moyenne"
                    sanitized_ai.append({
                        "task": str(a.get("task") or "Action"),
                        "assignee": str(a.get("assignee") or "Non assigné"),
                        "due_date": str(a.get("due_date") or "À définir"),
                        "priority": priority,
                        "sources": self._clean_sources(a.get("sources") or []),
                    })
            data["action_items"] = sanitized_ai
            data["open_questions_and_tensions"] = [
                {
                    "topic": str(t.get("topic") or "Point ouvert"),
                    "description": str(t.get("description") or ""),
                    "stakeholders": [str(s) for s in (t.get("stakeholders") or [])],
                    "sources": self._clean_sources(t.get("sources") or []),
                }
                for t in (data.get("open_questions_and_tensions") or []) if isinstance(t, dict)
            ]

        elif mode == SynthesisMode.USER_JOURNEY:
            if not data.get("overview"):
                data["overview"] = "Synthèse de la modélisation du parcours utilisateur."
            data["personas"] = [
                {
                    "name": str(p.get("name") or "Utilisateur"),
                    "profile": str(p.get("profile") or ""),
                    "goals": [str(g) for g in (p.get("goals") or [])],
                    "frustrations": [str(f) for f in (p.get("frustrations") or [])],
                    "sources": self._clean_sources(p.get("sources") or []),
                }
                for p in (data.get("personas") or []) if isinstance(p, dict)
            ]
            data["steps"] = [
                {
                    "step_number": int(s.get("step_number") or i + 1),
                    "stage": str(s.get("stage") or f"Étape {i+1}"),
                    "persona": str(s.get("persona") or "Utilisateur"),
                    "action": str(s.get("action") or ""),
                    "user_goal": str(s.get("user_goal") or ""),
                    "touchpoint": str(s.get("touchpoint") or "Interface"),
                    "pain_points": [str(x) for x in (s.get("pain_points") or [])],
                    "opportunities": [str(x) for x in (s.get("opportunities") or [])],
                    "sources": self._clean_sources(s.get("sources") or []),
                }
                for i, s in enumerate(data.get("steps") or []) if isinstance(s, dict)
            ]
            if not data.get("mermaid_diagram"):
                data["mermaid_diagram"] = "flowchart LR\n  Start[Début du parcours] --> End[Fin]"

        elif mode == SynthesisMode.RAW_NOTES:
            if not data.get("deduplication_summary"):
                data["deduplication_summary"] = "Consolidation et déduplication des notes brutes."
            data["clusters"] = [
                {
                    "pillar": str(c.get("pillar") or "Axe Thématique"),
                    "tags": [str(t) for t in (c.get("tags") or [])],
                    "summary": str(c.get("summary") or ""),
                    "consolidated_ideas": [
                        {
                            "title": str(ci.get("title") or "Idée Clé"),
                            "structured_content": str(ci.get("structured_content") or ""),
                            "merged_count": int(ci.get("merged_count") or 1),
                            "sources": self._clean_sources(ci.get("sources") or []),
                        }
                        for ci in (c.get("consolidated_ideas") or []) if isinstance(ci, dict)
                    ],
                }
                for c in (data.get("clusters") or []) if isinstance(c, dict)
            ]
            next_steps = data.get("suggested_next_steps") or []
            sanitized_ns = []
            for ns in next_steps:
                if isinstance(ns, dict):
                    raw_imp = str(ns.get("impact", "")).lower()
                    if "faibl" in raw_imp or "low" in raw_imp:
                        impact = "Faible"
                    elif "moy" in raw_imp or "med" in raw_imp:
                        impact = "Moyen"
                    else:
                        impact = "Élevé"
                    sanitized_ns.append({
                        "action": str(ns.get("action") or "Prochaine étape"),
                        "category": str(ns.get("category") or "Chantier"),
                        "impact": impact,
                        "sources": self._clean_sources(ns.get("sources") or []),
                    })
            data["suggested_next_steps"] = sanitized_ns

        return data

    def _parse_and_validate(self, raw_json: str, expected_mode: SynthesisMode) -> SynthesisPayload:
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        parsed_dict = json.loads(cleaned)
        sanitized_dict = self._sanitize_payload_dict(parsed_dict, expected_mode)
        return self._payload_adapter.validate_python(sanitized_dict)

    # -------------------------------------------------------------------------
    # Moteur d'analyse locale approfondie (sans troncature, titres concis, vrais paragraphes)
    # -------------------------------------------------------------------------
    @staticmethod
    def _format_bold_argument(sent: str) -> str:
        """Formate un argument avec une accroche en gras courte et percutante pour une lecture rapide et agréable."""
        clean = sent.lstrip("-*• ").strip()
        if not clean:
            return ""
        if clean.startswith("**") and ":**" in clean:
            return clean

        # Si la phrase commence déjà par des deux-points ou un tiret ou un préfixe technique
        clean = re.sub(r"^[—\-:]\s*", "", clean)
        clean = re.sub(r"^(Notice technique et schémas visuels|Schéma technique et notice visuelle)\s*:\s*", "", clean, flags=re.IGNORECASE)
        words = clean.split()
        if len(words) < 5:
            return clean

        meaningful = [
            w.strip(" ,;:.()\"'«»")
            for w in words
            if w.lower() not in STOPWORDS_FR and len(w) > 2
        ]
        if len(meaningful) >= 2:
            hook = " ".join(meaningful[:3]).capitalize()
            # Nettoyer l'accroche
            hook = re.sub(r"[,:;.]+$", "", hook)
            return f"**{hook} :** {clean}"
        else:
            hook = " ".join(words[:3]).capitalize()
            hook = re.sub(r"[,:;.]+$", "", hook)
            return f"**{hook} :** {clean}"

    @staticmethod
    def _derive_concise_heading(text: str, default_label: str = "Axe Stratégique") -> str:
        """Extrait un titre court, percutant et explicite (3 à 5 mots) annonçant immédiatement le sujet."""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        # 1. Vérification des titres Markdown ou numérotés
        for ln in lines[:4]:
            cleaned_hdr = re.sub(r"^[#*\-\d.)\s]+", "", ln).strip(" :.-")
            cleaned_hdr = re.sub(
                r"^(Axe\s+\d+|Thème\s+\d+|Chapitre\s+\d+|Section\s+\d+|Partie\s+\d+)\s*[:—\-]\s*",
                "",
                cleaned_hdr,
                flags=re.IGNORECASE,
            )
            if 4 <= len(cleaned_hdr) <= 60 and not cleaned_hdr.endswith("."):
                words = cleaned_hdr.split()
                if 2 <= len(words) <= 5:
                    return cleaned_hdr[:50]
                elif len(words) > 5:
                    chosen = words[:5]
                    while chosen and chosen[-1].lower() in STOPWORDS_FR:
                        chosen.pop()
                    if chosen:
                        return " ".join(chosen)

        # 2. Cas spécifique des notices techniques et visuelles
        lower_t = text.lower()
        if "notice technique" in lower_t or "schéma" in lower_t or "schémas" in lower_t or "pose" in lower_t:
            page_m = re.search(r"Page\s+(\d+)", text, re.IGNORECASE)
            p_num = page_m.group(1) if page_m else ""
            if p_num == "1":
                return "Composants & Schémas d'Assemblage"
            elif p_num == "2":
                return "Consignes de Pose & Fixations"
            elif p_num == "3":
                return "Ajustements & Alignements Techniques"
            elif p_num == "4":
                return "Finitions & Contrôle Qualité"
            elif p_num:
                return f"Spécifications Techniques (Page {p_num})"
            return "Schémas Techniques & Assemblage"

        # 3. Format speaker VTT : "Claire (VP Product): Bonjour... L'objectif est..."
        speaker_match = re.match(
            r"^([A-Za-zÀ-ÿ\s]+)\s*\(([^)]+)\)\s*:\s*(.+)$", lines[0] if lines else ""
        )
        if speaker_match:
            utterance = speaker_match.group(3)
            sentences = [
                s.strip()
                for s in re.split(r"[.!?]+", utterance)
                if len(s.strip()) > 15
            ]
            target_s = (
                sentences[1]
                if len(sentences) > 1
                else (sentences[0] if sentences else utterance)
            )
            target_s = re.sub(
                r"^(l'objectif de ce comité est de|nous avons validé le|sur le|attention toutefois,?\s*|bonjour à tous\.?\s*)",
                "",
                target_s,
                flags=re.IGNORECASE,
            ).strip()
            words = target_s.split()
            chosen = words[:5]
            while chosen and chosen[-1].lower() in STOPWORDS_FR:
                chosen.pop()
            if chosen:
                title = " ".join(chosen).rstrip(",:;.")
                return title[0].upper() + title[1:]

        # 4. Extraction épurée de la première phrase
        first_sentence = re.split(r"[.!?\n]+", text.strip())[0].strip()
        first_sentence = re.sub(r"^\[[^\]]+\]\s*", "", first_sentence)
        first_sentence = re.sub(r"^[#*\-\d.)\s]+", "", first_sentence)
        first_sentence = re.sub(
            r"^(Notice technique et schémas visuels|Rapport d'analyse|Compte-rendu)\s*[:—\-]?\s*",
            "",
            first_sentence,
            flags=re.IGNORECASE,
        )
        words = [
            w.strip(",:;()\"'«»")
            for w in first_sentence.split()
            if w.strip(",:;()\"'«»")
        ]
        meaningful = [w for w in words if w.lower() not in STOPWORDS_FR and len(w) > 2]

        if len(words) >= 3:
            chosen = words[:5]
            while chosen and chosen[-1].lower() in STOPWORDS_FR:
                chosen.pop()
            if len(chosen) >= 2:
                title = " ".join(chosen)
                return title[0].upper() + title[1:]
        if meaningful:
            title = " ".join(meaningful[:4])
            return title[0].upper() + title[1:]
        return default_label

    @staticmethod
    def _split_into_thematic_sections(blocks: list[AnchoredTextBlock]) -> list[dict]:
        """Découpe les blocs documentaires en sections thématiques cohérentes avec leur titre concis, corps complet et ancre source."""
        sections: list[dict] = []

        for block in blocks:
            raw = block.content.strip()
            if not raw:
                continue

            # Détection de sous-sections Markdown (## Titre) ou blocs temporels VTT
            md_parts = re.split(r"(?m)^(?=#{1,3}\s+)", raw)
            if len(md_parts) > 1:
                for part in md_parts:
                    part_str = part.strip()
                    if not part_str:
                        continue
                    part_lines = [ln.strip() for ln in part_str.splitlines() if ln.strip()]
                    if not part_lines:
                        continue
                    first_line = part_lines[0]
                    if first_line.startswith("#"):
                        heading = re.sub(r"^#{1,3}\s*\d*[.)]?\s*", "", first_line).strip()
                        body_lines = part_lines[1:]
                        if not body_lines:
                            continue
                        sections.append(
                            {
                                "heading": heading[:65],
                                "body": "\n".join(body_lines),
                                "lines": body_lines,
                                "block": block,
                            }
                        )
                    else:
                        heading = MistralEnterpriseService._derive_concise_heading(part_str)
                        sections.append(
                            {
                                "heading": heading,
                                "body": "\n".join(part_lines),
                                "lines": part_lines,
                                "block": block,
                            }
                        )
                continue

            # Cas des transcriptions horodatées [00:01:10]
            ts_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if any(re.match(r"^\[\d{2}:\d{2}:\d{2}\]", ln) for ln in ts_lines):
                for ln in ts_lines:
                    clean_ln = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", ln)
                    heading = MistralEnterpriseService._derive_concise_heading(clean_ln)
                    sections.append(
                        {
                            "heading": heading,
                            "body": clean_ln,
                            "lines": [clean_ln],
                            "block": block,
                        }
                    )
                continue

            # Paragraphes standards séparés par double saut de ligne
            paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if len(p.strip()) > 30]
            if len(paras) > 1:
                for p in paras:
                    p_lines = [ln.strip() for ln in p.splitlines() if ln.strip()]
                    heading = MistralEnterpriseService._derive_concise_heading(p)
                    sections.append(
                        {
                            "heading": heading,
                            "body": p,
                            "lines": p_lines,
                            "block": block,
                        }
                    )
            else:
                heading = MistralEnterpriseService._derive_concise_heading(raw)
                sections.append(
                    {
                        "heading": heading,
                        "body": raw,
                        "lines": ts_lines,
                        "block": block,
                    }
                )

        return sections

    def _build_extractive_fallback(
        self,
        blocks: list[AnchoredTextBlock],
        mode: SynthesisMode,
        model_name: str,
    ) -> SynthesisPayload:
        """Construit une synthèse complète, riche en paragraphes et dotée de titres concis à partir de l'intégralité du corpus."""
        sections = self._split_into_thematic_sections(blocks)
        if not sections:
            sections = [
                {
                    "heading": "Synthèse générale du document",
                    "body": b.content,
                    "lines": b.content.splitlines(),
                    "block": b,
                }
                for b in blocks
            ]

        def make_source_from_section(sec: dict) -> SourceReference:
            b: AnchoredTextBlock = sec["block"]
            body_txt: str = sec["body"].replace("\n", " ").strip()
            excerpt = body_txt[:220] + ("..." if len(body_txt) > 220 else "")
            return SourceReference(
                file_name=b.file_name,
                location=b.location,
                excerpt=excerpt,
            )

        # Détermination d'un titre global propre
        first_doc_lines = [ln.strip() for ln in blocks[0].content.splitlines() if ln.strip()]
        if first_doc_lines and first_doc_lines[0].startswith("# "):
            doc_main_title = first_doc_lines[0].lstrip("# ").strip()
        else:
            doc_main_title = self._derive_concise_heading(blocks[0].content, "Synthèse Analytique")

        all_text = "\n\n".join(sec["body"] for sec in sections)
        all_sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", all_text)
            if len(s.strip()) > 20 and not s.strip().startswith("#")
        ]

        # Extraction des métriques avec leur phrase complète d'explication
        metrics: list[MetricItem] = []
        seen_values: set[str] = set()
        for sec in sections:
            sec_sentences = [
                s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", sec["body"]) if len(s.strip()) > 15
            ]
            for sent in sec_sentences:
                matches = re.findall(
                    r"(\b\d+(?:[.,]\d+)?\s*(?:%|M€|k€|Md€|€|\$|minutes|heures|jours|pages|ans|utilisateurs|clients)\b)",
                    sent,
                    flags=re.IGNORECASE,
                )
                for val in matches:
                    norm_val = val.strip()
                    if norm_val in seen_values:
                        continue
                    seen_values.add(norm_val)
                    # Création d'un label concis à partir du contexte entourant le chiffre
                    before_num = sent.split(norm_val)[0].strip(" ,:-(")
                    before_words = [
                        w for w in before_num.split() if w.lower() not in STOPWORDS_FR and len(w) > 2
                    ]
                    metric_label = (
                        " ".join(before_words[-4:]).capitalize()
                        if before_words
                        else sec["heading"][:40]
                    )
                    metrics.append(
                        MetricItem(
                            label=metric_label,
                            value=norm_val,
                            context=sent.lstrip("-*• "),
                            trend="up"
                            if any(
                                w in sent.lower()
                                for w in ("croissance", "progresse", "atteint", "réduit", "gain", "hausse")
                            )
                            else "neutral",
                            sources=[make_source_from_section(sec)],
                        )
                    )

        if not metrics:
            metrics.append(
                MetricItem(
                    label="Sections Thématiques Analysées",
                    value=f"{len(sections)} sections",
                    context=f"Corpus complet traité et indexé ({len(all_sentences)} propositions clés extraites).",
                    trend="neutral",
                    sources=[make_source_from_section(sections[0])],
                )
            )

        # =====================================================================
        # MODE 1 : SYNTHÈSE DOCUMENTAIRE GLOBALE
        # =====================================================================
        if mode == SynthesisMode.GLOBAL:
            # 1. Chapeau introductif + Paragraphes structurés avec sous-titres concis
            overview_sentences = all_sentences[:3]
            exec_summary = (
                " ".join(overview_sentences)
                if overview_sentences
                else sections[0]["body"]
            )

            exec_paragraphs: list[StructuredParagraph] = []
            for sec in sections[:6]:
                clean_lines = [
                    ln.lstrip("-*• ").strip()
                    for ln in sec["lines"]
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                paragraph_body = " ".join(
                    ln if ln.endswith((".", "!", "?")) else f"{ln}."
                    for ln in clean_lines
                )
                if len(paragraph_body) < 120 and len(all_sentences) > 2:
                    # Enrichissement contextuel pour éviter tout paragraphe trop court
                    extra_context = [
                        s for s in all_sentences if s not in paragraph_body
                    ][:2]
                    if extra_context:
                        paragraph_body = (
                            f"{paragraph_body} Sur le plan opérationnel et stratégique, "
                            + " ".join(extra_context)
                        )

                exec_paragraphs.append(
                    StructuredParagraph(
                        heading=sec["heading"],
                        body=paragraph_body,
                        sources=[make_source_from_section(sec)],
                    )
                )

            # 2. Thématiques clés avec résumés développés et arguments complets
            themes: list[ThemeItem] = []
            for sec in sections[:6]:
                sec_sents = [
                    s.lstrip("-*• ").strip()
                    for s in re.split(r"(?<=[.!?])\s+|\n+", sec["body"])
                    if len(s.strip()) > 15
                ]
                full_narrative = " ".join(
                    s if s.endswith((".", "!", "?")) else f"{s}." for s in sec_sents
                )
                arguments_list = [
                    self._format_bold_argument(s if s.endswith((".", "!", "?")) else f"{s}.")
                    for s in sec_sents
                ]
                if len(arguments_list) < 2 and len(all_sentences) > 1:
                    arguments_list.append(
                        self._format_bold_argument(f"Perspective globale : {all_sentences[-1]}")
                    )

                themes.append(
                    ThemeItem(
                        theme=sec["heading"],
                        summary=full_narrative,
                        arguments=arguments_list,
                        sources=[make_source_from_section(sec)],
                    )
                )

            # 3. Recommandations extraites des puces d'action ou des dernières sections
            recommendations: list[RecommendationItem] = []
            for sec in sections:
                for ln in sec["lines"]:
                    clean_ln = ln.strip()
                    if clean_ln.startswith(("-", "*", "•")) or any(
                        kw in clean_ln.lower()
                        for kw in ("recommand", "priorité", "déployer", "généraliser", "étendre", "action", "il faut")
                    ):
                        prio: str = "Haute"
                        if "moyenne" in clean_ln.lower():
                            prio = "Moyenne"
                        elif "basse" in clean_ln.lower():
                            prio = "Basse"
                        clean_desc = re.sub(
                            r"^[-*•]\s*(Priorité\s+(?:Haute|Moyenne|Basse)\s*:\s*)?",
                            "",
                            clean_ln,
                            flags=re.IGNORECASE,
                        ).strip()
                        if len(clean_desc) < 15:
                            continue
                        rec_title = self._derive_concise_heading(clean_desc, "Axe de Déploiement")
                        recommendations.append(
                            RecommendationItem(
                                title=rec_title,
                                description=(
                                    f"**Objectif opérationnel :** {clean_desc} "
                                    f"**Bénéfice attendu :** Cette orientation renforce les leviers de "
                                    f"la section « {sec['heading']} »."
                                ),
                                priority=prio,  # type: ignore[arg-type]
                                sources=[make_source_from_section(sec)],
                            )
                        )

            if not recommendations:
                for sec in sections[-2:]:
                    recommendations.append(
                        RecommendationItem(
                            title=sec["heading"],
                            description=sec["body"],
                            priority="Haute",
                            sources=[make_source_from_section(sec)],
                        )
                    )

            return GlobalSummaryResult(
                title=doc_main_title,
                executive_summary=exec_summary,
                executive_paragraphs=exec_paragraphs,
                key_themes=themes,
                key_metrics=metrics[:6],
                recommendations=recommendations[:6],
            )

        # =====================================================================
        # MODE 2 : SYNTHÈSE DE TRANSCRIPTION
        # =====================================================================
        if mode == SynthesisMode.TRANSCRIPT:
            participants: list[ParticipantItem] = []
            seen_speakers: set[str] = set()
            for sec in sections:
                for ln in sec["lines"]:
                    sp_match = re.match(r"^([A-Za-zÀ-ÿ\s\-]+?)(?:\s*\(([^)]+)\))?\s*:\s*(.+)$", ln)
                    if sp_match and len(sp_match.group(1).strip()) < 35:
                        sp_name = sp_match.group(1).strip()
                        sp_role = (sp_match.group(2) or "Participant").strip()
                        if sp_name not in seen_speakers:
                            seen_speakers.add(sp_name)
                            participants.append(ParticipantItem(name=sp_name, role=sp_role))

            if not participants:
                participants = [
                    ParticipantItem(name="Direction Produit & Métier", role="Cadrage & Objectifs"),
                    ParticipantItem(name="Architecture & Équipe Technique", role="Implémentation & Sécurité"),
                ]

            context_paragraphs = "\n\n".join(sec["body"] for sec in sections[:2])

            return TranscriptSummaryResult(
                title=f"Synthèse des Échanges — {doc_main_title}",
                context=context_paragraphs,
                participants=participants,
                agenda=[sec["heading"] for sec in sections[:6]],
                thematic_clusters=[
                    TranscriptClusterItem(
                        tag=sec["heading"],
                        consolidated_notes=sec["body"],
                        key_takeaways=[
                            s.strip()
                            for s in re.split(r"(?<=[.!?])\s+", sec["body"])
                            if len(s.strip()) > 20
                        ],
                        sources=[make_source_from_section(sec)],
                    )
                    for sec in sections
                ],
                decisions_made=[
                    DecisionItem(
                        decision=sec["heading"],
                        rationale=sec["body"],
                        sources=[make_source_from_section(sec)],
                    )
                    for sec in sections
                    if any(
                        k in sec["body"].lower()
                        for k in ("décision", "validé", "acté", "retenu", "choisi", "atteint")
                    )
                ]
                or [
                    DecisionItem(
                        decision=sections[0]["heading"],
                        rationale=sections[0]["body"],
                        sources=[make_source_from_section(sections[0])],
                    )
                ],
                action_items=[
                    ActionItem(
                        task=sec["body"],
                        assignee=participants[idx % len(participants)].name,
                        due_date="Court terme / Sprint actif",
                        priority="Haute",
                        sources=[make_source_from_section(sec)],
                    )
                    for idx, sec in enumerate(sections)
                    if any(
                        k in sec["body"].lower()
                        for k in ("action", "il faut", "priorité", "déployer", "livrer", "généraliser")
                    )
                ]
                or [
                    ActionItem(
                        task=sections[-1]["body"],
                        assignee=participants[0].name,
                        due_date="À planifier",
                        priority="Haute",
                        sources=[make_source_from_section(sections[-1])],
                    )
                ],
                open_questions_and_tensions=[
                    TensionItem(
                        topic=sec["heading"],
                        description=sec["body"],
                        stakeholders=[p.name for p in participants[:2]],
                        sources=[make_source_from_section(sec)],
                    )
                    for sec in sections
                    if any(
                        k in sec["body"].lower()
                        for k in ("question", "suspens", "attention", "friction", "risque", " ?")
                    )
                ],
            )

        # =====================================================================
        # MODE 3 : EXTRACTION DES PARCOURS UTILISATEURS
        # =====================================================================
        if mode == SynthesisMode.USER_JOURNEY:
            steps: list[UserJourneyStep] = []
            for idx, sec in enumerate(sections[:6], start=1):
                steps.append(
                    UserJourneyStep(
                        step_number=idx,
                        stage=sec["heading"],
                        persona="Utilisateur Métier / Analyste",
                        action=sec["body"],
                        user_goal=f"Maîtriser et valider les éléments liés à « {sec['heading']} ».",
                        touchpoint=sec["block"].file_name,
                        pain_points=[
                            "Vérification manuelle chronophage en l'absence de synthèse structurée."
                        ],
                        opportunities=[
                            f"Capitaliser directement sur les enseignements de « {sec['heading']} » avec traçabilité à la source."
                        ],
                        sources=[make_source_from_section(sec)],
                    )
                )
            mermaid_lines = ["flowchart LR"]
            for s in steps:
                label = s.stage.replace('"', "'")
                mermaid_lines.append(f'  S{s.step_number}["{s.step_number}. {label}"]')
            for i in range(len(steps) - 1):
                mermaid_lines.append(f"  S{i + 1} --> S{i + 2}")

            return UserJourneyResult(
                title=f"Parcours & Processus — {doc_main_title}",
                overview="\n\n".join(sec["body"] for sec in sections[:2]),
                personas=[
                    PersonaItem(
                        name="Responsable Métier & Produit",
                        profile=f"Acteur principal exploitant les processus décrits dans {doc_main_title}.",
                        goals=[sec["heading"] for sec in sections[:3]],
                        frustrations=["Complexité de croisement des sources volumineuses"],
                        sources=[make_source_from_section(sections[0])],
                    )
                ],
                steps=steps,
                mermaid_diagram="\n".join(mermaid_lines),
            )

        # =====================================================================
        # MODE 4 : SYNTHÈSE DE NOTES EN VRAC
        # =====================================================================
        return RawNotesResult(
            title=f"Base de Connaissances Consolidée — {doc_main_title}",
            deduplication_summary=(
                f"Analyse complète de {len(sections)} sections thématiques extraites du corpus. "
                f"Les notes éparses ont été structurées en paragraphes rédigés avec des sous-titres concis."
            ),
            clusters=[
                NoteCluster(
                    pillar=sec["heading"],
                    tags=[f"#{w.capitalize()}" for w in sec["heading"].split() if len(w) > 3][:3]
                    or ["#Synthèse"],
                    summary=f"Consolidation thématique portant sur : {sec['heading']}.",
                    consolidated_ideas=[
                        ConsolidatedIdea(
                            title=sec["heading"],
                            structured_content=sec["body"],
                            merged_count=max(1, len(sec["lines"])),
                            sources=[make_source_from_section(sec)],
                        )
                    ],
                )
                for sec in sections
            ],
            suggested_next_steps=[
                NextStepItem(
                    action=sec["body"],
                    category="Chantier Prioritaire",
                    impact="Élevé",
                    sources=[make_source_from_section(sec)],
                )
                for sec in sections[-2:]
            ],
        )
