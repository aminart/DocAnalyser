"""Modèles d'IA réglés dans Studio Dock (Réglages › Modèles d'IA), en lecture seule.

Fichier identique dans chaque app de la suite (copie de StudioDock/contrat/studiodock_ia.py) : ne pas le
modifier ici, mais dans Studio Dock, puis recopier. Aucune dépendance en dehors de la bibliothèque standard.

Studio Dock enregistre ses connexions dans le dossier « ia » (format 1) :
    connexions.json   {"format": 1, "connections": [...], "default": {"connection", "model"} | null,
                       "apps": {"<id>": {"connection", "model"} | {"own": true}}}
    certificats/<id>.crt
Emplacement : variable STUDIODOCK_IA (donnée par Studio Dock aux apps qu'il lance), sinon
%LOCALAPPDATA%\\StudioDock\\ia (Windows), ~/Library/Application Support/StudioDock/ia (Mac),
~/.config/studiodock/ia (Linux).

La clé API est chiffrée avec le compte Windows (DPAPI) : l'app, lancée sous le même compte, la déchiffre.

Usage :
    import studiodock_ia
    choix = studiodock_ia.pour_app("specgen")   # Connexion et modèle choisis pour cette app, ou None
    toutes = studiodock_ia.connexions()          # Toutes les connexions (pour une app à plusieurs modèles)
"""
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FORMAT = 1


def dossier() -> Path:
    if autre := os.environ.get("STUDIODOCK_IA", "").strip():
        return Path(autre).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "StudioDock" / "ia"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "StudioDock" / "ia"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "studiodock" / "ia"


@dataclass(frozen=True)
class Connexion:
    id: str
    name: str
    provider: str  # « openai » (service compatible OpenAI) ou « ollama » (modèles sur ce poste)
    api_base: str  # adresse compatible OpenAI, terminée en général par /v1
    api_key: str  # en clair (déchiffrée), vide si aucune
    ca_bundle: str  # chemin du certificat de l'entreprise, vide si aucun
    models: tuple[str, ...] = field(default_factory=tuple)
    context_tokens: int = 128_000
    max_output_tokens: int = 0  # 0 : valeur par défaut du serveur

    @property
    def local(self) -> bool:
        return self.provider == "ollama"


@dataclass(frozen=True)
class Choix:
    connexion: Connexion
    model: str


# --- Déchiffrement de la clé ------------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _dpapi(donnees: bytes) -> bytes:
        tampon = ctypes.create_string_buffer(donnees, len(donnees))
        entree = _Blob(len(donnees), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))
        sortie = _Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entree), None, None, None, None, 0,
                                                        ctypes.byref(sortie)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(sortie.pbData, sortie.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(sortie.pbData)


def _cle(stocke: Any) -> str:
    if not isinstance(stocke, dict) or not stocke.get("data"):
        return ""
    try:
        brut = base64.b64decode(stocke["data"])
        if stocke.get("scheme") == "dpapi":
            return _dpapi(brut).decode("utf-8") if sys.platform == "win32" else ""
        return brut.decode("utf-8")
    except (OSError, ValueError):
        return ""  # chiffrée par un autre compte Windows, ou illisible


# --- Lecture ----------------------------------------------------------------------------------------------

def _brut() -> dict[str, Any]:
    try:
        donnees = json.loads((dossier() / "connexions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(donnees, dict) or int(donnees.get("format") or 0) > FORMAT:
        return {}  # format plus récent que cette copie : ignoré plutôt que mal lu
    return donnees


def _connexion(c: dict[str, Any]) -> Connexion | None:
    try:
        certificat = dossier() / "certificats" / f"{c['id']}.crt"
        return Connexion(
            id=str(c["id"]), name=str(c.get("name") or "Studio Dock"), provider=str(c.get("provider") or "openai"),
            api_base=str(c.get("api_base") or "").rstrip("/"), api_key=_cle(c.get("api_key")),
            ca_bundle=str(certificat) if c.get("certificate") and certificat.is_file() else "",
            models=tuple(str(m) for m in c.get("models") or [] if str(m).strip()),
            context_tokens=int(c.get("context_tokens") or 128_000),
            max_output_tokens=int(c.get("max_output_tokens") or 0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def connexions() -> list[Connexion]:
    """Connexions réglées dans Studio Dock (vide si Studio Dock n'en a aucune, ou n'est pas installé)."""
    return [c for c in (_connexion(x) for x in _brut().get("connections") or [] if isinstance(x, dict))
            if c is not None and c.api_base]


def _resoudre(choix: Any, toutes: list[Connexion]) -> Choix | None:
    if not isinstance(choix, dict):
        return None
    c = next((c for c in toutes if c.id == choix.get("connection")), None)
    if c is None or choix.get("model") not in c.models:
        return None
    return Choix(c, choix["model"])


def pour_app(app_id: str) -> Choix | None:
    """Connexion et modèle que Studio Dock attribue à cette app : son choix propre, sinon le modèle par défaut.

    None : Studio Dock n'a rien réglé, ou l'app doit garder sa configuration propre (« own »).
    """
    brut = _brut()
    toutes = connexions()
    choix = (brut.get("apps") or {}).get(app_id) if isinstance(brut.get("apps"), dict) else None
    if isinstance(choix, dict) and choix.get("own"):
        return None
    return _resoudre(choix, toutes) or _resoudre(brut.get("default"), toutes)


def garde_sa_configuration(app_id: str) -> bool:
    """Studio Dock indique que cette app garde sa configuration propre."""
    apps = _brut().get("apps")
    return isinstance(apps, dict) and isinstance(apps.get(app_id), dict) and bool(apps[app_id].get("own"))
