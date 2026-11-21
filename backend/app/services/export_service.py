"""Conversion de la synthèse Markdown en Word (.docx) et PDF (.pdf)."""
from __future__ import annotations

import html
import io
import re
from pathlib import Path
from typing import Callable

from docx import Document as DocxDocument
from docx.shared import Cm, Pt, RGBColor
from fpdf import FPDF

from app.services.report_markdown import ANNEX_MARK


_INLINE = re.compile(r"\*\*(.+?)\*\*|(?<![\w*])_(.+?)_(?!\w)")
MUTED = RGBColor(0x5A, 0x60, 0x70)


def _runs(paragraph, text: str, size: float | None = None, color: RGBColor | None = None, italic: bool = False) -> None:
    """Ajoute le texte au paragraphe en gardant le **gras** et l'_italique_ du Markdown."""
    pos = 0
    for m in _INLINE.finditer(text):
        chunks = [(text[pos:m.start()], False, italic)]
        chunks.append((m.group(1), True, italic) if m.group(1) is not None else (m.group(2), False, True))
        for chunk, bold, ital in chunks:
            if chunk:
                run = paragraph.add_run(chunk)
                run.bold, run.italic = bold or None, ital or None
                if size:
                    run.font.size = Pt(size)
                if color is not None:
                    run.font.color.rgb = color
        pos = m.end()
    if pos < len(text):
        run = paragraph.add_run(text[pos:])
        run.italic = italic or None
        if size:
            run.font.size = Pt(size)
        if color is not None:
            run.font.color.rgb = color


def _spacing(paragraph, before: float = 0, after: float = 6, indent: float | None = None) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before, fmt.space_after = Pt(before), Pt(after)
    fmt.line_spacing = 1.15
    if indent is not None:
        fmt.left_indent = Cm(indent)


