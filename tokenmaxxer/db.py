import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

_DEFAULT_DB = Path(__file__).parent.parent / ".claude" / "tokenmaxxer.db"


def get_conn(cwd: str = None):
    if cwd:
        db_path = Path(cwd) / ".claude" / "tokenmaxxer.db"
    else:
        db_path = Path(os.environ.get("TOKENMAXXER_DB", str(_DEFAULT_DB)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(cwd: str = None):
    with get_conn(cwd) as conn:
        conn.executescript("""
                           CREATE TABLE IF NOT EXISTS sessions (
                                                                   session_id         TEXT PRIMARY KEY,
                                                                   project_path       TEXT,
                                                                   started_at         TEXT,
                                                                   last_active        TEXT,
                                                                   model              TEXT,
                                                                   is_active          INTEGER DEFAULT 0,
                                                                   tool_output_tokens INTEGER DEFAULT 0,
                                                                   components_json    TEXT
                           );
                           CREATE TABLE IF NOT EXISTS context_files (
                                                                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                        session_id    TEXT REFERENCES sessions(session_id),
                               turn_id       INTEGER,
                               file_path     TEXT,
                               tokens        INTEGER,
                               include_count INTEGER,
                               is_wasteful   INTEGER DEFAULT 0,
                               waste_reason  TEXT,
                               group_name    TEXT
                               );
                           CREATE TABLE IF NOT EXISTS turns (
                               id           INTEGER PRIMARY KEY AUTOINCREMENT,
                               session_id   TEXT REFERENCES sessions(session_id),
                               turn_index   INTEGER,
                               total_tokens INTEGER,
                               timestamp    TEXT
                           );
                           """)
        # Migrate existing DBs that predate these columns
        for col, defn in [
            ("is_active",          "INTEGER DEFAULT 0"),
            ("tool_output_tokens", "INTEGER DEFAULT 0"),
            ("components_json",    "TEXT"),
            ("group_name",         "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass
        # Migrate context_files too
        try:
            conn.execute("ALTER TABLE context_files ADD COLUMN group_name TEXT")
        except sqlite3.OperationalError:
            pass


def save_session(session: dict, cwd: str = None):
    with get_conn(cwd) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO sessions
               (session_id, project_path, started_at, last_active, model, is_active, tool_output_tokens)
               VALUES (:session_id, :project_path, :started_at, :last_active, :model, 1, 0)""",
            session,
        )


def set_session_active(session_id: str, project_path: str, cwd: str = None):
    with get_conn(cwd) as conn:
        conn.execute(
            "UPDATE sessions SET is_active=0 WHERE project_path=? AND session_id!=?",
            (project_path, session_id),
        )
        conn.execute("UPDATE sessions SET is_active=1 WHERE session_id=?", (session_id,))


def add_tool_tokens(session_id: str, tokens: int, cwd: str = None):
    with get_conn(cwd) as conn:
        conn.execute(
            "UPDATE sessions SET tool_output_tokens = tool_output_tokens + ? WHERE session_id=?",
            (tokens, session_id),
        )


def get_tool_tokens(session_id: str, cwd: str = None) -> int:
    with get_conn(cwd) as conn:
        row = conn.execute(
            "SELECT tool_output_tokens FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return int(row["tool_output_tokens"]) if row else 0


def update_session_snapshot(session_id: str, components: dict, cwd: str = None):
    with get_conn(cwd) as conn:
        conn.execute(
            "UPDATE sessions SET components_json=?, last_active=datetime('now') WHERE session_id=?",
            (json.dumps(components), session_id),
        )


def update_session_meta(
        session_id: str, model: str, started_at: str, last_active: str, cwd: str = None
):
    with get_conn(cwd) as conn:
        if model:
            conn.execute(
                "UPDATE sessions SET model=? WHERE session_id=? AND (model IS NULL OR model='')",
                (model, session_id),
            )
        if started_at:
            conn.execute(
                "UPDATE sessions SET started_at=? WHERE session_id=? AND (started_at IS NULL OR started_at='')",
                (started_at, session_id),
            )
        if last_active:
            conn.execute(
                "UPDATE sessions SET last_active=? WHERE session_id=?",
                (last_active, session_id),
            )


def write_turn(session_id: str, total_tokens: int, cwd: str = None):
    with get_conn(cwd) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(turn_index), -1) FROM turns WHERE session_id=?",
            (session_id,),
        ).fetchone()
        next_index = (row[0] if row else -1) + 1
        conn.execute(
            "INSERT INTO turns (session_id, turn_index, total_tokens, timestamp) VALUES (?, ?, ?, datetime('now'))",
            (session_id, next_index, total_tokens),
        )


def deactivate_session(session_id: str, cwd: str = None):
    with get_conn(cwd) as conn:
        conn.execute("UPDATE sessions SET is_active=0 WHERE session_id=?", (session_id,))


def get_active_session(project_path: str, cwd: str = None) -> Optional[dict]:
    """Search for an active session, walking up the directory tree across DB files."""
    seen: set = set()
    p = Path(cwd or project_path).resolve()
    while True:
        db_path = p / ".claude" / "tokenmaxxer.db"
        key = str(db_path)
        if key not in seen and db_path.exists():
            seen.add(key)
            try:
                with sqlite3.connect(key) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT * FROM sessions WHERE project_path=? AND is_active=1 ORDER BY last_active DESC LIMIT 1",
                        (project_path,),
                    ).fetchone()
                    if row:
                        return dict(row)
                    row = conn.execute(
                        """SELECT * FROM sessions WHERE is_active=1
                                                    AND ? LIKE project_path || '/%'
                           ORDER BY length(project_path) DESC, last_active DESC LIMIT 1""",
                        (project_path,),
                    ).fetchone()
                    if row:
                        return dict(row)
            except Exception:
                pass
        parent = p.parent
        if parent == p:
            break
        p = parent
    return None


def replace_context_files(session_id: str, components: dict, skill_groups: list = None, cwd: str = None):
    with get_conn(cwd) as conn:
        conn.execute("DELETE FROM context_files WHERE session_id=?", (session_id,))
        # Top-level components
        for label, tokens in components.items():
            conn.execute(
                """INSERT INTO context_files
                   (session_id, turn_id, file_path, tokens, include_count, is_wasteful, waste_reason, group_name)
                   VALUES (?, NULL, ?, ?, 1, 0, NULL, NULL)""",
                (session_id, label, tokens),
            )
        # Individual skills under their group
        for group in (skill_groups or []):
            for skill in group["skills"]:
                conn.execute(
                    """INSERT INTO context_files
                       (session_id, turn_id, file_path, tokens, include_count, is_wasteful, waste_reason, group_name)
                       VALUES (?, NULL, ?, ?, 1, 0, NULL, ?)""",
                    (session_id, skill["name"], skill["tokens"], group["prefix"]),
                )


def get_all_sessions(cwd: str = None):
    with get_conn(cwd) as conn:
        return conn.execute(
            """SELECT s.*,
                      COALESCE(
                              (SELECT SUM(tokens) FROM context_files WHERE session_id=s.session_id AND group_name IS NULL),
                              0
                      ) as total_tokens
               FROM sessions s
               ORDER BY s.last_active DESC"""
        ).fetchall()


def get_top_burners(cwd: str = None):
    with get_conn(cwd) as conn:
        return conn.execute(
            """SELECT file_path                       AS label,
                      SUM(tokens)                     AS total_tokens,
                      COUNT(DISTINCT session_id)      AS session_count,
                      CAST(AVG(tokens) AS INTEGER)    AS avg_tokens
               FROM context_files
               WHERE group_name IS NULL
               GROUP BY file_path
               ORDER BY total_tokens DESC
                   LIMIT 20"""
        ).fetchall()


def get_session_components(session_id: str, cwd: str = None) -> list:
    with get_conn(cwd) as conn:
        return conn.execute(
            """SELECT file_path AS label, tokens
               FROM context_files
               WHERE session_id=? AND group_name IS NULL
               ORDER BY tokens DESC""",
            (session_id,),
        ).fetchall()