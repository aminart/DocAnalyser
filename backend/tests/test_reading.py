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


# -- Formats refusés -------------------------------------------------------------

import json

import openpyxl
import pytest

from app.services.parser_service import UnsupportedFormat, check_format


@pytest.mark.parametrize("name", ["photo.gif", "archive.zip", "donnees.json", "sans_extension"])
def test_format_inconnu_refuse_au_lieu_d_etre_lu_comme_du_texte(name):
    with pytest.raises(UnsupportedFormat, match="ne sait pas lire"):
        check_format(name, b"\x89PNG\r\n\x1a\n\x00\x00")


def test_binaire_renomme_en_txt_refuse():
    with pytest.raises(UnsupportedFormat, match="pas de texte lisible"):
        check_format("notes.txt", b"PK\x03\x04\x00\x00binaire")
    check_format("notes.txt", "Texte accentué".encode("utf-8"))  # un vrai texte passe


def test_image_abimee_refusee_avec_un_message_clair():
    from app.services import analysis_service as svc

    with pytest.raises(svc.AnalysisError, match="pas une image lisible"):
        svc.store_document(b"\x89PNG\r\n\x1a\n\x00\x00\x00", "capture.png")


# -- PDF : en-têtes et pieds répétés, tableaux -----------------------------------------

def _rapport_pdf(path):
    pdf = FPDF()
    pdf.set_auto_page_break(False)
    pdf.set_font("helvetica", size=11)
    for i in range(1, 5):
        pdf.add_page()
        pdf.set_xy(10, 8)
        pdf.cell(0, 6, "Rapport confidentiel - Projet Alpha")
        pdf.set_xy(10, 30)
        pdf.multi_cell(0, 6, f"Constat {i} : le délai de traitement reste trop long pour les usagers. " * 3)
        if i == 2:
            with pdf.table(col_widths=(40, 30, 30)) as t:
                for r in [("Pays", "Ventes", "Part"), ("France", "120", "40 %"), ("Espagne", "80", "27 %"), ("Italie", "100", "33 %")]:
                    row = t.row()
                    for c in r:
                        row.cell(c)
        if i == 3:  # mise en page en deux colonnes de texte courant, et liste à puces
            for k in range(5):
                pdf.set_xy(10, 70 + k * 6)
                pdf.cell(90, 6, f"Texte courant de la colonne gauche, ligne {k} du paragraphe")
                pdf.set_xy(110, 70 + k * 6)
                pdf.cell(90, 6, f"Texte courant de la colonne droite, ligne {k} du paragraphe")
            for k in range(3):
                pdf.set_xy(10, 110 + k * 6)
                pdf.cell(5, 6, "-")
                pdf.set_xy(20, 110 + k * 6)
                pdf.cell(80, 6, f"point de liste {k}")
        pdf.set_xy(10, 285)
        pdf.cell(0, 6, f"Page {i} / 4")
    pdf.output(str(path))


def test_pdf_en_tetes_et_pieds_repetes_retires_et_signales(tmp_path):
    _rapport_pdf(tmp_path / "r.pdf")
    r = P.parse(tmp_path / "r.pdf", "r.pdf")
    text = "\n".join(b.content for b in r.blocks)
    assert "Rapport confidentiel" not in text and "/ 4" not in text
    assert all(f"Constat {i} :" in text for i in range(1, 5))  # le corps, qui ne diffère que d'un chiffre, reste
    assert any("Rapport confidentiel - Projet Alpha" in w and "Page 1 / 4" in w for w in r.warnings)


def test_pdf_tableau_rendu_ligne_par_ligne(tmp_path):
    _rapport_pdf(tmp_path / "r.pdf")
    page2 = P.parse(tmp_path / "r.pdf", "r.pdf").blocks[1].content.splitlines()
    i = page2.index("[Tableau]")
    assert page2[i + 1 : i + 5] == ["| Pays | Ventes | Part |", "| France | 120 | 40 % |",
                                    "| Espagne | 80 | 27 % |", "| Italie | 100 | 33 % |"]


