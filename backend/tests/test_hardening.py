"""Garde-fous : API réservée à l'interface locale, anciens formats Office, taille d'import, export PDF Unicode."""
import io

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.export_service import markdown_to_pdf


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.mark.parametrize("origin", ["https://site-malveillant.example", "http://127.0.0.1.example.com",
                                    "http://localhost:5173", "http://127.0.0.1:8110"])
def test_aucune_autre_page_ne_lit_l_api(client, origin):
    """Pas de CORS : ni un site, ni une autre app sur localhost ne lit l'historique ou les connexions."""
    r = client.get("/api/v2/analyses", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers
    pre = client.options("/api/v2/connections/test", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert "access-control-allow-origin" not in pre.headers


def test_hote_inconnu_refuse_dns_rebinding(client):
    assert client.get("/api/v2/analyses", headers={"host": "piege.example.com:8020"}).status_code == 403
    assert client.get("/health", headers={"host": "localhost:8020"}).status_code == 200


def test_requete_d_un_autre_site_refusee(client):
    for chemin in ("/api/v2/documents", "/api/v2/connections/test", "/api/v2/analyses"):
        assert client.post(chemin, json={}, headers={"origin": "https://site-malveillant.example"}).status_code == 403
    assert client.post("/api/v2/analyses", json={}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    # l'interface (même origine) et les envois sans navigateur (Snappy Transcript, Studio Dock) : acceptés
    ok = client.post("/api/v2/documents", files={"file": ("a.txt", b"bonjour")}, headers={"origin": "http://127.0.0.1"})
    assert ok.status_code == 200
    assert client.post("/api/v2/documents", files={"file": ("b.txt", b"bonjour")}).status_code == 200


def test_entetes_de_protection(client):
    r = client.get("/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cross-origin-resource-policy"] == "same-origin"


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
    from pdfminer.high_level import extract_text

    text = " ".join(extract_text(io.BytesIO(pdf)).split())
    for attendu in ("Synthèse « œuvre » — bilan", "Cœur “citation” → Ελληνικά", "Texte gras"):
        assert attendu in text
