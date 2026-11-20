# Historique des versions de DocAnalyser

Format : chaque version liste ses changements par type (Ajouté, Modifié, Corrigé). Les numéros suivent
le [versionnage sémantique](https://semver.org/lang/fr/) : voir README, « Versions ».

## [Non publié]

## [2.8.1] — 2026-11-20

### Corrigé

- Modèle local (Ollama) qui se met à répéter le même passage en boucle : la réponse est interrompue, redemandée
  une fois, puis le lot est coupé en deux. Avant, l'analyse restait bloquée sans fin sur ce lot, car un modèle
  qui écrit encore n'était jamais arrêté.
- Longueur de réponse plafonnée pour un modèle local (`LOCAL_MAX_OUTPUT_TOKENS`, 16 000 tokens par défaut) si
  la connexion n'en fixe pas : une réponse plus longue est demandée en plusieurs parties.
- Mode Parcours, « fusion des doublons » : le modèle y recopie chaque paquet d'éléments presque en entier, ce qui
  est très long sur un modèle local. La progression s'affiche paquet par paquet, la durée restante est
  recalculée, les paquets fusionnés sont gardés pour « Reprendre l'analyse », et un paquet qui échoue (réponse en
  boucle, délai dépassé) est gardé tel quel au lieu d'arrêter l'analyse.
- Temps restant : une fois l'estimation dépassée, l'écran indique « plus long que prévu » au lieu de
  « presque terminé ».

### Ajouté

- Pendant l'analyse, sous l'étape en cours : ce que fait le modèle (« lit la demande depuis 4 min », « écrit :
  12 300 caractères reçus en 2 min »), pour distinguer un lot long d'un lot bloqué.

## [2.8.0] — 2026-11-19

### Ajouté

- « Approfondir ce thème », sur chaque thème d'une synthèse terminée, y compris depuis l'Historique : le thème
  est réécrit en version très détaillée à partir des passages des documents qui le concernent (corpus entier
  s'il tient dans la fenêtre du modèle, sinon passages cités puis passages retrouvés par la recherche des
  Questions). Le reste de la synthèse ne change pas, l'export suit.
- Garde-fous : un point de l'ancienne version dont un chiffre ou un nom propre a disparu est repris tel quel ;
  « Revenir à la version précédente » ; un texte exporté modifié à la main n'est jamais écrasé.

## [2.7.0] — 2026-11-18

### Ajouté

- Suivi d'une longue analyse sans garder la page sous les yeux : l'onglet du navigateur affiche la progression
  (« 42 % · Analyse en cours »), puis « Synthèse prête » ou « Analyse échouée ». « Me prévenir à la fin »
  propose une notification du système, affichée seulement si DocAnalyser n'est pas au premier plan.
- Sous « Pages à analyser » : nombre de pages retenues, ou ce qui n'est pas compris (« La page 400 n'existe
  pas »). Le lancement attend une sélection lisible au lieu d'échouer après coup.
- Après un échec dû à la connexion (clé refusée, modèle absent, adresse manquante ou serveur injoignable),
  un bouton « Ouvrir les Réglages ».

### Modifié

- Le menu du haut reste affiché pendant l'analyse : on peut aller dans l'Historique ou préparer une autre
  analyse, celle en cours continue.
- Durée estimée avant le lancement adaptée aux modèles installés sur ce poste (Ollama…), bien plus lents.
- « Annuler l'analyse » demande confirmation.
- Texte exporté : les modifications non enregistrées sont gardées en changeant d'onglet, et fermer la page
  demande confirmation.
- Messages d'erreur de connexion : ils renvoient aux Réglages plutôt qu'à backend/.env.

## [2.6.0] — 2026-11-18

### Ajouté

- Lecture des images par un modèle qui voit les images (facultatif) : pages scannées des PDF, images insérées
  dans les PDF, Word et PowerPoint, et fichiers image importés (PNG, JPG, WEBP). Au lancement, « Lire les images
  avec » propose les modèles configurés ; chaque image est transcrite (texte, tableau) ou décrite (schéma,
  graphique), puis analysée avec le texte à son repère d'origine (« Page 12 », « Slide 4 »). Les images
  décoratives (logos, icônes) sont ignorées, une image déjà lue n'est pas redemandée.
- Sans modèle de vision, rien ne change : l'analyse porte sur le texte seul. Un modèle qui refuse les images
  n'arrête pas l'analyse (texte seul, avec un message).

### Modifié

- Les fichiers image sont acceptés à l'import ; un document sans texte demande un modèle de vision au lancement.
- Nouvelle dépendance : pypdfium2, pour rendre en image les pages scannées des PDF.

## [2.5.0] — 2026-11-18

### Ajouté

- Bouton « Reprendre l'analyse » sur une analyse échouée ou annulée : elle repart avec les mêmes documents et
  réglages, sans refaire les lots déjà extraits, et remplace l'ancienne dans l'historique.
- Temps restant estimé pendant une analyse par lots, mesuré sur les premiers lots puis sur la rédaction des thèmes.
- Onglet « Texte exporté » : le texte de la synthèse se corrige avant export ; les exports Markdown, Word et PDF
  reprennent le texte modifié, qui est gardé dans l'historique. « Revenir au texte d'origine » annule tout.

## [2.4.1] — 2026-11-18

### Modifié

- Analyse par lots : les réponses du modèle sont reçues au fil de l'eau. Le délai d'attente porte sur chaque
  morceau : un modèle qui écrit encore une longue réponse n'est plus coupé, un modèle bloqué est repéré plus vite
  (10 minutes sans rien recevoir pour un modèle local, `LOCAL_STREAM_TIMEOUT_SECONDS`).
