"""Lecture fidèle des documents en blocs sourcés.

Principes :
- aucun texte n'est jamais inventé : une page sans couche texte (scan, image) est signalée, pas décrite ;
- chaque ligne ou paragraphe porte un repère (L12, §4, Slide 3, Page 2) que le modèle cite comme source ;
- l'ordre de lecture d'origine est conservé (tableaux Word à leur place, formes PowerPoint de haut en bas) ;
- seuls les formats connus sont lus : un fichier d'un autre format est refusé plutôt que lu comme du texte.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from docx import Document as DocxDocument
from docx.table import Table
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.services import pdf_layout, sheet_stats
from app.services.html_reader import html_lines
from app.services.mapline_reader import mapline_lines

BLOCK_CHARS = 3800  # taille cible d'un bloc envoyé au modèle
ROW_PREFIX = re.compile(r"^(?:L\d+|§\d+|\d{2}:\d{2}:\d{2}): ", re.M)

# Extensions lues, avec leur nom affiché dans les messages.
SUPPORTED_FORMATS: dict[str, str] = {
    ".pdf": "PDF",
    ".docx": "Word",
    ".pptx": "PowerPoint",
    ".xlsx": "Excel",
    ".csv": "CSV",
    ".txt": "texte",
    ".md": "Markdown",
    ".vtt": "sous-titres",
    ".srt": "sous-titres",
    ".html": "page web",
    ".htm": "page web",
    ".mapline": "projet Mapline",
    ".missionmap": "projet Mapline",
    # Images : lues seulement par un modèle qui voit les images, choisi au lancement de l'analyse.
    ".png": "image PNG",
    ".jpg": "image JPEG",
    ".jpeg": "image JPEG",
    ".webp": "image WebP",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
# Formats lus comme du texte : un contenu binaire y trahit un fichier renommé ou d'un autre type.
TEXT_FORMATS = {".csv", ".txt", ".md", ".vtt", ".srt", ".html", ".htm", ".mapline", ".missionmap"}


class UnsupportedFormat(ValueError):
    """Fichier d'un format que DocAnalyser ne sait pas lire."""


def formats_label() -> str:
    return "PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, VTT, SRT, HTML, MAPLINE et images (PNG, JPG, WEBP)"


@dataclass
class AnchoredTextBlock:
    file_name: str
    location: str
    content: str

    def to_prompt_segment(self) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", self.content.strip())
        return f"[SOURCE: {self.file_name} | LOC: {self.location}]\n{cleaned}\n"

    def plain_text(self) -> str:
        """Texte sans les repères de ligne, pour vérifier les citations."""
        return ROW_PREFIX.sub("", self.content)


