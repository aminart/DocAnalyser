"""Historique : enregistrement, rechargement après redémarrage, suppression."""
from datetime import datetime, timezone

from app.services import analysis_service as svc
from app.services import store


def _restart() -> None:
    """Simule un redémarrage du serveur : mémoire vidée, puis rechargement depuis la base."""
    svc.DOCUMENTS.clear()
    svc.ANALYSES.clear()
    svc.load_history()


def test_historique_survit_au_redemarrage_et_suppression_propre(fixtures_dir):
    d1 = svc.store_document((fixtures_dir / "compte_rendu_6_sujets.txt").read_bytes(), "cr.txt")
    d2 = svc.store_document((fixtures_dir / "entretiens_parcours.txt").read_bytes(), "parcours.txt")
    now = datetime.now(timezone.utc)
    done = svc.Analysis(id="h-done", mode="global", level="detail", model_id="X:m", language="fr", cite=True,
                        documents=[d1, d2], created_at=now, status="done", title="Terminée", markdown="# ok")
    running = svc.Analysis(id="h-run", mode="flow", level="synth", model_id="X:m", language="fr", cite=True,
                           documents=[d2], created_at=now, status="running")
    for a in (done, running):
        svc.ANALYSES[a.id] = a
        store.save_analysis(a)

    _restart()
    assert svc.ANALYSES["h-done"].status == "done" and svc.ANALYSES["h-done"].markdown == "# ok"
    assert svc.ANALYSES["h-run"].status == "failed"  # interrompue par le redémarrage
    assert [d.name for d in svc.ANALYSES["h-done"].documents] == ["cr.txt", "parcours.txt"]

    svc.delete_analysis(svc.ANALYSES["h-done"])
    assert d1.id not in svc.DOCUMENTS  # ne servait plus
    assert d2.id in svc.DOCUMENTS  # sert encore à « h-run »

    _restart()
    assert "h-done" not in svc.ANALYSES and d1.id not in svc.DOCUMENTS


def test_document_recu_d_une_autre_app_se_relit(fixtures_dir):
    """Snappy Transcript envoie un fichier puis ouvre #/importer/<id> : l'interface relit le document par son id."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, base_url="http://127.0.0.1")
    envoi = client.post("/api/v2/documents", files={"file": ("Réunion.txt", "[00:00:01] Alice : bonjour\n".encode(), "text/plain")})
    assert envoi.status_code == 200
    doc = client.get(f"/api/v2/documents/{envoi.json()['id']}")
    assert doc.status_code == 200 and doc.json()["name"] == "Réunion.txt"
    assert client.get("/api/v2/documents/inconnu").status_code == 404
