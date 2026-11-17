"""Tableaux Excel et CSV : texte des cellules, ligne d'en-tête réelle et statistiques par colonne.

Un modèle de langage synthétise bien du texte, mal des calculs sur des centaines de lignes. Les totaux, moyennes
et répartitions sont donc calculés ici, exactement, et joints au tableau sous la mention « calculé par
DocAnalyser » : le modèle les cite au lieu de les estimer.
"""
from __future__ import annotations

import datetime as dt
import math
import re

HEADER_SCAN = 30  # lignes examinées pour trouver l'en-tête
MIN_ROWS_FOR_STATS = 5
MAX_CATEGORIES = 12
# Colonnes chiffrées dont une somme n'a pas de sens : identifiants, codes, téléphones, années.
_IDENTIFIER = re.compile(r"(?<!\w)(?:id|n°|no|num[ée]ro|code|r[ée]f[ée]rence|r[ée]f|t[ée]l[ée]phone|t[ée]l|ann[ée]e|siret|siren|cp)(?!\w)", re.I)
_NUMBER = re.compile(r"^[-+]?\d{1,3}(?:[   ]?\d{3})*(?:[.,]\d+)?\s*%?$|^[-+]?\d+(?:[.,]\d+)?\s*%?$")


def cell_text(value: object) -> str:
    """Valeur d'une cellule telle qu'on la lit dans Excel : date sans heure nulle, nombre sans « .0 »."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "VRAI" if value else "FAUX"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return f"{value:.10g}"
    return str(value).strip()


def to_number(value: object) -> float | None:
    """Nombre d'une cellule : valeur numérique d'Excel, ou texte « 1 234,5 », « 12 % »."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str) or not _NUMBER.match(value.strip()):
        return None
    text = re.sub(r"[   %]", "", value.strip()).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def header_index(rows: list[list[str]]) -> int:
    """Indice de la ligne d'en-tête : la première ligne aussi large que le tableau et faite surtout de libellés.

    Un titre (« Enquête 2025 » seul en A1) ou une ligne vide au-dessus du tableau n'est donc pas pris pour l'en-tête.
    """
    head = rows[:HEADER_SCAN]
    widest = max((sum(1 for c in r if c) for r in head), default=0)
    for i, r in enumerate(head):
        filled = [c for c in r if c]
        if len(filled) >= max(2, math.ceil(0.6 * widest)):
            labels = sum(1 for c in filled if to_number(c) is None)
            if labels * 2 >= len(filled):
                return i
    return 0


def fmt(x: float) -> str:
    """Nombre à la française : espace des milliers, virgule décimale, deux décimales au plus."""
    if abs(x - round(x)) < 1e-9:
        text = f"{round(x):,}"
    else:
        text = f"{x:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def column_stats(rows: list[list[str]], header: int, raw: list[list[object]] | None = None) -> list[str]:
    """Lignes de statistiques : somme, moyenne, min, max des colonnes chiffrées ; répartition des colonnes à
    quelques valeurs (statut, oui/non, catégorie). Liste vide pour un petit tableau."""
    data = [(i, r) for i, r in enumerate(rows) if i > header and any(r)]
    if len(data) < MIN_ROWS_FOR_STATS:
        return []
    names = rows[header]
    out: list[str] = []
    for j, name in enumerate(names):
        label = name or f"colonne {j + 1}"
        values = [r[j] for _, r in data if j < len(r) and r[j]]
        if len(values) < 3:
            continue
        raws = [raw[i][j] if raw is not None and i < len(raw) and j < len(raw[i]) else r[j] for i, r in data
                if j < len(r) and r[j]]
        numbers = [n for n in (to_number(v) for v in raws) if n is not None]
        if len(numbers) >= 3 and len(numbers) >= 0.8 * len(values):
            if _IDENTIFIER.search(label):
                continue
            total = sum(numbers)
            out.append(
                f"« {label} » : {len(numbers)} valeurs chiffrées, somme {fmt(total)}, moyenne {fmt(total / len(numbers))}, "
                f"min {fmt(min(numbers))}, max {fmt(max(numbers))}"
            )
            continue
        counts: dict[str, int] = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        if len(counts) <= MAX_CATEGORIES and len(counts) * 2 <= len(values):
            ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            out.append(f"« {label} » : " + ", ".join(f"{v} {n}" for v, n in ranked) + f" (sur {len(values)} valeurs)")
    if not out:
        return []
    filled = len(data)
    return [f"[Statistiques calculées par DocAnalyser sur les {filled} lignes du tableau, pas écrites dans le fichier]"] + out
