"""« Approfondir ce thème » : réécrit un seul thème d'une synthèse terminée, plus en détail.

1. On rassemble les passages du thème : ceux que citent ses points, puis ceux que la recherche BM25
   (la même que l'onglet Questions) retrouve à partir de son intitulé, de son résumé et de ses points.
   Si tout le corpus tient dans la fenêtre du modèle, il est envoyé en entier.
2. Le modèle réécrit le thème au niveau « Très détaillé », en gardant tout ce que disait l'ancienne version
   et en ajoutant ce que les passages apportent de plus.
3. Garde-fou de fidélité : un point de l'ancienne version dont un chiffre ou un nom propre a disparu est
   repris tel quel. L'ancienne version est gardée pour pouvoir y revenir.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.services import analysis_service as svc
from app.services import batch_pipeline, qa_service, store
from app.services.normalize import QuoteChecker, normalize_themes

logger = logging.getLogger("analyse")

CORPUS_SHARE = 0.7  # part de la fenêtre pour les passages (le reste : consignes, thème actuel et réponse)
TITLE_WEIGHT, TEXT_WEIGHT = 1.0, 0.5

_TASKS: dict[str, asyncio.Task] = {}


class DeepenError(svc.AnalysisError):
    """Erreur remontée telle quelle à l'interface."""


def _prompt(analysis: svc.Analysis) -> str:
    return "\n\n".join([
        svc.BASE_RULES,
        svc.MODE_GUIDANCE[analysis.mode],
        "Approfondis un seul thème d'une synthèse existante, à partir des passages des documents fournis. "
        "La nouvelle version remplace l'ancienne : garde chaque information de l'ancienne version (aucun point, "
        "chiffre, nom ou verbatim ne doit disparaître), vérifie-la dans les passages, puis ajoute tout ce que les "
        "passages apportent de plus sur ce thème : faits, chiffres, exemples, cas particuliers, causes, "
        "conséquences, désaccords. Reste dans le périmètre du thème. Garde son intitulé.",
        svc.LEVEL_GUIDANCE["deep"],
        "Indique les sources de chaque point." if analysis.cite else "Laisse « sources » vide ([]) pour chaque point.",
        svc._language_rule(analysis.language),
        "Schéma JSON attendu :\n" + batch_pipeline.THEME_SCHEMA,
    ])


def _current(theme: dict[str, Any]) -> str:
    """Thème actuel, tel que présenté au modèle (sans les marques internes)."""
    keep = ("title", "summary", "points", "quote", "quote_by", "nuance")
    data = {k: theme.get(k) for k in keep}
    data["points"] = [{"lead": p["lead"], "body": p["body"], "sources": [
        {"document": s["document"], "location": s["location"]} for s in p["sources"]]} for p in theme["points"]]
    return json.dumps(data, ensure_ascii=False, indent=1)


def _terms(theme: dict[str, Any]) -> dict[str, float]:
    terms: dict[str, float] = {}
    text = " ".join([theme.get("summary", ""), *(p["lead"] for p in theme["points"])])
    for words, weight in ((qa_service.tokens(text), TEXT_WEIGHT), (qa_service.tokens(theme["title"]), TITLE_WEIGHT)):
        for w in words:
            terms[w] = max(terms.get(w, 0.0), weight)
    return terms


def passages_for(analysis: svc.Analysis, theme: dict[str, Any], budget: int) -> tuple[list[str], bool]:
    """Segments envoyés au modèle et True si c'est le corpus complet."""
    whole = [b.to_prompt_segment() for d in analysis.documents for b in d.blocks]
    if sum(map(len, whole)) <= budget:
        return whole, True
    # Passages cités par les points du thème : la base de la réécriture, envoyés en premier.
    blocks_by_doc = {d.name: d.blocks for d in analysis.documents}
    cited, seen, used = [], set(), 0
    for p in theme["points"]:
        for s in p["sources"]:
            block = batch_pipeline._find_block(blocks_by_doc.get(s["document"], []), s["location"])
            if block is None or id(block) in seen:
                continue
            seg = block.to_prompt_segment()
            if used + len(seg) > budget // 2:  # la moitié au plus : le reste pour ce que la recherche apporte
                continue
            seen.add(id(block))
            cited.append(seg)
            used += len(seg)
    index = qa_service.index_for(analysis.documents)
    found = [p.segment() for p in qa_service.select_passages(index, _terms(theme), budget - used)]
    return cited + found, False


def _keep_old_facts(old: dict[str, Any], new: dict[str, Any]) -> int:
    """Reprend les points de l'ancienne version dont un chiffre ou un nom propre a disparu. Renvoie leur nombre."""
    blob = batch_pipeline._content_text(new).lower()
    kept = 0
    for p in old["points"]:
        facts = batch_pipeline._key_facts(f"{p['lead']} {p['body']}")
        if any(not batch_pipeline._present(f.lower(), blob) for f in facts):
            new["points"].append({k: p[k] for k in ("lead", "body", "sources")})
            kept += 1
    if old.get("quote") and not new.get("quote"):
        new.update({k: old[k] for k in ("quote", "quote_check", "quote_by")})
    if old.get("nuance") and not new.get("nuance"):
        new["nuance"] = old["nuance"]
    new["documents"] = [d for d in dict.fromkeys(new["documents"] + old["documents"])]
    return kept


