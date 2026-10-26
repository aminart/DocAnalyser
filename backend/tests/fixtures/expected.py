"""Ce que toute synthèse fidèle des documents de test doit contenir.

Chaque fait est une liste de formulations acceptées (une seule suffit) : le modèle peut écrire
« 5 e-mails » ou « cinq e-mails ». Les verbatims doivent être retrouvés dans le texte d'origine.
"""

FACTS = {
    "compte_rendu_6_sujets.txt": {
        "Onboarding : nombre d'e-mails": [r"cinq (e-)?mails", r"\b5 (e-)?mails"],
        "Onboarding : parcours guidé demandé": [r"8 (participants )?sur 12", r"huit (participants )?sur douze"],
        "Suivi : relances au support": [r"\b5 participants", r"cinq participants"],
        "Outils : temps de double saisie": [r"20 minutes", r"vingt minutes"],
        "Notifications : alertes désactivées": [r"\b6 participants", r"six participants"],
        "Mobile : expiration des sessions": [r"5 minutes", r"cinq minutes"],
        "Accessibilité (fin du document) : lecteurs d'écran": [r"lecteurs? d.écran"],
        "Accessibilité : échéance du correctif": [r"fin de l.année", r"fin d.année", r"avant la fin"],
    },
    "entretiens_parcours.txt": {
        "Entrées : simulateur": [r"\b7 participants", r"sept participants", r"simulateur"],
        "Entrées : lien par SMS": [r"\bsms\b"],
        "Justificatifs : redépôts": [r"\b4 participants", r"quatre participants"],
        "Vérification : délai": [r"24 (à|-) ?72", r"72 ?h"],
        "Objectif : premier virement": [r"9 (participants )?sur 12", r"neuf (participants )?sur douze"],
    },
}

QUOTES = [
    "Je ne savais plus lequel ouvrir en premier.",
    "Ce qui m'inquiète, c'est de ne pas savoir pourquoi j'attends.",
    "Je passe plus de temps à remplir l'outil qu'à parler au client.",
    "Je dois demander à mon fils de signer à ma place.",
    "J'ai réinitialisé deux fois mon mot de passe avant que ça marche.",
    "J'ai tout perdu, j'ai laissé tomber pour la journée.",
]

# Étapes du parcours qu'une analyse « Flux » doit reconstituer (une formulation suffit par étape).
JOURNEY_STEPS = {
    "Entrée": [r"simulat", r"entrée", r"arrivée", r"sms"],
    "Identification": [r"identif", r"connexion", r"espace client", r"mot de passe"],
    "Justificatifs": [r"justificatif", r"pièce d.identité", r"dépôt"],
    "Vérification": [r"vérification", r"validation", r"attente"],
    "Signature / activation": [r"signature", r"activation"],
    "Objectif": [r"virement"],
}
