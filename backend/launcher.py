"""Lance DocAnalyser : python backend/launcher.py [--port 8020] [--no-browser] [--version] [--reload]

Le backend sert aussi l'interface compilée (frontend/dist) : une seule adresse, http://127.0.0.1:8020.

Contrat commun aux applications de la suite (lancement par le portail) :
- --port N : port imposé ; s'il est pris par une autre application, échec explicite (code 2) ;
- --no-browser : ne pas ouvrir le navigateur ;
- --version : affiche la version ;
- GET /health : {"status": "ok", "app": "docanalyser", "name": ..., "version": ...}.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
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


def _ouvrir_dans_le_terminal(argv: list[str]) -> bool:
    """Mac, double-clic sur DocAnalyser.app : relance l'application dans une fenêtre du Terminal.

    Comme la fenêtre noire de l'exe Windows, elle montre l'adresse et les messages, et la fermer arrête
    l'application. Sans elle, l'app tournerait sans fenêtre ni moyen simple de l'arrêter. Pas de relance quand des
    options sont données (portail Studio Dock, --no-browser…) ou quand on est déjà dans un terminal.
    """
    if sys.platform != "darwin" or not getattr(sys, "frozen", False) or argv:
        return False
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return False
        subprocess.run(["/usr/bin/open", "-a", "Terminal", sys.executable], check=True, timeout=30)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False  # Terminal indisponible : l'application démarre quand même, sans fenêtre
    return True


def main(argv: list[str] | None = None) -> None:
    # Ancien macOS : le Finder ajoute -psn_… au lancement d'une app
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if not a.startswith("-psn_")]
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
    if _ouvrir_dans_le_terminal(argv):
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
