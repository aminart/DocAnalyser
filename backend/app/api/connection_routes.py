"""Écran Réglages : connexions aux modèles (même logique que SpecGen et Audit ergonomique, plusieurs connexions).

GET    /api/v2/connections                   connexions de l'écran et fournisseurs du .env (lecture seule)
POST   /api/v2/connections                   ajouter une connexion
PUT    /api/v2/connections/{id}              modifier (api_key absente : clé gardée ; vide : clé effacée)
DELETE /api/v2/connections/{id}              supprimer
POST   /api/v2/connections/{id}/certificate  importer le certificat (.crt) ; DELETE pour le retirer
POST   /api/v2/connections/test              tester les valeurs saisies, avant d'enregistrer
"""
from __future__ import annotations

import base64
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core import connexions
from app.core.config import ENV_PATH
from app.services import analysis_service as svc
from app.services import llm_client

router = APIRouter(prefix="/api/v2/connections", tags=["Réglages"])

DELAI_TEST = 30.0
BASES = {"gemini": llm_client.GEMINI_BASE, "anthropic": llm_client.ANTHROPIC_BASE}
LIBELLES_TYPE = {"openai": "Compatible OpenAI", "gemini": "Google Gemini", "anthropic": "Anthropic Claude"}


class ConnexionForm(BaseModel):
    kind: Literal["openai"] = "openai"  # l'écran Réglages n'enregistre que des connexions compatibles OpenAI
    name: str = ""
    api_base: str = ""
    api_key: str | None = None  # None : garder la clé enregistrée
    models: list[str] = Field(default_factory=list)
    context_tokens: int | None = Field(default=None, ge=1000, le=10_000_000)
    max_output_tokens: int = Field(default=0, ge=0, le=1_000_000)
    last_test: dict[str, Any] | None = None  # test fait sur ces valeurs avant d'enregistrer : gardé avec la connexion


class TestForm(ConnexionForm):
    kind: Literal["openai", "gemini", "anthropic"] = "openai"  # GEMINI / ANTHROPIC du .env restent testables
    id: str | None = None  # connexion enregistrée : sa clé et son certificat servent si rien d'autre n'est fourni
    certificate_b64: str | None = None  # certificat choisi mais pas encore enregistré


# --- Représentation pour l'interface (jamais la clé) -------------------------------------------------------

def _indice(cle: str) -> str:
    return cle[-4:] if len(cle) >= 8 else ""


def _publique(c: connexions.Connexion) -> dict[str, Any]:
    cle = connexions.cle(c)
    return {
        "id": c.id, "source": "app", "kind": c.kind, "kind_label": LIBELLES_TYPE[c.kind], "name": c.name,
        "api_base": c.api_base if c.kind == "openai" else BASES[c.kind],
        "has_api_key": bool(cle), "api_key_hint": _indice(cle),
        "certificate": c.certificate if connexions.certificat(c) else None,
        "models": c.models, "context_tokens": c.context_tokens, "max_output_tokens": c.max_output_tokens,
        "last_test": c.last_test,
    }


def _depuis_env() -> list[dict[str, Any]]:
    """Fournisseurs déclarés dans le .env : affichés en lecture seule."""
    sortie = []
    for p in svc.providers():
        if p.key not in svc.ENV_PROVIDERS or not (p.models or p.api_key or (p.kind == "openai" and p.api_base)):
            continue
        sortie.append({
            "id": f"env:{p.key}", "source": "env", "env_prefix": p.key, "kind": p.kind, "kind_label": LIBELLES_TYPE[p.kind],
            "name": p.name, "api_base": p.api_base, "has_api_key": bool(p.api_key), "api_key_hint": _indice(p.api_key),
            "certificate": {"name": Path(p.ca_bundle).name} if p.ca_bundle else None, "models": list(p.models),
            "context_tokens": p.context_tokens, "max_output_tokens": p.max_output_tokens, "last_test": None,
        })
    return sortie


def _tout() -> dict[str, Any]:
    return {
        "connections": _depuis_env() + [_publique(c) for c in connexions.lister()],
        "env_file": str(ENV_PATH) if ENV_PATH.is_file() else None,
        "storage_dir": str(connexions.dossier_config()),
    }


# --- Routes ----------------------------------------------------------------------------------------------

def _verifier(form: ConnexionForm) -> None:
    if form.kind == "openai" and not form.api_base.strip().lower().startswith(("http://", "https://")):
        raise HTTPException(422, "Renseignez l'URL du service (http:// ou https://).")


