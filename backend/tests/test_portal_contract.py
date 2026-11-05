"""Contrat du portail : /health, --port, --no-browser, --version, et interface servie par le backend."""
import importlib
import socket
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import launcher  # noqa: E402
from app.info import APP_ID, DEFAULT_PORT, VERSION  # noqa: E402


@pytest.fixture
def app_with_frontend(tmp_path, monkeypatch):
    """Application chargée avec une fausse interface compilée."""
    (tmp_path.parent / "secret.txt").write_text("secret", encoding="utf-8")
    tmp_path = tmp_path / "dist"
    (tmp_path / "assets").mkdir(parents=True)
    (tmp_path / "index.html").write_text("<!doctype html><title>Analyse documentaire</title>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    import app.main

    module = importlib.reload(app.main)
    yield module.app
    monkeypatch.delenv("FRONTEND_DIST")
    importlib.reload(app.main)


def test_health():
    from app.main import app

    body = TestClient(app).get("/health").json()
    assert body == {"status": "ok", "app": APP_ID, "name": "Analyse documentaire", "version": VERSION}


def test_default_port():
    assert DEFAULT_PORT == 8020


def test_backend_serves_the_frontend(app_with_frontend):
    client = TestClient(app_with_frontend)
    assert "Analyse documentaire" in client.get("/").text
    assert "Analyse documentaire" in client.get("/historique").text  # route de l'interface : index.html
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/logo.svg").text == "<svg/>"
    assert client.get("/health").json()["app"] == APP_ID
    assert client.get("/api/v2/models").status_code == 200
    assert client.get("/api/v2/inconnue").status_code == 404  # une API inconnue ne renvoie pas la page
    # Rien en dehors de l'interface compilée n'est servi
    assert "secret" not in client.get("/..%2Fsecret.txt").text


def test_version_option(capsys):
    with pytest.raises(SystemExit) as exit_info:
        launcher.main(["--version"])
    assert exit_info.value.code == 0
    assert VERSION in capsys.readouterr().out


def test_port_taken_by_another_app(monkeypatch, capsys):
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        port = other.getsockname()[1]
        started = []
        monkeypatch.setattr(launcher.uvicorn, "run", lambda *a, **k: started.append(k))
        with pytest.raises(SystemExit) as exit_info:
            launcher.main(["--port", str(port), "--no-browser"])
    assert exit_info.value.code == 2
    assert not started
    assert str(port) in capsys.readouterr().err


def test_no_browser(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    started, opened = [], []
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **k: started.append(k))
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    launcher.main(["--port", str(port), "--no-browser"])
    assert started == [{"host": "127.0.0.1", "port": port, "log_level": "warning"}]
    assert not opened
