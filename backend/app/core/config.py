from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Configuration lue dans backend/.env (modèle : backend/.env.example)."""

    model_config = SettingsConfigDict(
        env_file=(str(ENV_PATH), "backend/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Fournisseur principal compatible OpenAI
    CUSTOM_LLM_PROVIDER_NAME: str = "Custom Endpoint"
    CUSTOM_LLM_API_KEY: str = ""
    CUSTOM_LLM_API_BASE: str = ""
    CUSTOM_LLM_CA_BUNDLE: Optional[str] = None
    CUSTOM_LLM_AVAILABLE_MODELS: str = ""
    CUSTOM_LLM_CONTEXT_TOKENS: int = 128000

    # 2. Fournisseur complémentaire compatible OpenAI
    CUSTOM_LLM_2_PROVIDER_NAME: str = "Fournisseur complémentaire"
    CUSTOM_LLM_2_API_KEY: str = ""
    CUSTOM_LLM_2_API_BASE: str = ""
    CUSTOM_LLM_2_CA_BUNDLE: Optional[str] = None
    CUSTOM_LLM_2_AVAILABLE_MODELS: str = ""
    CUSTOM_LLM_2_CONTEXT_TOKENS: int = 128000

    # 3. Clés de test : Google Gemini et Anthropic Claude
    GEMINI_API_KEY: str = ""
    GEMINI_CA_BUNDLE: Optional[str] = None
    GEMINI_TEST_MODELS: str = ""
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_CA_BUNDLE: Optional[str] = None
    ANTHROPIC_TEST_MODELS: str = ""

    # Paramètres généraux
    STORAGE_DIR: Path = Path("/tmp/doc_intel_storage")
    MAX_CONCURRENT_LLM_REQUESTS: int = 4

    @staticmethod
    def _is_key_set(raw_key: str) -> bool:
        placeholders = {"", "votre_cle_api_gemini", "local-dev-key"}
        return bool(raw_key and raw_key.strip() not in placeholders)


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
