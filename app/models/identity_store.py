import os
import sqlite3
import time
from typing import Dict, List

from flask import current_app, has_app_context


def _db_path() -> str:
    configured = ""
    if has_app_context():
        configured = str(current_app.config.get("IDENTITY_DB_PATH", "") or "").strip()
    if configured:
        return configured
    return os.path.join("output", "identity_profiles.sqlite3")


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identity_profiles (
                profile_key TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS linked_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_key TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                doc_label TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                file_key TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'self-declared',
                added_at INTEGER NOT NULL,
                UNIQUE(profile_key, doc_type, doc_id, file_key),
                FOREIGN KEY(profile_key) REFERENCES identity_profiles(profile_key) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


def upsert_profile(profile_key: str) -> None:
    key = str(profile_key or "").strip()
    if not key:
        return
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO identity_profiles(profile_key, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(profile_key) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (key, now, now),
        )
        conn.commit()


def add_document(profile_key: str, doc: Dict) -> Dict:
    key = str(profile_key or "").strip()
    if not key:
        raise ValueError("profileKey is required")

    doc_type = str((doc or {}).get("type", "") or "").strip().lower()
    doc_label = str((doc or {}).get("label", doc_type.upper()) or "").strip() or doc_type.upper()
    doc_id = str((doc or {}).get("id", "") or "").strip()
    file_key = str((doc or {}).get("fileKey", "") or "").strip()
    source = str((doc or {}).get("source", "self-declared") or "self-declared").strip().lower()

    if not doc_type:
        raise ValueError("type is required")

    upsert_profile(key)
    now = int(time.time())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO linked_documents(profile_key, doc_type, doc_label, doc_id, file_key, source, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_key, doc_type, doc_id, file_key)
            DO UPDATE SET
                doc_label=excluded.doc_label,
                source=excluded.source,
                added_at=excluded.added_at
            """,
            (key, doc_type, doc_label, doc_id, file_key, source, now),
        )
        conn.execute("UPDATE identity_profiles SET updated_at=? WHERE profile_key=?", (now, key))
        conn.commit()

    return {
        "type": doc_type,
        "label": doc_label,
        "id": doc_id,
        "fileKey": file_key,
        "source": source,
        "addedAt": now,
    }


def get_documents(profile_key: str) -> List[Dict]:
    key = str(profile_key or "").strip()
    if not key:
        return []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_type, doc_label, doc_id, file_key, source, added_at
            FROM linked_documents
            WHERE profile_key = ?
            ORDER BY added_at DESC, id DESC
            """,
            (key,),
        ).fetchall()

    return [
        {
            "type": str(row["doc_type"] or ""),
            "label": str(row["doc_label"] or ""),
            "id": str(row["doc_id"] or ""),
            "fileKey": str(row["file_key"] or ""),
            "source": str(row["source"] or "self-declared"),
            "addedAt": int(row["added_at"] or 0),
        }
        for row in rows
    ]


def remove_document(profile_key: str, doc_type: str, doc_id: str, file_key: str = "") -> int:
    key = str(profile_key or "").strip()
    normalized_type = str(doc_type or "").strip().lower()
    normalized_id = str(doc_id or "").strip()
    normalized_file_key = str(file_key or "").strip()

    if not key or not normalized_type:
        return 0

    with _connect() as conn:
        if normalized_file_key:
            result = conn.execute(
                """
                DELETE FROM linked_documents
                WHERE profile_key = ? AND doc_type = ? AND doc_id = ? AND file_key = ?
                """,
                (key, normalized_type, normalized_id, normalized_file_key),
            )
        else:
            result = conn.execute(
                """
                DELETE FROM linked_documents
                WHERE profile_key = ? AND doc_type = ? AND doc_id = ?
                """,
                (key, normalized_type, normalized_id),
            )

        if result.rowcount:
            conn.execute("UPDATE identity_profiles SET updated_at=? WHERE profile_key=?", (int(time.time()), key))
        conn.commit()
        return int(result.rowcount or 0)
