#!/bin/bash

# Gestion de l'arrêt propre avec Ctrl+C
cleanup() {
    echo -e "\nArrêt de l'application..."
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "🚀 Lancement de l'application Analyse documentaire..."

# 1. Vérifier / Lancer le backend
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✅ Le Backend est déjà actif sur http://localhost:8000"
else
    echo "📦 Démarrage du Backend sur http://localhost:8000..."
    if [ -f "backend/.venv/bin/activate" ]; then
        source backend/.venv/bin/activate
    else
        echo "❌ backend/.venv introuvable : voir « Première installation » dans le README."
        exit 1
    fi
    uvicorn app.main:app --app-dir backend --reload --port 8000 &
    BACKEND_PID=$!
    sleep 1
fi

# 2. Lancer le frontend
echo "💻 Démarrage du Frontend sur http://localhost:5173..."
cd "$(dirname "$0")/frontend" || exit 1
npm run dev