def _refresh_totals(result: dict[str, Any], doc_names: list[str]) -> None:
    """Compteurs du rapport (citations par document, points, verbatims) après le remplacement d'un thème."""
    themes = result["themes"]
    citations = {d: 0 for d in doc_names}
    for t in themes:
        for p in t["points"]:
            for s in p["sources"]:
                if s["document"] in citations:
                    citations[s["document"]] += 1
    result["sources"] = [{"document": d, "citations": citations[d]} for d in doc_names]
    result["stats"].update({
        "points": sum(len(t["points"]) for t in themes),
        "quotes": sum(1 for t in themes if t["quote"]),
        "quotes_exact": sum(1 for t in themes if t["quote_check"] == "exact"),
    })


def _refresh_markdown(analysis: svc.Analysis) -> None:
    # Un texte exporté modifié à la main n'est pas écrasé : l'onglet « Texte exporté » le signale.
    if not analysis.markdown_edited:
        analysis.markdown = svc.to_markdown(analysis)


def _check(analysis: svc.Analysis, index: int) -> dict[str, Any]:
    r = analysis.result
    if analysis.status != "done" or not r or r.get("kind") != "themes":
        raise DeepenError("Seule une synthèse par thèmes terminée peut être approfondie.")
    if not 0 <= index < len(r["themes"]):
        raise DeepenError("Ce thème n'existe pas dans la synthèse.")
    return r["themes"][index]


def deepen(analysis: svc.Analysis, index: int) -> None:
    theme = _check(analysis, index)
    if analysis.deepening.get("status") == "running":
        raise DeepenError("Un thème est déjà en cours d'approfondissement : attendez qu'il se termine.")
    if not any(d.blocks for d in analysis.documents):
        raise DeepenError("Les documents de cette analyse ne sont plus disponibles.")
    spec = svc.get_model(analysis.active_model_id or analysis.model_id)
    if not svc.is_configured(spec):
        raise DeepenError(f"Le modèle {spec.name} de cette analyse n'est plus configuré : vérifiez l'onglet Réglages.")
    analysis.deepening = {"theme": index, "title": theme["title"], "status": "running", "error": None}
    store.save_analysis(analysis)
    _TASKS[analysis.id] = asyncio.create_task(_run(analysis, index, spec))


async def _run(analysis: svc.Analysis, index: int, spec: svc.ModelSpec) -> None:
    state = analysis.deepening
    try:
        chain = svc.fallback_chain(spec)
        if spec.provider.local and not analysis.context_cap:
            await svc._fit_local_context(analysis, spec)
        old = analysis.result["themes"][index]
        budget = int(batch_pipeline.budget_chars(spec, analysis.context_cap) * CORPUS_SHARE) - len(_current(old))
        segments, full = passages_for(analysis, old, max(budget, 4000))
        scope = "Corpus complet" if full else "Passages des documents liés à ce thème"
        user = (f"Thème actuel :\n{_current(old)}\n\n{scope} :\n" + "\n".join(segments))
        data = await svc._call_json(analysis, chain, _prompt(analysis), user)
        raw = data.get("theme") if isinstance(data.get("theme"), dict) else data
        raw = {**raw, "title": old["title"]}  # l'intitulé reste celui de la synthèse
        doc_names = [d.name for d in analysis.documents]
        checker = QuoteChecker("\n".join(d.plain_text() for d in analysis.documents))
        new = normalize_themes({"themes": [raw]}, doc_names, checker)["themes"][0]
        if not new["points"]:
            raise DeepenError("Le modèle n'a rédigé aucun point pour ce thème. Réessayez.")
        _keep_old_facts(old, new)
        svc._flag_sources({"themes": [new]}, analysis.documents)
        # Thème encore affiché ? (analyse supprimée ou thèmes changés entre-temps)
        if analysis.result["themes"][index] is not old:
            return
        if old.get("details"):
            new["details"] = old["details"]  # l'annexe détaillée reste celle de l'analyse
        new["previous"] = {k: v for k, v in old.items() if k != "previous"}  # pour revenir en arrière
        new["deepened"] = True
        analysis.result["themes"][index] = new
        _refresh_totals(analysis.result, doc_names)
        _refresh_markdown(analysis)
        analysis.deepening = {}
    except asyncio.CancelledError:
        state.update(status="failed", error="Approfondissement interrompu.")
    except svc.AnalysisError as exc:
        state.update(status="failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 : erreur inattendue, affichée telle quelle
        logger.exception("Approfondissement : erreur inattendue")
        state.update(status="failed", error=f"Erreur inattendue : {str(exc)[:300]}")
    finally:
        _TASKS.pop(analysis.id, None)
        if analysis.id in svc.ANALYSES:
            store.save_analysis(analysis)


def undo(analysis: svc.Analysis, index: int) -> None:
    """Revient à la version du thème d'avant l'approfondissement."""
    theme = _check(analysis, index)
    previous = theme.get("previous")
    if not previous:
        raise DeepenError("Ce thème n'a pas de version précédente.")
    if analysis.deepening.get("status") == "running":
        raise DeepenError("Attendez la fin de l'approfondissement en cours.")
    analysis.result["themes"][index] = previous
    _refresh_totals(analysis.result, [d.name for d in analysis.documents])
    _refresh_markdown(analysis)
    store.save_analysis(analysis)


def dismiss(analysis: svc.Analysis) -> None:
    """Efface le message d'un approfondissement échoué."""
    if analysis.deepening.get("status") != "running":
        analysis.deepening = {}
        store.save_analysis(analysis)
