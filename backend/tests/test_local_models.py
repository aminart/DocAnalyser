"""Gros documents sur un modèle local (Ollama) : délais, une requête à la fois, fenêtre réelle, reprise des lots."""
import asyncio
from datetime import datetime

import httpx
import pytest

from app.services import analysis_service as svc
from app.services import batch_pipeline, llm_client
from app.services.models import is_local_base


def _spec(local=False, base="http://x", ctx=200_000):
    prov = svc.ProviderConf("T", "openai", "T", "", base, "", ctx, ("m",), local=local)
    return svc.ModelSpec("T:m", "m", prov, "", 3, 3, 3, "balanced")


def _analysis(doc):
    return svc.Analysis(id="lots", mode="global", level="detail", model_id="T:m", language="fr", cite=True,
                        documents=[doc], created_at=datetime.now())


def _doc(fixtures_dir, n=6):
    doc = svc.store_document((fixtures_dir / "compte_rendu_6_sujets.txt").read_bytes(), "cr.txt")
    doc.blocks = [svc.AnchoredTextBlock("cr.txt", f"Lignes L{i}", f"L{i}: Information {i} " + "x" * 40)
                  for i in range(1, n + 1)]
    return doc


def _answer(user):
    lines = [l for l in user.splitlines() if l.startswith("L")]
    items = ",".join('{"kind": "fait", "text": "%s", "document": "cr.txt", "location": "%s"}'
                     % (l.split(": ", 1)[1].split(" x")[0], l.split(":")[0]) for l in lines)
    return '{"items": [%s], "topics": []}' % items


@pytest.mark.parametrize("base, local", [
    ("http://localhost:11434/v1", True), ("http://127.0.0.1:1234/v1", True), ("http://pc-gpu:11434/v1", True),
    ("https://llm.entreprise.fr/v1", False), ("", False),
])
def test_adresse_locale_reconnue(base, local):
    assert is_local_base(base) is local


def test_modele_local_lots_plus_petits_et_delai_plus_long(monkeypatch):
    monkeypatch.setattr(svc.settings, "LOCAL_MAX_REQUEST_TOKENS", 32_000)
    assert batch_pipeline.window_tokens(_spec(local=True)) == 32_000
    assert batch_pipeline.window_tokens(_spec(local=False)) == 200_000
    assert svc.request_timeout(_spec(local=True)) == svc.settings.LOCAL_LLM_TIMEOUT_SECONDS
    assert svc.request_timeout(_spec(local=False)) == svc.settings.LLM_TIMEOUT_SECONDS
    assert svc.request_timeout(_spec(local=False), streaming=True) == llm_client.STREAM_READ_TIMEOUT
    assert svc.concurrency(_spec(local=True)) == 1


def test_modele_local_une_requete_a_la_fois(fixtures_dir, monkeypatch):
    running, peak = 0, 0

    async def fake_call(analysis, chain, system_prompt, user, **kw):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return _answer(user)

    monkeypatch.setattr(svc, "_call", fake_call)
    monkeypatch.setattr(batch_pipeline, "budget_chars", lambda spec, cap=0: 200)  # un lot par bloc
    doc = _doc(fixtures_dir)
    items, _, n = asyncio.run(batch_pipeline.extract(_analysis(doc), [_spec(local=True)], svc.QuoteChecker("")))
    assert n == 6 and len(items) == 6 and peak == 1


