"""Analyse par lots, pour les corpus plus grands que la fenêtre de contexte du modèle.

Chaque étape reste extractive pour préserver la fidélité :
  1. extraction : chaque lot du corpus donne une liste d'éléments sourcés (faits, chiffres, décisions,
     frictions, attentes, verbatims…) recopiés avec leur document et leur repère exact ;
  2. classement : les éléments sont répartis entre des thèmes ; aucun n'est perdu (sinon « Autres points ») ;
  3. rédaction thème par thème à partir de ses éléments et des passages d'origine retrouvés par leurs repères ;
  4. assemblage : titre, « En bref » et pistes d'action à partir des thèmes rédigés.
En mode Flux, les éléments extraits (dédoublonnés si besoin) remplacent le corpus pour construire le graphe.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services import analysis_service as svc
from app.services.parser_service import AnchoredTextBlock
from app.services.prompts import FLOW_GRAPH_RULES, FLOW_LEVEL_GUIDANCE

logger = logging.getLogger("analyse")

EXTRACT_SHARE = 0.5
FOLLOW_SHARE = 0.5  # classement et rédaction : environ la moitié du temps d'extraction, pour l'estimation
LOT_CACHE_DAYS = 7  # lots extraits gardés sur le disque, pour reprendre une analyse interrompue
ASSIGN_MAX_ITEMS = 100  # éléments par appel de classement : au-delà, les petits modèles en oublient
WRITE_MAX_ITEMS = 40  # éléments par appel de rédaction d'un thème
MAX_OTHER_SHARE = 0.15  # au-delà, de nouveaux thèmes sont dégagés à partir des éléments non classés
MAX_THEME_ROUNDS = 2  # part de la fenêtre utilisée par un lot (le reste : consignes et réponse)
PASSAGE_SHARE = 0.55  # part de la fenêtre pour éléments + passages lors de la rédaction d'un thème

THEME_KINDS = "fait | chiffre | decision | action | friction | attente | desaccord | verbatim"
FLOW_KINDS = THEME_KINDS + " | etape | transition | sortie | ressenti | point_de_contact"

# Extraction commune à tous les modes : les lots extraits resservent quand on relance l'analyse dans un autre
# mode (Parcours après Synthèse globale, par exemple). Les types propres au parcours servent aussi de repères
# aux thèmes ; le mode choisi n'intervient qu'au classement et à la rédaction.
EXTRACT_KINDS = FLOW_KINDS
EXTRACT_HINT = (
    "Les éléments serviront aussi bien à une synthèse par thèmes qu'à la reconstitution d'un parcours utilisateur : "
    "relève les faits, chiffres, décisions, actions annoncées, frictions, attentes, désaccords et verbatims, et "
    "aussi, quand l'extrait en parle : « etape » (ce que fait l'utilisateur), « transition » (passage d'une étape "
    "à une autre, avec sa condition), « sortie » (abandon, point de rupture), « ressenti » (émotion exprimée), "
    "« point_de_contact » (canal, écran, interlocuteur)."
)


def window_tokens(spec: svc.ModelSpec, cap: int = 0) -> int:
    """Taille de requête utilisable : fenêtre du modèle, bornée par MAX_REQUEST_TOKENS et par un plafond éventuel."""
    local = settings.LOCAL_MAX_REQUEST_TOKENS if spec.provider.local else 0
    limits = [spec.context_tokens] + [x for x in (settings.MAX_REQUEST_TOKENS, local, cap) if x]
    return min(limits)


def budget_chars(spec: svc.ModelSpec, cap: int = 0) -> int:
    tokens = window_tokens(spec, cap) - svc.RESERVED_TOKENS
    if tokens < 4000:
        raise svc.AnalysisError(f"La fenêtre de contexte de {spec.name} est trop petite pour analyser des documents.")
    return int(tokens * svc.CHARS_PER_TOKEN)


def needs_batches(spec: svc.ModelSpec, corpus: str, cap: int = 0) -> bool:
    return len(corpus) > budget_chars(spec, cap)


@dataclass
class Item:
    id: str
    kind: str
    text: str
    document: str
    location: str
    speaker: str = ""
    quote_check: str = ""

    def line(self) -> str:
        where = " ".join(x for x in (self.document, self.location) if x)
        who = f" — {self.speaker}" if self.speaker else ""
        body = f"« {self.text} »{who}" if self.kind == "verbatim" else self.text
        return f"{self.id} [{self.kind}] ({where}) {body}"


def _group(texts: list[str], max_chars: int, max_items: int = 0) -> list[list[int]]:
    """Regroupe des textes consécutifs en paquets d'au plus max_chars caractères (et max_items textes)."""
    groups, current, size = [], [], 0
    for i, t in enumerate(texts):
        if current and (size + len(t) > max_chars or (max_items and len(current) >= max_items)):
            groups.append(current)
            current, size = [], 0
        current.append(i)
        size += len(t) + 1
    if current:
        groups.append(current)
    return groups


async def _gather_limited(coros, limit: int):
    """Lance les appels, au plus limit à la fois ; au premier échec, les autres sont arrêtés.

    Sans cela, les requêtes restantes continueraient d'occuper le modèle après l'échec de l'analyse.
    """
    sem = asyncio.Semaphore(limit)

    async def run(c):
        try:
            async with sem:
                return await c
        finally:
            c.close()  # sans effet si l'appel est terminé ; évite un avertissement s'il n'a jamais démarré

    tasks = [asyncio.ensure_future(run(c)) for c in coros]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


# ---------------------------------------------------------------------------
# Lots déjà extraits : une analyse relancée reprend là où la précédente s'est arrêtée
# ---------------------------------------------------------------------------

def _lot_dir():
    return settings.STORAGE_DIR / "lots"


def _lot_key(spec: svc.ModelSpec, prompt: str, user: str) -> str:
    return hashlib.sha256("\0".join((spec.provider.api_base, spec.name, prompt, user)).encode("utf-8")).hexdigest()


