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
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services import analysis_service as svc
from app.services.parser_service import AnchoredTextBlock

EXTRACT_SHARE = 0.5  # part de la fenêtre utilisée par un lot (le reste : consignes et réponse)
PASSAGE_SHARE = 0.55  # part de la fenêtre pour éléments + passages lors de la rédaction d'un thème
MAX_MERGE_ROUNDS = 4

THEME_KINDS = "fait | chiffre | decision | action | friction | attente | desaccord | verbatim"
FLOW_KINDS = THEME_KINDS + " | etape | transition | sortie | ressenti | point_de_contact"

KIND_HINTS = {
    "themes": "",
    "flow": (
        "Pour le parcours, extrais aussi : « etape » (ce que fait l'utilisateur), « transition » (passage d'une "
        "étape à une autre, avec sa condition), « sortie » (abandon, point de rupture), « ressenti » (émotion "
        "exprimée), « point_de_contact » (canal, écran, interlocuteur)."
    ),
}


def budget_chars(spec: svc.ModelSpec) -> int:
    tokens = spec.context_tokens - svc.RESERVED_TOKENS
    if tokens < 4000:
        raise svc.AnalysisError(f"La fenêtre de contexte de {spec.name} est trop petite pour analyser des documents.")
    return int(tokens * svc.CHARS_PER_TOKEN)


def needs_batches(spec: svc.ModelSpec, corpus: str) -> bool:
    return len(corpus) > budget_chars(spec)


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


def _group(texts: list[str], max_chars: int) -> list[list[int]]:
    """Regroupe des textes consécutifs en paquets de max_chars caractères au plus (indices)."""
    groups, current, size = [], [], 0
    for i, t in enumerate(texts):
        if current and size + len(t) > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(i)
        size += len(t) + 1
    if current:
        groups.append(current)
    return groups


async def _gather_limited(coros):
    sem = asyncio.Semaphore(settings.MAX_CONCURRENT_LLM_REQUESTS)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))


# ---------------------------------------------------------------------------
# 1. Extraction
# ---------------------------------------------------------------------------