def test_pdf_colonnes_de_texte_et_puces_ne_sont_pas_des_tableaux(tmp_path):
    _rapport_pdf(tmp_path / "r.pdf")
    page3 = P.parse(tmp_path / "r.pdf", "r.pdf").blocks[2].content
    assert "[Tableau]" not in page3 and "|" not in page3
    assert "point de liste 2" in page3


def test_pdf_court_garde_ses_en_tetes(tmp_path):
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    for i in (1, 2):
        pdf.add_page()
        pdf.cell(0, 10, "Compte rendu")
        pdf.ln()
        pdf.cell(0, 10, f"Point {i}")
    pdf.output(str(tmp_path / "c.pdf"))
    r = P.parse(tmp_path / "c.pdf", "c.pdf")
    assert all("Compte rendu" in b.content for b in r.blocks) and not r.warnings


# -- Word : en-têtes, pieds, notes, zones de texte, révisions ---------------------------

def _docx_with_xml(path, body_xml: str, footnotes_xml: str | None = None):
    """Document Word dont on remplace le corps (et les notes) par du XML écrit à la main."""
    import zipfile

    d = Document()
    d.sections[0].header.paragraphs[0].text = "Direction des usages - confidentiel"
    d.sections[0].footer.paragraphs[0].text = "Page 1"  # simple numéro : ignoré
    d.save(path)
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    doc = files["word/document.xml"].decode()
    start, end = doc.index("<w:body>") + len("<w:body>"), doc.index("<w:sectPr")
    files["word/document.xml"] = (doc[:start] + body_xml + doc[end:]).encode()
    if footnotes_xml:
        ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        files["word/footnotes.xml"] = f'<?xml version="1.0"?><w:footnotes {ns}>{footnotes_xml}</w:footnotes>'.encode()
        files["[Content_Types].xml"] = files["[Content_Types].xml"].replace(
            b"</Types>",
            b'<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            b'wordprocessingml.footnotes+xml"/></Types>',
        )
        files["word/_rels/document.xml.rels"] = files["word/_rels/document.xml.rels"].replace(
            b"</Relationships>",
            b'<Relationship Id="rIdFn" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            b'footnotes" Target="footnotes.xml"/></Relationships>',
        )
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)


def test_word_en_tetes_notes_zones_de_texte_et_revisions(tmp_path):
    body = (
        '<w:p><w:r><w:t>Le délai moyen est de 12 jours</w:t></w:r>'
        '<w:r><w:footnoteReference w:id="1"/></w:r><w:r><w:t>.</w:t></w:r></w:p>'
        '<w:p><w:r><w:t xml:space="preserve">Texte </w:t></w:r><w:ins w:id="9" w:author="A"><w:r><w:t>ajouté</w:t></w:r></w:ins>'
        '<w:del w:id="8" w:author="A"><w:r><w:delText>supprimé</w:delText></w:r></w:del></w:p>'
        '<w:p><w:r><w:t>Ancre</w:t></w:r><w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        '<mc:Choice Requires="wps"><w:drawing><w:txbxContent><w:p><w:r><w:t>Encadré important</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>'
        '<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>Encadré important</w:t></w:r></w:p></w:txbxContent></w:pict></mc:Fallback>'
        '</mc:AlternateContent></w:r></w:p>'
    )
    notes = (
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:id="1"><w:p><w:r><w:t>Source : enquête interne 2025.</w:t></w:r></w:p></w:footnote>'
    )
    _docx_with_xml(tmp_path / "n.docx", body, notes)
    lines = P.parse(tmp_path / "n.docx", "n.docx").blocks[0].content.splitlines()
    assert lines[0] == "§1: Le délai moyen est de 12 jours[note 1]."
    assert lines[1] == "§2: [Note 1] Source : enquête interne 2025."
    assert lines[2] == "§3: Texte ajouté"
    assert lines[3:5] == ["§4: Ancre", "§5: [Zone de texte] Encadré important"]  # une seule fois
    assert lines[5] == "§6: [En-tête] Direction des usages - confidentiel"
    assert not any("Page 1" in ln for ln in lines)


