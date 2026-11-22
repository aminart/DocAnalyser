"""Version Mac : dossier de données, clé dans le trousseau, chemins depuis DocAnalyser.app, fenêtre du Terminal.

Le Mac est simulé (sys.platform et la commande « security » remplacés) : la CI tourne sous Linux. Le vrai
lancement de l'app est vérifié par le workflow « Build macOS app » sur un Mac de GitHub.
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launcher  # noqa: E402
from app.core import connexions  # noqa: E402


class FauxTrousseau:
    """Imite /usr/bin/security : add-, find- et delete-generic-password."""

    def __init__(self):
        self.cles: dict[str, str] = {}
        self.appels: list[list[str]] = []

    def __call__(self, commande, **_):
        self.appels.append(commande)
        assert commande[0] == "/usr/bin/security"
        action, options = commande[1], commande[2:]
        valeurs = dict(zip(options[::2], options[1::2])) if action != "add-generic-password" else \
            dict(zip([o for o in options if o != "-U"][::2], [o for o in options if o != "-U"][1::2]))
        compte = valeurs.get("-a", "")
        if action == "add-generic-password":
            self.cles[compte] = valeurs["-w"]
            return subprocess.CompletedProcess(commande, 0, "", "")
        if action == "find-generic-password" and compte in self.cles:
            return subprocess.CompletedProcess(commande, 0, self.cles[compte] + "\n", "")
        if action == "delete-generic-password" and compte in self.cles:
            del self.cles[compte]
            return subprocess.CompletedProcess(commande, 0, "", "")
        return subprocess.CompletedProcess(commande, 44, "", "introuvable")


@pytest.fixture
def mac(monkeypatch):
    trousseau = FauxTrousseau()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(connexions.subprocess, "run", trousseau)
    return trousseau


def test_dossier_mac(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCANALYSER_CONFIG")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert connexions.dossier_config() == tmp_path / "Library" / "Application Support" / "DocAnalyser"
    # Données d'un lancement depuis les sources avant la version Mac : gardées tant que le nouveau dossier n'existe pas
    (tmp_path / ".config" / "docanalyser").mkdir(parents=True)
    assert connexions.dossier_config() == tmp_path / ".config" / "docanalyser"


def test_cle_dans_le_trousseau(mac):
    c = connexions.creer("openai", "Passerelle", "https://passerelle.interne/v1", "sk-secret-123", ["m"], None)
    assert c.api_key["scheme"] == "keychain" and "sk-secret" not in str(c.api_key)
    assert "sk-secret" not in connexions._fichier().read_text(encoding="utf-8")
    assert connexions.cle(connexions.trouver(c.id)) == "sk-secret-123"
    # Clé remplacée : l'ancienne est retirée du trousseau ; connexion supprimée : la sienne aussi
    connexions.modifier(c.id, "openai", "Passerelle", "https://passerelle.interne/v1", "sk-nouvelle", ["m"], None)
    assert list(mac.cles.values()) == ["sk-nouvelle"]
    assert connexions.cle(connexions.trouver(c.id)) == "sk-nouvelle"
    connexions.supprimer(c.id)
    assert mac.cles == {}
    assert "trousseau macOS" in connexions.protection()


def test_trousseau_indisponible(monkeypatch):
    """Trousseau verrouillé ou absent : la clé est encodée dans le fichier, comme avant."""
    monkeypatch.setattr(sys, "platform", "darwin")

    def refuse(commande, **_):
        return subprocess.CompletedProcess(commande, 51, "", "refusé")

    monkeypatch.setattr(connexions.subprocess, "run", refuse)
    stocke = connexions.chiffrer("sk-abc")
    assert stocke["scheme"] == "plain" and connexions.dechiffrer(stocke) == "sk-abc"
    assert connexions.dechiffrer({"scheme": "keychain", "data": "cle-inconnue"}) == ""


def test_chemins_depuis_l_app_mac(monkeypatch, tmp_path):
    """Depuis DocAnalyser.app : .env et données dans le dossier de l'utilisateur, pas dans l'app."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DocAnalyser.app" / "Contents" / "MacOS" / "DocAnalyser"))
    monkeypatch.setenv("DOCANALYSER_CONFIG", str(tmp_path / "Support" / "DocAnalyser"))
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    from app.core import config

    try:
        recharge = importlib.reload(config)
        assert recharge.ENV_PATH == tmp_path / "Support" / "DocAnalyser" / ".env"
        assert recharge.settings.STORAGE_DIR == tmp_path / "Support" / "DocAnalyser" / "donnees"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


@pytest.fixture
def app_mac(monkeypatch):
    lancements = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(launcher.subprocess, "run", lambda commande, **_: lancements.append(commande))
    monkeypatch.setattr(launcher, "_already_running", lambda port: False)
    monkeypatch.setattr(launcher.uvicorn, "run", lambda *a, **k: lancements.append("serveur"))
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)
    return lancements


def test_double_clic_ouvre_le_terminal(app_mac):
    launcher.main(["-psn_0_12345"])
    assert app_mac == [["/usr/bin/open", "-a", "Terminal", sys.executable]]


def test_portail_sans_terminal(app_mac):
    """Lancé par le portail (options données) : démarre directement, sans fenêtre du Terminal."""
    launcher.main(["--port", "8597", "--no-browser"])
    assert app_mac == ["serveur"]
