"""Prépare un historique de test : une analyse terminée sur le document d'entretiens des tests backend.

À lancer avec STORAGE_DIR et DOCANALYSER_CONFIG pointant vers des dossiers temporaires (voir playwright.config.ts).
"""
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
for folder in (os.environ["STORAGE_DIR"], os.environ["DOCANALYSER_CONFIG"]):
    shutil.rmtree(folder, ignore_errors=True)
    Path(folder).mkdir(parents=True)
sys.path.insert(0, str(BACKEND))

from app.services import analysis_service as svc, store  # noqa: E402

doc = svc.store_document((BACKEND / "tests/fixtures/entretiens_parcours.txt").read_bytes(), "parcours.txt")
analysis = svc.Analysis(
    id="e2e-demo", mode="global", level="detail", model_id="CUSTOM_LLM:fake-model", language="fr", cite=True,
    documents=[doc], created_at=datetime.now(timezone.utc), status="done", title="Ouverture de compte",
    markdown="# Ouverture de compte",
    result={
        "kind": "themes", "title": "Ouverture de compte", "brief": "Le parcours d'ouverture de compte.",
        "themes": [{"title": "Points d'entrée", "summary": "D'où viennent les participants.", "documents": ["parcours.txt"],
                    "points": [{"lead": "Simulateur", "body": "Sept participants.", "sources": [{"document": "parcours.txt", "location": "L4", "found": True}]}],
                    "quote": "", "quote_check": "", "quote_by": "", "nuance": ""}],
        "actions": [], "sources": [{"document": "parcours.txt", "citations": 1}],
        "stats": {"themes": 1, "points": 1, "quotes": 0, "quotes_exact": 0, "actions": 0},
    },
)
svc.ANALYSES[analysis.id] = analysis
store.save_analysis(analysis)
print("Historique de test prêt")
