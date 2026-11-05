"""Préparation commune : stockage isolé, pour ne jamais toucher à l'historique réel (backend/data/)."""
import os
import tempfile
from pathlib import Path

# Doit être défini avant tout import de l'application (la configuration est lue à l'import).
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="docanalyser-tests-")

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LLM_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="appelle un vrai modèle : lancer avec RUN_LLM_TESTS=1")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
