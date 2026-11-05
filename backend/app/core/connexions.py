"""Connexions aux modèles enregistrées depuis l'écran Réglages, avec plusieurs connexions et plusieurs modèles.

Même logique que SpecGen et Audit ergonomique, étendue à plusieurs connexions :
- chaque connexion est compatible OpenAI (passerelle interne, vLLM, Ollama, LM Studio…) : un nom, une adresse,
  une clé facultative, un certificat facultatif et sa liste de modèles ;
- la clé est chiffrée avec le compte Windows (DPAPI) et n'est jamais renvoyée en clair à l'interface ;
- le certificat (.crt, PEM ou DER) est copié dans le dossier de l'utilisateur ;
- tout est enregistré dans %APPDATA%\\DocAnalyser (DOCANALYSER_CONFIG pour un autre dossier).

Les fournisseurs du fichier .env (CUSTOM_LLM, CUSTOM_LLM_2, GEMINI, ANTHROPIC) restent valables : ils s'ajoutent
aux connexions de l'écran, en lecture seule, pour un déploiement sur plusieurs postes.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Kind = Literal["openai", "gemini", "anthropic"]
KINDS: tuple[str, ...] = ("openai", "gemini", "anthropic")
CONTEXT_DEFAULT = {"openai": 128_000, "gemini": 1_000_000, "anthropic": 200_000}
_VERROU = threading.Lock()


def dossier_config() -> Path:
    """Dossier de l'utilisateur où l'écran Réglages enregistre les connexions."""
    if autre := os.environ.get("DOCANALYSER_CONFIG", "").strip():
        return Path(autre).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "DocAnalyser"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "docanalyser"


def _fichier() -> Path:
    return dossier_config() / "connexions.json"


def chemin_certificat(id_: str) -> Path:
    return dossier_config() / "certificats" / f"{id_}.crt"


@dataclass
class Connexion:
    id: str
    kind: Kind
    name: str
    api_base: str = ""
    api_key: dict[str, str] | None = None  # chiffrée
    certificate: dict[str, str] | None = None  # nom, date d'import, date d'expiration
    models: list[str] = field(default_factory=list)
    context_tokens: int = 128_000
    max_output_tokens: int = 0  # 0 : valeur par défaut du serveur
    last_test: dict[str, Any] | None = None


# --- Chiffrement de la clé (même code que SpecGen et Audit ergonomique) -----------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _dpapi(donnees: bytes, chiffrer: bool) -> bytes:
        tampon = ctypes.create_string_buffer(donnees, len(donnees))
        entree = _Blob(len(donnees), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))
        sortie = _Blob()
        if chiffrer:
            ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entree), "DocAnalyser", None, None, None, 0, ctypes.byref(sortie))
        else:
            ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entree), None, None, None, None, 0, ctypes.byref(sortie))
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(sortie.pbData, sortie.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(sortie.pbData)

    def chiffrer(valeur: str) -> dict[str, str]:
        return {"scheme": "dpapi", "data": base64.b64encode(_dpapi(valeur.encode("utf-8"), True)).decode("ascii")}

else:
    # Développement sous Linux / macOS : pas de coffre du système branché, la clé est seulement encodée.
    def chiffrer(valeur: str) -> dict[str, str]:
        return {"scheme": "plain", "data": base64.b64encode(valeur.encode("utf-8")).decode("ascii")}


def dechiffrer(stocke: dict[str, str] | None) -> str:
    if not stocke:
        return ""
    try:
        brut = base64.b64decode(stocke["data"])
        if stocke.get("scheme") == "dpapi":
            return _dpapi(brut, False).decode("utf-8") if sys.platform == "win32" else ""
        return brut.decode("utf-8")
    except (OSError, ValueError, KeyError):
        return ""  # chiffrée par un autre compte Windows, ou illisible : considérée comme absente


# --- Lecture et écriture --------------------------------------------------------------------------------

def lister() -> list[Connexion]:
    try:
        brut = json.loads(_fichier().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    connexions = []
    for c in brut.get("connections", []):
        try:
            connexions.append(Connexion(**{k: v for k, v in c.items() if k in Connexion.__dataclass_fields__}))
        except TypeError:
            continue
    return connexions


def _ecrire(connexions: list[Connexion]) -> None:
    dossier_config().mkdir(parents=True, exist_ok=True)
    _fichier().write_text(json.dumps({"connections": [asdict(c) for c in connexions]}, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def trouver(id_: str) -> Connexion | None:
    return next((c for c in lister() if c.id == id_), None)


def cle(c: Connexion) -> str:
    return dechiffrer(c.api_key)


def certificat(c: Connexion) -> str:
    """Chemin du certificat importé pour cette connexion, ou chaîne vide."""
    chemin = chemin_certificat(c.id)
    return str(chemin) if c.certificate and chemin.is_file() else ""


def nettoyer_modeles(modeles: list[str]) -> list[str]:
    vus, sortie = set(), []
    for m in modeles:
        m = m.strip()
        if m and m not in vus:
            vus.add(m)
            sortie.append(m)
    return sortie


def creer(kind: Kind, name: str, api_base: str, api_key: str | None, models: list[str], context_tokens: int | None,
          max_output_tokens: int = 0) -> Connexion:
    with _VERROU:
        connexions = lister()
        c = Connexion(
            id=f"c{uuid.uuid4().hex[:8]}", kind=kind, name=name.strip() or _nom_defaut(kind),
            api_base=api_base.strip().rstrip("/"), api_key=chiffrer(api_key.strip()) if api_key and api_key.strip() else None,
            models=nettoyer_modeles(models), context_tokens=context_tokens or CONTEXT_DEFAULT[kind],
            max_output_tokens=max_output_tokens,
        )
        connexions.append(c)
        _ecrire(connexions)
        return c


def modifier(id_: str, kind: Kind, name: str, api_base: str, api_key: str | None, models: list[str],
             context_tokens: int | None, max_output_tokens: int = 0) -> Connexion:
    """`api_key` None garde la clé enregistrée ; une chaîne vide l'efface."""
    with _VERROU:
        connexions = lister()
        c = next((c for c in connexions if c.id == id_), None)
        if c is None:
            raise KeyError(id_)
        c.kind, c.name = kind, name.strip() or _nom_defaut(kind)
        c.api_base = api_base.strip().rstrip("/")
        if api_key is not None:
            c.api_key = chiffrer(api_key.strip()) if api_key.strip() else None
        c.models = nettoyer_modeles(models)
        c.context_tokens = context_tokens or CONTEXT_DEFAULT[kind]
        c.max_output_tokens = max_output_tokens
        _ecrire(connexions)
        return c


