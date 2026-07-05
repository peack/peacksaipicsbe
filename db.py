import sqlite3
from pathlib import Path

from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(__file__).resolve().parent / "models" / "schema.sql"
    with get_conn() as conn:
        conn.executescript(schema.read_text())
        conn.execute("DELETE FROM generation_meta_fts")
        conn.execute(
            "INSERT INTO generation_meta_fts(item_id, prompt, negative_prompt) "
            "SELECT item_id, prompt, negative_prompt FROM generation_meta"
        )
        conn.commit()