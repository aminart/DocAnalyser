#!/bin/bash
# Lance Analyse documentaire : le backend sert aussi l'interface compilée, sur http://127.0.0.1:8020.
# Node.js n'est nécessaire que pour compiler l'interface (absente, ou plus ancienne que ses sources).
# Options transmises au lanceur : ./start.sh --no-browser, ./start.sh --port 8021, ./start.sh --reload…

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

echo "🚀 Lancement de l'application Analyse documentaire..."

# 1. Environnement Python
if [ ! -f "backend/.venv/bin/python" ]; then
    echo "❌ backend/.venv introuvable : voir « Première installation » dans le README."
    exit 1
fi

# 2. Interface compilée, reconstruite si une source est plus récente
DIST="frontend/dist/index.html"
if [ ! -f "$DIST" ] || [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer "$DIST" -print -quit)" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "❌ L'interface doit être compilée, mais npm est introuvable : installez Node.js LTS."
        exit 1
    fi
    echo "💻 Compilation de l'interface..."
    (cd frontend && { [ -d node_modules ] || npm install; } && npm run build) || { echo "❌ La compilation de l'interface a échoué."; exit 1; }
fi

# 3. Lancement (Ctrl+C pour arrêter)
exec backend/.venv/bin/python backend/launcher.py "$@"
