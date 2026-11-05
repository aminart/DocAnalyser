"""Identité de l'application, partagée par la route /health et le lanceur (contrat du portail).

Le numéro de version vit à UN seul endroit : le fichier VERSION à la racine du dépôt (embarqué dans l'exe).
Pour publier une version : python scripts/bump_version.py patch|minor|major (voir README, « Versions »).
"""
import sys
from pathlib import Path

APP_ID = "docanalyser"
APP_NAME = "DocAnalyser"
DEFAULT_PORT = 8020


def _fichier_version() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "VERSION"
    return Path(__file__).resolve().parent.parent.parent / "VERSION"


def _lire_version() -> str:
    try:
        return _fichier_version().read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


VERSION = _lire_version()
