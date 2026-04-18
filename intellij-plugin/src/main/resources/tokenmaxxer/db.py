# tokenmaxxer/db.py
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / ".claude" / "tokenmaxxer.db"

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets you access columns by name
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
                           CREATE TABLE IF NOT EXISTS sessions (
                                                                   session_id   TEXT PRIMARY KEY,
                                                                   project_path TEXT,
                                                                   started_at   TEXT,
                                                                   last_active  TEXT,
                                                                   model        TEXT
                           );

                           CREATE TABLE IF NOT EXISTS turns (
                                                                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                session_id      TEXT REFERENCES sessions(session_id),
                               turn_index      INTEGER,
                               role            TEXT,
                               total_tokens    INTEGER,
                               input_tokens    INTEGER,
                               output_tokens   INTEGER,
                               cache_read      INTEGER,
                               cache_write     INTEGER,
                               timestamp       TEXT
                               );

                           CREATE TABLE IF NOT EXISTS context_files (
                                                                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                        session_id    TEXT REFERENCES sessions(session_id),
                               turn_id       INTEGER REFERENCES turns(id),
                               file_path     TEXT,
                               tokens        INTEGER,
                               include_count INTEGER,
                               is_wasteful   INTEGER DEFAULT 0,
                               waste_reason  TEXT
                               );
                           """)

def save_session(session: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO sessions
            (session_id, project_path, started_at, last_active, model)
            VALUES (:session_id, :project_path, :started_at, :last_active, :model)
        """, session)

def save_turn(turn: dict):
    with get_conn() as conn:
        cursor = conn.execute("""
                              INSERT INTO turns
                              (session_id, turn_index, role, total_tokens, input_tokens,
                               output_tokens, cache_read, cache_write, timestamp)
                              VALUES (:session_id, :turn_index, :role, :total_tokens, :input_tokens,
                                      :output_tokens, :cache_read, :cache_write, :timestamp)
                              """, turn)
        return cursor.lastrowid  # returns the new turn's id

def save_context_file(file: dict):
    with get_conn() as conn:
        conn.execute("""
                     INSERT INTO context_files
                     (session_id, turn_id, file_path, tokens, include_count, is_wasteful, waste_reason)
                     VALUES (:session_id, :turn_id, :file_path, :tokens, :include_count, :is_wasteful, :waste_reason)
                     """, file)

def get_sessions():
    with get_conn() as conn:
        return conn.execute("""
                            SELECT s.*,
                                   SUM(t.total_tokens) as total_tokens,
                                   COUNT(DISTINCT t.id) as turn_count
                            FROM sessions s
                                     LEFT JOIN turns t ON s.session_id = t.session_id
                            GROUP BY s.session_id
                            ORDER BY s.last_active DESC
                            """).fetchall()

def get_top_files(session_id: str):
    with get_conn() as conn:
        return conn.execute("""
                            SELECT file_path,
                                   SUM(tokens) as total_tokens,
                                   SUM(include_count) as total_includes,
                                   MAX(is_wasteful) as is_wasteful,
                                   waste_reason
                            FROM context_files
                            WHERE session_id = ?
                            GROUP BY file_path
                            ORDER BY total_tokens DESC
                                LIMIT 20
                            """, (session_id,)).fetchall()