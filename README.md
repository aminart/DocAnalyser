# DocAnalyser

Importez vos documents, choisissez comment les lire, et laissez un modèle de langage en dégager les grands thèmes.

Quatre modes d'analyse : **Synthèse globale**, **Synthèse de transcription**, **Synthèse de notes en vrac** et **Flux et parcours utilisateurs**, chacun en trois niveaux de détail (synthétique, détaillé, très détaillé).

Interface : design system commun **Night Navy** (le même que SpecGen et Audit ergonomique, paquet `night-navy` du dépôt [Design-system-](https://github.com/aminart/Design-system-)), en mode clair ou sombre : le bouton en haut à droite bascule, sinon le thème suit celui du système.

Écrans : Configuration → Analyse en cours (progression et thèmes en direct) → Synthèse par thèmes, ou carte du parcours pour le mode Flux. Les synthèses s'exportent en Markdown, Word ou PDF.

## 1. Démarrage

### Windows : l'exécutable (recommandé)

`DocAnalyser.exe`, sans Python ni Node.js à installer. Le télécharger depuis la dernière release GitHub du dépôt (fichier `DocAnalyser-X.Y.Z.exe`), le copier dans un dossier, double-cliquer. Une fenêtre noire s'ouvre : la garder ouverte pendant l'utilisation (la fermer arrête l'application) ; le navigateur s'ouvre sur http://127.0.0.1:8020. Les connexions aux modèles se règlent dans l'onglet **Réglages**.

Depuis l'exe, les documents importés, l'historique et les connexions sont enregistrés dans `%APPDATA%\DocAnalyser` ; un fichier `.env` facultatif se place **à côté de l'exe**. Windows SmartScreen peut afficher « Windows a protégé votre ordinateur » au premier lancement (exécutable non signé) : « Informations complémentaires » puis « Exécuter quand même ».

### Sous Linux / macOS
```bash
./start.sh
```

### Sous Windows, depuis les sources
Double-cliquez simplement sur **`start.bat`** (ou lancez `start.bat` dans un terminal).

Le script vérifie automatiquement l'installation, installe les dépendances manquantes si nécessaire, compile l'interface si elle est absente ou plus ancienne que ses sources, puis lance l'application sur **http://127.0.0.1:8020** et ouvre votre navigateur. Le backend sert lui-même l'interface compilée (`frontend/dist`) : un seul processus, une seule fenêtre, une seule adresse.

Pour arrêter, fermez la fenêtre (ou Ctrl+C), ou exécutez **`stop.bat`**.

Prérequis Windows : **Python 3.10+** (cochez « Add python.exe to PATH » à l'installation ; le lanceur `py` est utilisé en priorité) et **Node.js LTS**, nécessaire seulement pour compiler l'interface (premier lancement, puis après une mise à jour de ses sources). Au premier lancement, `start.bat` crée `backend\.venv`, installe les dépendances et copie `backend\.env.example` en `backend\.env`. La fenêtre reste ouverte en cas d'erreur pour que vous puissiez lire le message. Si le port 8020 est déjà pris par un ancien lancement, exécutez `stop.bat` puis relancez `start.bat`.

**Réseau d'entreprise** : l'application n'utilise que des bibliothèques Python courantes (FastAPI, httpx, PyMuPDF, python-docx…). Les appels aux modèles passent par un petit client interne compatible OpenAI, sans dépendance spécialisée souvent bloquée par les proxys. Si `pip install` échoue quand même avec une erreur 403 ou de certificat, c'est le dépôt de paquets de l'entreprise qui refuse le téléchargement : demandez à votre service informatique l'adresse du miroir PyPI interne, puis configurez-le avec `pip config set global.index-url <adresse>`.

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
npm run build      # interface compilée, servie par le backend
```

### Lancement par le portail

L'application respecte le contrat commun aux applications de la suite :

| | |
|---|---|
| Port par défaut | **8020** |
| Options | `--port N` (port imposé : échec explicite, code 2, s'il est pris par une autre application), `--no-browser`, `--version` |
| État | `GET /health` → `{"status": "ok", "app": "docanalyser", "name": "DocAnalyser", "version": "…"}` |

Exemple : `DocAnalyser.exe --port 8020 --no-browser`, ou depuis les sources `backend/.venv/bin/python backend/launcher.py --port 8020 --no-browser`. La version vient du fichier `VERSION` (voir « Versions »).

### Développement de l'interface

```bash
backend/.venv/bin/python backend/launcher.py --no-browser --reload   # API sur http://127.0.0.1:8020
cd frontend && npm run dev                                          # interface sur http://localhost:5173, rechargée à chaque modification
```

Vite relaie `/api` vers le backend (voir `frontend/vite.config.ts`).

## 2. Connexions aux modèles : écran Réglages

Les modèles se configurent dans l'application, onglet **Réglages**, avec la même logique que SpecGen et Audit ergonomique, et **plusieurs connexions** possibles, chacune avec **plusieurs modèles**.

| Champ | Rôle |
|---|---|
| Nom | Affiché à côté de chaque modèle au moment de lancer une analyse. |
| URL du service | Adresse du service **compatible OpenAI** : passerelle interne, Mistral, vLLM, Ollama, LM Studio, Azure… |
| Clé API | **Chiffrée avec le compte Windows** (DPAPI), jamais réaffichée en clair. Facultative pour un serveur sans clé (Ollama, LM Studio). |
| Certificat de l'entreprise *(facultatif)* | `.crt` (PEM ou DER) de l'autorité qui a signé le certificat HTTPS du serveur, copié dans l'application ; expiration affichée. Les autorités internes sans extension « key usage » sont acceptées (chaîne et nom du serveur vérifiés). |
| Modèles | Autant que voulu. Le profil (approfondi, équilibré, rapide) est déduit du nom. |
| Options avancées | Fenêtre de contexte (tokens). |

**Tester la connexion** vérifie les valeurs saisies avant d'enregistrer et indique la cause d'un échec : serveur injoignable, délai dépassé, certificat non reconnu, clé refusée, adresse ou modèle introuvable. Si le serveur liste ses modèles, le test signale ceux qui n'y sont pas et **propose ceux qui y sont, à ajouter d'un clic**.

Les connexions sont enregistrées dans `%APPDATA%\DocAnalyser` (`~/.config/docanalyser` hors Windows ; `DOCANALYSER_CONFIG` pour un autre dossier).

### Déploiement sur plusieurs postes : fichier `backend/.env`

Les fournisseurs déclarés dans `backend/.env` (modèle : `backend/.env.example`) restent valables : ils **s'ajoutent** aux connexions de l'écran, qui les affiche en lecture seule (étiquette « Fichier .env »).

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

Redémarrez l'application après toute modification du `.env` (les changements faits dans l'écran Réglages s'appliquent tout de suite). Ne versionnez jamais `backend/.env` (il est exclu par `.gitignore`).

## Versions

Le numéro de version vit à **un seul endroit** : le fichier `VERSION`, à la racine. L'application (`/health`, `--version`) et l'exe (Propriétés › Détails sous Windows) le lisent là. Les changements sont notés au fil de l'eau dans `CHANGELOG.md`, section « Non publié ».

Numérotation `MAJEUR.MINEUR.CORRECTIF` ([versionnage sémantique](https://semver.org/lang/fr/)) : correction → `patch` (2.0.0 → 2.0.1), nouvelle fonction → `minor` (2.0.1 → 2.1.0), changement qui casse l'existant (historique ou connexions enregistrés illisibles par l'ancienne version) → `major` (2.1.0 → 3.0.0).

Publier une version :

1. Vérifier que `CHANGELOG.md` décrit bien ce qui a changé, sous « Non publié ».
2. `python scripts/bump_version.py minor` (ou `patch`, `major`, ou un numéro `2.2.0`) : met à jour `VERSION`, la version de l'interface et date la section du journal.
3. Committer, fusionner sur `main`.
4. Sur GitHub : *Releases › Draft a new release*, tag **`vX.Y.Z`** (le même numéro que `VERSION`), coller la section du journal en description, *Publish release*.
5. Le workflow « Build Windows exe » compile l'interface, fabrique l'exe, vérifie qu'il démarre et le joint à la release sous le nom `DocAnalyser-X.Y.Z.exe` (quelques minutes). Si le tag ne correspond pas à `VERSION`, il s'arrête avec un message.

À chaque push, le même workflow dépose l'exe en artefact `DocAnalyser-windows` (onglet *Actions*). Fabrication à la main, sur un PC Windows : `cd frontend && npm ci && npm run build`, puis à la racine `pip install -r backend/requirements.txt pyinstaller` et `pyinstaller --noconfirm DocAnalyser.spec` (résultat dans `dist\`).

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

- `GET /health` : état et version de l'application (contrat du portail)
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
