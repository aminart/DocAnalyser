"""Mise en page des PDF : texte dans l'ordre de lecture, en-têtes et pieds de page répétés retirés, tableaux repérés.

pdfminer.six rend les blocs de texte dans l'ordre de lecture, mais ne connaît ni les en-têtes ni les tableaux :
- un texte présent en haut ou en bas de la plupart des pages (titre courant, « Page 3 / 12 ») est retiré, car il
  parasite les thèmes et la recherche ; il est signalé à l'import ;
- des lignes alignées en colonnes sur plusieurs rangées consécutives sont rendues en tableau « | a | b | », pour
  que chaque valeur reste attachée à sa ligne.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer, LTTextLine

EDGE_ROWS = 2  # rangées examinées en haut et en bas de chaque page
MIN_PAGES_FOR_REPEATS = 3
COL_TOLERANCE = 12.0  # écart horizontal (pt) entre deux débuts de colonne considérés alignés
MIN_TABLE_ROWS = 3


@dataclass
class _Line:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    box: int
    row: int = -1
    table: int = -1
    removed: bool = False

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)


@dataclass
class PdfText:
    pages: list[str] = field(default_factory=list)  # texte de chaque page ("" si vide)
    empty: list[int] = field(default_factory=list)  # pages sans texte du tout (scans)
    repeated: list[str] = field(default_factory=list)  # en-têtes et pieds retirés


def _page_lines(page) -> list[_Line]:
    lines: list[_Line] = []
    for b, el in enumerate(e for e in page if isinstance(e, LTTextContainer)):
        for ln in [el] if isinstance(el, LTTextLine) else [x for x in el if isinstance(x, LTTextLine)]:
            text = re.sub(r"\s+", " ", ln.get_text()).strip()
            if text:
                lines.append(_Line(ln.x0, ln.y0, ln.x1, ln.y1, text, b))
    return lines


def _rows(lines: list[_Line]) -> list[list[_Line]]:
    """Rangées de lignes à la même hauteur, de haut en bas, chacune de gauche à droite."""
    rows: list[list[_Line]] = []
    for ln in sorted(lines, key=lambda x: -x.yc):
        if rows and abs(rows[-1][0].yc - ln.yc) <= 0.5 * min(rows[-1][0].height, ln.height):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    for r, row in enumerate(rows):
        row.sort(key=lambda x: x.x0)
        for ln in row:
            ln.row = r
    return rows


def _edge_key(row: list[_Line]) -> str:
    """Clé de comparaison d'une rangée de bord ; les numéros ne comptent que dans un texte court (« Page 3 / 12 »),
    pour qu'une phrase du corps qui ne diffère que par un chiffre ne soit pas prise pour un pied de page."""
    text = re.sub(r"\s+", " ", " ".join(ln.text for ln in row).lower()).strip()
    if len(text) > 120:
        return ""
    return re.sub(r"\d+", "#", text) if len(text) <= 40 else text


def _mark_repeats(pages: list[list[list[_Line]]]) -> list[str]:
    """Retire les rangées du haut ou du bas présentes sur la plupart des pages ; renvoie leurs textes."""
    if len(pages) < MIN_PAGES_FOR_REPEATS:
        return []
    counts: dict[str, int] = {}
    for rows in pages:
        for key in {_edge_key(r) for r in rows[:EDGE_ROWS] + rows[-EDGE_ROWS:]}:
            counts[key] = counts.get(key, 0) + 1
    threshold = max(MIN_PAGES_FOR_REPEATS, math.ceil(0.6 * len(pages)))
    repeated = {k for k, n in counts.items() if n >= threshold and k}
    shown: dict[str, str] = {}
    for rows in pages:
        edges = rows[:EDGE_ROWS] + rows[-EDGE_ROWS:]
        for row in edges:
            key = _edge_key(row)
            if key in repeated:
                shown.setdefault(key, " ".join(ln.text for ln in row)[:80])
                for ln in row:
                    ln.removed = True
    return list(shown.values())


