"""Choix des pages (PDF) ou slides (PowerPoint) à analyser, au lancement de l'analyse."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import analysis_service as svc
from app.services import store


def _pdf(n=20, skip=()):
    blocks = [svc.AnchoredTextBlock("rapport.pdf", f"Page {i}", f"Texte de la page {i}")
              for i in range(1, n + 1) if i not in skip]
    doc = svc.StoredDocument("pdf-1", "rapport.pdf", "pdf", 1000, f"{n} pages", len(blocks), blocks)
    svc.DOCUMENTS[doc.id] = doc
    return doc


@pytest.mark.parametrize("text, expected", [
    ("12-45, 80", [(12, 45), (80, 80)]),
    ("12 à 45 ; 3", [(12, 45), (3, 3)]),
    ("100-", [(100, 299)]),
    ("-5", [(1, 5)]),
    ("50-40", [(40, 50)]),
    ("290-400", [(290, 299)]),
])
def test_selection_lue(text, expected):
    assert svc.parse_selection(text, 299) == expected


@pytest.mark.parametrize("text, message", [("abc", "pas une sélection"), ("400", "n'existe pas"), ("0", "n'existe pas")])
def test_selection_illisible_message_clair(text, message):
    with pytest.raises(svc.AnalysisError, match=message):
        svc.parse_selection(text, 299)


def test_pdf_reduit_aux_pages_choisies_meme_nom_pour_les_sources():
    doc = _pdf(skip={4})  # page 4 scannée : pas de texte
    assert doc.public()["sections"] == "pages" and doc.public()["last_section"] == 20
    sel = svc.select_sections(doc, "3-5, 18")
    assert [b.location for b in sel.blocks] == ["Page 3", "Page 5", "Page 18"]
    assert sel.name == doc.name and sel.id != doc.id and sel.pages == 3
    assert sel.units == "3 pages sur 20 pages (p. 3-5, 18)"
    assert sel.id in {d.id for d in store.load_all()[0].values()}  # enregistré : l'historique le retrouve
    with pytest.raises(svc.AnalysisError, match="Aucune page avec du texte"):
        svc.select_sections(doc, "4")


def test_document_sans_pages_non_selectionnable():
    doc = svc.StoredDocument("txt-1", "notes.txt", "txt", 10, "3 lignes", 1,
                             [svc.AnchoredTextBlock("notes.txt", "Lignes L1-L3", "L1: a")])
    assert doc.public()["sections"] is None
    with pytest.raises(svc.AnalysisError, match="ne se découpe pas en pages"):
        svc.select_sections(doc, "1-2")


def test_lancement_avec_pages_choisies(monkeypatch):
    doc = _pdf()
    launched = {}

    async def fake_run(analysis, spec):
        launched["blocks"] = [b.location for d in analysis.documents for b in d.blocks]

    monkeypatch.setattr(svc, "_run", fake_run)
    monkeypatch.setattr(svc.settings, "GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(svc.settings, "GEMINI_TEST_MODELS", "gemini-3.8-flash")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = {"document_ids": [doc.id], "mode": "global", "level": "detail", "model_id": "GEMINI:gemini-3.8-flash",
                "sections": {doc.id: "2-3"}}
        res = client.post("/api/v2/analyses", json=body)
        assert res.status_code == 202, res.text
        assert res.json()["documents"][0]["units"].startswith("2 pages sur 20")
        bad = client.post("/api/v2/analyses", json={**body, "sections": {doc.id: "30"}})
        assert bad.status_code == 400 and "n'existe pas" in bad.json()["detail"]
    assert launched["blocks"] == ["Page 2", "Page 3"]
