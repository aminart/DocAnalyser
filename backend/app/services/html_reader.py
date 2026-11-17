"""Pages web (.html, .htm) : texte visible, titres, listes et tableaux, sans scripts, styles ni menus.

Lecture par html.parser de la bibliothèque standard : aucune dépendance de plus dans l'exécutable.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript", "template", "svg", "nav", "iframe", "object", "button", "select"}
_BLOCK = {
    "p", "div", "section", "article", "main", "header", "footer", "aside", "blockquote", "pre", "figure",
    "figcaption", "ul", "ol", "li", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr",
    "br", "hr", "form", "fieldset", "legend", "details", "summary", "address", "caption",
}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.title = ""
        self._buf: list[str] = []
        self._prefix = ""
        self._skip_tag: str | None = None  # élément ignoré en cours (script, menu, élément masqué…)
        self._skip = 0  # profondeur des éléments de même nom dans l'élément ignoré
        self._in_title = False
        self._pre = 0
        self._tables = 0
        self._table_stack: list[int] = []
        self._row: list[str] | None = None
        self._row_n = 0
        self._cell: list[str] | None = None

    # Lignes ------------------------------------------------------------------

    def _flush(self) -> None:
        text = "".join(self._buf)
        self._buf = []
        if self._pre:
            for ln in text.splitlines():
                if ln.strip():
                    self.lines.append(ln.rstrip())
        else:
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                self.lines.append(f"{self._prefix}{text}")
        self._prefix = ""

    def _write(self, text: str) -> None:
        if self._cell is not None:
            self._cell.append(text)
        else:
            self._buf.append(text)

    # Balises -----------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
            return
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip += 1
            return
        if tag not in _VOID and (tag in _SKIP or "hidden" in dict(attrs) or ("aria-hidden", "true") in attrs):
            self._skip_tag, self._skip = tag, 1
            return
        if tag == "table":
            self._flush()
            self._tables += 1
            self._table_stack.append(self._tables)
            self._row_n = 0
        elif tag == "tr" and self._table_stack:
            self._row, self._row_n = [], self._row_n + 1
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif self._cell is not None:
            if tag in ("br", "p", "div", "li"):
                self._cell.append(" ")
        elif tag in _BLOCK:
            self._flush()
            if tag == "pre":
                self._pre += 1
            elif re.fullmatch(r"h[1-6]", tag):
                self._prefix = "## "
            elif tag == "li":
                self._prefix = "- "

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip -= 1
                if not self._skip:
                    self._skip_tag = None
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._cell is not None:  # cellule non fermée
                self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
                self._cell = None
            if any(self._row):
                n = self._table_stack[-1] if self._table_stack else self._tables
                self.lines.append(f"[Tableau {n}, ligne {self._row_n}] | " + " | ".join(self._row) + " |")
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()
            self._row = self._cell = None
        elif tag in _BLOCK:
            self._flush()
            if tag == "pre" and self._pre:
                self._pre -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_tag:
            self._write(data)

    def close(self) -> None:
        super().close()
        self._flush()


def html_lines(source: str) -> list[str]:
    """Lignes de texte d'une page, dans l'ordre ; le titre de la page en tête s'il n'y figure pas déjà."""
    parser = _TextExtractor()
    parser.feed(source)
    parser.close()
    lines = parser.lines
    title = re.sub(r"\s+", " ", parser.title).strip()
    if title and not any(ln.lstrip("# ").strip() == title for ln in lines[:5]):
        lines.insert(0, f"## {title}")
    return lines
