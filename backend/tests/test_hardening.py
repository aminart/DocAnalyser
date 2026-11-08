"""Garde-fous : API réservée à l'interface locale, anciens formats Office, taille d'import, export PDF Unicode."""
import fitz
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.export_service import markdown_to_pdf


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8020", "http://localhost:5173"])
def test_cors_autorise_l_interface_locale(client, origin):
    r = client.get("/api/v2/analyses", headers={"Origin": origin})
    assert r.headers.get("access-control-allow-origin") == origin


@pytest.mark.parametrize("origin", ["https://site-malveillant.example", "http://127.0.0.1.example.com"])
def test_cors_refuse_les_autres_sites(client, origin):
    r = client.get("/api/v2/analyses", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers
    pre = client.options("/api/v2/connections/test", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert "access-control-allow-origin" not in pre.headers


@pytest.mark.parametrize("name,modern", [("vieux.doc", ".docx"), ("tableau.xls", ".xlsx"), ("diapo.ppt", ".pptx")])
def test_anciens_formats_office_message_clair(client, name, modern):
    r = client.post("/api/v2/documents", files={"file": (name, b"\xd0\xcf\x11\xe0 contenu binaire")})
    assert r.status_code == 422
    assert modern in r.json()["detail"] and "Enregistrer sous" in r.json()["detail"]


def test_fichier_trop_gros_refuse(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    r = client.post("/api/v2/documents", files={"file": ("gros.txt", b"a" * (1024 * 1024 + 1))})
    assert r.status_code == 413 and "1 Mo" in r.json()["detail"]


def test_export_pdf_garde_la_typographie():
    pdf = markdown_to_pdf("Synthèse « œuvre » — bilan", "## Thème 1\n- Cœur “citation” → Ελληνικά\nTexte **gras**")
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        text = doc[0].get_text()
    for attendu in ("Synthèse « œuvre » — bilan", "Cœur “citation” → Ελληνικά", "Texte gras"):
        assert attendu in text