_BULLET = re.compile(r"^(?:[•▪◦‣●■□·*o–—-]|\d{1,2}[.)]|[a-z][.)])$")


def _is_cell_row(row: list[_Line]) -> bool:
    kept = [ln for ln in row if not ln.removed]
    if kept and _BULLET.match(kept[0].text):  # puce ou numéro de liste détaché du texte : pas une cellule
        kept = kept[1:]
    return len(kept) >= 2 and all(b.x0 - a.x1 > 4 for a, b in zip(kept, kept[1:]))


def _columns(run: list[list[_Line]]) -> list[float]:
    starts = sorted(ln.x0 for row in run for ln in row if not ln.removed)
    cols: list[float] = []
    for x in starts:
        if not cols or x - cols[-1] > COL_TOLERANCE:
            cols.append(x)
    return cols


def _aligned(row: list[_Line], cols: list[float]) -> bool:
    kept = [ln for ln in row if not ln.removed]
    hits = sum(1 for ln in kept if any(abs(ln.x0 - c) <= COL_TOLERANCE for c in cols))
    return hits * 2 >= len(kept)


def _looks_like_prose(run: list[list[_Line]], cols: list[float]) -> bool:
    """Deux colonnes de texte courant (mise en page en colonnes) ne sont pas un tableau."""
    if len(cols) > 2:
        return False
    lengths = sorted(len(ln.text) for row in run for ln in row if not ln.removed)
    return lengths[len(lengths) // 2] > 35


def _mark_tables(rows: list[list[_Line]]) -> list[list[list[_Line]]]:
    """Repère les suites de rangées alignées en colonnes ; renvoie les tableaux trouvés."""
    tables: list[list[list[_Line]]] = []
    i = 0
    while i < len(rows):
        if not _is_cell_row(rows[i]):
            i += 1
            continue
        j = i + 1
        while j < len(rows) and _is_cell_row(rows[j]) and _aligned(rows[j], _columns(rows[i:j])):
            j += 1
        run = rows[i:j]
        cols = _columns(run)
        if len(run) >= MIN_TABLE_ROWS and not _looks_like_prose(run, cols):
            for row in run:
                for ln in row:
                    ln.table = len(tables)
            tables.append(run)
            i = j
        else:
            i += 1
    return tables


def _table_text(run: list[list[_Line]]) -> str:
    cols = _columns(run)
    out = ["[Tableau]"]
    for row in run:
        cells = [""] * len(cols)
        for ln in row:
            if ln.removed:
                continue
            c = min(range(len(cols)), key=lambda k: abs(cols[k] - ln.x0))
            cells[c] = f"{cells[c]} {ln.text}".strip()
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _page_text(lines: list[_Line], tables: list[list[list[_Line]]]) -> str:
    """Blocs dans l'ordre de pdfminer ; chaque tableau prend la place de sa première ligne."""
    parts: list[str] = []
    buf: list[str] = []
    done: set[int] = set()
    by_box: dict[int, list[_Line]] = {}
    for ln in lines:
        by_box.setdefault(ln.box, []).append(ln)
    for box in sorted(by_box):
        for ln in by_box[box]:
            if ln.removed:
                continue
            if ln.table >= 0:
                if ln.table not in done:
                    done.add(ln.table)
                    if buf:
                        parts.append("\n".join(buf))
                        buf = []
                    parts.append(_table_text(tables[ln.table]))
                continue
            buf.append(ln.text)
        if buf:
            parts.append("\n".join(buf))
            buf = []
    return "\n".join(parts).strip()


def read_pdf(path: str) -> PdfText:
    out = PdfText()
    pages: list[tuple[list[_Line], list[list[_Line]]]] = []
    for page in extract_pages(path, laparams=LAParams()):
        lines = _page_lines(page)
        pages.append((lines, _rows(lines)))
    out.repeated = _mark_repeats([rows for _, rows in pages if rows])
    for i, (lines, rows) in enumerate(pages, start=1):
        if not lines:
            out.empty.append(i)
            out.pages.append("")
            continue
        out.pages.append(_page_text(lines, _mark_tables(rows)))
    return out