def markdown_to_docx(title: str, md_text: str) -> bytes:
    """Word aéré : titres, puces avec l'idée en gras, explication et sources en retrait, citations à part."""
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    normal.font.size = Pt(11)
    doc.add_heading(title, level=0)

    for raw_line in md_text.splitlines():
        continuation = raw_line.startswith("  ") and raw_line.strip() and not raw_line.lstrip().startswith(("- ", "#"))
        line = raw_line.strip()
        if not line or line.startswith("# "):
            continue
        if line == ANNEX_MARK:
            doc.add_page_break()
        elif line.startswith("<!--"):
            continue
        elif line.startswith("## "):
            h = doc.add_heading(line[3:].replace("**", ""), level=1)
            _spacing(h, before=18, after=8)
        elif line.startswith("### "):
            h = doc.add_heading(line[4:].replace("**", ""), level=2)
            _spacing(h, before=12, after=6)
        elif continuation:
            # Suite d'un point : explication, puis sources en petit et en gris
            par = doc.add_paragraph()
            sources = line.startswith("_Sources")
            _runs(par, line.strip("_") if sources else line, size=9 if sources else None,
                  color=MUTED if sources else None, italic=sources)
            _spacing(par, after=8 if sources else 2, indent=0.63)
        elif line.startswith("- "):
            par = doc.add_paragraph(style="List Bullet")
            _runs(par, line[2:])
            _spacing(par, before=4, after=2)
        elif re.match(r"\d+\. ", line):
            par = doc.add_paragraph(style="List Number")
            _runs(par, line.split(" ", 1)[1])
            _spacing(par, before=2, after=4)
        elif line.startswith(">"):
            par = doc.add_paragraph(style="Quote")
            _runs(par, line.lstrip("> "))
            _spacing(par, before=6, after=10, indent=0.8)
        else:
            par = doc.add_paragraph()
            _runs(par, line)
            _spacing(par, after=8)

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
        continuation = raw_line.startswith("  ") and raw_line.strip() and not raw_line.lstrip().startswith(("- ", "#"))
        line = raw_line.strip()
        if not line or line.startswith("# "):
            continue
        if line == ANNEX_MARK:
            pdf.add_page()
            continue
        if line.startswith("<!--"):
            continue
        clean = clean_text(line)
        pdf.set_x(pdf.l_margin)
        if continuation:
            small = clean.startswith("_Sources") or clean.startswith("Sources :")
            pdf.set_x(pdf.l_margin + 5)
            pdf.set_font(family, size=8.5 if small else 10)
            pdf.multi_cell(usable_w - 5, 5 if small else 5.5, clean.strip("_"), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
            pdf.set_font(family, size=10)
            if small:
                pdf.ln(1.5)
        elif clean.startswith("- "):
            pdf.ln(1)
            pdf.multi_cell(usable_w, 5.5, "• " + clean[2:], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
        elif clean.startswith("## "):
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
            pdf.ln(1.5)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Page web (.html) : un seul fichier, lisible hors de l'application, aéré et imprimable
# ---------------------------------------------------------------------------

_HTML_STYLE = """
:root { --ink:#15171C; --body:#3A3F4B; --muted:#5A6070; --line:#E3E6EC; --soft:#F4F5F8; --accent:#3346D3; --bg:#FFFFFF; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#F2F3F6; --body:#C9CDD6; --muted:#9AA1B0; --line:#2C3039; --soft:#1C1F26; --accent:#8C9BFF; --bg:#121419; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--body); font: 17px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 48px 20px 80px; }
h1 { color: var(--ink); font-size: 34px; line-height: 1.2; margin: 0 0 8px; letter-spacing: -0.02em; }
h2 { color: var(--ink); font-size: 24px; line-height: 1.3; margin: 48px 0 14px; padding-top: 22px; border-top: 1px solid var(--line); }
h3 { color: var(--ink); font-size: 19px; margin: 30px 0 10px; }
p { margin: 0 0 14px; }
ul, ol { margin: 0 0 18px; padding-left: 22px; }
li { margin: 0 0 14px; }
li strong:first-child { color: var(--ink); }
.src { display: block; font-size: 13px; color: var(--muted); font-style: italic; margin-top: 2px; }
.meta { color: var(--muted); font-size: 14px; }
blockquote { margin: 18px 0 22px; padding: 16px 22px; background: var(--soft); border-left: 3px solid var(--accent);
  border-radius: 8px; font-style: italic; color: var(--ink); }
details.annexe { margin-top: 48px; border-top: 1px solid var(--line); padding-top: 18px; }
details.annexe > summary { cursor: pointer; font-weight: 700; color: var(--ink); font-size: 20px; }
details.annexe li { margin-bottom: 6px; font-size: 15px; }
pre.mermaid { background: var(--soft); padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; }
@media print { body { font-size: 11pt; } main { max-width: none; padding: 0; } details.annexe { break-before: page; }
  details.annexe:not([open]) > *:not(summary) { display: block; } }
"""


def _html_inline(text: str) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<strong>{html.escape(m.group(1))}</strong>")
        else:
            out.append(f"<em>{html.escape(m.group(2))}</em>")
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def markdown_to_html(title: str, md_text: str) -> bytes:
    """Page web autonome : mêmes contenus que le Markdown, mise en page aérée ; l'annexe est repliée."""
    body: list[str] = []
    in_list: str | None = None
    in_annex = False
    mermaid: list[str] | None = None

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            body.append(f"</li></{in_list}>")
            in_list = None

    for raw_line in md_text.splitlines():
        if mermaid is not None:
            if raw_line.strip() == "```":
                body.append(f'<pre class="mermaid">{html.escape(chr(10).join(mermaid))}</pre>')
                mermaid = None
            else:
                mermaid.append(raw_line)
            continue
        continuation = raw_line.startswith("  ") and raw_line.strip() and not raw_line.lstrip().startswith(("- ", "#"))
        line = raw_line.strip()
        if line.startswith("```mermaid"):
            close_list()
            mermaid = []
        elif not line:
            continue
        elif continuation and in_list:
            if line.startswith("_Sources"):
                body.append(f'<span class="src">{_html_inline(line.strip("_"))}</span>')
            else:
                body.append(f"<br>{_html_inline(line)}")
        elif line == ANNEX_MARK:
            close_list()
            in_annex = True
            body.append('<details class="annexe"><summary>Annexe — détail des éléments extraits</summary>')
        elif line.startswith("<!--") or line.startswith("# "):
            continue
        elif line.startswith("## "):
            close_list()
            if not (in_annex and line.startswith("## Annexe")):
                body.append(f"<h2>{_html_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            close_list()
            body.append(f"<h3>{_html_inline(line[4:])}</h3>")
        elif line.startswith("- ") or re.match(r"\d+\. ", line):
            kind = "ul" if line.startswith("- ") else "ol"
            text = _html_inline(line[2:] if kind == "ul" else line.split(" ", 1)[1])
            if in_list != kind:
                close_list()
                body.append(f"<{kind}><li>{text}")
                in_list = kind
            else:
                body.append(f"</li><li>{text}")
        elif line.startswith(">"):
            close_list()
            body.append(f"<blockquote>{_html_inline(line.lstrip('> '))}</blockquote>")
        else:
            close_list()
            if in_annex and line.startswith("_Synthèse générée"):
                body.append("</details>")
                in_annex = False
            body.append(f"<p>{_html_inline(line)}</p>")
    close_list()
    if in_annex:
        body.append("</details>")
    if mermaid is not None:
        body.append(f'<pre class="mermaid">{html.escape(chr(10).join(mermaid))}</pre>')
    script = ""
    if any('class="mermaid"' in b for b in body):
        # Schéma du parcours : dessiné si le navigateur a accès à Internet, sinon son texte reste lisible.
        script = ('<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs";'
                  'mermaid.initialize({startOnLoad: true});</script>')
    page = (
        f'<!doctype html>\n<html lang="fr"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_HTML_STYLE}</style></head>"
        f"<body><main><h1>{html.escape(title)}</h1>\n" + "\n".join(body) + f"\n</main>{script}</body></html>\n"
    )
    return page.encode("utf-8")
