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


def _flow_fake(calls, fail_first_phase=False):
    """Faux modèle du mode Parcours : répond selon la consigne reçue, et note la taille de chaque requête."""
    import re as _re

    state = {"failed": False}

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        calls.append((system_prompt, user))
        if "identifie uniquement les étapes du parcours dont parle cette partie" in system_prompt:
            return {"title": "Parcours d'achat", "phases": [{"name": "Inscription", "scope": "Création du compte"},
                                                           {"name": "Paiement", "scope": "Règlement"}]}
        if "Établis la liste unique des étapes" in system_prompt:
            return {"title": "Parcours d'achat", "phases": [{"name": "Inscription", "scope": "Création du compte"},
                                                           {"name": "Paiement", "scope": "Règlement"}]}
        if "entre les étapes d'un parcours" in system_prompt:
            ids = _re.findall(r"^(e\d+) ", user, _re.M)
            return {"assign": {i: (0 if i == "e7" else 1 + int(i[1:]) % 2) for i in ids}}
        if "Rédige une seule étape" in system_prompt:
            if fail_first_phase and not state["failed"]:
                state["failed"] = True
                raise svc.InvalidModelOutput("illisible")
            step = "Paiement" if "Étape à rédiger : 2." in user else "Inscription"
            return {"phase": {"does": f"L'utilisateur avance ({step})", "frictions": [f"Friction {step}"],
                              "touchpoints": ["Site web"]},
                    "priorities": [{"severity": "Majeur", "title": f"Blocage {step}", "body": "b"}]}
        if "Réunis-les en une seule description" in system_prompt:
            return {"phase": {"does": "Description réunie", "frictions": ["Friction réunie"]}}
        if "Donne le titre du parcours" in system_prompt:
            return {"title": "Achat en ligne", "brief": "Un *parcours* simple.",
                    "flow": {"nodes": [{"id": "a", "label": "Inscription", "type": "entry"},
                                       {"id": "b", "label": "Paiement", "type": "goal"}],
                             "edges": [{"from": "a", "to": "b", "kind": "main"}]}}
        raise AssertionError("consigne inattendue : " + system_prompt[:200])

    return fake_call_json


def test_parcours_d_un_tres_gros_document_redige_etape_par_etape(monkeypatch):
    """Mode Parcours, liste d'éléments bien plus grande que la fenêtre : aucune requête ne dépasse la fenêtre,
    chaque élément est rangé dans une étape, et rien n'est perdu (élément hors étape repris tel quel)."""
    from app.services import batch_pipeline

    kinds = ["etape", "friction", "transition", "attente", "sortie", "fait"]
    items = [batch_pipeline.Item(f"e{i}", kinds[i % len(kinds)], f"Constat {i} " + "z" * 80, "cr.txt", f"L{i}")
             for i in range(1, 301)]
    calls = []

    async def fake_extract(analysis, chain, checker):
        return list(items), [], 40

    monkeypatch.setattr(batch_pipeline, "extract", fake_extract)
    monkeypatch.setattr(svc, "_call_json", _flow_fake(calls, fail_first_phase=True))
    monkeypatch.setattr(batch_pipeline, "budget_chars", lambda spec, cap=0: 3000)
    a = svc.Analysis("fb1", "flow", "detail", "T:qwen:27b", "fr", True, [], svc.datetime.now(svc.timezone.utc))
    data = asyncio.run(batch_pipeline.run_flow(a, [_spec()], svc.QuoteChecker("")))

    # Taille de chaque requête bornée par la fenêtre, quel que soit le nombre d'éléments (≈ 30 000 caractères ici).
    assert max(len(u) for _, u in calls) <= 3000
    assert sum(1 for p, _ in calls if "dont parle cette partie" in p) > 1  # plan des étapes par parties
    assert any("Établis la liste unique des étapes" in p for p, _ in calls)

    result = svc.normalize_journey(data, ["cr.txt"], svc.QuoteChecker(""))
    assert [p["name"] for p in result["phases"]] == ["Inscription", "Paiement"]
    assert result["title"] == "Achat en ligne" and len(result["flow"]["nodes"]) == 2
    assert {p["phase"] for p in data["priorities"]} == {"Inscription", "Paiement"}
    # e7 n'est rangé dans aucune étape ; l'élément de la partie illisible, redécoupée, reste rédigé ou repris.
    assert any(e["location"] == "L7" for e in result["extra"])
    assert data["coverage"]["recovered"] == len(data["extra"])
    assert "étape par étape" in a.step_notes[1] and "(2/2)" in a.step_notes[3]

    # Reprise : tout ce qui a été rédigé est relu sur le disque ; seule la partie qui avait échoué est redemandée.
    calls.clear()
    a2 = svc.Analysis("fb2", "flow", "detail", "T:qwen:27b", "fr", True, [], svc.datetime.now(svc.timezone.utc))
    asyncio.run(batch_pipeline.run_flow(a2, [_spec()], svc.QuoteChecker("")))
    assert len(calls) == 1 and "Rédige une seule étape" in calls[0][0]


