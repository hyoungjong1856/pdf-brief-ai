"""Local document library. Originals are not retained; analysis responses are."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connection():
    path = Path(
        os.environ.get(
            "DOCUMENTS_DB_PATH",
            Path(__file__).resolve().parents[1] / "data" / "documents.db",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY, file_hash TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    summary TEXT NOT NULL, keyword TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS summaries_document ON summaries(document_id, id);
            """)
            yield db
    finally:
        db.close()


def response_from_row(row, existing=True):
    return {
        **json.loads(row["response_json"]),
        "document_id": row["document_id"],
        "summary_id": row["id"],
        "created_at": row["created_at"],
        "existing": existing,
    }


def find_existing(file_hash):
    with connection() as db:
        row = db.execute(
            """SELECT s.* FROM summaries s JOIN documents d ON d.id=s.document_id
            WHERE d.file_hash=? ORDER BY s.id DESC LIMIT 1""",
            (file_hash,),
        ).fetchone()
        return response_from_row(row) if row else None


def save_summary(file_hash, response, force=False):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT OR IGNORE INTO documents(file_hash, filename) VALUES (?, ?)",
            (file_hash, response["filename"]),
        )
        document_id = db.execute(
            "SELECT id FROM documents WHERE file_hash=?", (file_hash,)
        ).fetchone()[0]
        row = db.execute(
            "SELECT * FROM summaries WHERE document_id=? ORDER BY id DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if row and not force:
            return response_from_row(row)
        cursor = db.execute(
            "INSERT INTO summaries(document_id, summary, keyword, response_json) VALUES (?,?,?,?)",
            (
                document_id,
                response["summary"],
                response["keyword"],
                json.dumps(response, ensure_ascii=False),
            ),
        )
        row = db.execute(
            "SELECT * FROM summaries WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        return response_from_row(row, existing=False)


def list_documents(q="", limit=20, offset=0):
    pattern = (
        "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )
    where = """WHERE d.filename LIKE ? ESCAPE '\\' OR EXISTS (
        SELECT 1 FROM summaries h WHERE h.document_id=d.id AND
        (h.summary LIKE ? ESCAPE '\\' OR h.keyword LIKE ? ESCAPE '\\'))"""
    with connection() as db:
        total = db.execute(
            "SELECT count(*) FROM documents d " + where, (pattern,) * 3
        ).fetchone()[0]
        rows = db.execute(
            """SELECT d.id, d.filename, s.summary, s.keyword, COALESCE(s.created_at, d.created_at) AS created_at,
            (SELECT count(*) FROM summaries h WHERE h.document_id=d.id) AS summary_count
            FROM documents d LEFT JOIN summaries s ON s.id=(SELECT max(id) FROM summaries WHERE document_id=d.id)
            """
            + where
            + " ORDER BY COALESCE(s.created_at, d.created_at) DESC, d.id DESC LIMIT ? OFFSET ?",
            (pattern,) * 3 + (limit, offset),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}


def get_document(document_id):
    with connection() as db:
        document = db.execute(
            "SELECT id, filename, created_at FROM documents WHERE id=?", (document_id,)
        ).fetchone()
        if not document:
            return None
        rows = db.execute(
            "SELECT * FROM summaries WHERE document_id=? ORDER BY id DESC",
            (document_id,),
        ).fetchall()
        return {**dict(document), "summaries": [response_from_row(row) for row in rows]}


def delete_document(document_id):
    # Explicit transaction also supports databases created before cascade rules.
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM summaries WHERE document_id=?", (document_id,))
        return (
            db.execute("DELETE FROM documents WHERE id=?", (document_id,)).rowcount > 0
        )


def delete_summary(document_id, summary_id):
    with connection() as db:
        return (
            db.execute(
                "DELETE FROM summaries WHERE document_id=? AND id=?",
                (document_id, summary_id),
            ).rowcount
            > 0
        )
