"""Erreurs métier de l'analyse, remontées telles quelles à l'interface."""
from __future__ import annotations

class AnalysisError(Exception):
    """Erreur métier remontée telle quelle à l'interface."""


class SettingsProblem(AnalysisError):
    """Erreur qui se corrige dans les Réglages : clé refusée, modèle absent, adresse manquante ou injoignable."""


class InvalidModelOutput(AnalysisError):
    """La réponse du modèle n'est pas un JSON exploitable."""


class ProviderUnavailable(AnalysisError):
    """Le fournisseur n'a pas traité la requête (quota, surcharge, délai dépassé) malgré les essais."""

    def __init__(self, message: str, timed_out: bool = False, settings: bool = False) -> None:
        super().__init__(message)
        self.timed_out = timed_out  # délai dépassé : une requête plus petite a ses chances
        self.settings = settings  # serveur injoignable : l'adresse se vérifie dans les Réglages
