"""Consignes envoyées au modèle : modes, niveaux, règles de fidélité et schémas JSON attendus."""
from __future__ import annotations

MODE_LABELS: dict[str, str] = {
    "global": "Synthèse globale",
    "transcript": "Synthèse de transcription",
    "notes": "Synthèse de notes en vrac",
    "flow": "Flux et parcours utilisateurs",
}
LEVEL_LABELS: dict[str, str] = {"synth": "Synthétique", "detail": "Détaillé", "deep": "Très détaillé"}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MODE_GUIDANCE: dict[str, str] = {
    "global": (
        "Croise l'ensemble des documents pour dégager les grands thèmes, les convergences et les points "
        "de divergence. Les pistes d'action sont uniquement les recommandations, demandes, attentes ou décisions "
        "exprimées dans les documents : n'en propose aucune de ton cru. Liste vide si les documents n'en contiennent pas."
    ),
    "transcript": (
        "Il s'agit de transcriptions (entretien, réunion, atelier). Les thèmes sont les grands sujets abordés ; "
        "fais ressortir idées clés, décisions et verbatims marquants. Les pistes d'action sont les décisions prises "
        "et prochaines étapes annoncées (indique le responsable et l'échéance seulement s'ils sont cités)."
    ),
    "notes": (
        "Il s'agit de notes brutes (notes de terrain, post-its, comptes rendus épars). Dédoublonne, remets de l'ordre "
        "et regroupe les idées par thème. Les pistes d'action sont les prochaines étapes ou idées d'action "
        "notées dans les documents, sans en ajouter."
    ),
    "flow": (
        "Reconstitue le parcours utilisateur décrit dans les documents : ses étapes, ce que fait l'utilisateur, "
        "ses points de contact, son ressenti, les frictions et les points de sortie. Les opportunités sont "
        "uniquement les attentes, demandes ou idées d'amélioration exprimées dans les documents. "
        + "Une friction n'existe que si un document la signale : difficulté, blocage, erreur, abandon ou plainte "
        "rapportés, ou problème décrit par le document lui-même (rubrique de dépannage, problèmes connus). Ne déduis "
        "jamais une friction d'une étape qui te paraît compliquée. Si les documents décrivent un parcours sans "
        "retours d'utilisateurs (guide utilisateur, mode opératoire, procédure, spécification), restitue seulement "
        "le parcours : frictions, opportunités, ressenti et priorités restent vides, sauf ce que le document dit "
        "lui-même."
    ),
}

# Le niveau règle la profondeur de rédaction de chaque élément, jamais le nombre
# d'éléments : tous les thèmes, étapes et frictions présents dans le corpus sont traités.
COMPLETENESS_RULE = (
    "Exhaustivité : traite tous les thèmes (ou étapes) importants présents dans le corpus, y compris ceux qui "
    "apparaissent en fin de document. Leur nombre dépend uniquement du corpus, pas du niveau demandé. "
    "Ne supprime jamais un élément important pour raccourcir ; le niveau ne change que la profondeur de rédaction."
)

# Découpage en points : une information distincte par point, chacune avec sa source.
# Sans cette règle, le modèle fusionne plusieurs faits dans un seul long point.
GRANULARITY_RULE = (
    "Découpage : un point clé correspond à une information distincte (un fait, un chiffre, un constat, une "
    "décision, une attente ou un désaccord), avec sa propre source. Le nombre de points d'un thème dépend "
    "uniquement de la richesse du corpus sur ce thème."
)

