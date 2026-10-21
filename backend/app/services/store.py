"""Persistance SQLite des documents et des analyses (historique conservé entre deux redémarrages).

Les dictionnaires en mémoire d'analysis_service restent la source de travail ; ce module les recharge
au démarrage et y écrit à chaque étape clé (import, lancement, fin, annulation, suppression).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import settings
from app.services.parser_service import AnchoredTextBlock

if TYPE_CHECKING:
    from app.services.analysis_service import Analysis, StoredDocument

DB_PATH = settings.STORAGE_DIR / "analyses.db"
ORPHAN_DOC_TTL = timedelta(hours=24)  # document importé mais jamais analysé

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data TEXT NOT NULL
            );
        """)
    return _conn


def _write(sql: str, params: tuple) -> None:
    with _lock:
        db = _db()
        db.execute(sql, params)
        db.commit()


# -- Documents ----------------------------------------------------------------

def save_document(doc: "StoredDocument") -> None:
    data = {
        "id": doc.id, "name": doc.name, "ext": doc.ext, "size_bytes": doc.size_bytes, "units": doc.units,
        "pages": doc.pages, "warnings": doc.warnings,
        "blocks": [[b.file_name, b.location, b.content] for b in doc.blocks],
    }
    _write("INSERT OR REPLACE INTO documents VALUES (?, ?, ?)",
           (doc.id, datetime.now(timezone.utc).isoformat(), json.dumps(data, ensure_ascii=False)))


def delete_document(doc_id: str) -> None:
    _write("DELETE FROM documents WHERE id = ?", (doc_id,))
    for f in Path(settings.STORAGE_DIR).glob(f"v2_{doc_id}_*"):
        f.unlink(missing_ok=True)


# -- Analyses -----------------------------------------------------------------

_ANALYSIS_FIELDS = ("id", "mode", "level", "model_id", "language", "cite", "status", "progress", "step", "preview",
                    "title", "result", "markdown", "error", "active_model_id", "batched")


def save_analysis(a: "Analysis") -> None:
    data = {f: getattr(a, f) for f in _ANALYSIS_FIELDS}
    data["document_ids"] = [d.id for d in a.documents]
    data["step_notes"] = {str(k): v for k, v in a.step_notes.items()}
    _write("INSERT OR REPLACE INTO analyses VALUES (?, ?, ?)",
           (a.id, a.created_at.isoformat(), json.dumps(data, ensure_ascii=False)))


def delete_analysis(analysis_id: str) -> None:
    _write("DELETE FROM analyses WHERE id = ?", (analysis_id,))


# -- Chargement au démarrage ---------------------------------------------------

def load_all() -> tuple[dict[str, "StoredDocument"], dict[str, "Analysis"]]:
    from app.services.analysis_service import Analysis, StoredDocument

    with _lock:
        doc_rows = _db().execute("SELECT id, created_at, data FROM documents").fetchall()
        an_rows = _db().execute("SELECT id, created_at, data FROM analyses").fetchall()

    documents: dict[str, StoredDocument] = {}
    created: dict[str, datetime] = {}
    for doc_id, created_at, raw in doc_rows:
        d = json.loads(raw)
        documents[doc_id] = StoredDocument(
            d["id"], d["name"], d["ext"], d["size_bytes"], d["units"], d["pages"],
            [AnchoredTextBlock(*b) for b in d["blocks"]], d.get("warnings", []),
        )
        created[doc_id] = datetime.fromisoformat(created_at)

    analyses: dict[str, Analysis] = {}
    for an_id, created_at, raw in an_rows:
        d = json.loads(raw)
        docs = [documents[i] for i in d.pop("document_ids") if i in documents]
        notes = {int(k): v for k, v in d.pop("step_notes", {}).items()}
        a = Analysis(documents=docs, created_at=datetime.fromisoformat(created_at), step_notes=notes, **d)
        if a.status == "running":  # le backend s'est arrêté pendant l'analyse
            a.status = "failed"
            a.error = "L'analyse a été interrompue par un redémarrage du serveur. Relancez-la."
            save_analysis(a)
        analyses[an_id] = a

    # Documents importés mais jamais analysés depuis plus de 24 h : supprimés.
    used = {d.id for a in analyses.values() for d in a.documents}
    now = datetime.now(timezone.utc)
    for doc_id in list(documents):
        if doc_id not in used and now - created[doc_id] > ORPHAN_DOC_TTL:
            delete_document(doc_id)
            documents.pop(doc_id)
    return documents, analyses
