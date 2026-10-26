# Analyse documentaire

Importez vos documents, choisissez comment les lire, et laissez un modèle de langage en dégager les grands thèmes.

Quatre modes d'analyse : **Synthèse globale**, **Synthèse de transcription**, **Synthèse de notes en vrac** et **Flux et parcours utilisateurs**, chacun en trois niveaux de détail (synthétique, détaillé, très détaillé).

Écrans : Configuration → Analyse en cours (progression et thèmes en direct) → Synthèse par thèmes, ou carte du parcours pour le mode Flux. Les synthèses s'exportent en Markdown, Word ou PDF.

## 1. Démarrage

### Sous Linux / macOS
```bash
./start.sh
```

### Sous Windows
Double-cliquez simplement sur **`start.bat`** (ou lancez `start.bat` dans un terminal).

Le script vérifie automatiquement l'installation, installe les dépendances manquantes si nécessaire, lance le backend sur http://localhost:8000, le frontend sur **http://localhost:5173**, et ouvre directement votre navigateur.

Pour tout arrêter d'un coup sous Windows, vous pouvez fermer les fenêtres ou exécuter **`stop.bat`**.

Prérequis Windows : **Python 3.10+** (cochez « Add python.exe to PATH » à l'installation ; le lanceur `py` est utilisé en priorité) et **Node.js LTS**. Au premier lancement, `start.bat` crée `backend\.venv`, installe les dépendances et copie `backend\.env.example` en `backend\.env`. Le backend s'ouvre dans sa propre fenêtre, qui reste ouverte en cas d'erreur pour que vous puissiez lire le message. Si le port 5173 est déjà pris par un ancien lancement, exécutez `stop.bat` puis relancez `start.bat`.

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

**Gros documents et offres limitées** : certaines offres (par exemple une clé Gemini gratuite) limitent le volume traité par minute, bien en dessous de la fenêtre théorique du modèle. Si un gros document envoyé d'un bloc est refusé, l'application bascule automatiquement sur l'analyse par lots. Pour l'éviter d'emblée, fixez `MAX_REQUEST_TOKENS` (par exemple `120000`) et réduisez `MAX_CONCURRENT_LLM_REQUESTS` à 1 ou 2.

Redémarrez le backend après toute modification du `.env`. Ne versionnez jamais `backend/.env` (il est exclu par `.gitignore`).

## 3. Fidélité aux documents

La synthèse doit pouvoir remplacer la lecture des documents. L'application applique pour cela plusieurs garde-fous :

- **Lecture** : aucun texte n'est inventé. Les pages scannées ou les slides sans texte sont signalées, pas décrites. L'ordre d'origine est conservé (tableaux Word, formes PowerPoint). Les CSV/TXT en Windows-1252 sont décodés correctement.
- **Sources** : chaque ligne porte un repère (`L12`, `§4`, `Page 3`, `Slide 2`, `00:01:10`) que le modèle cite pour chaque point.
- **Consignes** : rien en dehors du corpus (chiffres, fréquences, recommandations), tous les documents et tous les thèmes traités, même en fin de document. Le niveau ne règle que la profondeur de rédaction.
- **Vérification en un clic** : chaque source et chaque verbatim ouvre le passage d'origine surligné, avec son contexte ; un repère introuvable est signalé et le passage le plus proche est proposé.
- **Verbatims vérifiés** dans le texte réel : exact, légèrement reformulé, ou introuvable (signalé « à vérifier » à l'écran et dans l'export).
- **Signaux** : document dont rien n'a été retenu, parties non lues, estimations du modèle (ressenti, gravité).
- **Pas de troncature** : une réponse coupée faute de place est reprise automatiquement là où le modèle s'est arrêté.
- **Corpus volumineux** (plus grand que la fenêtre du modèle, fréquent avec Mistral Medium ou Small) : analyse automatique par lots. Chaque lot donne des éléments sourcés (faits, chiffres, décisions, verbatims…) recopiés avec leur repère. Ils sont ensuite classés en thèmes ; un élément non classé va dans « Autres points », il n'est jamais perdu. Enfin, chaque thème est rédigé à partir de ses éléments et des passages d'origine. Réglez `CUSTOM_LLM_CONTEXT_TOKENS` sur la fenêtre réelle du modèle.

## 4. Tests de fidélité

À lancer après toute modification des consignes, du code d'analyse ou du modèle utilisé, pour vérifier que rien n'a régressé.

```bash
cd backend
.venv/bin/python -m pip install -r requirements-dev.txt   # une seule fois
.venv/bin/python -m pytest                                # tests rapides, sans modèle (quelques secondes)
RUN_LLM_TESTS=1 .venv/bin/python -m pytest -m llm -v      # fidélité avec un vrai modèle (payant, quelques minutes)
```

Sous Windows, remplacez `.venv/bin/python` par `.venv\Scripts\python`. Pour tester un modèle précis, ajoutez par exemple `TEST_MODEL="CUSTOM_LLM:mistral-medium-latest"` ; sinon, le premier modèle configuré est utilisé.

- **Tests rapides** : lecture de chaque format (pages scannées signalées, tableaux Word à leur place, formes PowerPoint groupées, CSV Windows-1252), vérification des verbatims, résolution des sources, contrôle de couverture, graphe de flux, aperçu en streaming, historique après redémarrage.
- **Tests avec modèle**, sur les documents de `backend/tests/fixtures/` :
  - aux trois niveaux, aucune information clé perdue, y compris en fin de document ;
  - tous les documents exploités, aucun verbatim inventé, une source par point, des repères existants ;
  - un parcours reconstitué avec ses abandons ;
  - un corpus volumineux analysé par lots sans perte (16 faits uniques).

## 5. API

- `GET /api/v2/models` : modèles déclarés et leur disponibilité
- `POST /api/v2/documents` : import et lecture d'un fichier (PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, VTT/SRT)
- `POST /api/v2/analyses` puis `GET /api/v2/analyses/{id}` : analyse en 5 étapes avec aperçu des thèmes en direct
- `GET /api/v2/analyses` : historique
- `POST /api/v2/analyses/{id}/cancel` : annulation
- `DELETE /api/v2/analyses/{id}` : suppression (avec les documents qui ne servent plus)
- `GET /api/v2/analyses/{id}/source?document=&location=&text=` : passage d'origine d'une source, lignes concernées surlignées
- `GET /api/v2/analyses/{id}/export?format=md|docx|pdf`

## 6. Historique et données

Documents importés et analyses sont enregistrés dans `backend/data/` (base SQLite `analyses.db` et fichiers d'origine). Ce dossier est exclu de git, car il contient des données confidentielles. L'écran **Historique** permet de rouvrir ou de supprimer une analyse. Supprimer une analyse efface aussi ses documents s'ils ne servent à aucune autre. Un document importé mais jamais analysé est effacé au bout de 24 h. Une analyse en cours lors d'un arrêt du backend est marquée comme interrompue au redémarrage.