- Modèles qui « réfléchissent » avant de répondre (Qwen…) : réflexion désactivée (champ `think` d'Ollama pour un
  modèle local, consigne `/no_think` pour Qwen), car elle ajoute des milliers de mots par lot. Une réflexion
  écrite malgré tout dans la réponse (`<think>…</think>`) en est retirée avant lecture. `DISABLE_THINKING=false`
  pour la garder.

## [2.4.0] — 2026-11-18

### Ajouté

- Choix des pages à analyser : pour un PDF (ou des slides pour un PowerPoint), un champ « Pages à analyser »
  (par exemple « 12-45, 80 ») sous le document importé. Seules ces pages sont envoyées au modèle ; les sources
  citées gardent leur numéro de page d'origine. Vide, le document est analysé en entier.

## [2.3.1] — 2026-11-18

### Corrigé

- Gros documents analysés avec un modèle local (Ollama) : l'analyse pouvait s'arrêter au bout d'une heure ou plus
  pendant le découpage en lots. Les lots étaient prévus pour la fenêtre théorique du modèle (128 000 tokens), alors
  qu'Ollama n'en ouvre souvent qu'une petite partie et coupe le reste sans prévenir ; envoyés par 4 à une carte
  graphique qui les traite un par un, ils attendaient leur tour en consommant leur délai de 10 minutes.
- Un lot en échec arrêtait l'analyse en perdant tous les lots déjà extraits, et les autres lots continuaient
  d'occuper le modèle après l'échec.

### Modifié

- Modèle local (adresse localhost ou port 11434) : une requête à la fois, lots d'au plus 32 000 tokens, jusqu'à
  30 minutes par réponse ; la fenêtre réellement ouverte par Ollama est lue avant de commencer (lots adaptés, ou
  arrêt immédiat avec le réglage à changer si elle est trop petite).
- Délais réglables dans le .env : `LLM_TIMEOUT_SECONDS`, `LOCAL_LLM_TIMEOUT_SECONDS`, ainsi que
  `LOCAL_CONCURRENT_LLM_REQUESTS` et `LOCAL_MAX_REQUEST_TOKENS`.
- Un lot qui dépasse le délai est coupé en deux et redemandé avant d'abandonner.

### Ajouté

- Reprise d'une analyse interrompue : les lots extraits sont gardés 7 jours, une analyse relancée avec les mêmes
  documents et le même modèle reprend là où elle s'était arrêtée.
- Message d'échec plus précis : lot où l'analyse s'est arrêtée, lots gardés, réglage à changer.

## [2.3.0] — 2026-11-17

### Ajouté

- Pages web (.html, .htm) : texte visible, titres, listes et tableaux, sans scripts, styles ni menus.
- Projets Mapline (.mapline, et .missionmap des anciennes versions) : cartes de parcours, flux, fiches persona et
  plans du site, lus document par document dans l'ordre de l'outil.
- Excel et CSV : un bloc « Statistiques » calculé par DocAnalyser (somme, moyenne, min, max des colonnes chiffrées,
  répartition des colonnes à quelques valeurs), pour des chiffres exacts dans les synthèses et les réponses.
- Word : zones de texte, notes de bas de page et de fin, en-têtes et pieds de page, texte des révisions.

### Modifié

- PDF : en-têtes et pieds de page répétés retirés (et signalés à l'import), tableaux rendus ligne par ligne.
- Excel et CSV : la vraie ligne d'en-tête est cherchée sous les titres, les colonnes vides sont retirées, dates et
  nombres sont écrits comme dans Excel (« 2025-01-03 », « 12 » au lieu de « 2025-01-03 00:00:00 », « 12.0 »).
- Word : une cellule fusionnée n'est lue qu'une fois ; les listes numérotées sont repérées comme listes.

### Corrigé

- Un fichier d'un format non prévu (image, archive…) glissé dans la zone d'import était lu comme du texte et
  analysé : il est maintenant refusé, avec la liste des formats acceptés.

## [2.2.0] — 2026-11-17

### Ajouté

- Modèles d'IA de Studio Dock : les connexions réglées une fois dans Studio Dock (Réglages › Modèles d'IA),
  communes à toutes les apps de la suite, y compris les modèles locaux d'Ollama, sont proposées dans
  « Nouvelle analyse ». Elles apparaissent en lecture seule dans les Réglages, marquées « Studio Dock ».
  Le modèle choisi pour DocAnalyser dans Studio Dock est sélectionné d'office. Studio Dock peut aussi laisser
  à DocAnalyser sa configuration propre.

## [2.1.1] — 2026-11-09

### Modifié

- Exécutable plus léger (environ un tiers de moins) : les PDF sont lus avec pdfminer.six (Python pur) au lieu de
  PyMuPDF, dont la bibliothèque native pesait plus de 20 Mo ; vitesse et texte extrait équivalents, pages sans texte
  toujours signalées. Retirés aussi de l'exe : uvloop, watchfiles, yaml.

## [2.1.0] — 2026-11-08

### Ajouté

- Nouvelle icône DocAnalyser, commune avec Studio Dock : icône de l'exe, logo de l'en-tête et icône de l'onglet (dossier `icone/`).
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

- En-tête commun à la suite (design system Night Navy 1.1.0) : onglets soulignés, Réglages devient une icône à
  droite à côté du thème. Titres de page au format commun (32 px, alignés à gauche).
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
