"""Rendu de la synthèse en Markdown (export) et du graphe de flux en Mermaid."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services.models import all_models
from app.services.prompts import LEVEL_LABELS, MODE_LABELS

if TYPE_CHECKING:
    from app.services.analysis_service import Analysis


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


# Début de l'annexe détaillée : l'export « sans annexe » coupe le texte ici (même s'il a été modifié à la main).
ANNEX_MARK = "<!-- annexe -->"
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÝÉ«\"])")


def _paragraphs(text: str, max_sentences: int = 3) -> list[str]:
    """Coupe un long résumé en paragraphes de quelques phrases, plus faciles à lire qu'un seul pavé."""
    sentences = _SENTENCE_END.split(text.strip()) if text else []
    if len(sentences) <= max_sentences:
        return [text.strip()] if text and text.strip() else []
    out = []
    for k in range(0, len(sentences), max_sentences):
        out += [" ".join(sentences[k:k + max_sentences]), ""]
    return out[:-1]


def without_annex(markdown: str) -> str:
    """Texte exporté sans l'annexe détaillée (la mention de fin est gardée)."""
    if ANNEX_MARK not in markdown:
        return markdown
    head, _, tail = markdown.partition(ANNEX_MARK)
    head = re.sub(r"^_Détail complet : .*_\n\n?", "", head, flags=re.M)  # renvoi vers l'annexe absente
    end = tail.rfind("_Synthèse générée")
    return head.rstrip() + "\n\n" + (tail[end:] if end >= 0 else "")


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
            lines += [f"## {i}. {t['title']}", ""]
            lines += [*_paragraphs(t["summary"]), ""]
            if t.get("note"):
                lines += [f"_{t['note']}_", ""]
            for p in t["points"]:
                # Un point aéré : l'idée en gras, son explication dessous, les sources à part.
                src = "; ".join(f"{s['document']} {s['location']}".strip() for s in p["sources"])
                lines.append(f"- **{p['lead']}**" + ("  " if p["body"] or src else ""))
                if p["body"]:
                    lines.append(f"  {p['body']}" + ("  " if src else ""))
                if src:
                    lines.append(f"  _Sources : {src}_")
            lines.append("")
            if t["quote"]:
                lines += [f"> « {t['quote']} » — {t['quote_by']}{QUOTE_NOTES.get(t['quote_check'], '')}", ""]
            if t["nuance"]:
                lines += [f"**Nuance / point de divergence :** {t['nuance']}", ""]
            if t.get("details"):
                n = len(t["details"])
                lines += [f"_Détail complet : {n} élément{'s' if n > 1 else ''} extrait{'s' if n > 1 else ''} "
                          "des documents, en annexe._", ""]
        if r["actions"]:
            lines += ["## Pistes d'action", ""]
            for i, a in enumerate(r["actions"], start=1):
                tag = f" _(Thème {a['theme']})_" if a.get("theme") else ""
                lines.append(f"{i}. **{a['title']}** {a['body']}{tag}")
            lines.append("")
        annex = [(i, t) for i, t in enumerate(r["themes"], start=1) if t.get("details")]
        if annex:
            lines += [ANNEX_MARK, "## Annexe — détail des éléments extraits", "",
                      "_Tous les éléments relevés dans les documents pour les thèmes résumés ci-dessus, tels "
                      "qu'extraits et avec leur source._", ""]
            for i, t in annex:
                lines += [f"### {i}. {t['title']}", ""]
                for d in t["details"]:
                    where = " ".join(x for x in (d["document"], d["location"]) if x)
                    lines.append(f"- {d['text']}" + (f" _({where})_" if where else ""))
                lines.append("")
    else:
        lines += ["## Carte du parcours", ""]
        phases = r.get("phases", [])
        if not any(ph["frictions"] or ph["opportunities"] or ph["mood"] for ph in phases) and not r.get("priorities"):
            lines += ["_Les documents ne signalent ni friction ni ressenti : seul le parcours est restitué._", ""]
        for i, ph in enumerate(phases, start=1):
            mood = f" ({ph['mood']})" if ph["mood"] else ""
            lines += [f"### Étape {i} — {ph['name']}{mood}", "", ph["does"], ""]
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
