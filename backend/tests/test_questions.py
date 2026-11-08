"""Questions sur les documents : passages repérés, recherche BM25, corpus entier s'il tient, sources vérifiées."""
import asyncio
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_service as svc
from app.services import qa_service as qa
from app.services import store


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(svc.settings, "GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(svc.settings, "GEMINI_TEST_MODELS", "gemini-3.8-flash,gemini-3.5-flash-lite")


def _analysis(docs, an_id="qa-1"):
    a = svc.Analysis(id=an_id, mode="global", level="detail", model_id="GEMINI:gemini-3.8-flash", language="fr",
                     cite=True, documents=docs, created_at=datetime.now(timezone.utc), status="done", title="T")
    svc.ANALYSES[a.id] = a
    store.save_analysis(a)
    return a


def _big_doc(name="gros.txt"):
    """Corpus bien plus grand que le budget : 400 lignes de remplissage, une seule parle de la cantine."""
    lines = [f"Remarque {i} sur le stationnement et les horaires du bâtiment B." for i in range(400)]
    lines[237] = "Participante 4 : « La cantine ferme trop tôt, je mange souvent à mon bureau. »"
    return svc.store_document("\n".join(lines).encode(), name)


def test_passages_gardent_les_reperes(fixtures_dir):
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    passages = qa.passages_of(doc)
    assert len(passages) > 1
    assert all(p.location.startswith("L") for p in passages)
    assert passages[0].text.startswith("L1: ")
    # Chaque ligne du document figure dans au moins un passage
    text = "\n".join(p.text for p in passages)
    for ln in qa.doc_lines(doc):
        assert f"{ln.ref}: {ln.text}" in text


def test_bm25_trouve_le_passage_y_compris_par_un_synonyme():
    doc = _big_doc()
    index = qa.index_for([doc])
    budget = 1200
    chosen = qa.select_passages(index, qa.query_terms("Que disent-ils de la cantine ?", []), budget)
    assert chosen and "cantine" in chosen[0].text and sum(len(p.segment()) for p in chosen) <= budget
    # « restauration » n'est pas dans le document : le synonyme proposé par le modèle le retrouve.
    assert qa.select_passages(index, qa.query_terms("Et la restauration ?", []), budget) == []
    chosen = qa.select_passages(index, qa.query_terms("Et la restauration ?", ["cantine", "repas"]), budget)
    assert chosen and "L238" in chosen[0].text


def test_sources_rattachees_et_verifiees(fixtures_dir):
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    answer = "Sept arrivent du simulateur [[parcours | L4]] ; repère inventé [[parcours.txt | L9999]] [[parcours.txt|L4]]."
    assert qa.extract_sources(answer, [doc]) == [
        {"document": "parcours.txt", "location": "L4", "found": True},
        {"document": "parcours.txt", "location": "L9999", "found": False},
    ]


def test_petit_corpus_envoye_en_entier(fixtures_dir, gemini, monkeypatch):
    seen = []

    async def fake_complete(spec, system, user, want_json=True, on_text=None):
        seen.append((system, user))
        if on_text:
            on_text("Sept participants")
        return "Sept participants arrivent depuis le simulateur [[parcours.txt | L4]]."

    monkeypatch.setattr(svc, "_complete", fake_complete)
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    a = _analysis([doc], "qa-full")

    async def go():
        item = qa.ask(a, "D'où viennent les participants ?")
        await qa._TASKS[a.id]
        return item

    item = asyncio.run(go())
    assert item["status"] == "done", item["error"]
    assert item["scope"] == "full" and len(seen) == 1  # pas d'appel pour les mots-clés
    assert "simulateur de tarif" in seen[0][1] and "Corpus complet" in seen[0][1]
    assert item["sources"] == [{"document": "parcours.txt", "location": "L4", "found": True}]


def test_gros_corpus_recherche_puis_reponse_et_historique(gemini, monkeypatch):
    monkeypatch.setattr(svc.settings, "QA_CONTEXT_TOKENS", 600)
    calls = []

    async def fake_complete(spec, system, user, want_json=True, on_text=None):
        calls.append(user)
        if want_json:
            return '{"keywords": ["cantine", "repas", "restaurant"]}'
        return "La cantine ferme trop tôt [[gros.txt | L238]]."

    monkeypatch.setattr(svc, "_complete", fake_complete)
    a = _analysis([_big_doc()], "qa-search")

    async def go(q):
        item = qa.ask(a, q)
        await qa._TASKS[a.id]
        return item

    item = asyncio.run(go("Que pensent-ils de la restauration ?"))
    assert item["status"] == "done", item["error"]
    assert item["scope"] == "search" and item["keywords"] == ["cantine", "repas", "restaurant"]
    assert "L238: Participante 4" in calls[1] and "Remarque 10 " not in calls[1]
    assert item["sources"][0]["found"]

    # Question de suivi : l'échange précédent est rappelé au modèle
    asyncio.run(go("Et le soir ?"))
    assert "Q : Que pensent-ils de la restauration ?" in calls[-1]

    # Enregistré avec l'analyse, rechargé après redémarrage
    svc.ANALYSES.clear()
    svc.DOCUMENTS.clear()
    svc.load_history()
    assert [q["question"] for q in svc.ANALYSES["qa-search"].questions] == [
        "Que pensent-ils de la restauration ?", "Et le soir ?"]


def test_routes_questions(fixtures_dir, gemini, monkeypatch):
    async def fake_complete(spec, system, user, want_json=True, on_text=None):
        return "Réponse [[parcours.txt | L4]]."

    monkeypatch.setattr(svc, "_complete", fake_complete)
    doc = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    _analysis([doc], "qa-routes")
    with TestClient(app) as client:
        r = client.post("/api/v2/analyses/qa-routes/questions", json={"question": "Combien de participants ?"})
        assert r.status_code == 202 and r.json()["status"] == "running"
        for _ in range(50):
            items = client.get("/api/v2/analyses/qa-routes/questions").json()
            if items[0]["status"] != "running":
                break
            time.sleep(0.05)
        assert items[0]["status"] == "done" and items[0]["answer"].startswith("Réponse")
        assert client.post("/api/v2/analyses/qa-routes/questions", json={"question": ""}).status_code == 422
        assert client.delete("/api/v2/analyses/qa-routes/questions").status_code == 204
        assert client.get("/api/v2/analyses/qa-routes/questions").json() == []
        assert client.get("/api/v2/analyses/inconnue/questions").status_code == 404
