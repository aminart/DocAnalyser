"""Conversion de la synthèse Markdown en Word (.docx) et PDF (.pdf)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Callable

from docx import Document as DocxDocument
from fpdf import FPDF


def markdown_to_docx(title: str, md_text: str) -> bytes:
    doc = DocxDocument()
    doc.add_heading(title, level=0)

    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:], level=1)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=2)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:].replace("**", ""), style="List Bullet")
        else:
            doc.add_paragraph(line.replace("**", ""))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT = "DejaVu"


def _clean(text: str) -> str:
    return text.replace("**", "").replace("`", "")


def _latin1(text: str) -> str:
    """Repli si la police Unicode manque : les polices PDF de base ne couvrent que le latin-1."""
    return (
        _clean(text)
        .replace("—", "-")
        .replace("–", "-")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("«", '"')
        .replace("»", '"')
        .replace("•", "-")
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )


def _setup_font(pdf: FPDF) -> tuple[str, Callable[[str], str]]:
    """Police Unicode embarquée (accents, œ, guillemets, alphabets non latins), sinon Helvetica en latin-1."""
    regular, bold = FONTS_DIR / "DejaVuSans.ttf", FONTS_DIR / "DejaVuSans-Bold.ttf"
    if regular.is_file() and bold.is_file():
        pdf.add_font(FONT, "", str(regular))
        pdf.add_font(FONT, "B", str(bold))
        return FONT, _clean
    return "Helvetica", _latin1


def markdown_to_pdf(title: str, md_text: str) -> bytes:
    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    family, clean_text = _setup_font(pdf)
    pdf.add_page()
    usable_w = pdf.epw

    pdf.set_font(family, style="B", size=15)
    pdf.multi_cell(usable_w, 9, clean_text(title), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    pdf.ln(4)

    pdf.set_font(family, size=10)
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("# "):
            continue
        clean = clean_text(line)
        pdf.set_x(pdf.l_margin)
        if clean.startswith("## "):
            pdf.ln(3)
            pdf.set_font(family, style="B", size=12)
            pdf.multi_cell(usable_w, 7, clean[3:], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            pdf.set_font(family, size=10)
        elif clean.startswith("### "):
            pdf.ln(2)
            pdf.set_font(family, style="B", size=11)
            pdf.multi_cell(usable_w, 6, clean[4:], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            pdf.set_font(family, size=10)
        else:
            pdf.multi_cell(usable_w, 5.5, clean, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

    return bytes(pdf.output())