def test_word_cellule_fusionnee_lue_une_fois(tmp_path):
    d = Document()
    t = d.add_table(rows=2, cols=3)
    t.cell(0, 0).merge(t.cell(0, 2)).text = "Synthèse"
    t.cell(1, 0).text, t.cell(1, 1).text, t.cell(1, 2).text = "a", "b", "c"
    d.save(tmp_path / "m.docx")
    lines = P.parse(tmp_path / "m.docx", "m.docx").blocks[0].content.splitlines()
    assert lines[0] == "§1: [Tableau 1, ligne 1] | Synthèse |"


# -- Excel / CSV : en-tête réel, statistiques ------------------------------------------

def test_excel_titre_au_dessus_du_tableau_et_statistiques(tmp_path):
    import datetime as dt

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Enquête satisfaction 2025"])
    ws.append([])
    ws.append(["N° dossier", "Date", "Statut", "Montant", None, "Commentaire"])
    statuts = ["Ouvert", "Fermé", "Ouvert", "Ouvert", "Fermé", "En attente"]
    for k, s in enumerate(statuts):
        ws.append([1000 + k, dt.datetime(2025, 1, k + 1), s, 10.5 * (k + 1), None, f"remarque {k}"])
    wb.save(tmp_path / "s.xlsx")
    blocks = P.parse(tmp_path / "s.xlsx", "s.xlsx").blocks
    rows = blocks[0].content.splitlines()
    assert rows[0] == "L1: | Enquête satisfaction 2025 |  |  |  |  |"  # colonne vide retirée
    assert rows[1] == "L3: | N° dossier | Date | Statut | Montant | Commentaire |"
    assert rows[2] == "L4: | 1000 | 2025-01-01 | Ouvert | 10.5 | remarque 0 |"  # date sans heure, nombre lisible
    stats = blocks[-1]
    assert stats.location == "Statistiques"
    lines = stats.content.splitlines()
    assert lines[0].startswith("[Statistiques calculées par DocAnalyser sur les 6 lignes")
    assert "« Montant » : 6 valeurs chiffrées, somme 220,5, moyenne 36,75, min 10,5, max 63" in lines
    assert "« Statut » : Ouvert 3, Fermé 2, En attente 1 (sur 6 valeurs)" in lines
    assert not any("N° dossier" in ln for ln in lines)  # pas de somme d'identifiants
    assert not any("Commentaire" in ln for ln in lines)  # texte libre : pas de répartition


def test_csv_nombres_a_la_francaise_et_en_tete_rappele(tmp_path):
    rows = ["Équipe;Heures"] + [f"Équipe {k % 2};{k + 1} 250,5" for k in range(400)]
    (tmp_path / "h.csv").write_text("\n".join(rows), encoding="utf-8")
    blocks = P.parse(tmp_path / "h.csv", "h.csv").blocks
    assert blocks[1].content.startswith("(en-tête) | Équipe | Heures |")
    assert "« Équipe » : Équipe 0 200, Équipe 1 200 (sur 400 valeurs)" in blocks[-1].content
    assert "« Heures » : 400 valeurs chiffrées" in blocks[-1].content


def test_petit_tableau_sans_statistiques(tmp_path):
    (tmp_path / "p.csv").write_text("A;B\n1;2\n3;4\n", encoding="utf-8")
    blocks = P.parse(tmp_path / "p.csv", "p.csv").blocks
    assert [b.location for b in blocks] == ["Lignes L1-3"]


# -- Page web -----------------------------------------------------------------

