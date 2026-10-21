"""Retrouve le passage d'origine d'une source citée (document + repère), pour la vérification en un clic.

Chaque document est indexé ligne par ligne avec son repère : L12 (texte, CSV, Excel), §4 (Word),
00:01:10 (sous-titres), ou « Page 3 » / « Slide 2 » (PDF, PowerPoint, lignes numérotées dans la page).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.parser_service import AnchoredTextBlock

CONTEXT = 5  # lignes de contexte affichées autour du passage
MAX_LINES = 40

_LINE_REF = re.compile(r"^(L\d+|§\d+|\d{2}:\d{2}:\d{2}): ?(.*)$")
_WORD = re.compile(r"\w+")


class _Doc(Protocol):
    id: str
    blocks: list[AnchoredTextBlock]


@dataclass
class Line:
    ref: str  # repère affiché : « L12 », « §4 », « p. 3 · l. 5 »
    anchor: str  # repère d'appartenance : « L12 », « Page 3 »…
    text: str


_INDEX: dict[str, list[Line]] = {}


def doc_lines(doc: _Doc) -> list[Line]:
    if doc.id not in _INDEX:
        lines: list[Line] = []
        for block in doc.blocks:
            k = 0
            for raw in block.content.splitlines():
                if not raw.strip() or raw.startswith("(en-tête) "):
                    continue
                m = _LINE_REF.match(raw)
                if m:
                    lines.append(Line(m.group(1), m.group(1), m.group(2)))
                else:  # page PDF ou slide : numérotation des lignes dans la page
                    k += 1
                    short = block.location.replace("Page ", "p. ").replace("Slide ", "slide ")
                    lines.append(Line(f"{short} · l. {k}", block.location, raw))
        _INDEX[doc.id] = lines
    return _INDEX[doc.id]


def resolve(doc: _Doc, location: str) -> list[int]:
    """Indices des lignes désignées par un repère, quelle que soit sa formulation."""
    lines = doc_lines(doc)
    loc = location.strip()
    if not loc:
        return []

    m = re.search(r"(?:p\.?|page)\s*(\d+)", loc, re.I)
    if m:
        return [i for i, ln in enumerate(lines) if ln.anchor == f"Page {m.group(1)}"]
    m = re.search(r"slide\s*(\d+)", loc, re.I)
    if m:
        return [i for i, ln in enumerate(lines) if ln.anchor == f"Slide {m.group(1)}"]
    m = re.search(r"(\d{2}:\d{2}:\d{2})", loc)
    if m:
        ts = m.group(1)
        stamps = [i for i, ln in enumerate(lines) if re.fullmatch(r"\d{2}:\d{2}:\d{2}", ln.anchor)]
        before = [i for i in stamps if lines[i].anchor <= ts]
        return [before[-1]] if before else []

    prefix = "§" if "§" in loc or re.search(r"paragraphe", loc, re.I) else "L"
    nums = [int(n) for n in re.findall(r"\d+", loc)]
    if not nums:
        return []
    start, end = nums[0], (nums[1] if len(nums) > 1 and nums[1] >= nums[0] else nums[0])
    wanted = {f"{prefix}{n}" for n in range(start, min(end, start + MAX_LINES) + 1)}
    return [i for i, ln in enumerate(lines) if ln.anchor in wanted]


def location_exists(doc: _Doc, location: str) -> bool:
    return bool(resolve(doc, location))


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 4 or w.isdigit()}


def _score(line: str, target: set[str]) -> int:
    return len(_words(line) & target)


def passage(doc: _Doc, location: str, text: str = "") -> dict[str, Any]:
    """Passage d'origine avec contexte ; les lignes concernées sont marquées « hit »."""
    lines = doc_lines(doc)
    target = _words(text)
    idx = resolve(doc, location)
    found = bool(idx)
    nearest = False
    score = 0

    if idx:
        hits = idx
        if len(idx) > 4 and target:  # page ou slide entière : on surligne les lignes qui portent le propos
            scored = sorted(idx, key=lambda i: _score(lines[i].text, target), reverse=True)
            best = _score(lines[scored[0]].text, target)
            hits = sorted(i for i in scored[:3] if best and _score(lines[i].text, target) >= max(2, best // 2)) or idx
    elif target:  # repère introuvable : passage le plus proche du texte du point
        best_i = max(range(len(lines)), key=lambda i: _score(lines[i].text, target), default=None)
        if best_i is None or _score(lines[best_i].text, target) < 2:
            return {"found": False, "nearest": False, "score": 0, "lines": []}
        hits, nearest = [best_i], True
        score = _score(lines[best_i].text, target)
    else:
        return {"found": False, "nearest": False, "score": 0, "lines": []}

    lo = max(0, min(hits) - CONTEXT)
    hi = min(len(lines), max(hits) + CONTEXT + 1, lo + MAX_LINES)
    hit_set = set(hits)
    return {
        "found": found,
        "nearest": nearest,
        "score": score if nearest else len(target),
        "lines": [{"ref": lines[i].ref, "text": lines[i].text, "hit": i in hit_set} for i in range(lo, hi)],
    }
