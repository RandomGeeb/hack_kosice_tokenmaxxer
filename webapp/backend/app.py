"""
tokenmaxxer history web app
Run: python app.py
Then open: http://localhost:5000
"""
import os
import sqlite3
import json


from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, g
import random

app = Flask(__name__)

# ── DB path: looks for .claude/tokenmaxxer.db relative to cwd ──────────────
DB_PATH = Path(os.environ.get("TOKENMAXXER_DB", ".claude/tokenmaxxer.db"))


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
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
    db.commit()
    return db


def seed_db(db):
    """Insert realistic fake sessions so the UI has data to show."""
    existing = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    if existing > 0:
        return  # already seeded

    projects = [
        ("/home/dev/auth-service", "auth-service"),
        ("/home/dev/dashboard-ui", "dashboard-ui"),
        ("/home/dev/api-gateway", "api-gateway"),
    ]
    models = ["claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"]
    wasteful = [
        ("package-lock.json", "Lockfile — rarely useful in context"),
        ("dist/bundle.js", "Built output — add dist/ to .claudeignore"),
        ("yarn.lock", "Lockfile — rarely useful in context"),
    ]
    file_pool = [
        "src/auth/index.ts", "src/database/schema.ts", "src/api/routes.ts",
        "src/components/Dashboard.tsx", "src/utils/helpers.ts",
        "src/models/user.ts", "src/services/email.ts", "src/config/env.ts",
        "tests/auth.test.ts", "README.md",
    ]

    now = datetime.now()
    for i in range(8):
        sid = f"session_{i:04d}"
        path, name = random.choice(projects)
        started = now - timedelta(days=random.randint(0, 14), hours=random.randint(0, 8))
        last = started + timedelta(minutes=random.randint(15, 120))
        model = random.choice(models)

        db.execute(
            "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?)",
            (sid, path, started.isoformat(), last.isoformat(), model)
        )

        num_turns = random.randint(4, 18)
        for t in range(num_turns):
            inp = random.randint(800, 12000)
            out = random.randint(200, 2000)
            cr  = random.randint(0, inp)
            cw  = random.randint(0, 500)
            ts  = (started + timedelta(minutes=t * 3)).isoformat()
            cursor = db.execute(
                "INSERT INTO turns (session_id,turn_index,role,total_tokens,input_tokens,output_tokens,cache_read,cache_write,timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, t, "user" if t % 2 == 0 else "assistant", inp + out, inp, out, cr, cw, ts)
            )
            turn_id = cursor.lastrowid

            # Add 3-7 files per turn
            chosen_files = random.sample(file_pool, random.randint(3, 7))
            for fp in chosen_files:
                tokens = random.randint(80, 2400)
                includes = random.randint(1, 5)
                db.execute(
                    "INSERT INTO context_files (session_id,turn_id,file_path,tokens,include_count,is_wasteful,waste_reason) VALUES (?,?,?,?,?,?,?)",
                    (sid, turn_id, fp, tokens, includes, 0, None)
                )

            # Occasionally add a wasteful file
            if random.random() < 0.4:
                wf, wr = random.choice(wasteful)
                db.execute(
                    "INSERT INTO context_files (session_id,turn_id,file_path,tokens,include_count,is_wasteful,waste_reason) VALUES (?,?,?,?,?,?,?)",
                    (sid, turn_id, wf, random.randint(1500, 6000), random.randint(2, 8), 1, wr)
                )

    db.commit()
    print(f"[tokenmaxxer] Seeded DB with 8 demo sessions at {DB_PATH}")


# ── API routes ───────────────────────────────────────────────────────────────

@app.route("/api/sessions")
def api_sessions():
    db = get_db()
    rows = db.execute("""
                      SELECT s.*,
                             COALESCE(SUM(t.input_tokens + t.output_tokens), 0) as total_tokens,
                             COALESCE(SUM(t.input_tokens), 0)  as total_input,
                             COALESCE(SUM(t.output_tokens), 0) as total_output,
                             COALESCE(SUM(t.cache_read), 0)    as total_cache_read,
                             COUNT(DISTINCT t.id)               as turn_count
                      FROM sessions s
                               LEFT JOIN turns t ON s.session_id = t.session_id
                      GROUP BY s.session_id
                      ORDER BY s.last_active DESC
                      """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sessions/<session_id>")
def api_session_detail(session_id):
    db = get_db()
    session = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not session:
        return jsonify({"error": "not found"}), 404

    turns = db.execute(
        "SELECT * FROM turns WHERE session_id=? ORDER BY turn_index",
        (session_id,)
    ).fetchall()

    top_files = db.execute("""
                           SELECT file_path,
                                  SUM(tokens)        as total_tokens,
                                  SUM(include_count) as total_includes,
                                  MAX(is_wasteful)   as is_wasteful,
                                  waste_reason
                           FROM context_files
                           WHERE session_id=?
                           GROUP BY file_path
                           ORDER BY total_tokens DESC
                               LIMIT 15
                           """, (session_id,)).fetchall()

    wasteful_count = db.execute(
        "SELECT COUNT(DISTINCT file_path) FROM context_files WHERE session_id=? AND is_wasteful=1",
        (session_id,)
    ).fetchone()[0]

    return jsonify({
        "session": dict(session),
        "turns": [dict(t) for t in turns],
        "top_files": [dict(f) for f in top_files],
        "wasteful_count": wasteful_count,
    })


@app.route("/api/stats")
def api_stats():
    db = get_db()
    totals = db.execute("""
                        SELECT COUNT(DISTINCT s.session_id)             as session_count,
                               COALESCE(SUM(t.input_tokens+t.output_tokens),0) as total_tokens,
                               COUNT(DISTINCT t.id)                     as total_turns
                        FROM sessions s
                                 LEFT JOIN turns t ON s.session_id=t.session_id
                        """).fetchone()
    waste = db.execute(
        "SELECT COUNT(DISTINCT file_path) FROM context_files WHERE is_wasteful=1"
    ).fetchone()[0]
    return jsonify({**dict(totals), "wasteful_files": waste})


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    db = init_db()
    seed_db(db)
    db.close()
    app.run(debug=True, port=5000)