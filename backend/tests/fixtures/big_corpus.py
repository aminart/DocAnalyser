"""Corpus volumineux de test : 8 sujets répartis dans 3 documents, noyés dans du remplissage.

Chaque sujet porte deux faits uniques (chiffres, lieux, noms) et un verbatim, faciles à retrouver dans une
synthèse. Le dernier sujet (accessibilité) est placé tout à la fin du corpus.
"""
from __future__ import annotations

import random
from pathlib import Path

TOPICS = [
    ("Onboarding", ["Le premier jour, chaque client reçoit 5 e-mails distincts.", "Un parcours guidé est réclamé par 8 participants sur 12."],
     "Je ne savais plus lequel ouvrir en premier.", ["5 e-mails", "8 participants sur 12"]),
    ("Suivi des dossiers", ["Le délai de validation varie de 24 à 72 heures.", "L'agence de Quimper reçoit 40 appels de relance par semaine."],
     "Ce qui m'inquiète, c'est de ne pas savoir pourquoi j'attends.", ["72 heures", "Quimper"]),
    ("Outils des conseillers", ["La double saisie coûte 20 minutes par rendez-vous.", "Le logiciel Orion plante en moyenne deux fois par jour."],
     "Je passe plus de temps à remplir l'outil qu'à parler au client.", ["20 minutes", "Orion"]),
    ("Notifications", ["6 participants ont désactivé toutes les alertes.", "Une alerte d'échéance manquée a coûté 35 euros de pénalité à une cliente."],
     "J'ai coupé les notifications et j'ai raté celle qui comptait.", ["désactivé", "35 euros"]),
    ("Application mobile", ["Les sessions expirent après 5 minutes d'inactivité.", "La recherche ne trouve pas les relevés de l'année 2023."],
     "J'ai tout perdu, j'ai laissé tomber pour la journée.", ["5 minutes", "2023"]),
    ("Tarification", ["Les frais de tenue de compte passent à 3,90 euros par mois.", "Les clients de moins de 26 ans en sont exonérés."],
     "Personne ne m'a prévenu de la hausse des frais.", ["3,90", "26 ans"]),
    ("Agences", ["L'agence de Vannes ferme à 17 h 30, trop tôt selon 4 clients sur 10.", "Le samedi, seule l'agence de Lorient est ouverte."],
     "Je ne peux jamais venir avant 18 h.", ["Vannes", "Lorient"]),
    ("Accessibilité", ["Le module de signature est incompatible avec les lecteurs d'écran.", "Le comité exige un correctif avant le 31 décembre pour conformité RGAA."],
     "Je dois demander à mon fils de signer à ma place.", ["lecteurs d'écran", "RGAA"]),
]

FILLER = [
    "La discussion se poursuit sur ce point sans élément nouveau.",
    "Plusieurs participants hochent la tête sans commenter davantage.",
    "L'animatrice reformule la question pour s'assurer qu'elle a été comprise.",
    "Un participant demande une précision sur le vocabulaire employé.",
    "Le groupe revient brièvement sur les échanges précédents.",
    "La prise de notes est reprise après une courte pause.",
]

DOCS = {"atelier_matin.txt": TOPICS[:3], "atelier_apres_midi.txt": TOPICS[3:6], "comite_final.txt": TOPICS[6:]}


def build(out_dir: Path) -> dict[str, list[str]]:
    """Écrit les 3 documents dans out_dir et renvoie les faits attendus par sujet."""
    rng = random.Random(7)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, topics in DOCS.items():
        lines = [f"Compte rendu — {name.replace('_', ' ').replace('.txt', '')}", ""]
        for title, facts, quote, _ in topics:
            lines.append(f"Sujet : {title}")
            for fact in facts:
                lines += [rng.choice(FILLER) for _ in range(28)]
                lines.append(fact)
            lines += [rng.choice(FILLER) for _ in range(20)]
            lines.append(f"Un participant déclare : « {quote} »")
            lines += [rng.choice(FILLER) for _ in range(25)]
            lines.append("")
        (out_dir / name).write_text("\n".join(lines), encoding="utf-8")
    return {title: keys for title, _, _, keys in TOPICS}