@router.get("")
def lister() -> dict[str, Any]:
    return _tout()


@router.post("")
def creer(form: ConnexionForm) -> dict[str, Any]:
    _verifier(form)
    c = connexions.creer(form.kind, form.name, form.api_base, form.api_key, form.models, form.context_tokens,
                         form.max_output_tokens)
    if form.last_test:
        connexions.enregistrer_test(c.id, form.last_test)
    return {**_tout(), "created": c.id}


@router.put("/{id_}")
def modifier(id_: str, form: ConnexionForm) -> dict[str, Any]:
    _verifier(form)
    try:
        connexions.modifier(id_, form.kind, form.name, form.api_base, form.api_key, form.models, form.context_tokens,
                            form.max_output_tokens)
    except KeyError as e:
        raise HTTPException(404, "Connexion introuvable.") from e
    if form.last_test:
        connexions.enregistrer_test(id_, form.last_test)
    return _tout()


@router.delete("/{id_}")
def supprimer(id_: str) -> dict[str, Any]:
    connexions.supprimer(id_)
    return _tout()


@router.post("/{id_}/certificate")
def importer_certificat(id_: str, file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        connexions.importer_certificat(id_, file.filename or "certificat.crt", file.file.read())
    except KeyError as e:
        raise HTTPException(404, "Connexion introuvable.") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _tout()


@router.delete("/{id_}/certificate")
def retirer_certificat(id_: str) -> dict[str, Any]:
    try:
        connexions.retirer_certificat(id_)
    except KeyError as e:
        raise HTTPException(404, "Connexion introuvable.") from e
    return _tout()


# --- Test de connexion -----------------------------------------------------------------------------------

def _echec(champ: str | None, titre: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "field": champ, "title": titre, "message": message, **extra}


def _certificat_refuse(exc: BaseException) -> bool:
    courante: BaseException | None = exc
    while courante is not None:
        if isinstance(courante, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(courante):
            return True
        courante = courante.__cause__ or courante.__context__
    return False


def _diagnostic(exc: Exception, base: str) -> dict[str, Any]:
    if _certificat_refuse(exc):
        return _echec("certificate", "Échec de la connexion : certificat non reconnu",
                      "Le serveur a été joint, mais la connexion sécurisée a été refusée. Importez le certificat (.crt) de "
                      "l'autorité qui a signé celui du serveur, fourni par votre service informatique.")
    if isinstance(exc, (llm_client.TimeoutError, httpx.TimeoutException)):
        return _echec("api_base", "Échec de la connexion : délai dépassé",
                      "Le service n'a pas répondu à temps. Vérifiez l'adresse et votre accès au réseau.")
    if isinstance(exc, llm_client.AuthenticationError):
        return _echec("api_key", "Échec de la connexion : clé API refusée",
                      "Le service a refusé la clé API. Vérifiez qu'elle a été copiée en entier et qu'elle est toujours valide.")
    if isinstance(exc, llm_client.NotFoundError):
        return _echec("models", "Échec de la connexion : adresse ou modèle introuvable",
                      "Le service répond, mais l'adresse ou le modèle demandé n'existe pas. Vérifiez l'adresse (elle se "
                      f"termine souvent par /v1) et le nom du modèle. Détail : {exc}")
    if isinstance(exc, (llm_client.ServiceUnavailableError, httpx.HTTPError)):
        return _echec("api_base", "Échec de la connexion : serveur injoignable",
                      f"Aucune réponse de {base}. Vérifiez l'adresse et votre accès au réseau (VPN). Détail : {exc}")
    if isinstance(exc, llm_client.LLMError):
        return _echec(None, f"Échec de la connexion : erreur {exc.status or ''}".strip(), str(exc))
    return _echec(None, "Échec de la connexion", f"{type(exc).__name__} : {exc}")


async def _modeles_du_serveur(base: str, cle: str, ca: str) -> list[str] | None:
    """Modèles listés par le serveur (GET /models), ou None s'il ne les liste pas. Lève les erreurs réseau."""
    entetes = {"Authorization": f"Bearer {cle}"} if cle else {}
    async with httpx.AsyncClient(verify=llm_client.verification(ca), timeout=httpx.Timeout(DELAI_TEST, connect=15.0)) as client:
        reponse = await client.get(base.rstrip("/") + "/models", headers=entetes)
    if reponse.status_code in (401, 403):
        raise llm_client.AuthenticationError(reponse.text[:300], reponse.status_code)
    if reponse.status_code >= 400:
        return None  # passerelle sans /models (404, 405, 501…)
    try:
        donnees = reponse.json().get("data", [])
        return sorted({str(m.get("id")) for m in donnees if isinstance(m, dict) and m.get("id")})
    except (ValueError, AttributeError):
        return None


async def _tester(base: str, cle: str, ca: str, modeles: list[str]) -> dict[str, Any]:
    try:
        disponibles = await _modeles_du_serveur(base, cle, ca)
    except Exception as e:  # noqa: BLE001 : diagnostiqué
        return _diagnostic(e, base)

    if disponibles is not None:
        # Ollama nomme les modèles « nom:étiquette » ; « mistral-small » désigne « mistral-small:latest »
        def present(m: str) -> bool:
            return any(d == m or d.split(":")[0] == m or d.endswith("/" + m) for d in disponibles)

        absents = [m for m in modeles if not present(m)]
        if modeles and len(absents) == len(modeles):
            return _echec("models", "Aucun des modèles indiqués n'est proposé par le serveur",
                          f"Introuvables : {', '.join(absents)}. Choisissez parmi les modèles disponibles.",
                          available=disponibles)
        message = f"{len(disponibles)} modèle(s) proposé(s) par le serveur"
        if absents:
            message += f" ; introuvable(s) : {', '.join(absents)}"
        return {"ok": True, "field": "models" if absents else None, "title": "Connexion opérationnelle",
                "message": message, "available": disponibles, "missing": absents}

    # Pas de liste : un petit appel au premier modèle vérifie l'adresse, la clé et le nom du modèle.
    if not modeles:
        return _echec("models", "Indiquez au moins un modèle",
                      "Ce serveur ne liste pas ses modèles : renseignez le nom d'un modèle pour tester la connexion.")
    try:
        await llm_client.chat(base_url=base, api_key=cle, model=modeles[0], max_tokens=1, ca_bundle=ca,
                              messages=[{"role": "user", "content": "ping"}])
    except Exception as e:  # noqa: BLE001 : diagnostiqué
        return _diagnostic(e, base)
    return {"ok": True, "field": None, "title": "Connexion opérationnelle", "message": f"modèle {modeles[0]}",
            "available": None, "missing": []}


@router.post("/test")
async def tester(form: TestForm) -> dict[str, Any]:
    enregistree = connexions.trouver(form.id) if form.id else None
    base = BASES.get(form.kind) or form.api_base.strip().rstrip("/")
    if not base.lower().startswith(("http://", "https://")):
        resultat = _echec("api_base", "Adresse invalide", "Renseignez l'URL du service (http:// ou https://).")
        return {**resultat, "at": datetime.now(timezone.utc).isoformat()}
    if form.api_key is None and enregistree and enregistree.api_base and base != enregistree.api_base:
        # La clé enregistrée ne part que vers l'adresse pour laquelle elle a été saisie : sinon, un appel à cette
        # route avec une autre adresse suffirait à l'envoyer à n'importe quel serveur.
        resultat = _echec("api_key", "Saisissez à nouveau la clé API",
                          "L'adresse du service a changé : par sécurité, la clé enregistrée n'est pas envoyée à la "
                          "nouvelle adresse. Saisissez la clé pour tester.")
        return {**resultat, "at": datetime.now(timezone.utc).isoformat()}
    cle = form.api_key.strip() if form.api_key is not None else (connexions.cle(enregistree) if enregistree else "")
    if form.kind != "openai" and not cle:
        resultat = _echec("api_key", "Clé API manquante", f"{LIBELLES_TYPE[form.kind]} exige une clé API.")
        return {**resultat, "at": datetime.now(timezone.utc).isoformat()}

    temporaire = None
    try:
        if form.certificate_b64:
            try:
                pem, _ = connexions.lire_certificat(base64.b64decode(form.certificate_b64))
            except ValueError as e:
                return {**_echec("certificate", "Certificat invalide", str(e)), "at": datetime.now(timezone.utc).isoformat()}
            temporaire = tempfile.NamedTemporaryFile(suffix=".crt", delete=False)
            temporaire.write(pem)
            temporaire.close()
            ca = temporaire.name
        else:
            ca = connexions.certificat(enregistree) if enregistree else ""
        resultat = await _tester(base, cle, ca, connexions.nettoyer_modeles(form.models))
    finally:
        if temporaire:
            Path(temporaire.name).unlink(missing_ok=True)

    resultat["at"] = datetime.now(timezone.utc).isoformat()
    if enregistree:
        connexions.enregistrer_test(enregistree.id, resultat)
    return resultat
