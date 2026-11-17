"""Modèles d'IA réglés dans Studio Dock : proposés par DocAnalyser, en lecture seule, avec le modèle choisi."""
import base64
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.core import studiodock_ia
from app.main import app


def ecrire(defaut=None, apps=None):
    dossier = studiodock_ia.dossier()
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "connexions.json").write_text(json.dumps({
        "format": 1,
        "connections": [
            {"id": "sd1", "name": "Passerelle (Studio Dock)", "provider": "openai", "api_base": "https://llm.interne/v1",
             "api_key": {"scheme": "plain", "data": base64.b64encode(b"sk-studiodock-ABCD1234").decode()},
             "models": ["mistral-large", "mistral-small"], "context_tokens": 128000},
            {"id": "sd2", "name": "Ollama (ce poste)", "provider": "ollama", "api_base": "http://localhost:11434/v1",
             "models": ["qwen3:8b"], "context_tokens": 4096},
        ],
        "default": defaut, "apps": apps or {},
    }), encoding="utf-8")


@pytest.fixture(autouse=True)
def vide():
    shutil.rmtree(studiodock_ia.dossier(), ignore_errors=True)
    yield
    shutil.rmtree(studiodock_ia.dossier(), ignore_errors=True)


def test_connexions_proposees_en_lecture_seule():
    ecrire(defaut={"connection": "sd1", "model": "mistral-small"},
           apps={"docanalyser": {"connection": "sd2", "model": "qwen3:8b"}})
    client = TestClient(app)
    modeles = client.get("/api/v2/models").json()
    ids = {m["id"]: m for m in modeles}
    assert "studiodock-sd1:mistral-large" in ids and "studiodock-sd2:qwen3:8b" in ids
    assert [m["id"] for m in modeles if m["preferred"]] == ["studiodock-sd2:qwen3:8b"]
    assert ids["studiodock-sd2:qwen3:8b"]["configured"]  # sans clé : Ollama n'en demande pas

    connexions = client.get("/api/v2/connections").json()["connections"]
    sd = [c for c in connexions if c["source"] == "studiodock"]
    assert [c["name"] for c in sd] == ["Passerelle (Studio Dock)", "Ollama (ce poste)"]
    assert sd[0]["has_api_key"] and sd[0]["api_key_hint"] == "1234"
    assert "sk-studiodock" not in json.dumps(connexions)

    # Le modèle choisi sert pour de vrai : clé et contexte de la connexion Studio Dock
    from app.services import analysis_service as svc

    spec = svc.get_model("studiodock-sd1:mistral-large")
    assert spec.provider.api_key == "sk-studiodock-ABCD1234" and spec.context_tokens == 128000


def test_modele_par_defaut_sans_choix_propre():
    ecrire(defaut={"connection": "sd1", "model": "mistral-small"})
    modeles = TestClient(app).get("/api/v2/models").json()
    assert [m["id"] for m in modeles if m["preferred"]] == ["studiodock-sd1:mistral-small"]


def test_configuration_propre():
    ecrire(defaut={"connection": "sd1", "model": "mistral-small"}, apps={"docanalyser": {"own": True}})
    client = TestClient(app)
    assert not [m for m in client.get("/api/v2/models").json() if m["id"].startswith("studiodock-")]
    etat = client.get("/api/v2/connections").json()
    assert etat["studiodock_own"] and not [c for c in etat["connections"] if c["source"] == "studiodock"]


def test_sans_studio_dock():
    assert not [m for m in TestClient(app).get("/api/v2/models").json() if m["id"].startswith("studiodock-")]
