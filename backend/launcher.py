"""Lance Analyse documentaire : python backend/launcher.py [--port 8020] [--no-browser] [--version] [--reload]

Le backend sert aussi l'interface compilée (frontend/dist) : une seule adresse, http://127.0.0.1:8020.

Contrat commun aux applications de la suite (lancement par le portail) :
- --port N : port imposé ; s'il est pris par une autre application, échec explicite (code 2) ;
- --no-browser : ne pas ouvrir le navigateur ;
- --version : affiche la version ;
- GET /health : {"status": "ok", "app": "analyse-documentaire", "name": ..., "version": ...}.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.info import APP_ID, APP_NAME, DEFAULT_PORT, VERSION  # noqa: E402

HOST = "127.0.0.1"


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/health", timeout=1) as response:
            return response.status == 200 and json.loads(response.read()).get("app") == APP_ID
    except (OSError, ValueError):
        return False


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((HOST, port)) != 0


def _open_when_ready(url: str, port: int) -> None:
    for _ in range(120):
        if _already_running(port):
            webbrowser.open(url)
            return
        time.sleep(0.5)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="launcher.py", description=APP_NAME)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port d'écoute (défaut {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur (lancement par le portail)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--reload", action="store_true", help="développement : redémarre à chaque modification du backend")
    args = parser.parse_args(argv)
    url = f"http://{HOST}:{args.port}"

    if _already_running(args.port):
        print(f"{APP_NAME} est déjà lancée : {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if not _port_is_free(args.port):
        print(f"Le port {args.port} est déjà utilisé par une autre application : {APP_NAME} ne peut pas démarrer.",
              file=sys.stderr)
        sys.exit(2)

    print(f"{APP_NAME} {VERSION}")
    print(f"L'application est disponible sur {url}")
    print("Gardez cette fenêtre ouverte pendant l'utilisation ; fermez-la pour arrêter l'application.")
    sys.stdout.flush()

    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.port), daemon=True).start()
    if args.reload:
        uvicorn.run("app.main:app", app_dir=str(BACKEND_DIR), host=HOST, port=args.port, reload=True,
                    reload_dirs=[str(BACKEND_DIR / "app")], log_level="warning")
    else:
        from app.main import app

        uvicorn.run(app, host=HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