def _extract_prompt(mode: str, language: str) -> str:
    kinds = FLOW_KINDS if mode == "flow" else THEME_KINDS
    return "\n\n".join([
        svc.BASE_RULES,
        svc.MODE_GUIDANCE[mode],
        "Tu traites une partie d'un corpus trop long pour être lu d'un seul tenant. Extrais de cet extrait TOUS les "
        "éléments utiles à la compréhension du sujet, sans en omettre aucun, y compris en fin d'extrait. Chaque "
        "élément reprend fidèlement le contenu (pas d'interprétation, pas de généralisation) et indique son document "
        "et le repère exact de la ligne d'origine. Les verbatims sont recopiés mot pour mot.",
        KIND_HINTS["flow" if mode == "flow" else "themes"],
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
    groups = _group(segments, int(budget_chars(chain[0]) * EXTRACT_SHARE))
    doc_names = [d.name for d in analysis.documents]
    prompt = _extract_prompt(analysis.mode, analysis.language)
    done = 0

    async def one(idx: list[int]) -> dict[str, Any]:
        nonlocal done
        raw = await svc._call(analysis, chain, prompt, "Extrait du corpus :\n\n" + "\n".join(segments[i] for i in idx))
        done += 1
        analysis.progress = 15 + 15 * done / len(groups)
        analysis.step_notes[1] = f"{len(groups)} lots pour tenir dans la fenêtre du modèle · lot {done}/{len(groups)} extrait"
        return svc._parse_json(raw)

    analysis.step_notes[1] = f"{len(groups)} lots pour tenir dans la fenêtre du modèle"
    results = await _gather_limited([one(g) for g in groups])

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

async def classify(analysis: svc.Analysis, chain: list[svc.ModelSpec], items: list[Item], topics: list[str]) -> tuple[str, list[dict[str, Any]], int]:
    """Retourne (titre, thèmes avec leurs éléments, nombre d'éléments non classés par le modèle)."""
    prompt = "\n\n".join([
        svc.BASE_RULES,
        svc.MODE_GUIDANCE[analysis.mode],
        "Voici les sujets repérés dans les différentes parties d'un même corpus. Établis la liste des grands thèmes "
        "de la synthèse : fusionne les sujets identiques ou très proches, mais ne perds aucun sujet. "
        + svc.COMPLETENESS_RULE,
        svc.LEVEL_GUIDANCE[analysis.level],
        _lang(analysis.language),
        'Schéma JSON attendu :\n{"title": "titre court et explicite de l\'étude", '
        '"themes": [{"title": "intitulé du thème (3 à 6 mots)", "scope": "ce que couvre le thème, en une phrase"}]}',
    ])
    budget = budget_chars(chain[0])
    topic_text = "\n".join(f"- {t}" for t in topics) or "\n".join(i.line() for i in items[:200])
    outline = svc._parse_json(await svc._call(analysis, chain, prompt, topic_text[:budget]))
    themes = [
        {"title": svc._s(t.get("title")), "scope": svc._s(t.get("scope")), "items": []}
        for t in outline.get("themes") or [] if isinstance(t, dict) and svc._s(t.get("title"))
    ]
    if not themes:
        raise svc.AnalysisError("Le modèle n'a identifié aucun thème exploitable.")
    for t in themes:
        analysis.preview.append(t["title"])
    analysis.progress = 40

    # Affectation des éléments par paquets : chaque élément va dans exactement un thème.
    theme_list = "\n".join(f"{i + 1}. {t['title']} — {t['scope']}" for i, t in enumerate(themes))
    assign_prompt = "\n\n".join([
        "Tu répartis des éléments extraits d'un corpus entre des thèmes. Chaque élément va dans le thème qui lui "
        "correspond le mieux ; 0 seulement s'il ne correspond à aucun thème.",
        "Thèmes :\n" + theme_list,
        'Schéma JSON attendu : {"assign": {"identifiant de l\'élément": numéro du thème}}',
    ])
    lines = [i.line() for i in items]
    groups = _group(lines, int(budget * 0.6) - len(theme_list))
    done = 0

    async def one(idx: list[int]) -> dict[str, Any]:
        nonlocal done
        raw = await svc._call(analysis, chain, assign_prompt, "Éléments :\n" + "\n".join(lines[i] for i in idx))
        done += 1
        analysis.progress = 40 + 20 * done / len(groups)
        analysis.step_notes[2] = f"{len(themes)} thèmes · classement des {len(items)} éléments extraits ({done}/{len(groups)})"
        return svc._parse_json(raw).get("assign") or {}

    by_id = {i.id: i for i in items}
    assigned: set[str] = set()
    for mapping in await _gather_limited([one(g) for g in groups]):
        if not isinstance(mapping, dict):
            continue
        for item_id, num in mapping.items():
            try:
                n = int(num)
            except (TypeError, ValueError):
                continue
            if item_id in by_id and item_id not in assigned and 1 <= n <= len(themes):
                themes[n - 1]["items"].append(by_id[item_id])
                assigned.add(item_id)

    leftovers = [i for i in items if i.id not in assigned]
    if leftovers:  # rien n'est perdu en silence
        themes.append({"title": OTHER_POINTS, "scope": OTHER_SCOPE, "items": leftovers})
    themes = [t for t in themes if t["items"]]
    return svc._s(outline.get("title")), themes, len(leftovers)


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


def _theme_prompt(analysis: svc.Analysis) -> str:
    return "\n\n".join([
        svc.BASE_RULES,
        svc.MODE_GUIDANCE[analysis.mode],
        "Rédige un seul thème de la synthèse à partir des éléments extraits des documents et des passages d'origine "
        "fournis. Couvre tous les éléments listés : chacun doit se retrouver dans un point clé. Reprends tels quels "
        "tous les chiffres, durées, montants, pourcentages, dates, lieux et noms qu'ils contiennent : une synthèse "
        "qui perd un chiffre est infidèle. Vérifie le sens et les citations dans les passages d'origine quand ils "
        "sont fournis.",
        svc.LEVEL_GUIDANCE[analysis.level],
        "Indique les sources de chaque point." if analysis.cite else "Laisse « sources » vide ([]) pour chaque point.",
        _lang(analysis.language),
        "Schéma JSON attendu :\n" + THEME_SCHEMA,
    ])


async def write_themes(analysis: svc.Analysis, chain: list[svc.ModelSpec], themes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    budget = int(budget_chars(chain[0]) * PASSAGE_SHARE)
    prompt = _theme_prompt(analysis)
    done = 0

    async def write_part(theme: dict[str, Any], part: list[Item], label: str) -> dict[str, Any]:
        lines = "\n".join(i.line() for i in part)
        passages = _passages(analysis, part, budget - len(lines))
        user = (f"Thème : {theme['title']} — {theme['scope']}{label}\n\nÉléments extraits :\n{lines}"
                + (f"\n\nPassages d'origine :\n{passages}" if passages else ""))
        return svc._parse_json(await svc._call(analysis, chain, prompt, user))

    async def write_one(theme: dict[str, Any]) -> dict[str, Any]:
        nonlocal done
        lines = [i.line() for i in theme["items"]]
        groups = _group(lines, budget)  # un thème très fourni est rédigé en plusieurs parties
        parts = await asyncio.gather(*(
            write_part(theme, [theme["items"][i] for i in g], f" (partie {k + 1}/{len(groups)})" if len(groups) > 1 else "")
            for k, g in enumerate(groups)
        ))
        merged = _merge_parts(theme, parts)
        done += 1
        analysis.progress = 60 + 30 * done / len(themes)
        analysis.step_notes[3] = f"Rédaction thème par thème depuis les passages d'origine ({done}/{len(themes)})"
        return merged

    analysis.step_notes[3] = f"Rédaction thème par thème depuis les passages d'origine (0/{len(themes)})"
    return await _gather_limited([write_one(t) for t in themes])


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


def _key_facts(text: str) -> set[str]:
    """Informations précises d'un élément : nombres et noms propres (hors début de phrase)."""
    numbers = {n.replace(".", ",") for n in _NUMBER.findall(text)}
    names = {m.lower() for m in _PROPER.findall(text)}
    return numbers | names


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
        return re.search(rf"(?<![\d,]){re.escape(fact)}(?![\d]|,\d)", blob) is not None
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
    head = svc._parse_json(await svc._call(analysis, chain, prompt, digest))
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
    written = await write_themes(analysis, chain, themes)
    svc._enter(analysis, 4)
    data = await assemble(analysis, chain, title, written)
    recovered = add_uncovered_points(data, items)
    data["coverage"] = {"batches": n_batches, "items": len(items), "unassigned": unassigned, "recovered": recovered}
    return data


# ---------------------------------------------------------------------------
# Mode Flux
# ---------------------------------------------------------------------------

MERGE_PROMPT = (
    "Tu reçois des éléments extraits de différentes parties d'un même corpus sur un parcours utilisateur. "
    "Fusionne uniquement les doublons (même étape, même friction, même transition dits plusieurs fois) en un seul "
    "élément qui garde tous les repères de source. Ne supprime aucun élément unique, n'ajoute rien, et recopie "
    "les verbatims mot pour mot.\n\n"
    'Schéma JSON attendu : {"items": [{"kind": "…", "text": "…", "speaker": "…", "document": "…", "location": "…"}]}'
)


async def run_flow(analysis: svc.Analysis, chain: list[svc.ModelSpec], checker: svc.QuoteChecker) -> dict[str, Any]:
    svc._enter(analysis, 1)
    items, _, n_batches = await extract(analysis, chain, checker)
    budget = budget_chars(chain[0])
    doc_names = [d.name for d in analysis.documents]

    # Dédoublonnage par paquets tant que la liste ne tient pas dans la fenêtre.
    rounds = 0
    while len("\n".join(i.line() for i in items)) > budget * 0.7:
        rounds += 1
        if rounds > MAX_MERGE_ROUNDS:
            raise svc.AnalysisError("Le parcours décrit est trop volumineux pour ce modèle : choisissez un modèle à plus grande fenêtre.")
        lines = [i.line() for i in items]
        groups = _group(lines, int(budget * EXTRACT_SHARE))
        analysis.step_notes[1] = f"{n_batches} lots extraits · fusion des doublons (passe {rounds})"
        results = await _gather_limited([
            svc._call(analysis, chain, MERGE_PROMPT, "\n".join(lines[i] for i in g)) for g in groups
        ])
        merged: list[Item] = []
        for raw_out in results:
            for raw in svc._parse_json(raw_out).get("items") or []:
                if isinstance(raw, dict) and svc._s(raw.get("text")):
                    kind = svc._s(raw.get("kind")) or "fait"
                    text = svc._s(raw.get("text"))
                    merged.append(Item(f"e{len(merged) + 1}", kind, text,
                                       svc._match_doc(svc._s(raw.get("document")), doc_names) or "",
                                       svc._s(raw.get("location")), svc._s(raw.get("speaker")),
                                       checker.check(text) if kind == "verbatim" else ""))
        if len(merged) >= len(items):  # plus rien à fusionner
            items = merged
            if len("\n".join(i.line() for i in items)) > budget * 0.7:
                raise svc.AnalysisError("Le parcours décrit est trop volumineux pour ce modèle : choisissez un modèle à plus grande fenêtre.")
            break
        items = merged

    corpus = ("Éléments extraits de l'ensemble du corpus (chacun avec son document et son repère d'origine) :\n"
              + "\n".join(i.line() for i in items))
    svc._enter(analysis, 2)
    outline = svc._parse_json(await svc._with_creep(
        analysis, 60, svc._call(analysis, chain, svc._outline_prompt("flow", analysis.level, analysis.language), corpus)))
    names = [svc._s(p.get("name")) for p in outline.get("phases") or [] if isinstance(p, dict) and svc._s(p.get("name"))]
    analysis.preview += names
    svc._enter(analysis, 3)
    user = ("Étapes identifiées lors de la première passe (traite-les toutes ; ajoutes-en si le corpus l'exige) :\n"
            + "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names)) + "\n\n" + corpus)
    data = svc._parse_json(await svc._with_creep(
        analysis, 90,
        svc._call(analysis, chain, svc._full_prompt("flow", analysis.level, analysis.language, analysis.cite), user)))
    svc._enter(analysis, 4)
    data.setdefault("title", svc._s(outline.get("title")))
    missing = uncovered(items, data)
    data["extra"] = [{"text": _as_point(it)["lead"], "document": it.document, "location": it.location} for it in missing]
    data["coverage"] = {"batches": n_batches, "items": len(items), "unassigned": 0, "recovered": len(missing)}
    return data
