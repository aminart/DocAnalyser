"""Modèle local qui tourne en boucle : réponse interrompue, lot redécoupé ; longueur de réponse plafonnée ; activité affichée."""
import asyncio
import json

import httpx
import pytest

from app.services import analysis_service as svc
from app.services import llm_client
from app.services.errors import InvalidModelOutput


def _spec(local=True, max_out=0):
    prov = svc.ProviderConf("T", "openai", "T", "", "http://localhost:11434/v1", "", 128_000, ("qwen:27b",),
                            max_output_tokens=max_out, local=local)
    return svc.ModelSpec("T:qwen:27b", "qwen:27b", prov, "", 3, 3, 3, "balanced")


def _install(monkeypatch, handler):
    monkeypatch.setattr(llm_client, "_CLIENTS", {"default": httpx.AsyncClient(transport=httpx.MockTransport(handler))})


def _sse(*texts):
    events = [{"choices": [{"delta": {"content": t}}]} for t in texts]
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def test_boucle_reconnue():
    line = '{"kind": "fait", "text": "Le délai de livraison est jugé trop long par les clients interrogés."},\n'
    assert svc.looping('{"items": [' + line * 40)
    assert svc.looping('{"items": [' + "\n" * 2000)
    varied = "".join(f'{{"kind": "fait", "text": "Constat numéro {i} sur un sujet différent à chaque fois."}},\n'
                     for i in range(60))
    assert not svc.looping('{"items": [' + varied)
    assert not svc.looping("court")


def test_reponse_en_boucle_interrompue(monkeypatch):
    line = '{"kind": "fait", "text": "Toujours la même ligne, répétée sans fin par le modèle."},\n'

    def handler(request):
        return httpx.Response(200, text=_sse('{"items": [', *([line] * 500)), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    activity = {}

    async def go():
        svc._ACTIVITY.set(activity)
        await svc._complete(_spec(), "Consigne", "Extrait")

    with pytest.raises(InvalidModelOutput, match="boucle"):
        asyncio.run(go())
    assert 0 < activity["chars"] < 100 * len(line)  # coupé bien avant la fin du flux


def test_longueur_de_reponse_plafonnee_pour_un_modele_local(monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content).get("max_tokens"))
        return httpx.Response(200, text=_sse("{}"), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    asyncio.run(svc._complete(_spec(), "Consigne", "Extrait"))
    asyncio.run(svc._complete(_spec(max_out=4000), "Consigne", "Extrait"))
    asyncio.run(svc._complete(_spec(local=False), "Consigne", "Extrait"))
    assert seen == [svc.settings.LOCAL_MAX_OUTPUT_TOKENS, 4000, None]


def test_activite_du_modele_affichee(monkeypatch):
    a = svc.Analysis("a1", "global", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    assert a.public()["activity"] is None
    a.activity.update(since=svc.time.time() - 240, chars=0)
    assert a.public()["activity"] == {"phase": "reading", "seconds": 240, "chars": 0}
    a.activity["chars"] = 1200
    assert a.public()["activity"]["phase"] == "writing"
    a.status = "done"
    assert a.public()["activity"] is None


def test_fusion_des_doublons_paquet_par_paquet_et_paquet_en_echec_garde(monkeypatch):
    """Mode Parcours : la fusion progresse paquet par paquet ; un paquet qui échoue est gardé tel quel."""
    from app.services import batch_pipeline

    items = [batch_pipeline.Item(f"e{i}", "fait", f"Constat {i} " + "y" * 60, "cr.txt", f"L{i}") for i in range(12)]
    calls = []

    async def fake_extract(analysis, chain, checker):
        return list(items), [], 3

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        if system_prompt == batch_pipeline.MERGE_PROMPT:
            calls.append(user)
            if len(calls) == 1:
                raise svc.InvalidModelOutput("boucle")
            lines = user.splitlines()
            return {"items": [{"kind": "fait", "text": l.split(") ", 1)[1], "document": "cr.txt", "location": "L"}
                              for l in lines[: max(1, len(lines) // 3)]]}
        if "phases" in system_prompt or "parcours" in system_prompt.lower():
            return {"title": "T", "phases": [{"name": "Étape"}]}
        return {"title": "T", "phases": [{"name": "Étape"}]}

    monkeypatch.setattr(batch_pipeline, "extract", fake_extract)
    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    monkeypatch.setattr(batch_pipeline, "budget_chars", lambda spec, cap=0: 900)
    monkeypatch.setattr(batch_pipeline, "EXTRACT_SHARE", 0.4)
    a = svc.Analysis("f1", "flow", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    asyncio.run(batch_pipeline.run_flow(a, [_spec()], svc.QuoteChecker("")))
    first = calls[0]
    assert len(calls) >= 3  # plusieurs paquets, l'échec du premier n'arrête pas l'analyse
    assert "fusion des doublons" in a.step_notes[1] and "fusionné" in a.step_notes[1]
    assert a.eta_at > 0

    # Reprise : les paquets déjà fusionnés sont relus sur le disque, seul celui qui avait échoué est redemandé.
    calls.clear()
    calls.append("déjà un appel")  # le prochain appel ne simule plus d'échec
    a2 = svc.Analysis("f2", "flow", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    asyncio.run(batch_pipeline.run_flow(a2, [_spec()], svc.QuoteChecker("")))
    assert calls[1] == first
