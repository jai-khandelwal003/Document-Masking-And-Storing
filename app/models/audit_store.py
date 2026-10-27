import logging
import os
import sqlite3
import time
from typing import Dict, List

from flask import current_app, has_app_context


_AUDIT_LOGGER = logging.getLogger("sdm.audit")
_AUDIT_LOGGER.setLevel(logging.INFO)


def _db_path() -> str:
    configured = ""
    if has_app_context():
        configured = str(current_app.config.get("ACCESS_STATE_DB_PATH", "") or "").strip()
    if configured:
        return configured
    return os.path.join("output", "access_state.sqlite3")


def _log_path() -> str:
    configured = ""
    if has_app_context():
        configured = str(current_app.config.get("AUDIT_LOG_PATH", "") or "").strip()
    if configured:
        return configured
    return os.path.join("output", "audit.log")


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
            CREATE TABLE IF NOT EXISTS audit_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                user TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                job_id TEXT NOT NULL,
                mask_mode TEXT NOT NULL,
                regions_masked INTEGER NOT NULL
            )
            """
        )
        conn.commit()

    log_path = _log_path()
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(log_path) for h in _AUDIT_LOGGER.handlers):
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        _AUDIT_LOGGER.addHandler(file_handler)


def log_mask_job(user: str, doc_type: str, job_id: str, mask_mode: str, regions_masked: int) -> None:
    now = int(time.time())
    safe_user = str(user or "anonymous").strip() or "anonymous"
    safe_doc_type = str(doc_type or "aadhaar").strip().lower() or "aadhaar"
    safe_job_id = str(job_id or "").strip()
    safe_mask_mode = str(mask_mode or "unknown").strip().lower() or "unknown"
    safe_regions = max(0, int(regions_masked or 0))

    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_entries(timestamp, user, doc_type, job_id, mask_mode, regions_masked)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now, safe_user, safe_doc_type, safe_job_id, safe_mask_mode, safe_regions),
        )
        conn.commit()

    _AUDIT_LOGGER.info(
        "user=%s doc_type=%s job_id=%s mask_mode=%s regions_masked=%s",
        safe_user,
        safe_doc_type,
        safe_job_id,
        safe_mask_mode,
        safe_regions,
    )


def get_recent_entries(limit: int = 20) -> List[Dict]:
    safe_limit = max(1, min(200, int(limit or 20)))
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT timestamp, user, doc_type, job_id, mask_mode, regions_masked
            FROM audit_entries
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    return [
        {
            "timestamp": int(row["timestamp"] or 0),
            "user": str(row["user"] or "anonymous"),
            "docType": str(row["doc_type"] or ""),
            "jobId": str(row["job_id"] or ""),
            "maskMode": str(row["mask_mode"] or ""),
            "regionsMasked": int(row["regions_masked"] or 0),
        }
        for row in rows
    ]
