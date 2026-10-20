from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.schemas.models import ModelOption


@dataclass
class ProviderCredentials:
    provider: Literal["gemini", "mistral", "custom"]
    api_key: str
    api_base: str
    ca_bundle: Optional[str]
    has_valid_key: bool


ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ENV_PATH), "backend/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Fournisseur Mistral
    MISTRAL_API_KEY: str = ""
    MISTRAL_API_BASE: str = "https://api.mistral.ai/v1"
    MISTRAL_CA_BUNDLE: Optional[str] = None
    MISTRAL_AVAILABLE_MODELS: str = "mistral-medium-latest,mistral-small-latest,mistral-large-latest"

    # 2. Fournisseur Google Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_CA_BUNDLE: Optional[str] = None
    GEMINI_AVAILABLE_MODELS: str = "gemini-3.8-flash,gemini-4-argon,gemini-3.5-flash-lite"

    # 2 bis. Clés de test pour l'interface « Analyse documentaire »
    # (GEMINI_API_KEY ci-dessus est partagée avec l'ancienne interface)
    GEMINI_TEST_MODELS: str = ""
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_CA_BUNDLE: Optional[str] = None
    ANTHROPIC_TEST_MODELS: str = ""

    # 3. Fournisseur principal compatible OpenAI (interface « Analyse documentaire »)
    CUSTOM_LLM_PROVIDER_NAME: str = "Custom Endpoint"
    CUSTOM_LLM_API_KEY: str = ""
    CUSTOM_LLM_API_BASE: str = "http://localhost:11434/v1"
    CUSTOM_LLM_CA_BUNDLE: Optional[str] = None
    CUSTOM_LLM_AVAILABLE_MODELS: str = ""
    CUSTOM_LLM_CONTEXT_TOKENS: int = 128000

    # 4. Fournisseur complémentaire compatible OpenAI
    CUSTOM_LLM_2_PROVIDER_NAME: str = "Fournisseur complémentaire"
    CUSTOM_LLM_2_API_KEY: str = ""
    CUSTOM_LLM_2_API_BASE: str = ""
    CUSTOM_LLM_2_CA_BUNDLE: Optional[str] = None
    CUSTOM_LLM_2_AVAILABLE_MODELS: str = ""
    CUSTOM_LLM_2_CONTEXT_TOKENS: int = 128000

    # Paramètres globaux
    DEFAULT_MODEL: str = "gemini-3.8-flash"
    ENABLE_FALLBACK_SIMULATION: bool = True

    STORAGE_DIR: Path = Path("/tmp/doc_intel_storage")
    MAX_CONCURRENT_LLM_REQUESTS: int = 4
    CHUNK_TOKEN_SIZE: int = 12000

    @staticmethod
    def _is_key_set(raw_key: str) -> bool:
        placeholders = {
            "",
            "votre_cle_api_mistral_ou_interne",
            "votre_cle_api_gemini",
            "local-dev-key",
        }
        return bool(raw_key and raw_key.strip() not in placeholders)

    def resolve_provider(self, model_id: str) -> ProviderCredentials:
        """Détermine automatiquement le fournisseur (Gemini, Mistral ou Custom) et ses clés .env selon le modèle choisi."""
        clean_id = model_id.strip()
        if ":" in clean_id:
            prefix, clean_id = clean_id.split(":", 1)
            prefix_low = prefix.lower().strip()
        else:
            prefix_low = ""

        gemini_models = {
            m.strip() for m in self.GEMINI_AVAILABLE_MODELS.split(",") if m.strip()
        }
        mistral_models = {
            m.strip() for m in self.MISTRAL_AVAILABLE_MODELS.split(",") if m.strip()
        }

        if (
            prefix_low == "gemini"
            or clean_id in gemini_models
            or clean_id.startswith(("gemini-", "gemma-"))
        ):
            return ProviderCredentials(
                provider="gemini",
                api_key=self.GEMINI_API_KEY.strip(),
                api_base=self.GEMINI_API_BASE.rstrip("/"),
                ca_bundle=self.GEMINI_CA_BUNDLE,
                has_valid_key=self._is_key_set(self.GEMINI_API_KEY),
            )

        if (
            prefix_low == "mistral"
            or clean_id in mistral_models
            or clean_id.startswith(("mistral-", "pixtral-", "codestral-"))
        ):
            return ProviderCredentials(
                provider="mistral",
                api_key=self.MISTRAL_API_KEY.strip(),
                api_base=self.MISTRAL_API_BASE.rstrip("/"),
                ca_bundle=self.MISTRAL_CA_BUNDLE,
                has_valid_key=self._is_key_set(self.MISTRAL_API_KEY),
            )

        return ProviderCredentials(
            provider="custom",
            api_key=self.CUSTOM_LLM_API_KEY.strip(),
            api_base=self.CUSTOM_LLM_API_BASE.rstrip("/"),
            ca_bundle=self.CUSTOM_LLM_CA_BUNDLE,
            has_valid_key=self._is_key_set(self.CUSTOM_LLM_API_KEY),
        )

    def get_model_options(self) -> list[ModelOption]:
        gemini_key_ok = self._is_key_set(self.GEMINI_API_KEY)
        mistral_key_ok = self._is_key_set(self.MISTRAL_API_KEY)
        custom_key_ok = self._is_key_set(self.CUSTOM_LLM_API_KEY)

        catalog: dict[str, dict] = {
            # Catalogue Gemini (1M tokens)
            "gemini-3.8-flash": {
                "provider": "gemini",
                "provider_label": "Google Gemini API",
                "label": "Gemini 3.8 Flash (Rapide & Multimodal - 1M)",
                "description": "Fenêtre d'1M de tokens : analyse des PDF de 300+ pages d'un seul tenant avec haute précision.",
                "context_window": 1000000,
                "api_key_configured": gemini_key_ok,
            },
            "gemini-4-argon": {
                "provider": "gemini",
                "provider_label": "Google Gemini API",
                "label": "Gemini 4 Argon (Raisonnement Max - 1M)",
                "description": "Le modèle Gemini le plus puissant pour l'analyse stratégique multi-documents et parcours complexes.",
                "context_window": 1000000,
                "api_key_configured": gemini_key_ok,
            },
            "gemini-3.5-flash-lite": {
                "provider": "gemini",
                "provider_label": "Google Gemini API",
                "label": "Gemini 3.5 Flash-Lite (Ultra-Rapide - 1M)",
                "description": "Exécution à très haut débit et faible latence pour les notes en vrac et grandes transcriptions.",
                "context_window": 1000000,
                "api_key_configured": gemini_key_ok,
            },
            # Catalogue Mistral
            "mistral-medium-latest": {
                "provider": "mistral",
                "provider_label": "Mistral AI",
                "label": "Mistral Medium (Équilibré)",
                "description": "Haute précision analytique pour rapports longs, classeurs Excel denses et parcours UX.",
                "context_window": 128000,
                "api_key_configured": mistral_key_ok,
            },
            "mistral-small-latest": {
                "provider": "mistral",
                "provider_label": "Mistral AI",
                "label": "Mistral Small (Rapide & Économique)",
                "description": "Idéal pour les notes en vrac, transcriptions de réunions et synthèses rapides.",
                "context_window": 32000,
                "api_key_configured": mistral_key_ok,
            },
            "mistral-large-latest": {
                "provider": "mistral",
                "provider_label": "Mistral AI",
                "label": "Mistral Large (Raisonnement Profond)",
                "description": "Synthèse croisée multi-documents complexe et arbitrage stratégique de haute précision.",
                "context_window": 128000,
                "api_key_configured": mistral_key_ok,
            },
        }

        options: list[ModelOption] = []

        # 1. Modèles Gemini déclarés dans .env
        for model_id in [
            m.strip() for m in self.GEMINI_AVAILABLE_MODELS.split(",") if m.strip()
        ]:
            if model_id in catalog:
                options.append(ModelOption(id=model_id, **catalog[model_id]))
            else:
                options.append(
                    ModelOption(
                        id=model_id,
                        provider="gemini",
                        provider_label="Google Gemini API",
                        label=f"{model_id} (Gemini)",
                        description="Modèle Google Gemini configuré dans .env",
                        context_window=1000000,
                        api_key_configured=gemini_key_ok,
                    )
                )

        # 2. Modèles Mistral déclarés dans .env
        for model_id in [
            m.strip() for m in self.MISTRAL_AVAILABLE_MODELS.split(",") if m.strip()
        ]:
            if model_id in catalog:
                options.append(ModelOption(id=model_id, **catalog[model_id]))
            else:
                options.append(
                    ModelOption(
                        id=model_id,
                        provider="mistral",
                        provider_label="Mistral AI",
                        label=f"{model_id} (Mistral)",
                        description="Modèle Mistral / Entreprise configuré dans .env",
                        context_window=128000,
                        api_key_configured=mistral_key_ok,
                    )
                )

        # 3. Modèles Custom (OpenAI / vLLM / Ollama) déclarés dans .env
        for model_id in [
            m.strip() for m in self.CUSTOM_LLM_AVAILABLE_MODELS.split(",") if m.strip()
        ]:
            options.append(
                ModelOption(
                    id=model_id,
                    provider="custom",
                    provider_label=self.CUSTOM_LLM_PROVIDER_NAME,
                    label=f"{model_id} ({self.CUSTOM_LLM_PROVIDER_NAME})",
                    description=f"Modèle servi sur {self.CUSTOM_LLM_API_BASE}",
                    context_window=64000,
                    api_key_configured=custom_key_ok,
                )
            )

        return options


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
