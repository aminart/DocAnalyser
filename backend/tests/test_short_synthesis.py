"""Synthèse courte des gros documents : longueur bornée, détail en annexe, mise en page aérée."""
import asyncio
import io
from datetime import datetime, timezone

from docx import Document

from app.services import analysis_service as svc
from app.services import batch_pipeline
from app.services.export_service import markdown_to_docx
from app.services.prompts import MAX_THEME_POINTS, MIN_THEME_POINTS, POINT_BUDGET, point_quotas
from app.services.report_markdown import ANNEX_MARK, _paragraphs, without_annex

SPEC = svc.ModelSpec("T:m", "m", svc.ProviderConf("T", "openai", "T", "", "http://x", "", 200_000, ("m",)),
                     "", 3, 3, 3, "balanced")


def _analysis(level="detail", **kw):
    return svc.Analysis(id="short", mode="global", level=level, model_id="T:m", language="fr", cite=True,
                        documents=[], created_at=datetime.now(timezone.utc), **kw)


def test_quotas_petit_corpus_inchange():
    """Un corpus qui tient dans le budget est rédigé comme avant : aucun thème limité."""
    assert point_quotas([10, 8, 5], "detail") == [0, 0, 0]


def test_quotas_gros_corpus_bornes_et_ponderes():
    sizes = [400, 200, 120, 80, 60, 40, 30, 20, 15, 10, 8, 6, 5, 4, 2]  # 15 thèmes, 1 000 éléments
    for level, budget in POINT_BUDGET.items():
        quotas = point_quotas(sizes, level)
        limited = [q for q in quotas if q]
        assert all(MIN_THEME_POINTS <= q <= MAX_THEME_POINTS for q in limited)
        assert quotas[0] >= quotas[8]  # les gros thèmes gardent plus de points
        assert sum(q or n for q, n in zip(quotas, sizes)) <= budget + MIN_THEME_POINTS * len(sizes)
        assert quotas[-1] == 0  # thème de 2 éléments : déjà court, pas limité


def test_theme_limite_resserre_et_detail_en_annexe(monkeypatch):
    items = [batch_pipeline.Item(f"e{k}", "fait", f"Fait numéro {k} sur le thème", "g.pdf", f"Page {k}")
             for k in range(1, 101)]
    prompts = []

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        prompts.append(system_prompt)
        if "Résumés des parties" in user:  # réunion des parties : un résumé, quota points
            return {"summary": "Résumé unique.", "points": [{"lead": f"Point {k}", "body": "", "sources": []} for k in range(9)]}
        facts = [l.split(") ", 1)[1] for l in user.splitlines() if l.startswith("e")]
        return {"theme": {"title": "T", "summary": "Résumé partiel. Encore une phrase.",
                          "points": [{"lead": f, "body": "", "sources": []} for f in facts[:3]]}, "actions": []}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    a = _analysis()
    [theme] = asyncio.run(batch_pipeline.write_themes(a, [SPEC], [{"title": "T", "scope": "s", "items": items}], [5]))
    assert theme["summary"] == "Résumé unique."  # plus de résumés mis bout à bout
    assert len(theme["points"]) == 5  # quota respecté même si le modèle en rend plus
    assert len(theme["details"]) == 100 and theme["details"][0]["location"] == "Page 1"
    assert any("au plus" in p and "Synthèse courte" in p for p in prompts)


def test_theme_complet_resume_unique_sans_limite(monkeypatch):
    """Sans limite (petit thème ou « Synthèse complète ») : tous les points, mais un seul résumé de thème."""
    items = [batch_pipeline.Item(f"e{k}", "fait", f"Fait numéro {k}", "g.pdf", f"Page {k}") for k in range(1, 61)]

    async def fake_call_json(analysis, chain, system_prompt, user, **kw):
        if "Résumés des parties" in user:
            return {"summary": "Résumé réuni.", "points": []}
        facts = [l.split(") ", 1)[1] for l in user.splitlines() if l.startswith("e")]
        return {"theme": {"summary": "Partiel.", "points": [{"lead": f, "body": "", "sources": []} for f in facts]}}

    monkeypatch.setattr(svc, "_call_json", fake_call_json)
    [theme] = asyncio.run(batch_pipeline.write_themes(_analysis(full_length=True), [SPEC],
                                                      [{"title": "T", "scope": "s", "items": items}]))
    assert len(theme["points"]) == 60 and theme["summary"] == "Résumé réuni." and "details" not in theme


def _done(result):
    a = _analysis(status="done", title="Étude")
    a.result = result
    return a