def test_echec_d_un_lot_message_clair_puis_reprise(fixtures_dir, monkeypatch):
    """Arrêt au lot 4 : le message dit où et que le travail est gardé ; relancée, l'analyse reprend au lot 4."""
    calls, fail = [], {"on": True}

    async def fake_call(analysis, chain, system_prompt, user, **kw):
        calls.append(user)
        await asyncio.sleep(0.01)
        if fail["on"] and "L4:" in user:
            raise svc.ProviderUnavailable("Le modèle m n'a pas répondu.", timed_out=False)
        return _answer(user)

    monkeypatch.setattr(svc, "_call", fake_call)
    monkeypatch.setattr(batch_pipeline, "budget_chars", lambda spec, cap=0: 200)
    doc, spec = _doc(fixtures_dir), _spec(local=True)
    with pytest.raises(svc.ProviderUnavailable) as exc:
        asyncio.run(batch_pipeline.extract(_analysis(doc), [spec], svc.QuoteChecker("")))
    assert "Arrêt au lot 4/6" in str(exc.value) and "les 3 lots déjà extraits sont gardés" in str(exc.value)
    assert len(calls) <= 5  # les lots suivants sont arrêtés après l'échec (au plus celui qui venait de partir)

    calls.clear()
    fail["on"] = False
    a = _analysis(doc)
    items, _, _ = asyncio.run(batch_pipeline.extract(a, [spec], svc.QuoteChecker("")))
    assert len(items) == 6 and len(calls) == 3  # seuls les lots 4 à 6 sont redemandés
    assert "3 repris de l'analyse précédente" in a.step_notes[1]


def test_lot_trop_long_coupe_en_deux_apres_un_delai_depasse(fixtures_dir, monkeypatch):
    async def fake_call(analysis, chain, system_prompt, user, **kw):
        if user.count("[SOURCE:") > 3:
            raise svc.ProviderUnavailable("délai dépassé", timed_out=True)
        return _answer(user)

    monkeypatch.setattr(svc, "_call", fake_call)
    monkeypatch.setattr(batch_pipeline, "EXTRACT_SHARE", 1.0)
    doc = _doc(fixtures_dir)
    items, _, n = asyncio.run(batch_pipeline.extract(_analysis(doc), [_spec()], svc.QuoteChecker("")))
    assert n == 1 and sorted(i.text for i in items) == [f"Information {i}" for i in range(1, 7)]


def _install(monkeypatch, handler):
    monkeypatch.setattr(llm_client, "_CLIENTS", {"default": httpx.AsyncClient(transport=httpx.MockTransport(handler))})


def _ollama(ctx):
    def handler(request):
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen:27b", "model": "qwen:27b", "context_length": ctx}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "length"}]})
    return handler


def test_fenetre_ollama_lue(monkeypatch):
    _install(monkeypatch, _ollama(8192))
    assert asyncio.run(llm_client.ollama_context_length("http://localhost:11434/v1", "qwen:27b")) == 8192
    assert asyncio.run(llm_client.ollama_context_length("http://localhost:11434/v1", "autre")) is None


def test_fenetre_ollama_trop_petite_arret_immediat_avec_la_marche_a_suivre(monkeypatch):
    _install(monkeypatch, _ollama(4096))
    spec = svc.ModelSpec("T:qwen:27b", "qwen:27b", _spec(local=True, base="http://localhost:11434/v1").provider,
                         "", 3, 3, 3, "balanced")
    a = svc.Analysis(id="ctx", mode="global", level="detail", model_id=spec.id, language="fr", cite=True,
                     documents=[], created_at=datetime.now())
    with pytest.raises(svc.AnalysisError, match="OLLAMA_CONTEXT_LENGTH"):
        asyncio.run(svc._fit_local_context(a, spec))


def test_fenetre_ollama_moyenne_les_lots_s_y_adaptent(monkeypatch):
    _install(monkeypatch, _ollama(28_000))
    spec = svc.ModelSpec("T:qwen:27b", "qwen:27b", _spec(local=True, base="http://localhost:11434/v1").provider,
                         "", 3, 3, 3, "balanced")
    a = svc.Analysis(id="ctx", mode="global", level="detail", model_id=spec.id, language="fr", cite=True,
                     documents=[], created_at=datetime.now())
    asyncio.run(svc._fit_local_context(a, spec))
    assert a.context_cap == 28_000 and batch_pipeline.window_tokens(spec, a.context_cap) == 28_000