def supprimer(id_: str) -> None:
    with _VERROU:
        _ecrire([c for c in lister() if c.id != id_])
        chemin_certificat(id_).unlink(missing_ok=True)


def lire_certificat(contenu: bytes) -> tuple[bytes, str]:
    """Vérifie un .crt (PEM ou DER, éventuellement une chaîne) ; renvoie (PEM, date d'expiration la plus proche)."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    try:
        certificats = x509.load_pem_x509_certificates(contenu)
    except ValueError:
        try:
            certificats = [x509.load_der_x509_certificate(contenu)]
        except ValueError as e:
            raise ValueError("Ce fichier n'est pas un certificat valide (.crt au format PEM ou DER attendu).") from e
    pem = b"".join(c.public_bytes(Encoding.PEM) for c in certificats)
    return pem, min(c.not_valid_after_utc for c in certificats).isoformat()


def importer_certificat(id_: str, nom: str, contenu: bytes) -> Connexion:
    pem, expiration = lire_certificat(contenu)
    with _VERROU:
        connexions = lister()
        c = next((c for c in connexions if c.id == id_), None)
        if c is None:
            raise KeyError(id_)
        chemin = chemin_certificat(id_)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(pem)
        c.certificate = {"name": nom, "imported_at": datetime.now(timezone.utc).isoformat(), "expires_at": expiration}
        c.last_test = None
        _ecrire(connexions)
        return c


def retirer_certificat(id_: str) -> Connexion:
    with _VERROU:
        connexions = lister()
        c = next((c for c in connexions if c.id == id_), None)
        if c is None:
            raise KeyError(id_)
        c.certificate = None
        chemin_certificat(id_).unlink(missing_ok=True)
        _ecrire(connexions)
        return c


def enregistrer_test(id_: str, resultat: dict[str, Any]) -> None:
    with _VERROU:
        connexions = lister()
        for c in connexions:
            if c.id == id_:
                c.last_test = resultat
                _ecrire(connexions)
                return


def _nom_defaut(kind: str) -> str:
    return {"openai": "Passerelle", "gemini": "Google Gemini", "anthropic": "Anthropic Claude"}[kind]
