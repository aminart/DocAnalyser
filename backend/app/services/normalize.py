"""Normalisation des réponses du modèle : thèmes, parcours, graphe de flux, vérification des verbatims."""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Literal

from app.services.errors import AnalysisError
from app.services.report_markdown import to_mermaid


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