def _lot_load(key: str) -> dict[str, Any] | None:
    try:
        data = json.loads((_lot_dir() / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _lot_save(key: str, data: dict[str, Any]) -> None:
    try:
        _lot_dir().mkdir(parents=True, exist_ok=True)
        (_lot_dir() / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # disque plein ou protégé : l'analyse continue, sans reprise possible
        logger.warning("Lot non enregistré : %s", exc)


def _lot_purge() -> None:
    limit = time.time() - LOT_CACHE_DAYS * 86_400
    try:
        for f in _lot_dir().glob("*.json"):
            if f.stat().st_mtime < limit:
                f.unlink(missing_ok=True)
    except OSError:
        pass


async def _cached_call_json(analysis: svc.Analysis, chain: list[svc.ModelSpec], prompt: str, user: str,
                            **kw) -> dict[str, Any]:
    """Appel gardé sur le disque comme un lot : « Reprendre l'analyse » ne le refait pas."""
    key = _lot_key(chain[0], prompt, user)
    cached = _lot_load(key)
    if cached is not None:
        return cached
    out = await svc._call_json(analysis, chain, prompt, user, **kw)
    _lot_save(key, out)
    return out


# ---------------------------------------------------------------------------
# 1. Extraction
# ---------------------------------------------------------------------------

def _extract_prompt(language: str) -> str:
    """Consigne d'extraction d'un lot, identique quel que soit le mode (voir EXTRACT_HINT)."""
    return "\n\n".join([
        svc.BASE_RULES,
        "Tu traites une partie d'un corpus trop long pour être lu d'un seul tenant. Extrais de cet extrait TOUS les "
        "éléments utiles à la compréhension du sujet, sans en omettre aucun, y compris en fin d'extrait. Chaque "
        "élément reprend fidèlement le contenu (pas d'interprétation, pas de généralisation) et indique son document "
        "et le repère exact de la ligne d'origine. Les verbatims sont recopiés mot pour mot.",
        EXTRACT_HINT,
        _lang(language),
        'Schéma JSON attendu :\n{\n  "items": [\n    {"kind": "' + EXTRACT_KINDS + '", "text": "contenu fidèle", '
        '"speaker": "qui parle (verbatim) ou chaîne vide", "document": "nom exact du document", '
        '"location": "repère exact (L12, §4, Page 3, Slide 2, 00:01:10)"}\n  ],\n'
        '  "topics": ["sujets abordés dans cet extrait (3 à 6 mots)"]\n}',
    ])


_LEGACY_FLOW_HINT = (
    "Pour le parcours, extrais aussi : « etape » (ce que fait l'utilisateur), « transition » (passage d'une "
    "étape à une autre, avec sa condition), « sortie » (abandon, point de rupture), « ressenti » (émotion "
    "exprimée), « point_de_contact » (canal, écran, interlocuteur)."
)


def _legacy_extract_prompt(mode: str, language: str) -> str:
    """Consigne d'extraction jusqu'à la 2.8.0 (une par mode) : relit les lots déjà extraits avant la mise à jour."""
    kinds = FLOW_KINDS if mode == "flow" else THEME_KINDS
    return "\n\n".join([
        svc.BASE_RULES,
        svc.MODE_GUIDANCE[mode],
        "Tu traites une partie d'un corpus trop long pour être lu d'un seul tenant. Extrais de cet extrait TOUS les "
        "éléments utiles à la compréhension du sujet, sans en omettre aucun, y compris en fin d'extrait. Chaque "
        "élément reprend fidèlement le contenu (pas d'interprétation, pas de généralisation) et indique son document "
        "et le repère exact de la ligne d'origine. Les verbatims sont recopiés mot pour mot.",
        _LEGACY_FLOW_HINT if mode == "flow" else "",
        _lang(language),
        'Schéma JSON attendu :\n{\n  "items": [\n    {"kind": "' + kinds + '", "text": "contenu fidèle", '
        '"speaker": "qui parle (verbatim) ou chaîne vide", "document": "nom exact du document", '
        '"location": "repère exact (L12, §4, Page 3, Slide 2, 00:01:10)"}\n  ],\n'
        '  "topics": ["sujets abordés dans cet extrait (3 à 6 mots)"]\n}',
    ])


def _lang(language: str) -> str:
    return svc._language_rule(language)


async def extract(analysis: svc.Analysis, chain: list[svc.ModelSpec], checker: svc.QuoteChecker) -> tuple[list[Item], list[str], int]:
    segments = [b.to_prompt_segment() for d in analysis.documents for b in d.blocks]
    groups = _group(segments, int(budget_chars(chain[0], analysis.context_cap) * EXTRACT_SHARE))
    doc_names = [d.name for d in analysis.documents]
    prompt = _extract_prompt(analysis.language)
    done = resumed = 0
    _lot_purge()
    started = time.monotonic()

    # Message de repli (envoi d'un bloc refusé) conservé en tête de la progression.
    previous = analysis.step_notes.get(1, "")
    prefix = f"{previous} · " if previous.startswith("Le modèle n'a pas pu") else ""

    async def extract_part(idx: list[int], timeouts: int = 0) -> dict[str, Any]:
        user = "Extrait du corpus :\n\n" + "\n".join(segments[i] for i in idx)
        key = _lot_key(chain[0], prompt, user)
        cached = _lot_load(key)
        if cached is None:
            # Lot extrait avant la 2.8.1 dans le même mode (ou en Parcours, qui relève tous les types).
            for mode in dict.fromkeys((analysis.mode, "flow")):
                cached = _lot_load(_lot_key(chain[0], _legacy_extract_prompt(mode, analysis.language), user))
                if cached is not None:
                    break
        if cached is not None:
            return {**cached, "_resumed": True}
        try:
            result = await svc._call_json(analysis, chain, prompt, user)
            _lot_save(key, result)
            return result
        except svc.ProviderUnavailable as exc:
            # Délai dépassé sur un gros lot : on le coupe une fois en deux, chaque moitié répond plus vite.
            if not exc.timed_out or timeouts or len(idx) < 2:
                raise
            half = len(idx) // 2
            a, b = await extract_part(idx[:half], 1), await extract_part(idx[half:], 1)
            return {"items": (a.get("items") or []) + (b.get("items") or []),
                    "topics": (a.get("topics") or []) + (b.get("topics") or [])}
        except svc.InvalidModelOutput:
            if len(idx) < 2:
                raise
            # Réponse illisible même après un nouvel essai : on redécoupe le lot (réponse plus courte, plus fiable).
            half = len(idx) // 2
            a, b = await extract_part(idx[:half], timeouts), await extract_part(idx[half:], timeouts)
            return {"items": (a.get("items") or []) + (b.get("items") or []),
                    "topics": (a.get("topics") or []) + (b.get("topics") or [])}

    async def one(k: int, idx: list[int]) -> dict[str, Any]:
        nonlocal done, resumed
        try:
            result = await extract_part(idx)
        except svc.AnalysisError as exc:
            # L'utilisateur doit savoir où l'analyse s'est arrêtée, et que le travail fait n'est pas perdu.
            kept = (f"les {done} lots déjà extraits sont gardés : « Reprendre l'analyse » repart de là." if done else
                    "reprenez l'analyse une fois le problème réglé.")
            raise type(exc)(f"{exc} (Arrêt au lot {k}/{len(groups)} de l'extraction ; {kept})") from exc
        done += 1
        resumed += bool(result.pop("_resumed", False))
        computed = done - resumed
        if computed >= 2:  # durée restante mesurée sur les lots réellement envoyés au modèle
            per_lot = (time.monotonic() - started) / computed
            analysis.eta_at = time.time() + per_lot * ((len(groups) - done) + FOLLOW_SHARE * len(groups))
        analysis.progress = 15 + 15 * done / len(groups)
        again = f" ({resumed} repris de l'analyse précédente)" if resumed else ""
        analysis.step_notes[1] = f"{prefix}{len(groups)} lots · lot {done}/{len(groups)} extrait{again}"
        return result

    analysis.step_notes[1] = f"{prefix}{len(groups)} lots pour tenir dans la fenêtre du modèle"
    results = await _gather_limited([one(k, g) for k, g in enumerate(groups, start=1)], svc.concurrency(chain[0]))

    items: list[Item] = []
    topics: list[str] = []
    seen: set[tuple[str, str]] = set()
    for res in results:
        topics += svc._str_list(res.get("topics"))
        for raw in res.get("items") or []:
            if not isinstance(raw, dict) or not svc._s(raw.get("text")):
                continue
            kind = svc._s(raw.get("kind")).lower().replace(" ", "_") or "fait"
            text = svc._s(raw.get("text")).strip("«»\"“” ")
            key = (kind, text.lower())
            if key in seen:  # même élément extrait deux fois (chevauchement de lots)
                continue
            seen.add(key)
            items.append(Item(
                id=f"e{len(items) + 1}", kind=kind, text=text,
                document=svc._match_doc(svc._s(raw.get("document")), doc_names) or "",
                location=svc._s(raw.get("location")), speaker=svc._s(raw.get("speaker")),
                quote_check=checker.check(text) if kind == "verbatim" else "",
            ))
    if not items:
        raise svc.AnalysisError("Aucun élément n'a pu être extrait des documents.")
    return items, list(dict.fromkeys(t for t in topics if t)), len(groups)


# ---------------------------------------------------------------------------
# 2. Classement en thèmes
# ---------------------------------------------------------------------------

THEMES_SCHEMA_SHORT = ('Schéma JSON attendu :\n{"title": "titre court et explicite de l\'étude", '
                       '"themes": [{"title": "intitulé du thème (3 à 6 mots)", "scope": "ce que couvre le thème, en une phrase"}]}')


async def _propose_themes(analysis: svc.Analysis, chain: list[svc.ModelSpec], material: str,
                          existing: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Thèmes de la synthèse, à partir des sujets repérés ou d'éléments restés sans thème."""
    if existing:
        task = ("Les éléments ci-dessous, extraits du corpus, ne rentrent dans aucun des thèmes existants. Propose des "
                "thèmes supplémentaires, distincts des existants, pour les couvrir tous.\nThèmes existants :\n"
                + "\n".join(f"- {t['title']}" for t in existing))
    else:
        task = ("Voici les sujets repérés dans les différentes parties d'un même corpus. Établis la liste des grands "
                "thèmes de la synthèse : fusionne les sujets identiques ou très proches, mais ne perds aucun sujet. "
                "Pour un corpus volumineux, prévois assez de thèmes pour que chacun reste lisible.")
    prompt = "\n\n".join([svc.BASE_RULES, svc.MODE_GUIDANCE[analysis.mode], task, svc.COMPLETENESS_RULE,
                           _lang(analysis.language), THEMES_SCHEMA_SHORT])
    outline = await _cached_call_json(analysis, chain, prompt, material[: budget_chars(chain[0], analysis.context_cap)])
    known = {t["title"].lower() for t in existing}
    themes = [
        {"title": svc._s(t.get("title")), "scope": svc._s(t.get("scope")), "items": []}
        for t in outline.get("themes") or []
        if isinstance(t, dict) and svc._s(t.get("title")) and svc._s(t.get("title")).lower() not in known
    ]
    return svc._s(outline.get("title")), themes


_ASSIGN_KEY = re.compile(r'"[^"\n]{1,20}"\s*:\s*\d')


async def _assign(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item],
                  themes: list[dict[str, Any]], phases: bool = False) -> dict[str, int]:
    """Numéro de thème (1…n) de chaque élément ; les éléments oubliés par le modèle sont redemandés une fois.

    phases : les « thèmes » sont les étapes d'un parcours (mode Parcours, gros documents).
    """
    theme_list = "\n".join(f"{i + 1}. {t['title']} — {t['scope']}" for i, t in enumerate(themes))
    if phases:
        prompt = "\n\n".join([
            "Tu répartis des éléments extraits d'un corpus entre les étapes d'un parcours utilisateur. Chaque élément "
            "va dans l'étape à laquelle il se rapporte le mieux (ce que fait l'utilisateur, ce qu'il ressent, ce qui le "
            "bloque ou ce qu'il attend à ce moment-là) ; 0 seulement s'il ne se rapporte à aucune étape. Réponds pour "
            "CHAQUE identifiant fourni.",
            "Étapes, dans l'ordre :\n" + theme_list,
            'Schéma JSON attendu : {"assign": {"identifiant de l\'élément": numéro de l\'étape}}',
        ])
    else:
        prompt = "\n\n".join([
            "Tu répartis des éléments extraits d'un corpus entre des thèmes. Chaque élément va dans le thème qui lui "
            "correspond le mieux ; 0 seulement s'il ne correspond à aucun thème. Réponds pour CHAQUE identifiant fourni.",
            "Thèmes :\n" + theme_list,
            'Schéma JSON attendu : {"assign": {"identifiant de l\'élément": numéro du thème}}',
        ])
    budget = int(budget_chars(chain[0], analysis.context_cap) * 0.6) - len(theme_list)
    result: dict[str, int] = {}

    state = {"done": 0, "total": 0, "computed": 0, "started": time.monotonic()}
    note = analysis.step_notes.get(2, "")

    async def one(part: list[Item]) -> dict[str, Any]:
        # Un modèle local peut se mettre à numéroter des éléments qui n'existent pas (« e345 », « e346 »…) sans
        # jamais s'arrêter : au-delà du nombre d'éléments envoyés, la réponse est interrompue.
        limit = len(part) + 10

        def watch(text: str) -> None:
            if len(_ASSIGN_KEY.findall(text)) > limit:
                raise svc.InvalidModelOutput("Le modèle classe des éléments qui n'existent pas : réponse interrompue.")

        user = "Éléments :\n" + "\n".join(i.line() for i in part)
        key = _lot_key(chain[0], prompt, user)
        out = _lot_load(key)
        if out is None:
            try:
                out = await svc._call_json(analysis, chain, prompt, user, on_text=watch)
                _lot_save(key, out)
            except (svc.InvalidModelOutput, svc.ProviderUnavailable) as exc:
                # Paquet laissé sans classement : ses éléments sont redemandés au second passage, sinon
                # rangés dans « Autres points ». L'analyse continue.
                logger.warning("Classement : paquet de %s éléments sans réponse exploitable (%s)", len(part), exc)
                out = {}
            state["computed"] += 1
        state["done"] += 1
        if state["computed"]:
            per_part = (time.monotonic() - state["started"]) / state["computed"]
            analysis.eta_at = time.time() + per_part * (state["total"] - state["done"]) + per_part * 3
        analysis.step_notes[2] = f"{note} · paquet {state['done']}/{state['total']} classé"
        mapping = out.get("assign")
        return mapping if isinstance(mapping, dict) else {}

    pending = items
    for _ in range(2):  # second passage : éléments que le modèle n'a pas renvoyés
        groups = _group([i.line() for i in pending], budget, ASSIGN_MAX_ITEMS)
        state.update(done=0, total=len(groups))
        for mapping in await _gather_limited([one([pending[k] for k in g]) for g in groups], svc.concurrency(chain[0])):
            for item_id, num in mapping.items():
                try:
                    result.setdefault(item_id, int(num))
                except (TypeError, ValueError):
                    continue
        pending = [i for i in pending if i.id not in result]
        if not pending:
            break
    return result


async def classify(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item], topics: list[str]) -> tuple[str, list[dict[str, Any]], int]:
    """Retourne (titre, thèmes avec leurs éléments, nombre d'éléments restés sans thème)."""
    topic_text = "\n".join(f"- {t}" for t in topics) or "\n".join(i.line() for i in items[:200])
    analysis.step_notes[2] = f"Choix des thèmes à partir de {len(topics) or len(items[:200])} sujets repérés"
    title, themes = await _propose_themes(analysis, chain, topic_text, [])
    if not themes:
        raise svc.AnalysisError("Le modèle n'a identifié aucun thème exploitable.")
    analysis.preview += [t["title"] for t in themes]
    analysis.progress = 40

    by_id = {i.id: i for i in items}
    placed: dict[str, int] = {}
    to_place = items
    for round_ in range(1 + MAX_THEME_ROUNDS):
        n = len(themes)
        analysis.step_notes[2] = f"{n} thème{'s' if n > 1 else ''} · classement de {len(to_place)} éléments extraits"
        for item_id, num in (await _assign(analysis, chain, to_place, themes)).items():
            if item_id in by_id and 1 <= num <= len(themes):
                placed[item_id] = num
        analysis.progress = min(59, 40 + 7 * (round_ + 1))
        leftovers = [i for i in items if i.id not in placed]
        if len(leftovers) <= max(10, MAX_OTHER_SHARE * len(items)) or round_ == MAX_THEME_ROUNDS:
            break
        # Trop d'éléments sans thème : de nouveaux thèmes sont dégagés à partir de ces éléments.
        try:
            _, extra = await _propose_themes(analysis, chain, "\n".join(i.line() for i in leftovers), themes)
        except (svc.InvalidModelOutput, svc.ProviderUnavailable) as exc:
            logger.warning("Thèmes supplémentaires non proposés (%s) : les éléments restants vont dans « Autres points »", exc)
            extra = []
        if not extra:
            break
        themes += extra
        analysis.preview += [t["title"] for t in extra]
        to_place = leftovers

    for item_id, num in placed.items():
        themes[num - 1]["items"].append(by_id[item_id])
    leftovers = [i for i in items if i.id not in placed]
    if leftovers:  # rien n'est perdu en silence
        themes.append({"title": OTHER_POINTS, "scope": OTHER_SCOPE, "items": leftovers})
    return title, [t for t in themes if t["items"]], len(leftovers)


# ---------------------------------------------------------------------------
# 3. Rédaction thème par thème
# ---------------------------------------------------------------------------

def _find_block(doc_blocks: list[AnchoredTextBlock], location: str) -> AnchoredTextBlock | None:
    loc = location.strip()
    m = re.match(r"(L|§)(\d+)", loc)
    if m:
        marker = f"{m.group(1)}{m.group(2)}: "
        return next((b for b in doc_blocks if f"\n{marker}" in f"\n{b.content}"), None)
    m = re.match(r"(?:p\.?|page)\s*(\d+)", loc, re.I)
    if m:
        return next((b for b in doc_blocks if b.location == f"Page {m.group(1)}"), None)
    m = re.match(r"slide\s*(\d+)", loc, re.I)
    if m:
        return next((b for b in doc_blocks if b.location == f"Slide {m.group(1)}"), None)
    m = re.match(r"\d{2}:\d{2}:\d{2}", loc)
    if m:
        return next((b for b in doc_blocks if f"\n{m.group(0)}: " in f"\n{b.content}"), None)
    return None


def _passages(analysis: svc.Analysis, items: list[Item], max_chars: int) -> str:
    """Passages d'origine des éléments, dans l'ordre, jusqu'à max_chars."""
    blocks_by_doc = {d.name: d.blocks for d in analysis.documents}
    out, seen, size = [], set(), 0
    for it in items:
        block = _find_block(blocks_by_doc.get(it.document, []), it.location) if it.document else None
        if block is None or id(block) in seen:
            continue
        seg = block.to_prompt_segment()
        if size + len(seg) > max_chars:
            break
        seen.add(id(block))
        out.append(seg)
        size += len(seg)
    return "\n".join(out)


THEME_SCHEMA = """{
  "theme": {
    "title": "intitulé du thème",
    "summary": "synthèse du thème",
    "documents": ["noms exacts des documents où le thème est présent"],
    "points": [
      {"lead": "le point clé en une phrase courte", "body": "développement",
       "sources": [{"document": "nom exact du document", "location": "repère exact (L12, §4, Page 3…)"}]}
    ],
    "quote": "verbatim marquant recopié mot pour mot (chaîne vide si aucun)",
    "quote_by": "qui parle et dans quel contexte",
    "nuance": "nuance ou point de divergence exprimé dans les documents (chaîne vide si aucun)"
  },
  "actions": [{"title": "recommandation, demande ou décision exprimée dans les documents", "body": "justification tirée des documents"}]
}"""


def _theme_prompt(analysis: svc.Analysis, quota: int = 0) -> str:
    """Consigne de rédaction d'un thème ; quota > 0 : synthèse courte, au plus quota points clés."""
    task = (
        "Rédige un seul thème de la synthèse à partir des éléments extraits des documents et des passages d'origine "
        "fournis. Couvre tous les éléments listés : chacun doit se retrouver dans un point clé. Reprends tels quels "
        "tous les chiffres, durées, montants, pourcentages, dates, lieux et noms qu'ils contiennent : une synthèse "
        "qui perd un chiffre est infidèle. Vérifie le sens et les citations dans les passages d'origine quand ils "
        "sont fournis."
    ) if not quota else (
        "Rédige un seul thème de la synthèse à partir des éléments extraits des documents et des passages d'origine "
        "fournis. Reprends tels quels les chiffres, dates et noms des points retenus. Vérifie le sens et les "
        "citations dans les passages d'origine quand ils sont fournis."
    )
    return "\n\n".join([
        svc.BASE_RULES,
        svc.MODE_GUIDANCE[analysis.mode],
        task,
        svc.short_theme_rule(quota, analysis.level) if quota else svc.LEVEL_GUIDANCE[analysis.level],
        "Indique les sources de chaque point." if analysis.cite else "Laisse « sources » vide ([]) pour chaque point.",
        _lang(analysis.language),
        "Schéma JSON attendu :\n" + THEME_SCHEMA,
    ])


CONDENSE_SCHEMA = """{
  "summary": "synthèse du thème",
  "points": [
    {"lead": "le point clé en une phrase courte", "body": "développement court",
     "sources": [{"document": "nom exact du document", "location": "repère exact"}]}
  ]
}"""


def _condense_prompt(analysis: svc.Analysis, quota: int) -> str:
    """Réunit les parties d'un thème rédigé en plusieurs fois : un résumé, et au plus quota points (0 = tous)."""
    if quota:
        task = (
            f"Voici un thème de synthèse rédigé en plusieurs parties. Garde-en l'essentiel en au plus {quota} points "
            "clés : les plus importants et les plus fréquents. Regroupe les points qui disent la même chose et réunis "
            "leurs sources. Ne reformule pas les chiffres, dates et noms. N'ajoute rien qui ne figure pas dans les "
            "points fournis. Résumé du thème : 2 phrases courtes au plus."
        )
    else:
        task = (
            "Voici les résumés partiels d'un même thème de synthèse, rédigé en plusieurs parties. Rédige un seul "
            "résumé du thème en 2 à 3 phrases courtes, sans rien ajouter qui n'y figure. Laisse « points » vide ([])."
        )
    return "\n\n".join([svc.BASE_RULES, task, _lang(analysis.language), "Schéma JSON attendu :\n" + CONDENSE_SCHEMA])


def _point_text(p: dict[str, Any]) -> str:
    src = "; ".join(f"{svc._s(s.get('document'))} {svc._s(s.get('location'))}".strip()
                    for s in p.get("sources") or [] if isinstance(s, dict))
    return f"- {svc._s(p.get('lead'))} {svc._s(p.get('body'))}".rstrip() + (f" [{src}]" if src else "")


async def _condense(analysis: svc.Analysis, chain: list[svc.ModelSpec], merged: dict[str, Any], summaries: list[str],
                    quota: int) -> None:
    """Résumé unique (et, si quota, points réduits) pour un thème rédigé en plusieurs parties. Modifie merged.

    Sans cette étape, les résumés des parties sont mis bout à bout et le thème s'ouvre sur un long pavé.
    """
    if quota:
        user = (f"Thème : {merged['title']}\n\nRésumés des parties :\n" + "\n".join(f"- {x}" for x in summaries)
                + "\n\nPoints clés :\n" + "\n".join(_point_text(p) for p in merged["points"]))
    else:
        user = f"Thème : {merged['title']}\n\nRésumés des parties :\n" + "\n".join(f"- {x}" for x in summaries)
    try:
        out = await _cached_call_json(analysis, chain, _condense_prompt(analysis, quota), user)
    except (svc.InvalidModelOutput, svc.ProviderUnavailable, svc.AnalysisError) as exc:
        logger.warning("Thème « %s » non resserré (%s)", merged["title"], exc)
        out = {}
    summary = svc._s(out.get("summary"))
    merged["summary"] = summary or (summaries[0] if summaries else merged["summary"])
    points = [p for p in out.get("points") or [] if isinstance(p, dict) and svc._s(p.get("lead"))]
    if quota:
        # Réponse inexploitable : on garde les premiers points rédigés, le reste figure en annexe.
        merged["points"] = (points or merged["points"])[:quota]


def _detail(it: Item) -> dict[str, Any]:
    """Élément extrait tel quel, pour l'annexe détaillée."""
    text = f"« {it.text} »" + (f" — {it.speaker}" if it.speaker else "") if it.kind == "verbatim" else it.text
    return {"text": text, "kind": it.kind, "document": it.document, "location": it.location}


async def write_themes(analysis: svc.Analysis, chain: list[svc.ModelSpec], themes: list[dict[str, Any]],
                       quotas: list[int] | None = None) -> list[dict[str, Any]]:
    """Rédige chaque thème ; quotas[i] > 0 : au plus quotas[i] points clés (synthèse courte des gros documents)."""
    budget = int(budget_chars(chain[0], analysis.context_cap) * PASSAGE_SHARE)
    quotas = quotas or [0] * len(themes)
    sem = asyncio.Semaphore(svc.concurrency(chain[0]))  # par requête, toutes parties confondues
    done = 0
    started = time.monotonic()

    async def write_part(theme: dict[str, Any], part: list[Item], label: str, quota: int) -> list[dict[str, Any]]:
        lines = "\n".join(i.line() for i in part)
        passages = _passages(analysis, part, budget - len(lines))
        user = (f"Thème : {theme['title']} — {theme['scope']}{label}\n\nÉléments extraits :\n{lines}"
                + (f"\n\nPassages d'origine :\n{passages}" if passages else ""))
        try:
            async with sem:
                return [await _cached_call_json(analysis, chain, _theme_prompt(analysis, quota), user)]
        except svc.ProviderUnavailable as exc:
            if not exc.timed_out:
                raise  # fournisseur indisponible : inutile de redécouper
            # Délai dépassé (modèle local lent sur une grosse partie) : redécoupe, comme pour une réponse illisible.
            if len(part) > 1:
                half = len(part) // 2
                q = (quota + 1) // 2 if quota else 0
                return await write_part(theme, part[:half], label, q) + await write_part(theme, part[half:], label, q)
            return [{"theme": {"points": [_as_point(part[0])]}, "raw": True}]
        except svc.AnalysisError:
            if len(part) > 1:  # requête refusée ou réponse illisible : on redécoupe
                half = len(part) // 2
                q = (quota + 1) // 2 if quota else 0
                return await write_part(theme, part[:half], label, q) + await write_part(theme, part[half:], label, q)
            # Dernier recours : l'élément est repris tel qu'extrait, avec sa source ; rien n'est perdu.
            return [{"theme": {"points": [_as_point(part[0])]}, "raw": True}]

    async def write_one(theme: dict[str, Any], quota: int) -> dict[str, Any]:
        nonlocal done
        lines = [i.line() for i in theme["items"]]
        groups = _group(lines, budget, WRITE_MAX_ITEMS)  # un thème très fourni est rédigé en plusieurs parties
        n_items = len(theme["items"])
        results = await asyncio.gather(*(
            write_part(theme, [theme["items"][i] for i in g], f" (partie {k + 1}/{len(groups)})" if len(groups) > 1 else "",
                       max(2, -(-quota * len(g) // n_items)) if quota else 0)
            for k, g in enumerate(groups)
        ))
        parts = [p for r in results for p in r]
        merged = _merge_parts(theme, parts)
        summaries = [x for x in merged.pop("summaries") if x]
        raw = sum(1 for p in parts if p.get("raw"))
        if len(summaries) > 1 or (quota and len(merged["points"]) > quota):
            await _condense(analysis, chain, merged, summaries, quota)
        if quota:
            merged["details"] = [_detail(it) for it in theme["items"]]  # tout le détail, en annexe
        if raw and not quota:
            merged["note"] = (f"{raw} élément{'s' if raw > 1 else ''} de ce thème n'ont pas pu être rédigés par le "
                              "modèle : ils sont repris tels qu'extraits des documents.")
        done += 1
        per_theme = (time.monotonic() - started) / done
        analysis.eta_at = time.time() + per_theme * (len(themes) - done + 0.5)  # + titre et « En bref »
        analysis.progress = 60 + 30 * done / len(themes)
        analysis.step_notes[3] = f"Rédaction thème par thème depuis les passages d'origine ({done}/{len(themes)})"
        return merged

    analysis.step_notes[3] = f"Rédaction thème par thème depuis les passages d'origine (0/{len(themes)})"
    return await asyncio.gather(*(write_one(t, q) for t, q in zip(themes, quotas)))


def _merge_parts(theme: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Réunit les parties d'un thème rédigé en plusieurs fois, sans rien retirer."""
    out = {"title": theme["title"], "summary": "", "documents": [], "points": [], "quote": "", "quote_by": "",
           "nuance": "", "actions": []}
    summaries, nuances = [], []
    for p in parts:
        t = p.get("theme") if isinstance(p.get("theme"), dict) else p
        summaries.append(svc._s(t.get("summary")))
        nuances.append(svc._s(t.get("nuance")))
        out["documents"] += svc._str_list(t.get("documents"))
        out["points"] += [x for x in t.get("points") or [] if isinstance(x, dict)]
        if not out["quote"] and svc._s(t.get("quote")):
            out["quote"], out["quote_by"] = svc._s(t.get("quote")), svc._s(t.get("quote_by"))
        out["actions"] += [a for a in p.get("actions") or [] if isinstance(a, dict)]
    out["summary"] = " ".join(x for x in summaries if x)
    out["summaries"] = summaries  # résumés des parties, réunis ensuite en un seul (_condense)
    out["nuance"] = " ".join(dict.fromkeys(x for x in nuances if x))
    # Les documents d'où viennent les éléments du thème sont forcément concernés.
    out["documents"] = list(dict.fromkeys(out["documents"] + [i.document for i in theme["items"] if i.document]))
    return out


# ---------------------------------------------------------------------------
# Contrôle de couverture : aucune information précise ne doit disparaître
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PROPER = re.compile(r"(?<![.!?:]\s)(?<!^)\b[A-ZÀ-Ý][\wÀ-ÿ'-]{2,}")
OTHER_POINTS = "Autres points"
OTHER_SCOPE = "Éléments des documents non repris dans les thèmes précédents, tels qu'extraits"


_NUMBER_WITH_WORD = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s+([a-zà-ÿ]{2,}))?", re.I)


def _key_facts(text: str) -> set[str]:
    """Informations précises d'un élément : nombres (avec le mot qui les suit) et noms propres.

    Un nombre seul (« 6 ») se retrouve presque toujours ailleurs dans une synthèse : on vérifie donc
    « 6 particip… », « 35 euro… », « 26 ans » pour savoir si l'information elle-même a été reprise.
    """
    facts = set()
    for number, word in _NUMBER_WITH_WORD.findall(text):
        number = number.replace(".", ",")
        facts.add(f"{number} {word[:5].lower()}" if word else number)
    names = {m.lower() for m in _PROPER.findall(text)}
    return facts | names


_NON_CONTENT = {"location", "document", "documents", "sources", "id", "from", "to", "kind", "type", "mermaid"}


def _content_text(value: Any) -> str:
    """Texte rédigé seulement : repères, noms de fichiers et identifiants exclus de la comparaison."""
    if isinstance(value, dict):
        return " ".join(_content_text(v) for k, v in value.items() if k not in _NON_CONTENT)
    if isinstance(value, list):
        return " ".join(_content_text(v) for v in value)
    return value if isinstance(value, str) else ""


def _present(fact: str, blob: str) -> bool:
    if fact[0].isdigit():  # nombre entier : « 20 » ne doit pas être trouvé dans « 2023 » ou « 120 »
        number, _, word = fact.partition(" ")
        after = rf"\s+{re.escape(word)}" if word else r"(?![\d]|,\d)"
        return re.search(rf"(?<![\d,]){re.escape(number)}{after}", blob) is not None
    return fact in blob


def uncovered(items: list[Item], produced: Any) -> list[Item]:
    """Éléments dont au moins une information précise est absente du texte rédigé."""
    blob = re.sub(r"(?<=\d)\.(?=\d)", ",", _content_text(produced)).lower()
    return [it for it in items if any(not _present(f.lower(), blob) for f in _key_facts(it.text))]


def _as_point(it: Item) -> dict[str, Any]:
    text = f"« {it.text} »" + (f" — {it.speaker}" if it.speaker else "") if it.kind == "verbatim" else it.text
    return {"lead": text, "body": "",
            "sources": [{"document": it.document, "location": it.location}] if it.document else []}


def add_uncovered_points(data: dict[str, Any], items: list[Item]) -> int:
    """Ajoute à « Autres points » les éléments extraits que la rédaction n'a pas repris."""
    missing = uncovered(items, data)
    if not missing:
        return 0
    other = next((t for t in data["themes"] if t.get("title") == OTHER_POINTS), None)
    if other is None:
        other = {"title": OTHER_POINTS, "summary": OTHER_SCOPE + ".", "documents": [], "points": [],
                 "quote": "", "quote_by": "", "nuance": ""}
        data["themes"].append(other)
    other["points"] += [_as_point(it) for it in missing]
    other["documents"] = list(dict.fromkeys(other.get("documents", []) + [i.document for i in missing if i.document]))
    return len(missing)


# ---------------------------------------------------------------------------
# 4. Assemblage
# ---------------------------------------------------------------------------

async def assemble(analysis: svc.Analysis, chain: list[svc.ModelSpec], title: str, written: list[dict[str, Any]]) -> dict[str, Any]:
    digest = "\n".join(f"{i + 1}. {t['title']} : {t['summary']}" for i, t in enumerate(written))
    prompt = "\n\n".join([
        svc.BASE_RULES,
        "Voici les thèmes d'une synthèse documentaire déjà rédigés. Rédige le titre de l'étude et « En bref » : "
        "2 à 3 phrases qui résument l'essentiel des thèmes, sans rien ajouter qui n'y figure ; entoure de "
        "*astérisques* un seul mot ou groupe de 2 à 4 mots, le plus important.",
        _lang(analysis.language),
        'Schéma JSON attendu : {"title": "titre court et explicite", "brief": "…"}',
    ])
    try:
        head = await _cached_call_json(analysis, chain, prompt, digest)
    except (svc.InvalidModelOutput, svc.ProviderUnavailable) as exc:
        # Titre et « En bref » seulement : les thèmes rédigés ne sont pas perdus pour autant.
        logger.warning("Titre et « En bref » non rédigés (%s)", exc)
        head = {}
    actions, seen = [], set()
    for n, t in enumerate(written, start=1):
        for a in t.pop("actions", []):
            key = svc._s(a.get("title")).lower()
            if key and key not in seen:
                seen.add(key)
                actions.append({"title": svc._s(a.get("title")), "body": svc._s(a.get("body")), "theme": n})
    return {"title": svc._s(head.get("title")) or title, "brief": svc._s(head.get("brief")),
            "themes": written, "actions": actions}


async def run_themes(analysis: svc.Analysis, chain: list[svc.ModelSpec], checker: svc.QuoteChecker) -> dict[str, Any]:
    svc._enter(analysis, 1)
    items, topics, n_batches = await extract(analysis, chain, checker)
    svc._enter(analysis, 2)
    title, themes, unassigned = await classify(analysis, chain, items, topics)
    svc._enter(analysis, 3)
    # Synthèse courte (par défaut) : longueur bornée, le détail complet passe en annexe.
    quotas = [0] * len(themes) if analysis.full_length else svc.point_quotas([len(t["items"]) for t in themes], analysis.level)
    written = await write_themes(analysis, chain, themes, quotas)
    svc._enter(analysis, 4)
    data = await assemble(analysis, chain, title, written)
    short = any(quotas)
    # Contrôle de couverture : les thèmes limités ont tout leur détail en annexe ; les autres sont vérifiés.
    recovered = add_uncovered_points(data, [i for t, q in zip(themes, quotas) if not q for i in t["items"]])
    data["coverage"] = {"batches": n_batches, "items": len(items), "unassigned": unassigned, "recovered": recovered,
                        "short": short}
    return data


# ---------------------------------------------------------------------------
# Mode Parcours
# ---------------------------------------------------------------------------
#
# Corpus moyen : la liste des éléments extraits tient dans une requête ; le plan des étapes puis le parcours complet
# sont rédigés en deux appels.
# Très gros corpus (des centaines de pages) : la liste ne tient plus dans la fenêtre du modèle, et une fusion des
# doublons ne la réduit pas assez, puisqu'elle ne retire que les vrais doublons. Le parcours est alors reconstitué
# étape par étape, comme la Synthèse globale thème par thème :
# 1. plan des étapes sur une liste condensée (les éléments qui décrivent le déroulé), par parties si besoin ;
# 2. chaque élément est rangé dans son étape ;
# 3. chaque étape est rédigée à partir de ses éléments et de leurs passages d'origine ;
# 4. titre, « En bref » et graphe sont dressés à partir des étapes rédigées et des transitions et sorties relevées.
# Aucune requête ne dépend de la taille du corpus : la méthode tient quel que soit le nombre de pages.

FLOW_FIT_SHARE = 0.7  # part de la fenêtre que peut occuper la liste des éléments pour une rédaction en un bloc
FLOW_STEP_KINDS = {"etape", "transition", "sortie", "point_de_contact"}  # éléments qui décrivent le déroulé
OUTLINE_LINE_CHARS = 220  # élément raccourci, pour le plan des étapes
PHASE_LISTS = ("touchpoints", "frictions", "opportunities")
SENTIMENT_RULE = ("« sentiment » est un entier de -2 (très négatif) à 2 (très positif), ou null si les documents "
                  "n'expriment aucun ressenti à cette étape (« mood » vide).")

PHASES_SCHEMA = ('Schéma JSON attendu :\n{"title": "titre court et explicite du parcours (max 8 mots)", '
                 '"phases": [{"name": "nom de l\'étape (1 à 3 mots)", "scope": "ce qui se passe à cette étape, en une phrase"}]}')

PHASE_SCHEMA = """{
  "phase": {
    "mood": "ressenti exprimé dans les documents, en un mot ; chaîne vide si aucun",
    "sentiment": "entier de -2 à 2, ou null si aucun ressenti n'est exprimé",
    "does": "ce que fait l'utilisateur à cette étape",
    "touchpoints": ["points de contact (2 à 4 mots chacun)"],
    "frictions": ["frictions ou points de rupture signalés dans les documents (phrase courte) ; [] si aucun"],
    "opportunities": ["attentes ou idées d'amélioration exprimées dans les documents (phrase courte) ; [] si aucune"]
  },
  "priorities": [
    {"severity": "Bloquant | Majeur | Mineur", "title": "intitulé de la friction", "body": "explication en 1 à 2 phrases",
     "quote": "verbatim recopié mot pour mot", "frequency": "fréquence citée dans les documents, sinon chaîne vide"}
  ]
}"""

FLOW_HEAD_SCHEMA = """{
  "title": "titre court et explicite du parcours",
  "brief": "2 à 3 phrases qui résument le parcours ; entoure de *astérisques* un seul groupe de 2 à 6 mots, le plus important",
  "flow": {
    "nodes": [{"id": "identifiant court unique (ex. n1)", "label": "action, écran ou décision (2 à 8 mots)",
               "type": "entry | step | decision | exit | goal", "friction": false}],
    "edges": [{"from": "id du nœud de départ", "to": "id du nœud d'arrivée",
               "label": "condition ou action déclenchante (chaîne vide si évident)", "kind": "main | alt | exit | loop"}]
  }
}"""


def _flow_base(analysis: svc.Analysis) -> list[str]:
    return [svc.BASE_RULES, svc.MODE_GUIDANCE["flow"]]


def _phases_of(out: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"title": svc._s(p.get("name")), "scope": svc._s(p.get("scope")), "items": []}
            for p in out.get("phases") or [] if isinstance(p, dict) and svc._s(p.get("name"))]


async def flow_outline(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item]) -> tuple[str, list[dict[str, Any]]]:
    """Étapes du parcours (titre, [{title, scope, items}]) sur une liste condensée, découpée en parties si besoin."""
    budget = int(budget_chars(chain[0], analysis.context_cap) * 0.6)
    steps = [i for i in items if i.kind in FLOW_STEP_KINDS]
    if len(steps) < 5:  # document qui décrit peu le déroulé lui-même : tous les éléments servent au plan
        steps = items
    lines = [f"[{i.kind}] {i.text[:OUTLINE_LINE_CHARS]}" for i in steps]
    groups = _group(lines, budget)
    scope = "d'un corpus" if len(groups) == 1 else "d'une partie d'un corpus volumineux"
    task = (f"Voici, dans l'ordre, les éléments {scope} qui décrivent le déroulé d'un parcours utilisateur (étapes, "
            "transitions, sorties, points de contact). Première passe : identifie uniquement les étapes du parcours "
            + ("dont parle cette partie, " if len(groups) > 1 else "") + "dans l'ordre chronologique.")
    prompt = "\n\n".join(_flow_base(analysis) + [task, svc.COMPLETENESS_RULE, FLOW_LEVEL_GUIDANCE[analysis.level],
                                                 _lang(analysis.language), PHASES_SCHEMA])
    done = 0

    async def one(g: list[int]) -> dict[str, Any]:
        nonlocal done
        try:
            out = await _cached_call_json(analysis, chain, prompt, "\n".join(lines[i] for i in g))
        except (svc.InvalidModelOutput, svc.ProviderUnavailable) as exc:
            if len(groups) == 1:
                raise
            logger.warning("Étapes d'une partie du corpus non repérées (%s)", exc)  # les autres parties suffisent
            out = {}
        done += 1
        analysis.progress = 30 + 10 * done / len(groups)
        analysis.step_notes[2] = f"Repérage des étapes du parcours · partie {done}/{len(groups)}"
        return out

    analysis.step_notes[2] = f"Repérage des étapes du parcours sur {len(steps)} éléments"
    outs = await _gather_limited([one(g) for g in groups], svc.concurrency(chain[0]))
    title = next((svc._s(o.get("title")) for o in outs if svc._s(o.get("title"))), "")
    if len(groups) == 1:
        return title, _phases_of(outs[0])

    # Plusieurs parties : leurs étapes sont réunies en une seule liste ordonnée (requête courte).
    partial = [_phases_of(o) for o in outs]
    listing = "\n\n".join(f"Partie {k} :\n" + "\n".join(f"- {p['title']} — {p['scope']}" for p in ps)
                          for k, ps in enumerate(partial, start=1) if ps)
    if not listing:
        raise svc.AnalysisError("Le modèle n'a reconstitué aucune étape de parcours.")
    merge_prompt = "\n\n".join(_flow_base(analysis) + [
        "Voici les étapes repérées dans les parties successives d'un même corpus. Établis la liste unique des étapes "
        "du parcours, dans l'ordre chronologique : réunis celles qui désignent la même étape, mais ne perds aucune "
        "étape. Pour un corpus volumineux, prévois assez d'étapes pour que chacune reste lisible.",
        FLOW_LEVEL_GUIDANCE[analysis.level], _lang(analysis.language), PHASES_SCHEMA])
    analysis.step_notes[2] = f"Réunion des étapes repérées dans les {len(groups)} parties"
    try:
        out = await _cached_call_json(analysis, chain, merge_prompt, listing)
    except (svc.InvalidModelOutput, svc.ProviderUnavailable) as exc:
        logger.warning("Étapes non réunies par le modèle (%s) : liste mise bout à bout", exc)
        out = {}
    phases = _phases_of(out)
    if not phases:  # repli : étapes des parties dans l'ordre, sans les doublons de nom
        seen: set[str] = set()
        for p in (p for ps in partial for p in ps):
            if p["title"].lower() not in seen:
                seen.add(p["title"].lower())
                phases.append(p)
    return svc._s(out.get("title")) or title, phases


async def place_in_phases(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item],
                          phases: list[dict[str, Any]]) -> list[Item]:
    """Range chaque élément dans son étape (phases[i]["items"], dans l'ordre du corpus) ; renvoie les éléments restés hors étape."""
    analysis.step_notes[2] = f"{len(phases)} étapes · rangement de {len(items)} éléments extraits"
    mapping = await _assign(analysis, chain, items, phases, phases=True)
    leftovers = []
    for it in items:
        try:
            num = int(mapping.get(it.id, 0))
        except (TypeError, ValueError):
            num = 0
        if 1 <= num <= len(phases):
            phases[num - 1]["items"].append(it)
        else:
            leftovers.append(it)
    analysis.progress = 59
    return leftovers


def _phase_prompt(analysis: svc.Analysis) -> str:
    return "\n\n".join(_flow_base(analysis) + [
        "Rédige une seule étape du parcours à partir des éléments extraits des documents et des passages d'origine "
        "fournis. Couvre tous les éléments listés : chaque action, point de contact, ressenti, friction et attente "
        "doit se retrouver dans l'étape. Reprends tels quels les chiffres, durées, dates et noms. Vérifie le sens et "
        "les citations dans les passages d'origine quand ils sont fournis.",
        FLOW_LEVEL_GUIDANCE[analysis.level],
        SENTIMENT_RULE + " « priorities » : frictions prioritaires de cette étape, [] si aucune friction n'est signalée.",
        _lang(analysis.language),
        "Schéma JSON attendu :\n" + PHASE_SCHEMA,
    ])


def _merge_phase(phase: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Réunit les parties d'une étape rédigée en plusieurs fois, sans rien retirer."""
    out: dict[str, Any] = {"name": phase["title"], "mood": "", "sentiment": None, "does": "",
                           **{f: [] for f in PHASE_LISTS}, "priorities": []}
    does = []
    for p in parts:
        ph = p.get("phase") if isinstance(p.get("phase"), dict) else {}
        if not out["mood"] and svc._s(ph.get("mood")):
            out["mood"], out["sentiment"] = svc._s(ph.get("mood")), ph.get("sentiment")
        does.append(svc._s(ph.get("does")))
        for f in PHASE_LISTS:
            out[f] += svc._str_list(ph.get(f))
        out["priorities"] += [dict(x, phase=phase["title"]) for x in p.get("priorities") or [] if isinstance(x, dict)]
    out["does"] = " ".join(dict.fromkeys(d for d in does if d))
    for f in PHASE_LISTS:
        out[f] = list(dict.fromkeys(out[f]))
    return out


async def _condense_phase(analysis: svc.Analysis, chain: list[svc.ModelSpec], merged: dict[str, Any]) -> None:
    """Étape rédigée en plusieurs parties : un seul « does », listes dédoublonnées. Modifie merged."""
    user = (f"Étape : {merged['name']}\n\nCe que fait l'utilisateur (parties) :\n{merged['does']}\n\n"
            + "\n\n".join(f"{f} :\n" + "\n".join(f"- {x}" for x in merged[f]) for f in PHASE_LISTS if merged[f]))
    prompt = "\n\n".join([
        svc.BASE_RULES,
        "Voici une étape d'un parcours utilisateur rédigée en plusieurs parties. Réunis-les en une seule description : "
        "« does » en 1 à 3 phrases ; dans chaque liste, regroupe les éléments qui disent la même chose, sans perdre "
        "aucune information distincte ni aucun chiffre. N'ajoute rien qui ne figure dans les parties fournies.",
        SENTIMENT_RULE, _lang(analysis.language), "Schéma JSON attendu :\n" + PHASE_SCHEMA.split(',\n  "priorities"')[0] + "\n}",
    ])
    try:
        out = await _cached_call_json(analysis, chain, prompt, user)
    except (svc.InvalidModelOutput, svc.ProviderUnavailable, svc.AnalysisError) as exc:
        logger.warning("Étape « %s » non resserrée (%s)", merged["name"], exc)
        return
    ph = out.get("phase") if isinstance(out.get("phase"), dict) else {}
    if svc._s(ph.get("does")):
        merged["does"] = svc._s(ph.get("does"))
    for f in PHASE_LISTS:
        if svc._str_list(ph.get(f)):  # liste vide ou absente : on garde la version complète
            merged[f] = svc._str_list(ph.get(f))


async def write_phases(analysis: svc.Analysis, chain: list[svc.ModelSpec],
                       phases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[Item]]:
    """Rédige chaque étape ; renvoie (étapes rédigées, éléments que le modèle n'a pas pu rédiger)."""
    budget = int(budget_chars(chain[0], analysis.context_cap) * PASSAGE_SHARE)
    sem = asyncio.Semaphore(svc.concurrency(chain[0]))
    prompt = _phase_prompt(analysis)
    outline = "\n".join(f"{k}. {p['title']}" for k, p in enumerate(phases, start=1))
    unwritten: list[Item] = []
    done = 0
    started = time.monotonic()

    async def write_part(k: int, phase: dict[str, Any], part: list[Item], label: str) -> list[dict[str, Any]]:
        lines = "\n".join(i.line() for i in part)
        passages = _passages(analysis, part, budget - len(lines) - len(outline))
        user = (f"Étapes du parcours :\n{outline}\n\nÉtape à rédiger : {k}. {phase['title']} — {phase['scope']}{label}"
                f"\n\nÉléments extraits :\n{lines}" + (f"\n\nPassages d'origine :\n{passages}" if passages else ""))
        try:
            async with sem:
                return [await _cached_call_json(analysis, chain, prompt, user)]
        except svc.AnalysisError as exc:
            if isinstance(exc, svc.SettingsProblem) or (isinstance(exc, svc.ProviderUnavailable) and not exc.timed_out):
                raise  # réglage à corriger ou fournisseur indisponible : inutile de redécouper
            if len(part) > 1:  # délai dépassé, requête refusée ou réponse illisible : on redécoupe
                half = len(part) // 2
                return await write_part(k, phase, part[:half], label) + await write_part(k, phase, part[half:], label)
            unwritten.append(part[0])  # dernier recours : repris tel qu'extrait, rien n'est perdu
            return []

    async def write_one(k: int, phase: dict[str, Any]) -> dict[str, Any]:
        nonlocal done
        lines = [i.line() for i in phase["items"]]
        groups = _group(lines, budget, WRITE_MAX_ITEMS) if lines else []
        results = await asyncio.gather(*(
            write_part(k, phase, [phase["items"][i] for i in g], f" (partie {n + 1}/{len(groups)})" if len(groups) > 1 else "")
            for n, g in enumerate(groups)
        ))
        parts = [p for r in results for p in r]
        merged = _merge_phase(phase, parts)
        if len(parts) > 1:
            await _condense_phase(analysis, chain, merged)
        if not merged["does"]:
            merged["does"] = phase["scope"]
        done += 1
        per_phase = (time.monotonic() - started) / done
        analysis.eta_at = time.time() + per_phase * (len(phases) - done + 1)  # + titre, « En bref » et graphe
        analysis.progress = 60 + 28 * done / len(phases)
        analysis.step_notes[3] = f"Rédaction étape par étape depuis les passages d'origine ({done}/{len(phases)})"
        return merged

    analysis.step_notes[3] = f"Rédaction étape par étape depuis les passages d'origine (0/{len(phases)})"
    written = await asyncio.gather(*(write_one(k, p) for k, p in enumerate(phases, start=1)))
    return list(written), unwritten


async def flow_head(analysis: svc.Analysis, chain: list[svc.ModelSpec], title: str, written: list[dict[str, Any]],
                    items: list[Item]) -> dict[str, Any]:
    """Titre, « En bref » et graphe du parcours, à partir des étapes rédigées et des transitions et sorties relevées."""
    budget = budget_chars(chain[0], analysis.context_cap)
    digest = "\n".join(
        f"{k}. {p['name']} : {p['does']}"
        + (f" | Points de contact : {', '.join(p['touchpoints'])}" if p["touchpoints"] else "")
        + (f" | Frictions : {' ; '.join(p['frictions'])}" if p["frictions"] else "")
        for k, p in enumerate(written, start=1)
    )[: int(budget * 0.5)]
    moves, size = [], len(digest)
    for it in items:
        if it.kind in {"transition", "sortie"}:
            line = f"- [{it.kind}] {it.text[:OUTLINE_LINE_CHARS]}"
            if size + len(line) > budget * 0.8:
                break
            moves.append(line)
            size += len(line) + 1
    prompt = "\n\n".join(_flow_base(analysis) + [
        "Voici les étapes d'un parcours utilisateur, déjà rédigées à partir d'un corpus volumineux, puis les "
        "transitions et points de sortie relevés dans le corpus. Donne le titre du parcours, « En bref » (2 à 3 "
        "phrases, sans rien ajouter qui n'y figure) et le graphe du parcours.",
        FLOW_GRAPH_RULES[analysis.level], _lang(analysis.language), "Schéma JSON attendu :\n" + FLOW_HEAD_SCHEMA,
    ])
    user = "Étapes :\n" + digest + ("\n\nTransitions et sorties relevées :\n" + "\n".join(moves) if moves else "")
    analysis.step_notes[3] = f"{analysis.step_notes.get(3, '')} · titre, « En bref » et graphe du parcours".lstrip(" ·")
    try:
        head = await _cached_call_json(analysis, chain, prompt, user)
    except (svc.InvalidModelOutput, svc.ProviderUnavailable) as exc:
        # Les étapes rédigées ne sont pas perdues : graphe linéaire des étapes, à défaut de mieux.
        logger.warning("Titre, « En bref » et graphe du parcours non rédigés (%s)", exc)
        head = {}
    flow = head.get("flow")
    if not (isinstance(flow, dict) and flow.get("nodes")):
        flow = {"nodes": [{"id": f"p{k}", "label": p["name"], "type": "step", "friction": bool(p["frictions"])}
                          for k, p in enumerate(written, start=1)], "edges": []}
    return {"title": svc._s(head.get("title")) or title, "brief": svc._s(head.get("brief")), "flow": flow}


async def _flow_in_one_go(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item]) -> dict[str, Any]:
    """Liste des éléments assez courte : plan des étapes puis parcours complet, en deux appels."""
    corpus = ("Éléments extraits de l'ensemble du corpus (chacun avec son document et son repère d'origine) :\n"
              + "\n".join(i.line() for i in items))
    svc._enter(analysis, 2)
    outline = await svc._with_creep(
        analysis, 60, _cached_call_json(analysis, chain, svc._outline_prompt("flow", analysis.level, analysis.language), corpus))
    names = [svc._s(p.get("name")) for p in outline.get("phases") or [] if isinstance(p, dict) and svc._s(p.get("name"))]
    analysis.preview += names
    svc._enter(analysis, 3)
    user = ("Étapes identifiées lors de la première passe (traite-les toutes ; ajoutes-en si le corpus l'exige) :\n"
            + "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names)) + "\n\n" + corpus)
    data = await svc._with_creep(
        analysis, 90,
        _cached_call_json(analysis, chain, svc._full_prompt("flow", analysis.level, analysis.language, analysis.cite), user))
    data.setdefault("title", svc._s(outline.get("title")))
    return data


async def _flow_by_phase(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item]) -> tuple[dict[str, Any], list[Item]]:
    """Très gros corpus : parcours reconstitué étape par étape ; renvoie (parcours, éléments hors étape ou non rédigés)."""
    svc._enter(analysis, 2)
    title, phases = await flow_outline(analysis, chain, items)
    if not phases:
        raise svc.AnalysisError("Le modèle n'a reconstitué aucune étape de parcours.")
    analysis.preview += [p["title"] for p in phases]
    leftovers = await place_in_phases(analysis, chain, items, phases)
    svc._enter(analysis, 3)
    written, unwritten = await write_phases(analysis, chain, phases)
    head = await flow_head(analysis, chain, title, written, items)
    priorities = [p for ph in written for p in ph.pop("priorities")]
    return {**head, "phases": written, "priorities": priorities}, leftovers + unwritten


async def run_flow(analysis: svc.Analysis, chain: list[svc.ModelSpec], checker: svc.QuoteChecker) -> dict[str, Any]:
    svc._enter(analysis, 1)
    items, _, n_batches = await extract(analysis, chain, checker)
    budget = budget_chars(chain[0], analysis.context_cap)
    if len("\n".join(i.line() for i in items)) <= budget * FLOW_FIT_SHARE:
        data, apart = await _flow_in_one_go(analysis, chain, items), []
    else:
        analysis.step_notes[1] = f"{n_batches} lots extraits · {len(items)} éléments : parcours rédigé étape par étape"
        data, apart = await _flow_by_phase(analysis, chain, items)
    svc._enter(analysis, 4)
    # Rien n'est perdu en silence : éléments hors étape, non rédigés, ou dont une information précise manque.
    kept = {it.id for it in apart}
    missing = apart + [it for it in uncovered([i for i in items if i.id not in kept], data)]
    data["extra"] = [{"text": _as_point(it)["lead"], "document": it.document, "location": it.location} for it in missing]
    data["coverage"] = {"batches": n_batches, "items": len(items), "unassigned": 0, "recovered": len(missing)}
    return data