def test_html_texte_visible_titres_listes_tableaux(tmp_path):
    html = """<!doctype html><html><head><title>Bilan de l'atelier</title><style>p{color:red}</style>
    <script>var x = "ne pas lire";</script></head><body>
    <nav><ul><li>Accueil<li>Contact</ul></nav>
    <h1>Bilan de l'atelier</h1><p>Les usagers&nbsp;veulent <b>moins</b> de formulaires.</p>
    <ul><li>Simplifier l'inscription</li><li>Relancer par SMS</li></ul>
    <div hidden>Contenu masqué</div>
    <table><tr><th>Irritant</th><th>Fréquence</th></tr><tr><td>Délai</td><td>12</td></tr></table>
    <pre>ligne 1
ligne 2</pre></body></html>"""
    (tmp_path / "a.html").write_text(html, encoding="utf-8")
    lines = [ln.split(": ", 1)[1] for ln in P.parse(tmp_path / "a.html", "a.html").blocks[0].content.splitlines()]
    assert lines == [
        "## Bilan de l'atelier",
        "Les usagers veulent moins de formulaires.",
        "- Simplifier l'inscription",
        "- Relancer par SMS",
        "[Tableau 1, ligne 1] | Irritant | Fréquence |",
        "[Tableau 1, ligne 2] | Délai | 12 |",
        "ligne 1",
        "ligne 2",
    ]


# -- Projet Mapline -----------------------------------------------------------------

MAPLINE = {
    "version": 2,
    "title": "Parcours inscription",
    "docs": [
        {"id": "d1", "kind": "mission-map", "name": "État actuel", "map": {
            "objective": "S'inscrire à la crèche",
            "phases": [{"id": "ph1", "title": "Découvrir", "span": 1}, {"id": "ph2", "title": "S'inscrire", "span": 1}],
            "steps": [{"id": "s1", "title": "Chercher une place", "slots": ["k1"]},
                      {"id": "s2", "title": "Remplir le dossier", "slots": ["k2"]}],
            "personas": [{"id": "p1", "name": "Parent", "role": "Usager", "color": 0},
                         {"id": "p2", "name": "Agent", "role": "Mairie", "color": 1}],
            "activities": {
                "p1:k1": {"id": "a1", "text": "Consulte le site", "tags": ["irritant"], "note": "Site peu clair"},
                "p1:k1:b": {"id": "a2", "text": "Appelle la mairie", "joiner": "ou"},
                "p2:k2": {"id": "a3", "text": "Vérifie les pièces", "kind": "choice"},
            },
            "scenes": {"s1": {"img": None, "text": "Le soir, sur son téléphone"}},
            "links": [{"id": "l1", "from": "a1", "to": "a3", "label": "dossier envoyé"}],
            "dividers": [], "tagColors": {}, "styles": {}, "storyboard": True,
            "textRows": [{"id": "t1", "title": "Émotions", "cells": {"s2": "Stress"}}],
        }},
        {"id": "d2", "kind": "flow", "name": "Dépôt du dossier", "flow": {
            "nodes": [{"id": "n2", "kind": "choice", "col": 1, "row": 1, "text": "Pièces complètes ?"},
                      {"id": "n1", "kind": "start", "col": 0, "row": 0, "text": "", "personaIds": ["p1"]}],
            "links": [{"id": "f1", "from": "n1", "to": "n2"}], "styles": {}, "personaId": "p1",
        }},
        {"id": "d3", "kind": "persona", "name": "", "sheet": {
            "name": "Parent", "role": "Usager", "color": 0, "photo": None,
            "fields": [{"id": "f", "label": "Âge", "value": "34 ans"}], "quote": "Je n'ai pas le temps",
            "tags": ["pressé"], "styles": {}, "link": None, "sync": False,
            "blocks": [{"id": "b", "title": "Frustrations", "view": "gauges", "accent": "#000", "text": "",
                        "items": [{"id": "i", "text": "Délais", "level": 80}]}],
        }},
        {"id": "d4", "kind": "sitemap", "name": "Site", "sitemap": {
            "roots": [{"id": "r", "name": "Accueil", "status": "existing", "children": [
                {"id": "c", "name": "Inscription", "status": "new", "children": [],
                 "extras": [{"id": "e", "kind": "error", "name": "Pièce manquante"}]}]}],
            "globals": [{"id": "g", "name": "Mon compte", "status": "existing", "children": []}],
        }},
    ],
}


