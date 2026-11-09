"""Lecture fidèle des documents en blocs sourcés.

Principes :
- aucun texte n'est jamais inventé : une page sans couche texte (scan, image) est signalée, pas décrite ;
- chaque ligne ou paragraphe porte un repère (L12, §4, Slide 3, Page 2) que le modèle cite comme source ;
- l'ordre de lecture d'origine est conservé (tableaux Word à leur place, formes PowerPoint de haut en bas).
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
from docx.text.paragraph import Paragraph
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

# PDF : pdfminer.six (Python pur, quelques Mo) plutôt que PyMuPDF (plus de 20 Mo de bibliothèque native dans l'exe),
# pour une vitesse et un texte équivalents ; l'analyse de mise en page rend les blocs dans l'ordre de lecture.
from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer

BLOCK_CHARS = 3800  # taille cible d'un bloc envoyé au modèle
ROW_PREFIX = re.compile(r"^(?:L\d+|§\d+|\d{2}:\d{2}:\d{2}): ", re.M)


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


def decode_text(raw: bytes) -> str:
    """UTF-8 (avec ou sans BOM), sinon Windows-1252 : l'encodage des exports Excel français."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


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


class MultiFormatDocumentParser:
    def parse(self, file_path: Path, original_name: str) -> ParsedDocument:
        suffix = Path(original_name).suffix.lower()
        if suffix == ".pdf":
            return self._parse_pdf(file_path, original_name)
        if suffix == ".docx":
            return self._parse_docx(file_path, original_name)
        if suffix == ".xlsx":
            return self._parse_excel(file_path, original_name)
        if suffix == ".csv":
            return self._parse_csv(file_path, original_name)
        if suffix == ".pptx":
            return self._parse_pptx(file_path, original_name)
        if suffix in {".vtt", ".srt"}:
            return self._parse_subtitles(file_path, original_name)
        return self._parse_plain_text(file_path, original_name)

    # -- PDF -----------------------------------------------------------------

    def _parse_pdf(self, file_path: Path, name: str) -> ParsedDocument:
        out = ParsedDocument()
        empty: list[int] = []
        total = 0
        for i, page in enumerate(extract_pages(str(file_path), laparams=LAParams()), start=1):
            total = i
            text = "\n".join(
                element.get_text().strip() for element in page if isinstance(element, LTTextContainer)
            ).strip()
            text = re.sub(r"\n{3,}", "\n\n", text)
            if text:
                out.blocks.append(AnchoredTextBlock(name, f"Page {i}", text))
            else:
                empty.append(i)
        out.units = _plural(total, "page")
        if empty:
            listed = ", ".join(map(str, empty[:10])) + ("…" if len(empty) > 10 else "")
            out.warnings.append(
                f"{_plural(len(empty), 'page')} sans texte lisible (scan ou image), non analysée"
                f"{'s' if len(empty) > 1 else ''} : p. {listed}"
            )
        return out

    # -- Word ----------------------------------------------------------------

    def _parse_docx(self, file_path: Path, name: str) -> ParsedDocument:
        doc = DocxDocument(str(file_path))
        lines: list[tuple[str, str]] = []
        n_par, n_tab = 0, 0
        # Parcours du corps dans l'ordre : paragraphes et tableaux restent à leur place.
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(child, doc)
                text = p.text.strip()
                if not text:
                    continue
                n_par += 1
                style = (p.style.name if p.style is not None else "").lower()
                if style.startswith(("heading", "titre", "title")):
                    text = f"## {text}"
                elif style.startswith(("list", "liste")):
                    text = f"- {text}"
                lines.append((f"§{n_par}", text))
            elif tag == "tbl":
                n_tab += 1
                table = Table(child, doc)
                for r, row in enumerate(table.rows, start=1):
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        n_par += 1
                        lines.append((f"§{n_par}", f"[Tableau {n_tab}, ligne {r}] | " + " | ".join(cells) + " |"))
        pages = max(1, round(sum(len(t) for _, t in lines) / 2500))
        return ParsedDocument(_chunk_lines(name, lines, "Paragraphes"), [], f"≈ {_plural(pages, 'page')}")

    # -- Excel / CSV ----------------------------------------------------------

    def _rows_to_blocks(self, name: str, rows: list[list[str]], label_prefix: str = "") -> list[AnchoredTextBlock]:
        """Lignes de tableau numérotées ; l'en-tête est rappelé en tête de chaque bloc."""
        if not rows:
            return []
        header = "| " + " | ".join(rows[0]) + " |"
        lines = [(f"L{i}", "| " + " | ".join(r) + " |") for i, r in enumerate(rows, start=1) if any(r)]
        blocks = _chunk_lines(name, lines, f"{label_prefix}Lignes")
        for b in blocks[1:]:
            b.content = f"(en-tête) {header}\n{b.content}"
        return blocks

    def _parse_excel(self, file_path: Path, name: str) -> ParsedDocument:
        out = ParsedDocument()
        total = 0
        wb = openpyxl.load_workbook(filename=str(file_path), read_only=True, data_only=True)
        try:
            for sheet_name in wb.sheetnames:
                rows = [
                    [str(c).strip() if c is not None else "" for c in row]
                    for row in wb[sheet_name].iter_rows(values_only=True)
                ]
                while rows and not any(rows[-1]):
                    rows.pop()
                total += sum(1 for r in rows if any(r))
                prefix = f"Feuille '{sheet_name}', " if len(wb.sheetnames) > 1 else ""
                out.blocks += self._rows_to_blocks(name, rows, prefix)
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

    # -- Texte brut / Markdown -------------------------------------------------

    def _parse_plain_text(self, file_path: Path, name: str) -> ParsedDocument:
        text = decode_text(file_path.read_bytes())
        lines = [(f"L{i}", ln.rstrip()) for i, ln in enumerate(text.splitlines(), start=1) if ln.strip()]
        total = len(text.splitlines())
        return ParsedDocument(_chunk_lines(name, lines, "Lignes"), [], _plural(total, "ligne"))
