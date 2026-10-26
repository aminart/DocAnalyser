"""Repli automatique : un gros corpus refusé d'un bloc par le fournisseur est analysé par lots."""
import asyncio

import litellm

from app.services import analysis_service as svc
from app.services import batch_pipeline


def test_gros_corpus_refuse_d_un_bloc_bascule_en_lots(fixtures_dir, monkeypatch):
    calls = []

    async def fake_complete(spec, system_prompt, user, want_json=True, on_text=None):
        calls.append(len(user))
        # Le fournisseur refuse la requête démesurée (cas d'une clé gratuite limitée par minute).
        raise litellm.ServiceUnavailableError("overloaded", llm_provider="gemini", model=spec.name)

    async def fake_batches(analysis, chain, checker):
        assert analysis.batched and analysis.context_cap == svc.FALLBACK_REQUEST_TOKENS
        assert batch_pipeline.window_tokens(chain[0], analysis.context_cap) <= svc.FALLBACK_REQUEST_TOKENS
        return {"title": "T", "brief": "b", "themes": [{"title": "Thème", "summary": "s", "points": []}],
                "actions": [], "coverage": {"batches": 3, "items": 10, "unassigned": 0, "recovered": 0}}

    monkeypatch.setattr(svc, "_complete", fake_complete)
    monkeypatch.setattr(svc, "LARGE_REQUEST_TOKENS", 10)  # le petit document de test compte comme « gros »
    monkeypatch.setattr(batch_pipeline, "run_themes", fake_batches)
    monkeypatch.setattr(svc.settings, "GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(svc.settings, "GEMINI_TEST_MODELS", "gemini-3.8-flash,gemini-3.5-flash-lite")

    doc = svc.store_document((fixtures_dir / "compte_rendu_6_sujets.txt").read_bytes(), "cr.txt")

    async def go():
        a = svc.create_analysis([doc.id], "global", "detail", "GEMINI:gemini-3.8-flash", "fr", True)
        await a.task
        return a

    a = asyncio.run(go())
    assert a.status == "done", a.error
    assert a.batched and "passage à l'analyse par lots" in a.step_notes[1]
    assert len(calls) == 2  # un seul essai par modèle pour la requête démesurée, pas de réessais en boucle


def test_json_tolerant():
    data = svc._parse_json('Voici :\n```json\n{"items": [{"text": "ligne 1\nligne 2"},], "topics": ["a",]}\n```')
    assert data == {"items": [{"text": "ligne 1\nligne 2"}], "topics": ["a"]}


def test_lot_illisible_redecoupe_sans_rien_perdre(fixtures_dir, monkeypatch):
    """Un lot dont la réponse reste illisible est redécoupé : chaque partie est extraite, aucune n'est perdue."""
    async def fake_call(analysis, chain, system_prompt, user, want_json=True, on_text=None, patient=True):
        if user.count("[SOURCE:") > 1:
            return '{"items": [{"text": "réponse coupée'  # trop long : JSON tronqué
        line = next(l for l in user.splitlines() if l.startswith("L"))
        return '{"items": [{"kind": "fait", "text": "%s", "document": "cr.txt", "location": "%s"}], "topics": []}' % (
            line.split(": ", 1)[1].replace('"', "'"), line.split(":")[0])

    monkeypatch.setattr(svc, "_call", fake_call)
    monkeypatch.setattr(batch_pipeline, "EXTRACT_SHARE", 1.0)
    doc = svc.store_document((fixtures_dir / "compte_rendu_6_sujets.txt").read_bytes(), "cr.txt")
    doc.blocks = [svc.AnchoredTextBlock("cr.txt", f"Lignes L{i}", f"L{i}: Information {i}") for i in range(1, 7)]
    spec = svc.ModelSpec("T:m", "m", svc.ProviderConf("T", "openai", "T", "", "http://x", "", 200_000, ("m",)),
                         "", 3, 3, 3, "balanced")
    a = svc.Analysis(id="split", mode="global", level="detail", model_id="T:m", language="fr", cite=True,
                     documents=[doc], created_at=__import__("datetime").datetime.now())
    items, _, _ = asyncio.run(batch_pipeline.extract(a, [spec], svc.QuoteChecker(doc.plain_text())))
    assert sorted(i.text for i in items) == [f"Information {i}" for i in range(1, 7)]


def test_classement_degage_de_nouveaux_themes_et_redemande_les_oublis(monkeypatch):
    """Scénario du glossaire de 299 pages : 1 seul thème proposé et un modèle qui oublie des éléments."""
    domains = ["air", "mer", "terre", "logistique"]
    items = [batch_pipeline.Item(f"e{k}", "fait", f"Définition {domains[k % 4]} numéro {k}", "g.pdf", f"Page {k}")
             for k in range(1, 201)]
    seen_assign = []

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        if '"themes"' in system_prompt:  # proposition de thèmes
            if "Thèmes existants" in system_prompt:
                return {"themes": [{"title": f"Domaine {d}", "scope": d} for d in domains[1:]]}
            return {"title": "Glossaire", "themes": [{"title": "Domaine air", "scope": "air"}]}
        # classement : le modèle ne renvoie que la moitié des identifiants au premier passage
        ids = [l.split(" ", 1)[0] for l in user.splitlines()[1:]]
        seen_assign.append(len(ids))
        titles = [l.split(". ", 1)[1].split(" — ")[0] for l in system_prompt.split("Thèmes :\n")[1].split("\n\n")[0].splitlines()]
        out = {}
        for line in user.splitlines()[1:]:
            item_id, text = line.split(" ", 1)
            match = next((n for n, t in enumerate(titles, 1) if t.split()[-1] in text), 0)
            out[item_id] = match
        if len(seen_assign) == 1:
            out = dict(list(out.items())[::2])
        return {"assign": out}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    spec = svc.ModelSpec("T:m", "m", svc.ProviderConf("T", "openai", "T", "", "http://x", "", 200_000, ("m",)),
                         "", 3, 3, 3, "balanced")
    a = svc.Analysis(id="cls", mode="global", level="detail", model_id="T:m", language="fr", cite=True,
                     documents=[], created_at=__import__("datetime").datetime.now())
    title, themes, unassigned = asyncio.run(batch_pipeline.classify(a, [spec], items, ["Glossaire militaire"]))

    assert max(seen_assign) <= batch_pipeline.ASSIGN_MAX_ITEMS  # paquets limités
    assert {t["title"] for t in themes} == {f"Domaine {d}" for d in domains}  # thèmes dégagés des restes
    assert unassigned == 0 and sum(len(t["items"]) for t in themes) == len(items)


def test_redaction_refusee_isolee_et_element_repris_tel_quel(monkeypatch):
    """Une requête refusée (BadRequest) ne fait pas échouer l'analyse : le reste est rédigé, l'élément en cause repris."""
    items = [batch_pipeline.Item(f"e{k}", "fait", f"Fait numéro {k} sur le thème", "g.pdf", f"Page {k}") for k in range(1, 9)]

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        if "Fait numéro 5 " in user:
            raise svc.AnalysisError("Le fournisseur de m a refusé une requête : Request contains an invalid argument.")
        facts = [l.split(") ", 1)[1] for l in user.splitlines() if l.startswith("e")]
        return {"theme": {"title": "T", "summary": "Résumé.", "points": [{"lead": f, "body": "", "sources": []} for f in facts]},
                "actions": []}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    spec = svc.ModelSpec("T:m", "m", svc.ProviderConf("T", "openai", "T", "", "http://x", "", 200_000, ("m",)),
                         "", 3, 3, 3, "balanced")
    a = svc.Analysis(id="wr", mode="global", level="detail", model_id="T:m", language="fr", cite=True,
                     documents=[], created_at=__import__("datetime").datetime.now())
    [theme] = asyncio.run(batch_pipeline.write_themes(a, [spec], [{"title": "T", "scope": "s", "items": items}]))
    leads = " ".join(p["lead"] for p in theme["points"])
    assert all(f"Fait numéro {k} " in leads for k in range(1, 9))  # rien de perdu
    assert "repris tels qu'extraits" in theme["summary"]