@dataclass
class ParsedDocument:
    blocks: list[AnchoredTextBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    units: str = ""  # « 18 pages », « 412 lignes », « 12 slides »…
    empty_pages: list[int] = field(default_factory=list)  # pages PDF sans texte (scans), lues en image si possible


def decode_text(raw: bytes) -> str:
    """UTF-8 (avec ou sans BOM), sinon Windows-1252 : l'encodage des exports Excel français."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def check_format(name: str, content: bytes) -> None:
    """Refuse un format inconnu, ou un fichier binaire déguisé en texte, avec un message clair."""
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        what = f"le format {suffix}" if suffix else "un fichier sans extension"
        raise UnsupportedFormat(
            f"{name} : DocAnalyser ne sait pas lire {what}. Formats acceptés : {formats_label()}. "
            "Les archives (.zip) ne sont pas lues."
        )
    if suffix in IMAGE_SUFFIXES:
        from app.services.image_reader import is_image

        if not is_image(content):
            raise UnsupportedFormat(f"{name} n'est pas une image lisible : le fichier est peut-être abîmé.")
    if suffix in TEXT_FORMATS and b"\x00" in content[:8192]:
        raise UnsupportedFormat(
            f"{name} ne contient pas de texte lisible : c'est sans doute un fichier d'un autre type renommé en {suffix}."
        )


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def _chunk_lines(name: str, lines: list[tuple[str, str]], label: str) -> list[AnchoredTextBlock]:
    """Regroupe des lignes repérées (repère, texte) en blocs d'environ BLOCK_CHARS caractères."""
    blocks, buf, size = [], [], 0
    for ref, text in lines:
        buf.append((ref, text))
        size += len(text) + len(ref) + 3
        if size >= BLOCK_CHARS:
            blocks.append(_make_block(name, buf, label))
            buf, size = [], 0
    if buf:
        blocks.append(_make_block(name, buf, label))
    return blocks


def _make_block(name: str, buf: list[tuple[str, str]], label: str) -> AnchoredTextBlock:
    first, last = buf[0][0], buf[-1][0]
    span = first if first == last else f"{first}-{last.lstrip('L§')}"
    return AnchoredTextBlock(name, f"{label} {span}", "\n".join(f"{r}: {t}" for r, t in buf))


def _numbered(texts: list[str]) -> list[tuple[str, str]]:
    return [(f"§{i}", t) for i, t in enumerate(texts, start=1)]


def _approx_pages(lines: list[tuple[str, str]]) -> str:
    return f"≈ {_plural(max(1, round(sum(len(t) for _, t in lines) / 2500)), 'page')}"


# -- Word : texte des paragraphes ----------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_SKIPPED = {f"{_W}txbxContent", _MC_FALLBACK, f"{_W}del", f"{_W}instrText", f"{_W}footnotes", f"{_W}endnotes"}


def _run_text(el, out: list[str]) -> None:
    """Texte visible d'un élément Word, révisions acceptées, sans les zones de texte ancrées dedans."""
    for child in el:
        tag = child.tag
        if tag in _SKIPPED:
            continue
        if tag == f"{_W}t":
            out.append(child.text or "")
        elif tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
            out.append(" ")
        elif tag == f"{_W}footnoteReference":
            out.append(f"[note {child.get(f'{_W}id')}]")
        elif tag == f"{_W}endnoteReference":
            out.append(f"[note de fin {child.get(f'{_W}id')}]")
        else:
            _run_text(child, out)


def _para_text(p_el) -> str:
    out: list[str] = []
    _run_text(p_el, out)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _text_boxes(p_el) -> list[str]:
    """Paragraphes des zones de texte ancrées dans un paragraphe (une seule fois, sans la copie de secours)."""
    texts: list[str] = []

    def walk(el, in_fallback: bool) -> None:
        for child in el:
            fb = in_fallback or child.tag == _MC_FALLBACK
            if child.tag == f"{_W}txbxContent":
                if not fb:
                    texts.extend(t for t in (_para_text(p) for p in child.iter(f"{_W}p")) if t)
                continue
            walk(child, fb)

    walk(p_el, False)
    return texts


def _notes_of(doc, kind: str) -> dict[str, str]:
    """Notes de bas de page (footnotes) ou de fin (endnotes), par numéro."""
    from lxml import etree

    for part in doc.part.package.iter_parts():
        if str(part.partname) == f"/word/{kind}.xml":
            root = etree.fromstring(part.blob)
            notes = {}
            for note in root:
                if note.get(f"{_W}type") in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                text = " ".join(t for t in (_para_text(p) for p in note.iter(f"{_W}p")) if t)
                if text:
                    notes[note.get(f"{_W}id")] = text
            return notes
    return {}


def _row_cells(row) -> list[str]:
    """Cellules d'une ligne de tableau Word ; une cellule fusionnée n'est lue qu'une fois."""
    cells, seen = [], None
    for c in row.cells:
        if c._tc is seen:
            continue
        seen = c._tc
        cells.append(c.text.strip().replace("\n", " "))
    return cells


_PAGE_ONLY = re.compile(r"^(?:page|p|pagesur|pageof|sur|of)?$")


class MultiFormatDocumentParser:
    def parse(self, file_path: Path, original_name: str) -> ParsedDocument:
        suffix = Path(original_name).suffix.lower()
        readers = {
            ".pdf": self._parse_pdf,
            ".docx": self._parse_docx,
            ".xlsx": self._parse_excel,
            ".csv": self._parse_csv,
            ".pptx": self._parse_pptx,
            ".vtt": self._parse_subtitles,
            ".srt": self._parse_subtitles,
            ".html": self._parse_html,
            ".htm": self._parse_html,
            ".mapline": self._parse_mapline,
            ".missionmap": self._parse_mapline,
            ".txt": self._parse_plain_text,
            ".md": self._parse_plain_text,
            **{ext: self._parse_image for ext in IMAGE_SUFFIXES},
        }
        if suffix not in readers:
            raise UnsupportedFormat(f"{original_name} : format {suffix or 'sans extension'} non pris en charge")
        return readers[suffix](file_path, original_name)

    # -- PDF -----------------------------------------------------------------

    def _parse_pdf(self, file_path: Path, name: str) -> ParsedDocument:
        out = ParsedDocument()
        result = pdf_layout.read_pdf(str(file_path))
        for i, text in enumerate(result.pages, start=1):
            if text:
                out.blocks.append(AnchoredTextBlock(name, f"Page {i}", text))
        out.units = _plural(len(result.pages), "page")
        out.empty_pages = list(result.empty)
        if result.empty:
            empty = result.empty
            listed = ", ".join(map(str, empty[:10])) + ("…" if len(empty) > 10 else "")
            out.warnings.append(
                f"{_plural(len(empty), 'page')} sans texte lisible (scan ou image), lue"
                f"{'s' if len(empty) > 1 else ''} seulement avec un modèle qui voit les images : p. {listed}"
            )
        if result.repeated:
            listed = ", ".join(f"« {t} »" for t in result.repeated[:3]) + ("…" if len(result.repeated) > 3 else "")
            out.warnings.append(f"En-têtes et pieds de page répétés à chaque page, ignorés : {listed}")
        return out

    # -- Word ----------------------------------------------------------------

    def _parse_docx(self, file_path: Path, name: str) -> ParsedDocument:
        doc = DocxDocument(str(file_path))
        footnotes, endnotes = _notes_of(doc, "footnotes"), _notes_of(doc, "endnotes")
        styles = {s.style_id: (s.name or "").lower() for s in doc.styles}
        texts: list[str] = []
        n_tab = 0

        def add_paragraph(p_el) -> None:
            text = _para_text(p_el)
            if text:
                ppr = p_el.find(f"{_W}pPr")
                style_el = ppr.find(f"{_W}pStyle") if ppr is not None else None
                style = styles.get(style_el.get(f"{_W}val"), "") if style_el is not None else ""
                is_list = ppr is not None and ppr.find(f"{_W}numPr") is not None
                if style.startswith(("heading", "titre", "title")):
                    text = f"## {text}"
                elif is_list or style.startswith(("list", "liste")):
                    text = f"- {text}"
                texts.append(text)
            texts.extend(f"[Zone de texte] {t}" for t in _text_boxes(p_el))
            # Les notes appelées dans le paragraphe suivent le paragraphe : elles restent dans leur contexte.
            for ref in p_el.iter(f"{_W}footnoteReference"):
                if (note := footnotes.get(ref.get(f"{_W}id"))):
                    texts.append(f"[Note {ref.get(f'{_W}id')}] {note}")
            for ref in p_el.iter(f"{_W}endnoteReference"):
                if (note := endnotes.get(ref.get(f"{_W}id"))):
                    texts.append(f"[Note de fin {ref.get(f'{_W}id')}] {note}")

        # Parcours du corps dans l'ordre : paragraphes et tableaux restent à leur place.
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                add_paragraph(child)
            elif tag == "tbl":
                n_tab += 1
                table = Table(child, doc)
                for r, row in enumerate(table.rows, start=1):
                    cells = _row_cells(row)
                    if any(cells):
                        texts.append(f"[Tableau {n_tab}, ligne {r}] | " + " | ".join(cells) + " |")

        texts += self._docx_headers_footers(doc)
        lines = _numbered(texts)
        return ParsedDocument(_chunk_lines(name, lines, "Paragraphes"), [], _approx_pages(lines))

    def _docx_headers_footers(self, doc) -> list[str]:
        """En-têtes et pieds de page de toutes les sections, sans doublon ni simple numéro de page."""
        seen: set[str] = set()
        out: list[str] = []
        for section in doc.sections:
            for attr, label in (
                ("header", "En-tête"), ("first_page_header", "En-tête"), ("even_page_header", "En-tête"),
                ("footer", "Pied de page"), ("first_page_footer", "Pied de page"), ("even_page_footer", "Pied de page"),
            ):
                part = getattr(section, attr)
                if part.is_linked_to_previous:
                    continue
                for el in part._element.iter(f"{_W}p"):
                    text = _para_text(el)
                    letters = re.sub(r"[\W\d_]+", "", text.lower())
                    if not text or _PAGE_ONLY.match(letters) or text in seen:
                        continue
                    seen.add(text)
                    out.append(f"[{label}] {text}")
        return out

    # -- Excel / CSV ----------------------------------------------------------

    def _rows_to_blocks(self, name: str, rows: list[list[str]], label_prefix: str = "",
                        raw: list[list[object]] | None = None) -> list[AnchoredTextBlock]:
        """Lignes de tableau numérotées ; l'en-tête est rappelé en tête des blocs suivants.

        Les colonnes vides sont retirées, la vraie ligne d'en-tête est cherchée sous les éventuels titres,
        et un bloc de statistiques calculées par colonne suit les lignes.
        """
        if not rows:
            return []
        keep = [j for j in range(max(len(r) for r in rows)) if any(j < len(r) and r[j] for r in rows)]
        rows = [[r[j] if j < len(r) else "" for j in keep] for r in rows]
        if raw is not None:
            raw = [[r[j] if j < len(r) else None for j in keep] for r in raw]
        h = sheet_stats.header_index(rows)
        header = "| " + " | ".join(rows[h]) + " |"
        lines = [(f"L{i}", "| " + " | ".join(r) + " |") for i, r in enumerate(rows, start=1) if any(r)]
        blocks = _chunk_lines(name, lines, f"{label_prefix}Lignes")
        past_header = False
        for b in blocks:
            if past_header:
                b.content = f"(en-tête) {header}\n{b.content}"
            past_header = past_header or f"L{h + 1}: " in b.content
        stats = sheet_stats.column_stats(rows, h, raw)
        if stats:
            blocks.append(AnchoredTextBlock(name, f"{label_prefix}Statistiques", "\n".join(stats)))
        return blocks

    def _parse_excel(self, file_path: Path, name: str) -> ParsedDocument:
        out = ParsedDocument()
        total = 0
        wb = openpyxl.load_workbook(filename=str(file_path), read_only=True, data_only=True)
        try:
            for sheet_name in wb.sheetnames:
                raw = [list(row) for row in wb[sheet_name].iter_rows(values_only=True)]
                rows = [[sheet_stats.cell_text(c) for c in row] for row in raw]
                while rows and not any(rows[-1]):
                    rows.pop()
                raw = raw[: len(rows)]
                total += sum(1 for r in rows if any(r))
                prefix = f"Feuille '{sheet_name}', " if len(wb.sheetnames) > 1 else ""
                out.blocks += self._rows_to_blocks(name, rows, prefix, raw)
        finally:
            wb.close()
        out.units = _plural(total, "ligne")
        return out

    def _parse_csv(self, file_path: Path, name: str) -> ParsedDocument:
        text = decode_text(file_path.read_bytes())
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
        out = ParsedDocument(self._rows_to_blocks(name, rows))
        out.units = _plural(sum(1 for r in rows if any(r)), "ligne")
        return out

    # -- PowerPoint -----------------------------------------------------------

    def _shape_texts(self, shapes) -> list[str]:
        parts: list[str] = []
        ordered = sorted(shapes, key=lambda s: ((s.top or 0), (s.left or 0)))  # ordre de lecture
        for shape in ordered:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                parts += self._shape_texts(shape.shapes)
                continue
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    parts.append("| " + " | ".join(cells) + " |")
        return parts

    def _parse_pptx(self, file_path: Path, name: str) -> ParsedDocument:
        out = ParsedDocument()
        prs = Presentation(str(file_path))
        empty = []
        for i, slide in enumerate(prs.slides, start=1):
            parts = self._shape_texts(slide.shapes)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append(f"[Notes de l'orateur] {notes}")
            if parts:
                out.blocks.append(AnchoredTextBlock(name, f"Slide {i}", "\n".join(parts)))
            else:
                empty.append(i)
        out.units = _plural(len(prs.slides), "slide")
        if empty:
            out.warnings.append(f"{_plural(len(empty), 'slide')} sans texte (images seules) : {', '.join(map(str, empty[:10]))}")
        return out

    # -- Images ----------------------------------------------------------------

    def _parse_image(self, file_path: Path, name: str) -> ParsedDocument:
        # Aucun texte : l'image est mise de côté à l'import (image_reader) et lue par un modèle de vision.
        return ParsedDocument([], [], "1 image")

    # -- Sous-titres -----------------------------------------------------------

    def _parse_subtitles(self, file_path: Path, name: str) -> ParsedDocument:
        raw = decode_text(file_path.read_bytes())
        ts = re.compile(r"(\d{2}:\d{2}:\d{2})[.,]\d{3}\s*-->\s*(\d{2}:\d{2}:\d{2})")
        lines: list[tuple[str, str]] = []
        for block in re.split(r"\n\s*\n", raw.strip()):
            rows = [r.strip() for r in block.splitlines() if r.strip()]
            if not rows or rows[0].upper().startswith("WEBVTT"):
                continue
            m = ts.search(block)
            utterance = " ".join(r for r in rows if not ts.search(r) and not r.isdigit())
            if utterance:
                lines.append((m.group(1) if m else f"L{len(lines) + 1}", utterance))
        blocks = _chunk_lines(name, lines, "Timestamp")
        duration = lines[-1][0] if lines and ":" in lines[-1][0] else ""
        return ParsedDocument(blocks, [], f"{duration} de transcription" if duration else _plural(len(lines), "réplique"))

    # -- Page web ----------------------------------------------------------------

    def _parse_html(self, file_path: Path, name: str) -> ParsedDocument:
        lines = _numbered(html_lines(decode_text(file_path.read_bytes())))
        return ParsedDocument(_chunk_lines(name, lines, "Paragraphes"), [], _approx_pages(lines))

    # -- Projet Mapline ------------------------------------------------------------

    def _parse_mapline(self, file_path: Path, name: str) -> ParsedDocument:
        texts, units = mapline_lines(decode_text(file_path.read_bytes()))
        lines = _numbered(texts)
        return ParsedDocument(_chunk_lines(name, lines, "Paragraphes"), [], units)

    # -- Texte brut / Markdown -------------------------------------------------

    def _parse_plain_text(self, file_path: Path, name: str) -> ParsedDocument:
        text = decode_text(file_path.read_bytes())
        lines = [(f"L{i}", ln.rstrip()) for i, ln in enumerate(text.splitlines(), start=1) if ln.strip()]
        total = len(text.splitlines())
        return ParsedDocument(_chunk_lines(name, lines, "Lignes"), [], _plural(total, "ligne"))
