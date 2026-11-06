"""Exécutable et versions : chemins valables depuis l'exe, numéro de version unique, script de version."""
import datetime as dt
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app import info

RACINE = Path(__file__).resolve().parent.parent.parent


def test_version_unique():
    version = (RACINE / "VERSION").read_text(encoding="utf-8").strip()
    assert re.match(r"^\d+\.\d+\.\d+$", version) and info.VERSION == version
    assert json.loads((RACINE / "frontend" / "package.json").read_text(encoding="utf-8"))["version"] == version
    journal = (RACINE / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Non publié]" in journal and f"## [{version}]" in journal


def test_recette_embarque_l_interface_et_la_version():
    recette = (RACINE / "DocAnalyser.spec").read_text(encoding="utf-8")
    assert '("VERSION", ".")' in recette and '("frontend/dist", "frontend_dist")' in recette
    assert '["backend/launcher.py"]' in recette


def test_chemins_depuis_l_exe(monkeypatch, tmp_path):
    """Depuis l'exe : .env à côté de l'exe, données dans le dossier de l'utilisateur."""
    import importlib
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Programmes" / "DocAnalyser.exe"))
    monkeypatch.setenv("DOCANALYSER_CONFIG", str(tmp_path / "AppData" / "DocAnalyser"))
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    from app.core import config

    try:
        recharge = importlib.reload(config)
        assert recharge.EMPAQUETE
        assert recharge.ENV_PATH == tmp_path / "Programmes" / ".env"
        assert recharge.settings.STORAGE_DIR == tmp_path / "AppData" / "DocAnalyser" / "donnees"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def _bump():
    spec = importlib.util.spec_from_file_location("bump_version", RACINE / "scripts" / "bump_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("demande", "attendu"), [("patch", "2.0.1"), ("minor", "2.1.0"), ("major", "3.0.0"), ("2.4.0", "2.4.0")])
def test_version_suivante(demande, attendu):
    assert _bump().next_version("2.0.0", demande) == attendu


def test_bump_date_la_section(tmp_path, monkeypatch):
    bump = _bump()
    journal = tmp_path / "CHANGELOG.md"
    journal.write_text("# H\n\n## [Non publié]\n\n### Ajouté\n\n- Une chose\n\n## [2.0.0] — référence\n", encoding="utf-8")
    monkeypatch.setattr(bump, "CHANGELOG", journal)
    bump.update_changelog("2.1.0", dt.date(2026, 11, 5))
    assert "## [Non publié]\n\n## [2.1.0] — 2026-11-05\n\n### Ajouté" in journal.read_text(encoding="utf-8")
