"""Réponses reçues au fil de l'eau en analyse par lots, et réflexion préalable des modèles désactivée."""
import asyncio
import json

import httpx

from app.services import analysis_service as svc
from app.services import llm_client


def _spec(name="qwen3.8:27b", local=True):
    prov = svc.ProviderConf("T", "openai", "T", "", "http://localhost:11434/v1", "", 128_000, (name,), local=local)
    return svc.ModelSpec(f"T:{name}", name, prov, "", 3, 3, 3, "balanced")


def _install(monkeypatch, handler):
    monkeypatch.setattr(llm_client, "_CLIENTS", {"default": httpx.AsyncClient(transport=httpx.MockTransport(handler))})


def _sse(*texts):
    events = [{"choices": [{"delta": {"content": t}}]} for t in texts]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def test_lot_recu_au_fil_de_l_eau_reflexion_desactivee_et_retiree(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=_sse("<think>Je réfléchis {beaucoup}…</think>", '{"items": ', "[]}"),
                              headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    out = asyncio.run(svc._complete(_spec(), "Consigne", "Extrait"))  # appel sans on_text : cas des lots
    assert out == '{"items": []}'
    assert seen["stream"] is True and seen["think"] is False
    assert seen["messages"][0]["content"].endswith("/no_think")


def test_modele_en_ligne_sans_champ_think(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=_sse("{}"), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    asyncio.run(svc._complete(_spec("mistral-large", local=False), "Consigne", "Extrait"))
    assert "think" not in seen and not seen["messages"][0]["content"].endswith("/no_think")


def test_reflexion_gardee_si_demande(monkeypatch):
    monkeypatch.setattr(svc.settings, "DISABLE_THINKING", False)
    assert svc._thinking_off(_spec(), "Consigne") == ({}, "Consigne")


def test_delai_par_morceau_pour_un_modele_local():
    assert svc.request_timeout(_spec(), streaming=True) == svc.settings.LOCAL_STREAM_TIMEOUT_SECONDS
