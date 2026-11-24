"""Choix des grands thèmes sur un gros corpus : réflexion de Qwen coupée, réponse vide redemandée, sujets par parties."""
import asyncio
import json

import httpx
import pytest

from app.services import analysis_service as svc
from app.services import batch_pipeline
from app.services import llm_client
from app.services.errors import InvalidModelOutput


def _spec(local=True):
    prov = svc.ProviderConf("T", "openai", "T", "", "http://localhost:11434/v1", "", 128_000, ("qwen3.6:27b",), local=local)
    return svc.ModelSpec("T:qwen3.6:27b", "qwen3.6:27b", prov, "", 3, 3, 3, "balanced")


def _install(monkeypatch, handler):
    monkeypatch.setattr(llm_client, "_CLIENTS", {"default": httpx.AsyncClient(transport=httpx.MockTransport(handler))})


def _events(*deltas):
    return "".join(f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in deltas) + "data: [DONE]\n\n"


def _analysis(an_id="t1"):
    return svc.Analysis(an_id, "global", "synth", "T:qwen3.6:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))


def test_reflexion_coupee_par_reasoning_effort_pour_ollama(monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=_events({"content": "{}"}), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    asyncio.run(svc._complete(_spec(), "Consigne", "Extrait"))
    assert seen["reasoning_effort"] == "none" and seen["think"] is False


def test_reasoning_effort_refuse_la_requete_repart_sans(monkeypatch):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(400, json={"error": {"message": "Unrecognized request argument: reasoning_effort"}})
        return httpx.Response(200, text=_events({"content": "{}"}), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    assert asyncio.run(svc._complete(_spec(), "Consigne", "Extrait")) == "{}"
    assert len(sent) == 2 and "reasoning_effort" not in sent[1]


def test_reflexion_sans_reponse_donne_une_erreur_explicite_et_l_activite(monkeypatch):
    def handler(request):
        text = _events(*({"reasoning": f"Je trie le sujet {i}. "} for i in range(40)), {"content": ""})
        return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    a = _analysis()
    token = svc._ACTIVITY.set(a.activity)
    try:
        with pytest.raises(InvalidModelOutput, match="réfléchir sans rien écrire"):
            asyncio.run(svc._complete(_spec(), "Consigne", "Extrait"))
        assert a._activity()["phase"] == "thinking" and a._activity()["chars"] > 0
    finally:
        svc._ACTIVITY.reset(token)


def test_reflexion_en_boucle_interrompue(monkeypatch):
    def handler(request):
        text = _events(*({"reasoning_content": "Je reprends la liste depuis le début, encore une fois. "}
                         for _ in range(200)))
        return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    with pytest.raises(InvalidModelOutput, match="en boucle"):
        asyncio.run(svc._complete(_spec(), "Consigne", "Extrait"))


def test_370_sujets_choisis_par_parties_puis_reunis(monkeypatch, tmp_path):
    monkeypatch.setattr(svc.settings, "STORAGE_DIR", tmp_path)
    calls = []

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        calls.append(user)
        if "proposés séparément" in system_prompt:
            assert user.count("\n") < 20  # réunion : la liste des thèmes, pas celle des sujets
            return {"title": "Étude", "themes": [{"title": "Thème commun", "scope": "tout"}]}
        n = len(calls)
        if n == 2:  # une partie dont la réponse reste vide : coupée en deux
            raise InvalidModelOutput("Réponse vide")
        return {"title": "Étude", "themes": [{"title": f"Thème {n}", "scope": "s"}]}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    topics = "\n".join(f"- Sujet numéro {i} repéré dans un lot" for i in range(370))
    a = _analysis()
    title, themes = asyncio.run(batch_pipeline._propose_themes(a, [_spec()], topics, []))
    parts = [u for u in calls if "Sujet numéro" in u]
    assert max(u.count("\n") + 1 for u in parts) <= batch_pipeline.THEMES_PART_TOPICS
    assert sum(u.count("Sujet numéro") for u in parts[2:4]) == parts[1].count("Sujet numéro")  # moitiés redemandées
    assert title == "Étude" and themes == [{"title": "Thème commun", "scope": "tout", "items": []}]
    assert "partie" in a.step_notes[2]


def test_reunion_ratee_garde_les_themes_des_parties(monkeypatch, tmp_path):
    monkeypatch.setattr(svc.settings, "STORAGE_DIR", tmp_path)

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        if "proposés séparément" in system_prompt:
            raise InvalidModelOutput("Réponse vide")
        first = user.split("\n", 1)[0]
        return {"themes": [{"title": f"Thème {first[-3:]}", "scope": "s"}, {"title": "Commun", "scope": "s"}]}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    topics = "\n".join(f"- Sujet {i:03d}" for i in range(200))
    _, themes = asyncio.run(batch_pipeline._propose_themes(_analysis(), [_spec()], topics, []))
    titles = [t["title"] for t in themes]
    assert titles.count("Commun") == 1 and len(titles) == 4  # 3 parties + le thème commun, sans doublon
