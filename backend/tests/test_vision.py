"""Images des documents lues par un modèle qui voit les images (facultatif)."""
import asyncio
import io
import json
from datetime import datetime

import httpx
import pytest
from PIL import Image, ImageDraw

from app.services import analysis_service as svc
from app.services import image_reader, llm_client, vision_service


def _png(w=400, h=300, color="white") -> bytes:
    img = Image.new("RGB", (w, h), color)
    ImageDraw.Draw(img).rectangle([20, 20, w - 20, h - 20], outline="black", width=4)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _pdf(tmp_path) -> bytes:
    from fpdf import FPDF

    (tmp_path / "schema.png").write_bytes(_png())
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    pdf.add_page()
    pdf.cell(0, 10, "Rapport annuel : chiffres clés de la page un.".encode("latin-1", "replace").decode("latin-1"))
    pdf.image(str(tmp_path / "schema.png"), x=20, y=40, w=100)
    pdf.add_page()  # page scannée : une image, aucun texte
    pdf.image(str(tmp_path / "schema.png"), x=0, y=0, w=210)
    return bytes(pdf.output())


def _pptx(tmp_path) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    (tmp_path / "photo.png").write_bytes(_png())
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Atelier"
    slide.shapes.add_picture(str(tmp_path / "photo.png"), Inches(1), Inches(2))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _docx(tmp_path) -> bytes:
    from docx import Document
    from docx.shared import Inches

    (tmp_path / "photo.png").write_bytes(_png())
    doc = Document()
    doc.add_paragraph("Compte rendu avec une photo du tableau blanc.")
    doc.add_picture(str(tmp_path / "photo.png"), width=Inches(3))
    doc.add_picture(str(tmp_path / "photo.png"), width=Inches(3))  # même image deux fois : une seule fois
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_images_mises_de_cote_a_l_import(tmp_path):
    pdf = svc.store_document(_pdf(tmp_path), "rapport.pdf")
    assert [(i["location"], i["scanned"]) for i in pdf.images] == [("Page 1", False), ("Page 2", True)]
    assert [b.location for b in pdf.blocks] == ["Page 1"] and "seulement avec un modèle qui voit" in pdf.warnings[0]
    assert pdf.public()["images"] == 2

    pptx = svc.store_document(_pptx(tmp_path), "atelier.pptx")
    assert [i["location"] for i in pptx.images] == ["Slide 1"]
    docx = svc.store_document(_docx(tmp_path), "cr.docx")
    assert [i["location"] for i in docx.images] == ["Image 1"]

    png = svc.store_document(_png(), "tableau.png")
    assert png.public()["images_only"] and png.units == "1 image" and png.images[0]["scanned"]
    assert (image_reader.images_dir() / png.images[0]["file"]).exists()


def test_petite_image_ignoree():
    assert image_reader._normalize(_png(60, 60)) is None  # logo, icône


def test_sans_modele_de_vision_document_image_seule_refuse_au_lancement(monkeypatch):
    monkeypatch.setattr(svc.settings, "GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(svc.settings, "GEMINI_TEST_MODELS", "gemini-3.8-flash")
    doc = svc.store_document(_png(), "seule.png")
    with pytest.raises(svc.AnalysisError, match="ne contient que des images"):
        svc.create_analysis([doc.id], "global", "detail", "GEMINI:gemini-3.8-flash", "fr", True)


def _vision_analysis(docs):
    return svc.Analysis(id="vis", mode="global", level="detail", model_id="T:m", language="fr", cite=True,
                        documents=docs, created_at=datetime.now(), vision_model_id="T:vision")


def _install(monkeypatch, handler):
    monkeypatch.setattr(llm_client, "_CLIENTS", {"default": httpx.AsyncClient(transport=httpx.MockTransport(handler))})
    prov = svc.ProviderConf("T", "openai", "T", "", "https://llm.test/v1", "", 128_000, ("vision",))
    spec = svc.ModelSpec("T:vision", "vision", prov, "", 3, 3, 3, "balanced")
    monkeypatch.setattr(svc, "get_model", lambda model_id: spec)


def _sse(text):
    return httpx.Response(200, text=f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\ndata: [DONE]\n\n",
                          headers={"content-type": "text/event-stream"})


def test_images_lues_et_inserees_a_leur_page(tmp_path, monkeypatch):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        label = body["messages"][1]["content"][0]["text"]
        return _sse("RIEN" if "Page 1" in label else "Ventes 2025 | 12 M€")

    _install(monkeypatch, handler)
    doc = svc.store_document(_pdf(tmp_path), "rapport.pdf")
    a = _vision_analysis([doc])
    asyncio.run(vision_service.read_images(a))

    assert bodies[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert [b.location for b in doc.blocks] == ["Page 1", "Page 2"]  # image décorative ignorée, scan à sa place
    assert doc.blocks[1].content == "[Page scannée, lue par le modèle de vision]\nVentes 2025 | 12 M€"
    assert all(i["done"] for i in doc.images) and "Images lues par vision : 2/2" in a.step_notes[0]

    # Le même document importé à nouveau : les images déjà lues ne sont pas redemandées au modèle.
    bodies.clear()
    again = svc.store_document(_pdf(tmp_path), "rapport.pdf")
    asyncio.run(vision_service.read_images(_vision_analysis([again])))
    assert bodies == [] and again.blocks[1].content.endswith("12 M€")


def test_modele_sans_vision_analyse_sur_le_texte_seul(tmp_path, monkeypatch):
    _install(monkeypatch, lambda r: httpx.Response(400, json={"error": {"message": "image input is not supported"}}))
    doc = svc.store_document(_pdf(tmp_path), "rapport.pdf")
    a = _vision_analysis([doc])
    asyncio.run(vision_service.read_images(a))
    assert [b.location for b in doc.blocks] == ["Page 1"]  # texte intact
    assert "n'a pas pu lire les images" in a.step_notes[0] and "texte seul" in a.step_notes[0]
