"""« Approfondir ce thème » : un seul thème réécrit, passages retrouvés, rien de perdu, retour possible."""
import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_service as svc
from app.services import deepen_service as deepen
from app.services import store


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(svc.settings, "GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(svc.settings, "GEMINI_TEST_MODELS", "gemini-3.8-flash,gemini-3.5-flash-lite")


def _theme(title, lead, location="L4"):
    return {"title": title, "summary": f"Résumé {title}.", "documents": ["parcours.txt"],
            "points": [{"lead": lead, "body": "", "sources": [{"document": "parcours.txt", "location": location, "found": True}]}],
            "quote": "", "quote_check": "", "quote_by": "", "nuance": ""}


def _analysis(doc, an_id, markdown_edited=False):
    a = svc.Analysis(id=an_id, mode="global", level="synth", model_id="GEMINI:gemini-3.8-flash", language="fr",
                     cite=True, documents=[doc], created_at=datetime.now(timezone.utc), status="done", title="T")
    a.result = {
        "kind": "themes", "title": "T", "brief": "B",
        "themes": [_theme("Points d'entrée", "7 participants viennent du simulateur."),
                   _theme("Identification", "3 clients oublient leur mot de passe.", "L9")],
        "actions": [], "sources": [{"document": "parcours.txt", "citations": 2}],
        "stats": {"themes": 2, "points": 2, "quotes": 0, "quotes_exact": 0, "actions": 0},
    }
    a.markdown = "texte modifié" if markdown_edited else svc.to_markdown(a)
    a.markdown_edited = markdown_edited
    svc.ANALYSES[a.id] = a
    store.save_analysis(a)
    return a


REPLY = {"theme": {
    "title": "Autre titre", "summary": "Version approfondie.", "documents": ["parcours.txt"],
    "points": [
        {"lead": "Les participants arrivent par deux canaux.", "body": "Le simulateur et le conseiller en agence.",
         "sources": [{"document": "parcours.txt", "location": "L4"}]},
        {"lead": "Le lien par SMS désoriente.", "body": "Une participante a cru devoir tout refaire.",
         "sources": [{"document": "parcours.txt", "location": "L5"}]},
    ],
    "quote": "Le conseiller m'a envoyé un lien, j'ai cru que je devais tout refaire depuis le début.",
    "quote_by": "Participante 2", "nuance": "",
}}


def _run(a, index):
    async def go():
        deepen.deepen(a, index)
        await deepen._TASKS[a.id]
    asyncio.run(go())


def test_un_theme_approfondi_sans_rien_perdre(fixtures_dir, gemini, monkeypatch):
    seen = []

    async def fake_complete(spec, system, user, want_json=True, on_text=None):
        seen.append((system, user))
        return json.dumps(REPLY, ensure_ascii=False)

    monkeypatch.setattr(svc, "_complete", fake_complete)
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    a = _analysis(doc, "dp-1")
    other = a.result["themes"][1]
    _run(a, 0)

    assert a.deepening == {} and len(seen) == 1
    system, user = seen[0]
    assert "Niveau très détaillé" in system and "Approfondis un seul thème" in system
    assert "7 participants viennent du simulateur." in user and "Corpus complet" in user
    t = a.result["themes"][0]
    assert t["title"] == "Points d'entrée"  # intitulé gardé
    assert t["deepened"] and t["previous"]["summary"] == "Résumé Points d'entrée."
    assert t["quote_check"] == "exact"
    # « 7 participants » n'apparaît plus dans la nouvelle version : l'ancien point est repris tel quel.
    assert [p["lead"] for p in t["points"]][-1] == "7 participants viennent du simulateur."
    assert len(t["points"]) == 3
    assert a.result["themes"][1] is other  # le reste de la synthèse ne bouge pas
    assert a.result["stats"]["points"] == 4 and a.result["stats"]["quotes"] == 1
    assert "Le lien par SMS désoriente." in a.markdown

    # Retour à la version précédente
    deepen.undo(a, 0)
    assert a.result["themes"][0]["summary"] == "Résumé Points d'entrée." and a.result["stats"]["points"] == 2
    assert "Le lien par SMS" not in a.markdown
    with pytest.raises(deepen.DeepenError):
        deepen.undo(a, 0)


def test_texte_exporte_modifie_garde_et_echec_signale(fixtures_dir, gemini, monkeypatch):
    async def fake_complete(spec, system, user, want_json=True, on_text=None):
        return json.dumps(REPLY, ensure_ascii=False)

    monkeypatch.setattr(svc, "_complete", fake_complete)
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    a = _analysis(doc, "dp-2", markdown_edited=True)
    _run(a, 1)
    assert a.markdown == "texte modifié"  # modifications à la main jamais écrasées

    async def broken(spec, system, user, want_json=True, on_text=None):
        return "pas du JSON"

    monkeypatch.setattr(svc, "_complete", broken)
    before = a.result["themes"][0]
    _run(a, 0)
    assert a.deepening["status"] == "failed" and a.deepening["error"]
    assert a.result["themes"][0] is before
    deepen.dismiss(a)
    assert a.deepening == {}


def test_gros_corpus_passages_cites_puis_recherche(gemini, monkeypatch):
    lines = [f"Remarque {i} sur le stationnement et les horaires du bâtiment B." for i in range(2000)]
    lines[1500] = "Participante 4 : la cantine ferme trop tôt, je mange souvent à mon bureau."
    lines[1800] = "Participant 7 : la cantine propose peu de plats végétariens."
    doc = svc.store_document("\n".join(lines).encode(), "gros.txt")
    theme = {"title": "Cantine", "summary": "La cantine pose problème.", "documents": ["gros.txt"],
             "points": [{"lead": "La cantine ferme trop tôt.", "body": "",
                         "sources": [{"document": "gros.txt", "location": "L1501"}]}],
             "quote": "", "quote_by": "", "nuance": ""}
    a = svc.Analysis(id="dp-3", mode="global", level="synth", model_id="GEMINI:gemini-3.8-flash", language="fr",
                     cite=True, documents=[doc], created_at=datetime.now(timezone.utc), status="done")
    segments, full = deepen.passages_for(a, theme, 4000)
    text = "\n".join(segments)
    assert not full and sum(map(len, segments)) <= 4000
    assert "L1501" in text and "végétariens" in text  # passage cité, puis passage retrouvé par la recherche


def test_routes_et_refus(fixtures_dir, gemini, monkeypatch):
    async def fake_complete(spec, system, user, want_json=True, on_text=None):
        await asyncio.sleep(0.05)
        return json.dumps(REPLY, ensure_ascii=False)

    monkeypatch.setattr(svc, "_complete", fake_complete)
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    _analysis(doc, "dp-4")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/v2/analyses/dp-4/themes/9/deepen").status_code == 409
        r = client.post("/api/v2/analyses/dp-4/themes/0/deepen")
        assert r.status_code == 202 and r.json()["deepening"]["status"] == "running"
        assert client.post("/api/v2/analyses/dp-4/themes/1/deepen").status_code == 409  # un seul à la fois
        for _ in range(100):
            data = client.get("/api/v2/analyses/dp-4").json()
            if not data["deepening"]:
                break
            asyncio.run(asyncio.sleep(0.05))
        assert data["result"]["themes"][0]["deepened"]
        r = client.post("/api/v2/analyses/dp-4/themes/0/undo")
        assert r.status_code == 200 and not r.json()["result"]["themes"][0].get("deepened")
