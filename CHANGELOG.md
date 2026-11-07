# Historique des versions de DocAnalyser

Format : chaque version liste ses changements par type (Ajouté, Modifié, Corrigé). Les numéros suivent
le [versionnage sémantique](https://semver.org/lang/fr/) : voir README, « Versions ».

## [Non publié]

### Ajouté

- Exécutable Windows `DocAnalyser.exe`, sans Python ni Node.js à installer : fabriqué par GitHub à chaque
  push et joint à chaque release. Depuis l'exe, documents et historique sont dans `%APPDATA%\DocAnalyser`,
  le `.env` facultatif à côté de l'exe.
- Versionnement : fichier `VERSION` unique, ce journal, `scripts/bump_version.py`.
- Onglet Réglages : plusieurs connexions aux modèles compatibles OpenAI (passerelle interne, Ollama, LM Studio…), chacune avec ses
  modèles, clé chiffrée, certificat `.crt`, test avec diagnostic et modèles du serveur proposés à l'ajout.
  Les fournisseurs du `.env` restent valables, en lecture seule.
- Mode sombre.
- Onglet **Questions** : interroger les documents d'une analyse. Corpus envoyé en entier s'il tient dans
  `QA_CONTEXT_TOKENS`, sinon recherche par mots-clés (BM25, synonymes proposés par le modèle) sur des passages
  repérés. Réponses rédigées au fil de l'eau, uniquement à partir des documents, avec sources vérifiables en un
  clic ; questions enregistrées avec l'analyse.

### Modifié

- Analyse documentaire devient **DocAnalyser** (identifiant du portail : `docanalyser`).
- Interface sur le design system commun Night Navy (couleurs, police Roboto, arrondis), comme SpecGen et
  Audit ergonomique ; plus de polices téléchargées.
- Dépendances à jour (FastAPI 0.162, Uvicorn 0.54, python-multipart 0.0.32, PyMuPDF 1.28, python-docx 1.2,
  fpdf2 2.8.9…) ; chargement de l'historique au démarrage par `lifespan` (remplace `on_event`, déprécié).
- Tests de l'interface : composants avec Vitest (`npm test`) et bout en bout avec Playwright (`npm run e2e`,
  vrai backend et faux modèle), lancés par la CI.
- Code : `analysis_service.py` découpé (catalogue des modèles, consignes, normalisation, export).

### Corrigé

- Sécurité : la clé API enregistrée d'une connexion n'est plus envoyée à une autre adresse que la sienne lors
  d'un test (il faut la saisir à nouveau), et l'API n'accepte plus que l'interface locale (CORS limité à
  `127.0.0.1` et `localhost`) : un site ouvert dans le navigateur ne peut plus lire l'historique ni utiliser
  les connexions.
- Anciens formats Office (`.doc`, `.xls`, `.ppt`) : message clair invitant à les enregistrer en `.docx`,
  `.xlsx` ou `.pptx`, au lieu d'une erreur technique.
- Import limité à 50 Mo par fichier (`MAX_UPLOAD_MB` dans le `.env`), lu par morceaux, avec un message clair.
- Export PDF en police Unicode embarquée (DejaVu Sans) : œ, guillemets, tirets, flèches et alphabets grec ou
  cyrillique ne sont plus remplacés par « ? ».
- Les autorités de certification internes sans extension « key usage », refusées par défaut depuis
  Python 3.13, sont acceptées.

## [2.0.0] — version de référence

État de l'application avant le versionnement : quatre modes d'analyse (synthèse globale, transcription,
notes en vrac, flux et parcours) en trois niveaux de détail, analyse par lots des gros corpus, sources
vérifiables, exports Markdown, Word et PDF, historique, contrat du portail (port 8020, `/health`).
