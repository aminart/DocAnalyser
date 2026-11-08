"""Erreurs métier de l'analyse, remontées telles quelles à l'interface."""
from __future__ import annotations

class AnalysisError(Exception):
    """Erreur métier remontée telle quelle à l'interface."""


class InvalidModelOutput(AnalysisError):
    """La réponse du modèle n'est pas un JSON exploitable."""


class ProviderUnavailable(AnalysisError):
    """Le fournisseur n'a pas traité la requête (quota, surcharge, délai dépassé) malgré les essais."""
