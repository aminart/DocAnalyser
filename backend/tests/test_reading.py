"""Lecture des documents : rien d'inventé, ordre conservé, repères de ligne, encodages."""
from fpdf import FPDF
from docx import Document
from pptx import Presentation
from pptx.util import Inches

from app.services.parser_service import MultiFormatDocumentParser

P = MultiFormatDocumentParser()


def test_pdf_page_sans_texte_signalee_et_non_inventee(tmp_path):
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    pdf.add_page()
    pdf.cell(0, 10, "Bonjour page 1")
    pdf.add_page()  # page scannée simulée
    pdf.output(str(tmp_path / "d.pdf"))
    r = P.parse(tmp_path / "d.pdf", "d.pdf")
    assert [b.location for b in r.blocks] == ["Page 1"]
    assert r.warnings and "p. 2" in r.warnings[0]
    assert all("schéma" not in b.content.lower() for b in r.blocks)
    assert r.blocks[0].content == "Bonjour page 1"


def test_word_tableau_reste_a_sa_place_et_titres_reperes(tmp_path):
    d = Document()
    d.add_heading("Contexte", level=1)
    d.add_paragraph("Avant le tableau.")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Délai", "72 h"
    d.add_paragraph("Après le tableau.")
    d.save(tmp_path / "a.docx")
    lines = P.parse(tmp_path / "a.docx", "a.docx").blocks[0].content.splitlines()
    assert lines[0] == "§1: ## Contexte"
    assert lines[2].startswith("§3: [Tableau 1, ligne 1]") and "72 h" in lines[2]
    assert lines[3] == "§4: Après le tableau."


def test_powerpoint_formes_groupees_lues_dans_l_ordre(tmp_path):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(1), Inches(2), Inches(3), Inches(1)).text_frame.text = "Texte dans un groupe"
    slide.shapes.add_textbox(Inches(1), Inches(0.5), Inches(3), Inches(1)).text_frame.text = "Titre en haut"
    prs.slides.add_slide(prs.slide_layouts[6])  # slide sans texte
    prs.save(tmp_path / "b.pptx")
    r = P.parse(tmp_path / "b.pptx", "b.pptx")
    assert r.blocks[0].content.splitlines() == ["Titre en haut", "Texte dans un groupe"]
    assert r.warnings and "2" in r.warnings[0]


def test_csv_windows_1252_point_virgule(tmp_path):
    (tmp_path / "c.csv").write_bytes("Prénom;Remarque\nRené;Délai trop long\n".encode("cp1252"))
    content = P.parse(tmp_path / "c.csv", "c.csv").blocks[0].content
    assert "L2: | René | Délai trop long |" in content


def test_texte_numerote_par_ligne_et_texte_brut_sans_reperes(tmp_path):
    (tmp_path / "e.txt").write_text("ligne un\n\nligne trois\n", encoding="utf-8")
    block = P.parse(tmp_path / "e.txt", "e.txt").blocks[0]
    assert block.content == "L1: ligne un\nL3: ligne trois"
    assert block.plain_text() == "ligne un\nligne trois"


def test_sous_titres_horodates(tmp_path):
    (tmp_path / "f.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nBonjour\n\n00:01:10.500 --> 00:01:12.000\nOn commence\n",
        encoding="utf-8",
    )
    block = P.parse(tmp_path / "f.vtt", "f.vtt").blocks[0]
    assert block.content == "00:00:01: Bonjour\n00:01:10: On commence"
    assert block.plain_text() == "Bonjour\nOn commence"
