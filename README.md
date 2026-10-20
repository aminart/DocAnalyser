# Analyse documentaire

Importez vos documents, choisissez comment les lire, et laissez un modèle de langage en dégager les grands thèmes.

Quatre modes d'analyse : **Synthèse globale**, **Synthèse de transcription**, **Synthèse de notes en vrac** et **Flux et parcours utilisateurs**, chacun en trois niveaux de détail (synthétique, détaillé, très détaillé).

Écrans : Configuration → Analyse en cours (progression et thèmes en direct) → Synthèse par thèmes, ou carte du parcours pour le mode Flux. Les synthèses s'exportent en Markdown, Word ou PDF.

## 1. Démarrage

```bash
./start.sh
```

Le script lance le backend sur http://localhost:8000 puis le frontend sur **http://localhost:5173**. Ctrl+C arrête les deux.

### Première installation

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

```bash
cd frontend
npm install
```

## 2. Configuration des modèles (`backend/.env`)

Les modèles proposés dans l'application sont **exactement ceux listés dans `backend/.env`**, dans le même ordre (modèle : `backend/.env.example`).

**Fournisseurs compatibles OpenAI** (vLLM, Ollama, Azure OpenAI, passerelle interne…), deux au plus : `CUSTOM_LLM_*` et `CUSTOM_LLM_2_*`.

```ini
CUSTOM_LLM_PROVIDER_NAME="Passerelle interne"
CUSTOM_LLM_API_KEY="..."            # facultative
CUSTOM_LLM_API_BASE="https://votre-endpoint/v1"
CUSTOM_LLM_CA_BUNDLE=""             # certificat d'entreprise (PEM), si nécessaire
CUSTOM_LLM_AVAILABLE_MODELS="mistral-large-latest,qwen2.5-32b"
CUSTOM_LLM_CONTEXT_TOKENS=128000
```

Un modèle n'est sélectionnable que si l'`API_BASE` de son fournisseur est renseignée.

**Clés de test** : renseignez `GEMINI_API_KEY` et/ou `ANTHROPIC_API_KEY`. Le fournisseur apparaît alors avec les modèles de `GEMINI_TEST_MODELS` / `ANTHROPIC_TEST_MODELS` ; sans clé, il reste masqué.

En cas de quota dépassé ou de surcharge, l'analyse bascule automatiquement sur un autre modèle du même fournisseur.

Redémarrez le backend après toute modification du `.env`. Ne versionnez jamais `backend/.env` (il est exclu par `.gitignore`).

## 3. API

- `GET /api/v2/models` : modèles déclarés et leur disponibilité
- `POST /api/v2/documents` : import et lecture d'un fichier (PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, VTT/SRT)
- `POST /api/v2/analyses` puis `GET /api/v2/analyses/{id}` : analyse en 5 étapes avec aperçu des thèmes en direct
- `DELETE /api/v2/analyses/{id}` : annulation
- `GET /api/v2/analyses/{id}/export?format=md|docx|pdf`

Les documents et analyses sont conservés en mémoire : un redémarrage du backend les efface.
