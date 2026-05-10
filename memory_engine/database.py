"""SQLite storage for the local memory engine."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


DEFAULT_DB_PATH = Path("data") / "jarvis_memory.db"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def open_db(db_path: str | Path = DEFAULT_DB_PATH):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    path = Path(db_path)
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)

    with open_db(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_type TEXT NOT NULL,
                scope TEXT NOT NULL,
                project TEXT,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                importance INTEGER NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_scope
                ON memories(scope);
            CREATE INDEX IF NOT EXISTS idx_memories_type_status
                ON memories(memory_type, status);
            CREATE INDEX IF NOT EXISTS idx_memories_project
                ON memories(project);

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                source TEXT NOT NULL,
                related_memory_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (related_memory_id) REFERENCES memories(id)
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER,
                summary TEXT NOT NULL,
                rationale TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id)
            );

            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER,
                mistake TEXT NOT NULL,
                correction TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id)
            );

            CREATE TABLE IF NOT EXISTS procedures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER,
                name TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (memory_id) REFERENCES memories(id)
            );
            """
        )
        conn.commit()
    return path