def test_parcours_qui_tient_dans_la_fenetre_reste_en_deux_appels(monkeypatch):
    from app.services import batch_pipeline

    items = [batch_pipeline.Item(f"e{i}", "etape", f"Étape courte {i}", "cr.txt", f"L{i}") for i in range(1, 6)]
    prompts = []

    async def fake_extract(analysis, chain, checker):
        return list(items), [], 2

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        prompts.append(system_prompt)
        if "Première passe" in system_prompt:
            return {"title": "T", "phases": [{"name": "Étape"}]}
        return {"title": "T", "phases": [{"name": "Étape", "does": "x"}], "flow": {"nodes": [], "edges": []},
                "priorities": []}

    monkeypatch.setattr(batch_pipeline, "extract", fake_extract)
    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    a = svc.Analysis("fs1", "flow", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    data = asyncio.run(batch_pipeline.run_flow(a, [_spec()], svc.QuoteChecker("")))
    assert len(prompts) == 2 and data["phases"][0]["name"] == "Étape"


def test_classement_qui_invente_des_elements_interrompu_et_repris(monkeypatch):
    """Identification des thèmes : un paquet dont la réponse numérote des éléments inexistants est interrompu,
    l'analyse continue, et une reprise relit les paquets déjà classés."""
    from app.services import batch_pipeline

    items = [batch_pipeline.Item(f"e{i}", "fait", f"Constat {i} " + "z" * 50, "cr.txt", f"L{i}") for i in range(1, 31)]
    calls = []
    loop = {"on": True}

    async def fake_call_json(analysis, chain, system_prompt, user, on_text=None, **kw):
        if "Établis la liste" in system_prompt or "thèmes supplémentaires" in system_prompt:
            return {"title": "Étude", "themes": [{"title": "Thème A", "scope": "tout"}]}
        calls.append(user)
        ids = [l.split(" ", 1)[0] for l in user.splitlines()[1:]]
        if loop["on"] and len(calls) == 1:
            text = '{"assign": {' + ", ".join(f'"e{n}": 1' for n in range(1, 500))
            on_text(text)  # doit lever avant
            raise AssertionError("réponse en boucle non interrompue")
        return {"assign": {i: 1 for i in ids}}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    monkeypatch.setattr(batch_pipeline, "budget_chars", lambda spec, cap=0: 1500)
    a = svc.Analysis("c1", "global", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    title, themes, unassigned = asyncio.run(batch_pipeline.classify(a, [_spec()], items, ["sujet"]))
    assert sum(len(t["items"]) for t in themes) == 30 and unassigned == 0  # paquet raté redemandé au second passage
    assert "classé" in a.step_notes[2] and a.eta_at > 0
    n = len(calls)

    a2 = svc.Analysis("c2", "global", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    asyncio.run(batch_pipeline.classify(a2, [_spec()], items, ["sujet"]))
    assert len(calls) == n  # tout est relu sur le disque


def test_redaction_d_un_theme_en_delai_depasse_redecoupee_puis_reprise(monkeypatch):
    from app.services import batch_pipeline

    items = [batch_pipeline.Item(f"e{i}", "fait", f"Constat {i}", "cr.txt", f"L{i}") for i in range(1, 5)]
    calls = []

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        calls.append(user)
        if user.count("[fait]") > 1:
            raise svc.ProviderUnavailable("délai dépassé", timed_out=True)
        return {"summary": "", "points": [{"lead": user.split("[fait] (cr.txt ")[1].split(")")[1].strip()}]}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    a = svc.Analysis("w1", "global", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    themes = [{"title": "A", "scope": "tout", "items": items}]
    written = asyncio.run(batch_pipeline.write_themes(a, [_spec()], themes))
    assert len(written) == 1  # le délai dépassé n'arrête pas l'analyse : partie redécoupée
    n = len(calls)
    asyncio.run(batch_pipeline.write_themes(a, [_spec()], themes))
    assert len(calls) == n + 3  # reprise : les 4 parties rédigées sont relues, seules les 3 en délai dépassé sont redemandées


def test_titre_et_en_bref_en_echec_n_arretent_pas_l_analyse(monkeypatch):
    from app.services import batch_pipeline

    async def fake_call_json(*a, **kw):
        raise svc.InvalidModelOutput("boucle")

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    a = svc.Analysis("w2", "global", "synth", "T:qwen:27b", "fr", False, [], svc.datetime.now(svc.timezone.utc))
    data = asyncio.run(batch_pipeline.assemble(a, [_spec()], "Titre des thèmes", [{"title": "A", "summary": "s"}]))
    assert data["title"] == "Titre des thèmes" and data["brief"] == ""


def test_transcription_d_image_en_boucle_interrompue(monkeypatch):
    from app.services import vision_service

    line = "Le même texte lu sur l'image, répété indéfiniment par le modèle de vision.\n"

    def handler(request):
        return httpx.Response(200, text=_sse(*([line] * 400)), headers={"content-type": "text/event-stream"})

    _install(monkeypatch, handler)
    with pytest.raises(InvalidModelOutput):
        asyncio.run(vision_service._read_one(_spec(), b"img", "Image : x"))