def _result():
    point = {"lead": "Les délais sont trop longs.", "body": "9 participants sur 12 le disent.",
             "sources": [{"document": "a.pdf", "location": "Page 3"}]}
    theme = {"title": "Délais", "summary": "Un. Deux. Trois. Quatre. Cinq.", "documents": ["a.pdf"], "points": [point],
             "quote": "", "quote_check": "", "quote_by": "", "nuance": "",
             "details": [{"text": "Délai de 6 semaines", "kind": "chiffre", "document": "a.pdf", "location": "Page 4"}]}
    return {"kind": "themes", "title": "Étude", "brief": "B", "themes": [theme], "actions": []}


def test_markdown_aere_et_annexe_detachable():
    md = svc.to_markdown(_done(_result()))
    assert "- **Les délais sont trop longs.**  \n  9 participants sur 12 le disent.  \n  _Sources : a.pdf Page 3_" in md
    assert "Un. Deux. Trois.\n\nQuatre. Cinq." in md  # résumé long coupé en paragraphes
    assert ANNEX_MARK in md and "Délai de 6 semaines _(a.pdf Page 4)_" in md
    short = without_annex(md)
    assert "Délai de 6 semaines" not in short and "nnexe" not in short
    assert "Les délais sont trop longs." in short and "_Synthèse générée" in short


def test_paragraphes_courts():
    assert _paragraphs("Une phrase. Deux phrases.") == ["Une phrase. Deux phrases."]
    assert _paragraphs("") == []


def test_word_gras_retraits_et_saut_de_page():
    md = svc.to_markdown(_done(_result()))
    doc = Document(io.BytesIO(markdown_to_docx("Étude", md)))
    paras = doc.paragraphs
    lead = next(p for p in paras if p.text.startswith("Les délais"))
    assert lead.style.name == "List Bullet" and lead.runs[0].bold  # l'idée en gras
    body = next(p for p in paras if p.text.startswith("9 participants"))
    assert body.paragraph_format.left_indent  # explication en retrait, sous la puce
    src = next(p for p in paras if p.text.startswith("Sources"))
    assert src.runs[0].italic and src.runs[0].font.size.pt == 9
    assert any('w:br w:type="page"' in p._p.xml for p in paras)  # annexe sur une nouvelle page
    assert not any("**" in p.text or "<!--" in p.text for p in paras)


def test_page_web_aeree_annexe_repliee():
    from app.services.export_service import markdown_to_html

    md = svc.to_markdown(_done(_result()))
    page = markdown_to_html("Étude <test>", md).decode("utf-8")
    assert page.startswith("<!doctype html>") and "<title>Étude &lt;test&gt;</title>" in page
    assert "<li><strong>Les délais sont trop longs.</strong>" in page
    assert '<span class="src">Sources : a.pdf Page 3</span>' in page
    assert '<details class="annexe">' in page and page.index("Délai de 6 semaines") > page.index("<details")
    assert page.index("</details>") < page.index("Synthèse générée")
    assert "<script" not in page  # pas de schéma, aucun script
    short = markdown_to_html("Étude", without_annex(md)).decode("utf-8")
    assert '<details' not in short and "Délai de 6 semaines" not in short


def test_page_web_parcours_avec_schema():
    from app.services.export_service import markdown_to_html

    md = "# P\n\n## Flux\n\n```mermaid\nflowchart LR\n  a --> b\n```\n\n- A → B"
    page = markdown_to_html("P", md).decode("utf-8")
    assert '<pre class="mermaid">flowchart LR\n  a --&gt; b</pre>' in page and "mermaid@11" in page


def test_pdf_comme_la_page_web():
    import pypdfium2

    from app.services.export_service import markdown_to_pdf

    md = svc.to_markdown(_done(_result()))
    raw = markdown_to_pdf("Étude", md)
    assert b"DejaVuSansOblique" in raw  # italiques réels (sources, citations), comme la page web
    pdf = pypdfium2.PdfDocument(raw)
    first = pdf[0].get_textpage().get_text_range()
    assert "Les délais sont trop longs." in first and "Sources : a.pdf Page 3" in first
    assert "**" not in first and "_Sources" not in first and "<!--" not in first
    last = pdf[len(pdf) - 1].get_textpage().get_text_range()
    assert "Délai de 6 semaines" in last and "Délai de 6 semaines" not in first  # annexe sur sa propre page
    short = pypdfium2.PdfDocument(markdown_to_pdf("Étude", without_annex(md)))
    assert len(short) == 1
