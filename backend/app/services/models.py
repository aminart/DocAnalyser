"""Catalogue des modèles : connexions de l'écran Réglages et fournisseurs du .env, profils, chaîne de repli."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from app.core import connexions, studiodock_ia
from app.core.config import settings
from app.services import llm_client
from app.services.errors import AnalysisError


# ---------------------------------------------------------------------------
# Catalogue des modèles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderConf:
    key: str  # préfixe des variables .env : CUSTOM_LLM, CUSTOM_LLM_2, GEMINI, ANTHROPIC
    kind: Literal["openai", "gemini", "anthropic"]
    name: str
    api_key: str
    api_base: str
    ca_bundle: str
    context_tokens: int
    models: tuple[str, ...]
    max_output_tokens: int = 0  # 0 : valeur par défaut du serveur
    local: bool = False  # modèle sur ce poste (Ollama, LM Studio…) : lent, une requête à la fois


def is_local_base(api_base: str) -> bool:
    """Adresse d'un serveur de modèles installé sur ce poste (localhost, ou port d'Ollama)."""
    try:
        url = urlsplit(api_base if "//" in api_base else f"http://{api_base}")
        host, port = (url.hostname or "").lower(), url.port
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or port == 11434


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    provider: ProviderConf
    description: str
    quality: int
    speed: int
    economy: int
    tier: Literal["deep", "balanced", "fast"]

    @property
    def context_tokens(self) -> int:
        return self.provider.context_tokens


def _names(raw: str) -> tuple[str, ...]:
    return tuple(m.strip() for m in (raw or "").split(",") if m.strip())


def providers() -> list[ProviderConf]:
    """Fournisseurs : ceux du fichier .env (voir .env.example), puis les connexions de l'écran Réglages.

    - CUSTOM_LLM / CUSTOM_LLM_2 : endpoints compatibles OpenAI.
    - GEMINI / ANTHROPIC : clés de test, proposées seulement si la clé est renseignée.
    - Connexions de Studio Dock (Réglages › Modèles d'IA, lues avec app/core/studiodock_ia.py) : communes à
      toutes les apps de la suite, en lecture seule ici ; ignorées si Studio Dock garde à DocAnalyser sa
      configuration propre.
    - Connexions de l'écran Réglages (app/core/connexions.py) : autant que voulu, chacune avec ses modèles.
    """
    out = [
        ProviderConf(
            key=key,
            kind="openai",
            name=(getattr(settings, f"{key}_PROVIDER_NAME") or key).strip(),
            api_key=(getattr(settings, f"{key}_API_KEY") or "").strip(),
            api_base=(getattr(settings, f"{key}_API_BASE") or "").strip().rstrip("/"),
            ca_bundle=(getattr(settings, f"{key}_CA_BUNDLE") or "").strip(),
            context_tokens=getattr(settings, f"{key}_CONTEXT_TOKENS"),
            models=_names(getattr(settings, f"{key}_AVAILABLE_MODELS")),
            max_output_tokens=getattr(settings, f"{key}_MAX_OUTPUT_TOKENS"),
            local=is_local_base(getattr(settings, f"{key}_API_BASE") or ""),
        )
        for key in ("CUSTOM_LLM", "CUSTOM_LLM_2")
    ]
    tests = [
        ("GEMINI", "gemini", "Google Gemini (test)", settings.GEMINI_API_KEY,
         settings.GEMINI_CA_BUNDLE, settings.GEMINI_CONTEXT_TOKENS, settings.GEMINI_TEST_MODELS),
        ("ANTHROPIC", "anthropic", "Anthropic Claude (test)", settings.ANTHROPIC_API_KEY,
         settings.ANTHROPIC_CA_BUNDLE, settings.ANTHROPIC_CONTEXT_TOKENS, settings.ANTHROPIC_TEST_MODELS),
    ]
    for key, kind, name, api_key, ca, ctx, models in tests:
        if settings._is_key_set(api_key or ""):
            base = llm_client.GEMINI_BASE if kind == "gemini" else llm_client.ANTHROPIC_BASE
            out.append(ProviderConf(key, kind, name, api_key.strip(), base, (ca or "").strip(), ctx, _names(models),
                                    max_output_tokens=32_000))
    for c in connexions_studiodock():
        out.append(ProviderConf(
            key=f"{STUDIODOCK}{c.id}", kind="openai", name=c.name, api_key=c.api_key, api_base=c.api_base,
            ca_bundle=c.ca_bundle, context_tokens=c.context_tokens, models=c.models,
            max_output_tokens=c.max_output_tokens, local=c.local or is_local_base(c.api_base),
        ))
    for c in connexions.lister():
        base = {"gemini": llm_client.GEMINI_BASE, "anthropic": llm_client.ANTHROPIC_BASE}.get(c.kind, c.api_base)
        out.append(ProviderConf(
            key=c.id, kind=c.kind, name=c.name, api_key=connexions.cle(c), api_base=base.rstrip("/"),
            ca_bundle=connexions.certificat(c), context_tokens=c.context_tokens, models=tuple(c.models),
            max_output_tokens=c.max_output_tokens or (32_000 if c.kind != "openai" else 0),
            local=c.kind == "openai" and is_local_base(c.api_base),
        ))
    return out


ENV_PROVIDERS = ("CUSTOM_LLM", "CUSTOM_LLM_2", "GEMINI", "ANTHROPIC")
STUDIODOCK = "studiodock-"  # préfixe des fournisseurs venus de Studio Dock
APP_ID = "docanalyser"  # identifiant de DocAnalyser dans le catalogue de Studio Dock


def connexions_studiodock() -> list[studiodock_ia.Connexion]:
    """Connexions de Studio Dock, sauf si Studio Dock garde à DocAnalyser sa configuration propre."""
    return [] if studiodock_ia.garde_sa_configuration(APP_ID) else studiodock_ia.connexions()


def modele_studiodock() -> str | None:
    """Identifiant du modèle choisi pour DocAnalyser dans Studio Dock (proposé d'office), ou None."""
    choix = studiodock_ia.pour_app(APP_ID)
    return f"{STUDIODOCK}{choix.connexion.id}:{choix.model}" if choix else None


# Profil déduit du nom du modèle : la liste elle-même vient uniquement du .env.
_DEEP = re.compile(r"large|opus|pro\b|ultra|argon|70b|72b|405b|-max", re.I)
_FAST = re.compile(r"small|\bmini\b|haiku|lite|nano|tiny|\b[1-9]b\b", re.I)
_TIER_SCORES = {"deep": (5, 2, 2), "balanced": (4, 4, 4), "fast": (3, 5, 5)}
_TIER_DESC = {
    "deep": "Raisonnement approfondi, pour les analyses très détaillées et les corpus complexes.",
    "balanced": "Équilibre entre profondeur d'analyse et rapidité.",
    "fast": "Rapide et économique, idéal pour des synthèses courtes.",
}


def _tier(model: str) -> Literal["deep", "balanced", "fast"]:
    if _DEEP.search(model):
        return "deep"
    if _FAST.search(model):
        return "fast"
    return "balanced"


def all_models() -> list[ModelSpec]:
    """Modèles listés dans *_AVAILABLE_MODELS, dans l'ordre du .env."""
    models = []
    for prov in providers():
        for n in prov.models:
            tier = _tier(n)
            q, v, c = _TIER_SCORES[tier]
            models.append(ModelSpec(f"{prov.key}:{n}", n, prov, _TIER_DESC[tier], q, v, c, tier))
    return models


def is_configured(spec: ModelSpec) -> bool:
    if spec.provider.kind != "openai":
        return bool(spec.provider.api_key)  # Gemini et Claude exigent une clé
    # La clé est facultative : un endpoint interne (vLLM, Ollama) peut ne pas en exiger.
    return bool(spec.provider.api_base)


def model_options() -> list[dict[str, Any]]:
    prefere = modele_studiodock()
    return [
        {
            "id": m.id,
            "name": m.name,
            "provider": m.provider.key,
            "provider_label": m.provider.name,
            "description": m.description,
            "quality": m.quality,
            "speed": m.speed,
            "economy": m.economy,
            "tier": m.tier,
            "configured": is_configured(m),
            "preferred": m.id == prefere,  # choisi pour DocAnalyser dans Studio Dock
        }
        for m in all_models()
    ]


def get_model(model_id: str) -> ModelSpec:
    for m in all_models():
        if m.id == model_id:
            return m
    raise AnalysisError(f"Modèle inconnu : {model_id} (vérifiez *_AVAILABLE_MODELS dans backend/.env)")


def fallback_chain(spec: ModelSpec) -> list[ModelSpec]:
    """Modèle choisi puis, en cas de quota ou surcharge, les autres modèles configurés du même fournisseur."""
    order = {"deep": 0, "balanced": 1, "fast": 2}
    others = [m for m in all_models() if m.provider.key == spec.provider.key and m.id != spec.id and is_configured(m)]
    others.sort(key=lambda m: abs(order[m.tier] - order[spec.tier]))
    return [spec, *others]