def test_projet_mapline_lu_document_par_document(tmp_path):
    (tmp_path / "p.mapline").write_text(json.dumps(MAPLINE), encoding="utf-8")
    r = P.parse(tmp_path / "p.mapline", "p.mapline")
    assert r.units == "1 carte, 1 flux, 1 persona, 1 plan du site"
    lines = [ln.split(": ", 1)[1] for ln in r.blocks[0].content.splitlines()]
    assert lines == [
        "# Projet Mapline : Parcours inscription",
        "## Carte de parcours : État actuel",
        "Objectif : S'inscrire à la crèche",
        "Personas : Parent (Usager); Agent (Mairie)",
        "## Phase : Découvrir",
        "### Étape 1 : Chercher une place",
        "- Parent : Consulte le site [étiquettes : irritant] (commentaire : Site peu clair)",
        "- Parent : ou : Appelle la mairie",
        "Storyboard : Le soir, sur son téléphone",
        "## Phase : S'inscrire",
        "### Étape 2 : Remplir le dossier",
        "- Agent : (choix) Vérifie les pièces",
        "Émotions : Stress",
        "Lien : Consulte le site → Vérifie les pièces (dossier envoyé)",
        "## Flux : Dépôt du dossier",
        "Persona principal : Parent",
        "- Début :  (Parent)",
        "- Choix : Pièces complètes ?",
        "Enchaînement : Début → Pièces complètes ?",
        "## Fiche persona : Parent (Usager)",
        "Âge : 34 ans",
        "Citation : « Je n'ai pas le temps »",
        "Étiquettes : pressé",
        "Frustrations : Délais (80 %)",
        "## Plan du site : Site",
        "- Accueil (existant)",
        "- Accueil › Inscription (à créer) ; avec : message d'erreur « Pièce manquante »",
        "Écrans accessibles partout : Mon compte",
    ]


def test_ancien_fichier_missionmap(tmp_path):
    old = {"version": 1, "title": "Projet 0.9", "objective": "Ancien objectif",
           "phases": [{"id": "ph", "title": "Phase", "span": 1}],
           "steps": [{"id": "s1", "title": "Étape", "slots": ["k1"]}],
           "personas": [{"id": "p1", "name": "Client", "role": "", "color": 0}],
           "activities": {"p1:k1": {"id": "a1", "text": "Activité héritée"}}, "scenes": {}, "links": []}
    (tmp_path / "o.missionmap").write_text(json.dumps(old), encoding="utf-8")
    content = P.parse(tmp_path / "o.missionmap", "o.missionmap").blocks[0].content
    assert "- Client : Activité héritée" in content and "Objectif : Ancien objectif" in content


def test_mapline_invalide_message_clair(tmp_path):
    (tmp_path / "x.mapline").write_text("pas du json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON valide"):
        P.parse(tmp_path / "x.mapline", "x.mapline")


def test_source_statistiques_retrouvee(tmp_path):
    from types import SimpleNamespace

    from app.services import source_lookup

    (tmp_path / "s.csv").write_text("Statut;Montant\n" + "\n".join(f"Ouvert;{k}" for k in range(6)), encoding="utf-8")
    doc = SimpleNamespace(id="stats-test", blocks=P.parse(tmp_path / "s.csv", "s.csv").blocks)
    hit = source_lookup.passage(doc, "Statistiques", "Montant somme")
    assert hit["found"] and any("« Montant »" in ln["text"] for ln in hit["lines"] if ln["hit"])
