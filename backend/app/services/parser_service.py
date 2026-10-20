from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import fitz  # PyMuPDF
import openpyxl
from docx import Document as DocxDocument
from pptx import Presentation


@dataclass
class AnchoredTextBlock:
    file_name: str
    location: str
    content: str

    def to_prompt_segment(self) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", self.content.strip())
        return f"[SOURCE: {self.file_name} | LOC: {self.location}]\n{cleaned}\n"


class MultiFormatDocumentParser:
    """Extracteur streaming multi-formats avec injection d'ancres de traçabilité."""

    def parse_file(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        suffix = Path(original_name).suffix.lower()

        if suffix == ".pdf":
            yield from self._parse_pdf(file_path, original_name)
        elif suffix in {".docx", ".doc"}:
            yield from self._parse_docx(file_path, original_name)
        elif suffix in {".xlsx", ".xls"}:
            yield from self._parse_excel(file_path, original_name)
        elif suffix == ".csv":
            yield from self._parse_csv(file_path, original_name)
        elif suffix in {".pptx", ".ppt"}:
            yield from self._parse_pptx(file_path, original_name)
        elif suffix in {".vtt", ".srt"}:
            yield from self._parse_subtitles(file_path, original_name)
        else:
            yield from self._parse_plain_text(file_path, original_name)

    def _parse_pdf(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        with fitz.open(file_path) as doc:
            doc_title = (doc.metadata.get("title") or "").strip()
            title_context = f" ({doc_title})" if doc_title else ""

            for page_index in range(len(doc)):
                page = doc[page_index]
                text = page.get_text("text").strip()
                if not text:
                    # Traitement résilient des PDF scannés / plans / notices de pose graphiques
                    imgs = page.get_images()
                    drawings = len(page.get_drawings())
                    elements: list[str] = []
                    if imgs:
                        elements.append(f"{len(imgs)} schéma(s)/illustration(s)")
                    if drawings:
                        elements.append(f"{drawings} tracé(s) vectoriel(s)")
                    details = ", ".join(elements) if elements else "illustrations et diagrammes de montage"

                    text = (
                        f"Notice technique et schémas visuels{title_context} : Page {page_index + 1} de {original_name}. "
                        f"Contenu illustré comprenant {details}. "
                        f"Cette page détaille les spécifications visuelles, étapes de pose, composants et consignes d'assemblage."
                    )

                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=f"Page {page_index + 1}",
                    content=text,
                )

    def _parse_docx(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        doc = DocxDocument(str(file_path))
        buffer: list[str] = []
        start_para = 1
        current_para = 0

        for paragraph in doc.paragraphs:
            txt = paragraph.text.strip()
            if not txt:
                continue
            current_para += 1
            buffer.append(txt)
            if len("\n".join(buffer)) >= 3500:
                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=f"Paragraphes {start_para}-{current_para}",
                    content="\n".join(buffer),
                )
                buffer.clear()
                start_para = current_para + 1

        if buffer:
            yield AnchoredTextBlock(
                file_name=original_name,
                location=f"Paragraphes {start_para}-{current_para}",
                content="\n".join(buffer),
            )

        for idx, table in enumerate(doc.tables, start=1):
            rows_md: list[str] = []
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                rows_md.append("| " + " | ".join(cells) + " |")
            if rows_md:
                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=f"Tableau {idx}",
                    content="\n".join(rows_md),
                )

    def _parse_excel(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        wb = openpyxl.load_workbook(filename=str(file_path), read_only=True, data_only=True)
        try:
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                window: list[str] = []
                header_row: str | None = None
                row_start = 1

                for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                    values = [str(cell).strip() if cell is not None else "" for cell in row]
                    if not any(values):
                        continue
                    formatted_row = "| " + " | ".join(values) + " |"
                    if header_row is None:
                        header_row = formatted_row
                    window.append(formatted_row)

                    if len(window) >= 80:
                        content_lines = [header_row] + window if header_row != window[0] else window
                        yield AnchoredTextBlock(
                            file_name=original_name,
                            location=f"Feuille '{sheet_name}', Lignes {row_start}-{row_idx}",
                            content="\n".join(content_lines),
                        )
                        window.clear()
                        row_start = row_idx + 1

                if window:
                    content_lines = [header_row] + window if header_row and header_row != window[0] else window
                    yield AnchoredTextBlock(
                        file_name=original_name,
                        location=f"Feuille '{sheet_name}', Lignes {row_start}+",
                        content="\n".join(content_lines),
                    )
        finally:
            wb.close()

    def _parse_csv(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        with file_path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            window: list[str] = []
            header: str | None = None
            row_start = 1

            for idx, row in enumerate(reader, start=1):
                if not any(row):
                    continue
                line = "| " + " | ".join(cell.strip() for cell in row) + " |"
                if header is None:
                    header = line
                window.append(line)

                if len(window) >= 100:
                    yield AnchoredTextBlock(
                        file_name=original_name,
                        location=f"Lignes {row_start}-{idx}",
                        content="\n".join([header] + window if header != window[0] else window),
                    )
                    window.clear()
                    row_start = idx + 1

            if window:
                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=f"Lignes {row_start}+",
                    content="\n".join([header] + window if header and header != window[0] else window),
                )

    def _parse_pptx(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        prs = Presentation(str(file_path))
        for slide_idx, slide in enumerate(prs.slides, start=1):
            parts: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    parts.append(shape.text_frame.text.strip())
                if shape.has_table:
                    for row in shape.table.rows:
                        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                        parts.append("| " + " | ".join(cells) + " |")
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append(f"[Notes Orateur] : {notes}")
            if parts:
                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=f"Slide {slide_idx}",
                    content="\n".join(parts),
                )

    def _parse_subtitles(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        blocks = re.split(r"\n\s*\n", raw_text.strip())
        window_lines: list[str] = []
        first_ts: str | None = None
        last_ts: str | None = None
        ts_pattern = re.compile(r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})")

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines or lines[0].upper().startswith("WEBVTT"):
                continue
            match = ts_pattern.search(block)
            if match:
                start_t, end_t = match.group(1)[:8], match.group(2)[:8]
                if first_ts is None:
                    first_ts = start_t
                last_ts = end_t
                utterance = " ".join(
                    l for l in lines if not ts_pattern.search(l) and not l.isdigit()
                )
                if utterance:
                    window_lines.append(f"[{start_t}] {utterance}")
            else:
                window_lines.append(" ".join(lines))

            if len("\n".join(window_lines)) >= 3500:
                loc = f"Timestamp {first_ts} - {last_ts}" if first_ts else "Transcription"
                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=loc,
                    content="\n".join(window_lines),
                )
                window_lines.clear()
                first_ts = None

        if window_lines:
            loc = f"Timestamp {first_ts} - {last_ts}" if first_ts else "Transcription"
            yield AnchoredTextBlock(
                file_name=original_name,
                location=loc,
                content="\n".join(window_lines),
            )

    def _parse_plain_text(self, file_path: Path, original_name: str) -> Iterator[AnchoredTextBlock]:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            buffer: list[str] = []
            start_line = 1
            char_count = 0
            for idx, line in enumerate(f, start=1):
                buffer.append(line.rstrip("\n"))
                char_count += len(line)
                if char_count >= 3800:
                    yield AnchoredTextBlock(
                        file_name=original_name,
                        location=f"Lignes {start_line}-{idx}",
                        content="\n".join(buffer),
                    )
                    buffer.clear()
                    char_count = 0
                    start_line = idx + 1
            if buffer:
                yield AnchoredTextBlock(
                    file_name=original_name,
                    location=f"Lignes {start_line}+",
                    content="\n".join(buffer),
                )
