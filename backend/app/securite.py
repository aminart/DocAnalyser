"""Protection de l'API locale contre les pages web ouvertes dans le navigateur.

Le serveur n'écoute que sur 127.0.0.1, mais n'importe quel site ouvert dans le navigateur peut lui envoyer des
requêtes. DocAnalyser garde des documents, des analyses et les clés des connexions aux modèles : sans garde-fou, une
page piégée pourrait les lire, ou lancer des analyses avec ces clés. Trois protections (les mêmes que Studio Dock et
Snappy Transcript) :

1. Host : seulement 127.0.0.1 / localhost / ::1. Contre le « DNS rebinding » (un site fait pointer son propre
   domaine vers 127.0.0.1 et lit alors toutes les réponses comme si c'était lui).
2. Requêtes qui modifient (POST, PUT, PATCH, DELETE) : seulement depuis l'interface servie par ce même serveur
   (en-tête Origin identique, ou Sec-Fetch-Site « same-origin »). Les envois sans navigateur (Snappy Transcript qui
   dépose une transcription, Studio Dock, curl) n'envoient pas ces en-têtes et restent acceptés.
3. En-têtes : pas d'affichage dans une page tierce (clic piégé), pas de lecture des fichiers depuis un autre site.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

HOTES_LOCAUX = {"127.0.0.1", "localhost", "::1"}
SURES = {"GET", "HEAD", "OPTIONS"}
ENTETES = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
}


def nom_d_hote(valeur: str) -> str:
    try:
        return (urlsplit(valeur if "://" in valeur else f"http://{valeur}").hostname or "").lower()
    except ValueError:
        return ""


def refus(requete: Request, nom: str) -> str | None:
    """Raison du refus, ou None si la requête est acceptée."""
    hote = requete.headers.get("host", "")
    if nom_d_hote(hote) not in HOTES_LOCAUX:
        return f"Adresse refusée : {nom} ne répond qu'à 127.0.0.1."
    if requete.method not in SURES:
        origine = requete.headers.get("origin")
        site = requete.headers.get("sec-fetch-site", "")
        meme = {f"http://{hote}".lower(), f"https://{hote}".lower()}
        if origine is not None and origine.rstrip("/").lower() not in meme:
            return f"Requête refusée : elle ne vient pas de l'interface de {nom}."
        if origine is None and site in ("cross-site", "same-site"):
            return f"Requête refusée : elle ne vient pas de l'interface de {nom}."
    return None


def proteger(app: FastAPI, nom: str) -> None:
    @app.middleware("http")
    async def garde_locale(requete: Request, suite):
        raison = refus(requete, nom)
        if raison:
            return JSONResponse({"detail": raison}, status_code=403)
        reponse = await suite(requete)
        for cle, valeur in ENTETES.items():
            reponse.headers.setdefault(cle, valeur)
        return reponse
