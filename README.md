# DocIntel Studio — Plateforme d'Analyse Documentaire Multi-Formats & Multi-Modes

Application complète d'ingestion documentaire haute volumétrie et de synthèse intelligente sourcée en **4 modes métiers** (Synthèse Globale, Transcription, Parcours Utilisateurs, Notes en Vrac).

## 1. Démarrage Rapide

### A. Backend (FastAPI + Parsing Multi-Formats + Client Mistral `.env`)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copier et configurer le fichier .env (API KEY, API Base et CA Bundle)
cp .env.example .env

# Lancer le serveur FastAPI sur http://localhost:8000
uvicorn app.main:app --reload --port 8000
```

### B. Frontend (React + Vite + TypeScript + Tailwind CSS + Material Icons)

```bash
cd frontend
npm install
npm run dev
```

Ouvrez ensuite **http://localhost:5173** dans votre navigateur.

---

## 2. Configuration LLM Locale / Entreprise (`backend/.env`)

```ini
MISTRAL_API_KEY="votre_cle_api_mistral_ou_interne"
MISTRAL_API_BASE="https://api.mistral.ai/v1"
MISTRAL_CA_BUNDLE="/chemin/vers/entreprise-ca-bundle.crt"
MISTRAL_AVAILABLE_MODELS="mistral-medium-latest,mistral-small-latest,mistral-large-latest"
MISTRAL_DEFAULT_MODEL="mistral-medium-latest"
```

- Si `MISTRAL_CA_BUNDLE` est renseigné, toutes les requêtes `httpx.AsyncClient` vers votre endpoint LLM utilisent ce certificat d'autorité racine TLS.
- Si vous souhaitez tester l'interface, le découpage par chunks, la traçabilité par page/slide/ligne et les exports (`PDF`, `DOCX`, `Markdown`) avant d'avoir renseigné votre clé API Mistral, laissez `ENABLE_FALLBACK_SIMULATION=true` dans `.env`.

---

## 3. Interface « Analyse documentaire » (API v2)

L'interface (écrans Configuration → Analyse en cours → Synthèse par thèmes / Flux et parcours) s'appuie sur `/api/v2` :

- `POST /api/v2/documents` : import et lecture d'un fichier (pages, lignes…)
- `GET /api/v2/models` : modèles déclarés dans `backend/.env` (`CUSTOM_LLM_AVAILABLE_MODELS`, `CUSTOM_LLM_2_AVAILABLE_MODELS`)
- `POST /api/v2/analyses` puis `GET /api/v2/analyses/{id}` : analyse en 5 étapes avec aperçu des thèmes en direct
- `GET /api/v2/analyses/{id}/export?format=md|docx|pdf`

Les modèles proposés dans l'application sont exactement ceux listés dans `backend/.env` (modèle : `backend/.env.example`), pour deux fournisseurs compatibles OpenAI au plus : `CUSTOM_LLM_*` et `CUSTOM_LLM_2_*` (nom affiché, adresse `API_BASE`, clé facultative, certificat `CA_BUNDLE`, fenêtre de contexte). Un modèle n'est sélectionnable que si l'`API_BASE` de son fournisseur est renseignée. En cas de quota dépassé ou de surcharge, l'analyse bascule automatiquement sur un autre modèle du même fournisseur. Redémarrez le backend après toute modification du `.env`.

**Clés de test (Gemini, Claude)** : renseignez `GEMINI_API_KEY` et/ou `ANTHROPIC_API_KEY` dans `backend/.env`. Le fournisseur apparaît alors dans l'application avec les modèles listés dans `GEMINI_TEST_MODELS` / `ANTHROPIC_TEST_MODELS`. Sans clé, il reste masqué.

Les analyses sont conservées en mémoire : un redémarrage du backend les efface.
