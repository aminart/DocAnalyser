"""Projets Mapline (.mapline, et .missionmap des versions d'avant 0.10) : fichiers JSON de l'outil Mapline.

Un projet réunit des documents : cartes de parcours (phases, étapes, personas, activités), flux, fiches persona et
plans de site. Chacun devient un texte structuré, dans l'ordre de lecture de l'outil : étape par étape pour une
carte, de haut en bas pour un flux, par niveau pour un plan de site. Les images (storyboard, photos) ne sont pas lues.
"""
from __future__ import annotations

import json
from typing import Any

STATUS = {"existing": "existant", "new": "à créer", "redo": "à refaire"}
EXTRAS = {"modal": "modale", "error": "message d'erreur", "success": "message de succès", "info": "message d'information"}
NODE_KINDS = {"start": "Début", "end": "Fin", "choice": "Choix", "activity": "Activité"}


class MaplineError(ValueError):
    pass


def _obj(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _s(v: Any) -> str:
    return " ".join(str(v).split()) if isinstance(v, (str, int, float)) else ""


def _card(act: dict[str, Any]) -> str:
    """Texte d'une carte : texte, nature, étiquettes et commentaire."""
    text = _s(act.get("text"))
    if act.get("kind") == "choice":
        text = f"(choix) {text}"
    tags = [t for t in (_s(t) for t in _list(act.get("tags"))) if t]
    if tags:
        text += f" [étiquettes : {', '.join(tags)}]"
    note = _s(act.get("note"))
    if note:
        text += f" (commentaire{' traité' if act.get('noteResolved') else ''} : {note})"
    return text


def _alternatives(activities: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """La carte d'une case puis ses alternatives (clés « clé:b », « clé:b2 »…), dans l'ordre."""
    cards = []
    if isinstance(activities.get(key), dict):
        cards.append(activities[key])
    n = 1
    while isinstance(activities.get(f"{key}:b{n if n > 1 else ''}"), dict):
        cards.append(activities[f"{key}:b{n if n > 1 else ''}"])
        n += 1
    return cards


def _map_lines(name: str, m: dict[str, Any], personas_by_id: dict[str, str]) -> list[str]:
    out = [f"## Carte de parcours : {name}"]
    if (objective := _s(m.get("objective"))):
        out.append(f"Objectif : {objective}")
    personas = [_obj(p) for p in _list(m.get("personas"))]
    if personas:
        out.append("Personas : " + "; ".join(
            f"{_s(p.get('name')) or 'sans nom'}" + (f" ({_s(p.get('role'))})" if _s(p.get("role")) else "") for p in personas
        ))
    steps = [_obj(s) for s in _list(m.get("steps"))]
    phase_of: list[str] = []
    for ph in _list(m.get("phases")):
        ph = _obj(ph)
        span = ph.get("span") if isinstance(ph.get("span"), int) and ph.get("span") > 0 else 1
        phase_of += [_s(ph.get("title"))] * span
    activities = _obj(m.get("activities"))
    scenes = _obj(m.get("scenes"))
    rows = [_obj(r) for r in _list(m.get("textRows"))]
    if not rows and isinstance(m.get("infos"), dict):  # fichiers d'avant Mapline 1.2 : une seule ligne de texte
        rows = [{"title": m.get("infoTitle") or "Informations", "cells": m.get("infos")}]
    act_text: dict[str, str] = {}
    current_phase = None
    for i, step in enumerate(steps):
        phase = phase_of[i] if i < len(phase_of) else ""
        if phase and phase != current_phase:
            out.append(f"## Phase : {phase}")
        current_phase = phase
        out.append(f"### Étape {i + 1} : {_s(step.get('title')) or 'sans titre'}")
        sid = str(step.get("id", ""))
        slots = [str(x) for x in _list(step.get("slots"))] or [f"{sid}-0"]
        for p in personas:
            who = _s(p.get("name")) or "sans nom"
            for slot in slots:
                for k, act in enumerate(_alternatives(activities, f"{p.get('id')}:{slot}")):
                    text = _card(act)
                    if not text:
                        continue
                    act_text[str(act.get("id", ""))] = _s(act.get("text"))
                    joiner = f"{_s(act.get('joiner')) or 'ou'} : " if k else ""
                    out.append(f"- {who} : {joiner}{text}")
        scene = _obj(scenes.get(sid))
        if (story := _s(scene.get("text"))):
            out.append(f"Storyboard : {story}")
        for r in rows:
            cell = _s(_obj(r.get("cells")).get(sid))
            if cell:
                out.append(f"{_s(r.get('title')) or 'Notes'} : {cell}")
    for link in _list(m.get("links")):
        link = _obj(link)
        a, b = act_text.get(str(link.get("from"))), act_text.get(str(link.get("to")))
        if a and b:
            label = _s(link.get("label"))
            out.append(f"Lien : {a} → {b}" + (f" ({label})" if label else ""))
    return out


def _flow_lines(name: str, f: dict[str, Any], personas_by_id: dict[str, str]) -> list[str]:
    out = [f"## Flux : {name}"]
    if (brief := _s(f.get("brief"))):
        out.append(f"{_s(f.get('briefTitle')) or 'Objectifs'} : {brief}")
    if (main := personas_by_id.get(str(f.get("personaId")))):
        out.append(f"Persona principal : {main}")
    nodes = sorted((_obj(n) for n in _list(f.get("nodes"))),
                   key=lambda n: (n.get("row", 0) if isinstance(n.get("row"), (int, float)) else 0,
                                  n.get("col", 0) if isinstance(n.get("col"), (int, float)) else 0))
    text_of: dict[str, str] = {}
    for n in nodes:
        kind = NODE_KINDS.get(str(n.get("kind")), "Activité")
        text = _card(n) if n.get("kind") != "choice" else _card({**n, "kind": None})
        text_of[str(n.get("id"))] = _s(n.get("text")) or kind
        ids = [str(x) for x in _list(n.get("personaIds"))] or ([str(n["personaId"])] if n.get("personaId") else [])
        who = ", ".join(p for p in (personas_by_id.get(i, "") for i in ids) if p)
        if text or kind in ("Début", "Fin"):
            out.append(f"- {kind} : {text}" + (f" ({who})" if who else ""))
    for link in _list(f.get("links")):
        link = _obj(link)
        a, b = text_of.get(str(link.get("from"))), text_of.get(str(link.get("to")))
        if a and b:
            label = _s(link.get("label"))
            out.append(f"Enchaînement : {a} → {b}" + (f" ({label})" if label else ""))
    return out


def _sheet_lines(s: dict[str, Any]) -> list[str]:
    name, role = _s(s.get("name")) or "sans nom", _s(s.get("role"))
    out = [f"## Fiche persona : {name}" + (f" ({role})" if role else "")]
    for fld in _list(s.get("fields")):
        fld = _obj(fld)
        if _s(fld.get("value")):
            out.append(f"{_s(fld.get('label')) or 'Information'} : {_s(fld.get('value'))}")
    if (quote := _s(s.get("quote"))):
        out.append(f"Citation : « {quote} »")
    tags = [t for t in (_s(t) for t in _list(s.get("tags"))) if t]
    if tags:
        out.append(f"Étiquettes : {', '.join(tags)}")
    for blk in _list(s.get("blocks")):
        blk = _obj(blk)
        title = _s(blk.get("title")) or "Bloc"
        if blk.get("view") == "text":
            if (text := _s(blk.get("text"))):
                out.append(f"{title} : {text}")
            continue
        for item in _list(blk.get("items")):
            item = _obj(item)
            text = _s(item.get("text"))
            if not text:
                continue
            level = item.get("level")
            if blk.get("view") == "gauges" and isinstance(level, (int, float)):
                text += f" ({round(level)} %)"
            out.append(f"{title} : {text}")
    return out


def _screen_lines(screen: dict[str, Any], path: list[str], out: list[str]) -> None:
    name = _s(screen.get("name")) or "écran sans nom"
    here = path + [name]
    status = STATUS.get(str(screen.get("status")), "")
    extras = [f"{EXTRAS.get(str(_obj(e).get('kind')), 'élément')} « {_s(_obj(e).get('name'))} »"
              for e in _list(screen.get("extras")) if _s(_obj(e).get("name"))]
    line = f"- {' › '.join(here)}" + (f" ({status})" if status else "")
    if extras:
        line += f" ; avec : {', '.join(extras)}"
    out.append(line)
    for child in _list(screen.get("children")):
        _screen_lines(_obj(child), here, out)


def _sitemap_lines(name: str, sm: dict[str, Any]) -> list[str]:
    out = [f"## Plan du site : {name}"]
    for root in _list(sm.get("roots")):
        _screen_lines(_obj(root), [], out)
    globals_ = [_s(_obj(g).get("name")) for g in _list(sm.get("globals")) if _s(_obj(g).get("name"))]
    if globals_:
        out.append(f"Écrans accessibles partout : {', '.join(globals_)}")
    return out


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


def mapline_lines(source: str) -> tuple[list[str], str]:
    """Lignes de texte d'un projet Mapline et son résumé (« 2 cartes, 1 flux, 1 persona »)."""
    try:
        raw = json.loads(source)
    except json.JSONDecodeError as exc:
        raise MaplineError("ce fichier Mapline n'est pas un JSON valide") from exc
    if not isinstance(raw, dict):
        raise MaplineError("ce fichier n'est pas un projet Mapline")
    if raw.get("version") in (None, 1):  # avant Mapline 0.10 : le fichier est la carte elle-même
        docs = [{"kind": "mission-map", "name": "", "map": raw}]
    else:
        docs = [_obj(d) for d in _list(raw.get("docs"))]
    if not docs:
        raise MaplineError("ce projet Mapline ne contient aucun document")

    lines: list[str] = []
    if (title := _s(raw.get("title"))):
        lines.append(f"# Projet Mapline : {title}")
    # Les personas des cartes nomment ceux des cartes de flux.
    personas_by_id = {
        str(_obj(p).get("id")): _s(_obj(p).get("name"))
        for d in docs if d.get("kind") == "mission-map" for p in _list(_obj(d.get("map")).get("personas"))
    }
    counts = {"mission-map": 0, "flow": 0, "persona": 0, "sitemap": 0}
    for doc in docs:
        kind = doc.get("kind")
        if kind not in counts:
            continue
        counts[kind] += 1
        name = _s(doc.get("name"))
        if kind == "mission-map":
            lines += _map_lines(name or f"carte {counts[kind]}", _obj(doc.get("map")), personas_by_id)
        elif kind == "flow":
            lines += _flow_lines(name or f"flux {counts[kind]}", _obj(doc.get("flow")), personas_by_id)
        elif kind == "persona":
            lines += _sheet_lines(_obj(doc.get("sheet")))
        else:
            lines += _sitemap_lines(name or f"plan {counts[kind]}", _obj(doc.get("sitemap")))
    parts = [
        _plural(counts["mission-map"], "carte"), _plural(counts["flow"], "flux", "flux"),
        _plural(counts["persona"], "persona"), _plural(counts["sitemap"], "plan du site", "plans du site"),
    ]
    units = ", ".join(p for p, n in zip(parts, counts.values()) if n)
    return lines, units or "projet Mapline"
