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

### Modifié

- Analyse documentaire devient **DocAnalyser** (identifiant du portail : `docanalyser`).
- Interface sur le design system commun Night Navy (couleurs, police Roboto, arrondis), comme SpecGen et
  Audit ergonomique ; plus de polices téléchargées.

### Corrigé

- Les autorités de certification internes sans extension « key usage », refusées par défaut depuis
  Python 3.13, sont acceptées.

## [2.0.0] — version de référence

État de l'application avant le versionnement : quatre modes d'analyse (synthèse globale, transcription,
notes en vrac, flux et parcours) en trois niveaux de détail, analyse par lots des gros corpus, sources
vérifiables, exports Markdown, Word et PDF, historique, contrat du portail (port 8020, `/health`).
