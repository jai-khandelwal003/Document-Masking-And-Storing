import os
import sqlite3

from flask import current_app, has_app_context


def _db_path() -> str:
    configured = ""
    if has_app_context():
        configured = str(current_app.config.get("ACCESS_STATE_DB_PATH", "") or "").strip()
    return configured or os.path.join("output", "access_state.sqlite3")


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS auth_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def get_password_hash() -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM auth_settings WHERE key = 'password_hash'").fetchone()
    return str(row[0]) if row else ""


def set_password_hash(password_hash: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_settings(key, value) VALUES ('password_hash', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (password_hash,),
        )
        conn.commit()