LEVEL_GUIDANCE: dict[str, str] = {
    "synth": (
        GRANULARITY_RULE + " Niveau synthétique : regroupe seulement les informations qui disent la même chose ; "
        "chaque point tient en une phrase courte. Résumé du thème en 1 à 2 phrases. "
        "Verbatim et nuance seulement s'ils sont marquants."
    ),
    "detail": (
        GRANULARITY_RULE + " Niveau détaillé : ne fusionne jamais deux informations distinctes dans un même point ; "
        "chaque point est développé en 2 à 3 phrases avec un exemple tiré du corpus. "
        "Un verbatim marquant par thème ; nuance ou divergence quand le corpus en montre une."
    ),
    "deep": (
        GRANULARITY_RULE + " Niveau très détaillé : un point par information distincte, et décompose aussi les "
        "causes, conséquences et cas particuliers en points séparés ; chaque point est argumenté (3 à 5 phrases) "
        "avec exemples, chiffres et contexte. Pour chaque thème : verbatim, nuance ou point de divergence, "
        "sources précises pour chaque point."
    ),
}

# Gros documents (analyse par lots) : longueur bornée de la synthèse. Sans borne, chaque élément extrait
# devient un point clé et un corpus de plusieurs centaines de pages donne une synthèse de plus de cent pages.
# Nombre total de points clés visé selon le niveau (≈ 5, 8 à 10 et 12 à 15 pages Word, thèmes compris) ;
# le détail complet reste en annexe (éléments extraits, rangés par thème, avec leurs sources).
POINT_BUDGET: dict[str, int] = {"synth": 60, "detail": 50, "deep": 40}
MIN_THEME_POINTS, MAX_THEME_POINTS = 3, 8


def point_quotas(sizes: list[int], level: str) -> list[int]:
    """Nombre maximal de points clés par thème, selon le poids du thème (nombre d'éléments extraits).

    0 = pas de limite : le thème tient déjà dans sa part du budget, il est rédigé comme avant.
    Si le corpus entier tient dans le budget, aucun thème n'est limité.
    """
    total = sum(sizes)
    budget = POINT_BUDGET[level]
    if total <= budget:
        return [0] * len(sizes)
    quotas = []
    for n in sizes:
        q = max(MIN_THEME_POINTS, min(MAX_THEME_POINTS, round(budget * n / total)))
        quotas.append(0 if n <= q else q)
    return quotas


SHORT_BODY = {"synth": "rien ou une phrase", "detail": "1 à 2 phrases", "deep": "2 à 3 phrases"}


def short_theme_rule(quota: int, level: str) -> str:
    """Consigne de rédaction d'un thème limité à quota points clés (gros documents), à la place de LEVEL_GUIDANCE."""
    return (
        f"Synthèse courte : au plus {quota} points clés pour ce thème. Retiens les informations les plus importantes "
        "et les plus fréquentes dans les documents, et regroupe celles qui disent la même chose (un point peut citer "
        "plusieurs sources). Le détail complet figure déjà en annexe : n'essaie pas de tout reprendre. "
        "Résumé du thème : 2 phrases courtes au plus. Chaque point : une phrase courte en « lead », et en « body » "
        f"{SHORT_BODY[level]} au plus (chiffres et noms utiles repris tels quels). Un verbatim au plus."
    )


FLOW_GRAPH_RULES: dict[str, str] = {
    level: (
        "« flow » est un graphe libre qui reflète fidèlement ce que décrivent les documents : "
        "il peut être linéaire, comporter des embranchements, des chemins alternatifs, des retours en arrière "
        "ou plusieurs points d'entrée. N'invente pas de branches absentes du corpus. "
        "Types de nœuds : « entry » point d'entrée, « step » action ou écran, « decision » choix ou condition "
        "(au moins 2 liens sortants, chacun avec un label), « exit » abandon ou sortie du parcours (aucun lien sortant), "
        "« goal » objectif atteint. Mets « friction » à true sur les nœuds où des utilisateurs bloquent ou décrochent. "
        "Types de liens : « main » chemin principal, « alt » chemin alternatif, « exit » vers un abandon, "
        "« loop » retour en arrière ou répétition. "
        f"Granularité : {grain} Le graphe compte autant de nœuds que le parcours en décrit réellement."
    )
    for level, grain in {
        "synth": "regroupe les micro-étapes en étapes clés, mais garde toutes les décisions, abandons et retours.",
        "detail": "une étape par action ou écran significatif.",
        "deep": "détaille chaque écran, choix, condition et cas particulier décrits dans le corpus.",
    }.items()
}

