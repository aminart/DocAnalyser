"""Reprise d'une analyse échouée, durée restante mesurée, et texte de la synthèse modifié avant export."""
import asyncio
import time
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_service as svc
from app.services import batch_pipeline, store


def _gemini(monkeypatch):
    monkeypatch.setattr(svc.settings, "GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(svc.settings, "GEMINI_TEST_MODELS", "gemini-3.8-flash")


def _doc():
    blocks = [svc.AnchoredTextBlock("r.pdf", f"Page {i}", f"Texte {i}") for i in range(1, 4)]
    doc = svc.StoredDocument(f"doc-{time.time_ns()}", "r.pdf", "pdf", 10, "3 pages", 3, blocks)
    svc.DOCUMENTS[doc.id] = doc
    store.save_document(doc)
    return doc


def test_reprise_remplace_l_analyse_echouee_avec_les_memes_reglages(monkeypatch):
    _gemini(monkeypatch)

    async def fake_run(analysis, spec):
        analysis.status = "running"

    monkeypatch.setattr(svc, "_run", fake_run)
    doc = _doc()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        old = client.post("/api/v2/analyses", json={"document_ids": [doc.id], "mode": "notes", "level": "synth",
                                                     "model_id": "GEMINI:gemini-3.8-flash", "cite": False}).json()
        assert client.post(f"/api/v2/analyses/{old['id']}/retry").status_code == 400  # encore en cours
        svc.ANALYSES[old["id"]].status = "failed"
        new = client.post(f"/api/v2/analyses/{old['id']}/retry")
        assert new.status_code == 202, new.text
        new = new.json()
        assert new["id"] != old["id"] and (new["mode"], new["level"], new["cite"]) == ("notes", "synth", False)
        assert [d["id"] for d in new["documents"]] == [doc.id]
        assert old["id"] not in svc.ANALYSES and doc.id in svc.DOCUMENTS  # l'ancienne disparaît, pas le document


def test_texte_modifie_avant_export_puis_retour_au_texte_d_origine(monkeypatch):
    a = svc.Analysis(id=f"md-{time.time_ns()}", mode="global", level="detail", model_id="T:m", language="fr",
                     cite=True, documents=[], created_at=datetime.now(), status="done",
                     result={"kind": "themes", "title": "Titre", "brief": "", "themes": [], "actions": []})
    a.markdown = svc.to_markdown(a)
    original = a.markdown
    svc.ANALYSES[a.id] = a
    with TestClient(app, base_url="http://127.0.0.1") as client:
        res = client.put(f"/api/v2/analyses/{a.id}/markdown", json={"markdown": "# Mon titre corrigé\n\nTexte."})
        assert res.status_code == 200 and res.json()["markdown_edited"] is True
        export = client.get(f"/api/v2/analyses/{a.id}/export?format=md")
        assert export.text.startswith("# Mon titre corrigé")
        assert client.get(f"/api/v2/analyses/{a.id}/export?format=docx").status_code == 200
        assert store.load_all()[1][a.id].markdown_edited is True  # gardé après un redémarrage
        res = client.put(f"/api/v2/analyses/{a.id}/markdown", json={"markdown": None})
        assert res.json()["markdown_edited"] is False and res.json()["markdown"] == original


def test_duree_restante_mesuree_sur_les_lots(monkeypatch):
    async def fake_call(analysis, chain, system_prompt, user, **kw):
        await asyncio.sleep(0.02)
        return '{"items": [{"kind": "fait", "text": "%s", "document": "r.pdf", "location": "Page 1"}], "topics": []}' % len(user)

    seen = []
    monkeypatch.setattr(svc, "_call", fake_call)
    monkeypatch.setattr(batch_pipeline, "budget_chars", lambda spec, cap=0: 10)  # un lot par page
    prov = svc.ProviderConf("T", "openai", "T", "", "http://x", "", 200_000, ("m",), local=True)
    spec = svc.ModelSpec("T:m", "m", prov, "", 3, 3, 3, "balanced")
    doc = _doc()
    a = svc.Analysis(id="eta", mode="global", level="detail", model_id="T:m", language="fr", cite=True,
                     documents=[doc], created_at=datetime.now())
    original = batch_pipeline.extract

    async def go():
        task = asyncio.create_task(original(a, [spec], svc.QuoteChecker("")))
        while not task.done():
            seen.append(a.public()["eta_seconds"])
            await asyncio.sleep(0.005)
        return await task

    asyncio.run(go())
    assert seen[0] is None  # inconnue avant deux lots mesurés
    assert a.eta_at > 0  # estimée ensuite


def _failed_run(monkeypatch, exc):
    """Lance _run avec un modèle qui échoue sur l'erreur donnée ; renvoie l'analyse échouée."""
    _gemini(monkeypatch)
    monkeypatch.setattr(svc, "RETRY_WAITS", (0, 0, 0))

    async def fake_complete(spec, system_prompt, user, want_json=True, on_text=None):
        raise exc

    monkeypatch.setattr(svc, "_complete", fake_complete)
    doc = _doc()
    a = svc.Analysis(id=f"err-{time.time_ns()}", mode="global", level="synth", model_id="GEMINI:gemini-3.8-flash",
                     language="fr", cite=False, documents=[doc], created_at=datetime.now())
    svc.ANALYSES[a.id] = a
    asyncio.run(svc._run(a, svc.get_model(a.model_id)))
    assert a.status == "failed"
    return a


def test_cle_refusee_renvoie_vers_les_reglages(monkeypatch):
    from app.services import llm_client

    a = _failed_run(monkeypatch, llm_client.AuthenticationError("invalid key", 401))
    assert a.public()["error_settings"] is True
    assert "Réglages" in a.error and "backend/.env" not in a.error


def test_serveur_injoignable_renvoie_vers_les_reglages(monkeypatch):
    from app.services import llm_client

    a = _failed_run(monkeypatch, llm_client.ConnectionFailedError("connexion impossible à http://localhost:11434"))
    assert a.error_settings is True


def test_autre_echec_ne_renvoie_pas_vers_les_reglages(monkeypatch):
    from app.services import llm_client

    a = _failed_run(monkeypatch, llm_client.BadRequestError("bad json", 400))
    assert a.error_settings is False
