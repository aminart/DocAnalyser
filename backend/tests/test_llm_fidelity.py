"""Fidélité de bout en bout avec un vrai modèle (payant, lent) : lancés seulement avec RUN_LLM_TESTS=1.

    RUN_LLM_TESTS=1 .venv/bin/python -m pytest -m llm -v
    RUN_LLM_TESTS=1 TEST_MODEL="CUSTOM_LLM:mistral-medium-latest" .venv/bin/python -m pytest -m llm -v

Sans TEST_MODEL, le premier modèle configuré dans backend/.env est utilisé.
"""
import asyncio
import json
import os
import re

import pytest

from app.core.config import settings
from app.services import analysis_service as svc
from tests.fixtures import big_corpus
from tests.fixtures.expected import FACTS, JOURNEY_STEPS

pytestmark = pytest.mark.llm


def _model_id() -> str:
    wanted = os.environ.get("TEST_MODEL")
    configured = [m["id"] for m in svc.model_options() if m["configured"]]
    if wanted:
        return wanted
    if not configured:
        pytest.skip("aucun modèle configuré dans backend/.env")
    return configured[0]


def _run(paths, mode: str, level: str) -> svc.Analysis:
    docs = [svc.store_document(p.read_bytes(), p.name) for p in paths]

    async def go():
        a = svc.create_analysis([d.id for d in docs], mode, level, _model_id(), "fr", True)
        await a.task
        return a

    analysis = asyncio.run(go())
    assert analysis.status == "done", analysis.error
    return analysis


def _text(result: dict) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", ",", json.dumps(result, ensure_ascii=False)).lower().replace(" ", " ")


def _missing(blob: str, facts: dict[str, list[str]]) -> list[str]:
    return [name for name, variants in facts.items() if not any(re.search(v, blob) for v in variants)]


@pytest.mark.parametrize("level", ["synth", "detail", "deep"])
def test_synthese_globale_complete_et_fidele(fixtures_dir, level):
    paths = [fixtures_dir / name for name in FACTS]
    a = _run(paths, "global", level)
    r, blob = a.result, _text(a.result)

    # Aucune information clé perdue, quel que soit le niveau (le niveau ne règle que la profondeur).
    missing = [m for facts in FACTS.values() for m in _missing(blob, facts)]
    assert not missing, f"informations perdues : {missing}"

    # Tous les documents exploités.
    used = {d for t in r["themes"] for d in t["documents"]}
    assert used == set(FACTS), f"documents non exploités : {set(FACTS) - used}"

    # Verbatims : aucun inventé, la plupart recopiés mot pour mot.
    quotes = [t for t in r["themes"] if t["quote"]]
    assert not [t["quote"] for t in quotes if t["quote_check"] == "absent"], "verbatim introuvable dans les documents"
    assert r["stats"]["quotes_exact"] >= min(3, len(quotes))

    # Une information distincte par point : pas de point qui mélange plusieurs sources.
    points = [p for t in r["themes"] for p in t["points"]]
    if a.cite and points:
        assert sum(len(p["sources"]) for p in points) / len(points) <= 1.5

    # Toutes les sources pointent vers des repères existants.
    bad = [s for p in points for s in p["sources"] if s.get("found") is False]
    assert len(bad) <= max(1, len(points) // 10), f"repères introuvables : {bad}"


def test_parcours_reconstitue(fixtures_dir):
    a = _run([fixtures_dir / "entretiens_parcours.txt"], "flow", "detail")
    r = a.result
    blob = _text({"phases": r["phases"], "flow": r["flow"]["nodes"]})
    missing = _missing(blob, JOURNEY_STEPS)
    assert not missing, f"étapes du parcours absentes : {missing}"
    types = {n["type"] for n in r["flow"]["nodes"]}
    assert "exit" in types, "les abandons décrits dans les entretiens n'apparaissent pas dans le flux"
    assert not [p["quote"] for p in r["priorities"] if p["quote"] and p["quote_check"] == "absent"]


def test_corpus_volumineux_par_lots_sans_perte(tmp_path, monkeypatch):
    """Fenêtre réduite artificiellement : le corpus est analysé par lots et rien ne doit se perdre."""
    expected = big_corpus.build(tmp_path)
    key = _model_id().split(":", 1)[0]
    monkeypatch.setattr(settings, f"{key}_CONTEXT_TOKENS", 24_000)

    a = _run(sorted(tmp_path.glob("*.txt")), "global", "detail")
    assert a.batched, "le corpus aurait dû être analysé par lots"
    blob = _text(a.result)
    missing = [f"{topic} : {kw}" for topic, kws in expected.items() for kw in kws if kw.lower() not in blob]
    assert not missing, f"faits uniques perdus : {missing}"
    assert not [t["quote"] for t in a.result["themes"] if t["quote"] and t["quote_check"] == "absent"]