FLOW_LEVEL_GUIDANCE: dict[str, str] = {
    "synth": (
        "Niveau synthétique : textes courts (une phrase). Les étapes du parcours sont les grandes phases ; "
        "pour chacune, les frictions et opportunités principales."
    ),
    "detail": (
        "Niveau détaillé : chaque étape décrit précisément ce que fait l'utilisateur ; "
        "frictions et opportunités formulées avec leur contexte."
    ),
    "deep": (
        "Niveau très détaillé : phases fines, toutes les frictions et opportunités citées dans le corpus, "
        "frictions prioritaires argumentées avec verbatim et fréquence."
    ),
}

BASE_RULES = (
    "Tu es un analyste expert en recherche qualitative. Ta synthèse remplace la lecture des documents : "
    "elle doit être d'une fidélité absolue au corpus. Règles impératives :\n"
    "- N'invente rien : chaque affirmation, chiffre, nom, date ou fréquence doit figurer dans le corpus. "
    "Si une information n'y est pas, laisse le champ vide plutôt que de la deviner.\n"
    "- Ne déforme pas : conserve le sens, les nuances et les désaccords tels qu'ils sont exprimés, et reprends tels "
    "quels les chiffres, durées, montants, dates, lieux et noms utiles.\n"
    "- Les citations (verbatims) sont recopiées mot pour mot depuis le corpus, sans les reformuler ni les traduire.\n"
    "- Exploite chaque document fourni ; n'en ignore aucun.\n"
    "- Les noms de documents sont recopiés exactement tels qu'indiqués dans les balises [SOURCE: ...]. "
    "Comme emplacement, reprends le repère de la ligne citée tel qu'il apparaît dans le corpus "
    "(L12, §4, Page 3, Slide 2, 00:01:10).\n"
    "- Réponds uniquement avec un objet JSON valide, sans texte autour."
)


def _language_rule(language: str) -> str:
    target = "anglais" if language == "en" else "français"
    return f"Rédige tout le contenu textuel en {target} (les verbatims restent dans leur langue d'origine)."


THEMES_OUTLINE_SCHEMA = """{
  "title": "titre court et explicite de l'étude (max 8 mots)",
  "themes": [{"title": "intitulé du thème (3 à 6 mots)"}]
}"""

FLOW_OUTLINE_SCHEMA = """{
  "title": "titre court et explicite du parcours (max 8 mots)",
  "phases": [{"name": "nom de l'étape (1 à 3 mots)"}]
}"""

THEMES_SCHEMA = """{
  "title": "titre court et explicite de l'étude",
  "brief": "2 à 3 phrases qui résument l'essentiel ; entoure de *astérisques* un seul mot ou groupe de 2 à 4 mots, le plus important",
  "themes": [
    {
      "title": "intitulé du thème",
      "summary": "2 à 3 phrases de synthèse du thème",
      "documents": ["noms exacts des documents où le thème est présent"],
      "points": [
        {
          "lead": "le point clé en une phrase courte",
          "body": "développement argumenté avec exemples",
          "sources": [{"document": "nom exact du document", "location": "repère exact du passage (L12, §4, Page 3, Slide 2, 00:01:10)"}]
        }
      ],
      "quote": "verbatim marquant recopié mot pour mot (chaîne vide si aucun)",
      "quote_by": "qui parle et dans quel contexte (ex. Participante 7 — entretien individuel)",
      "nuance": "nuance ou point de divergence observé (chaîne vide si aucun)"
    }
  ],
  "actions": [
    {"title": "piste d'action concrète", "body": "1 à 2 phrases de justification", "theme": 1}
  ]
}"""

FLOW_SCHEMA = """{
  "title": "titre court et explicite du parcours",
  "brief": "2 à 3 phrases qui résument le parcours ; entoure de *astérisques* un seul groupe de 2 à 6 mots, le plus important",
  "phases": [
    {
      "name": "nom de l'étape",
      "mood": "ressenti exprimé dans les documents, en un mot (ex. Curieux, Hésitant, Perdu, Confiant, Frustré) ; chaîne vide si aucun",
      "sentiment": "entier de -2 à 2, ou null si aucun ressenti n'est exprimé",
      "does": "ce que fait l'utilisateur à cette étape (1 phrase)",
      "touchpoints": ["points de contact (2 à 4 mots chacun)"],
      "frictions": ["frictions ou points de rupture signalés dans les documents (phrase courte) ; [] si aucun"],
      "opportunities": ["attentes ou idées d'amélioration exprimées dans les documents (phrase courte) ; [] si aucune"]
    }
  ],
  "flow": {
    "nodes": [
      {
        "id": "identifiant court unique (ex. n1)",
        "label": "action, écran ou décision (2 à 8 mots)",
        "type": "entry | step | decision | exit | goal",
        "friction": false
      }
    ],
    "edges": [
      {
        "from": "id du nœud de départ",
        "to": "id du nœud d'arrivée",
        "label": "condition ou action déclenchante (chaîne vide si évident)",
        "kind": "main | alt | exit | loop"
      }
    ]
  },
  "priorities": [
    {
      "severity": "Bloquant | Majeur | Mineur",
      "title": "intitulé de la friction",
      "body": "explication en 1 à 2 phrases",
      "quote": "verbatim recopié mot pour mot",
      "phase": "nom de l'étape concernée",
      "frequency": "fréquence citée dans les documents (ex. 9 participants sur 12), sinon chaîne vide"
    }
  ]
}"""


def _outline_prompt(mode: str, level: str, language: str) -> str:
    schema = FLOW_OUTLINE_SCHEMA if mode == "flow" else THEMES_OUTLINE_SCHEMA
    guidance = FLOW_LEVEL_GUIDANCE[level] if mode == "flow" else LEVEL_GUIDANCE[level]
    target = "les étapes du parcours, dans l'ordre chronologique" if mode == "flow" else "les grands thèmes, du plus au moins présent"
    return "\n\n".join([
        BASE_RULES,
        MODE_GUIDANCE[mode],
        f"Première passe : identifie uniquement {target}.",
        COMPLETENESS_RULE,
        guidance,
        _language_rule(language),
        "Schéma JSON attendu :\n" + schema,
    ])


def _full_prompt(mode: str, level: str, language: str, cite: bool) -> str:
    if mode == "flow":
        parts = [
            BASE_RULES,
            MODE_GUIDANCE[mode],
            COMPLETENESS_RULE,
            FLOW_LEVEL_GUIDANCE[level],
            "« sentiment » est un entier de -2 (très négatif) à 2 (très positif), ou null si les documents n'expriment "
            "aucun ressenti à cette étape (« mood » vide). « priorities » est vide ([]) si aucune friction n'est signalée.",
            FLOW_GRAPH_RULES[level],
            _language_rule(language),
            "Schéma JSON attendu :\n" + FLOW_SCHEMA,
        ]
    else:
        parts = [
            BASE_RULES,
            MODE_GUIDANCE[mode],
            COMPLETENESS_RULE,
            LEVEL_GUIDANCE[level],
            "« theme » dans actions est le numéro (1, 2, ...) du thème concerné. Autant de pistes d'action que le corpus en justifie.",
            "Indique les sources de chaque point." if cite else "Laisse « sources » vide ([]) pour chaque point.",
            _language_rule(language),
            "Schéma JSON attendu :\n" + THEMES_SCHEMA,
        ]
    return "\n\n".join(parts)
