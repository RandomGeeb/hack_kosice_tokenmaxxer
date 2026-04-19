"""
tokenmaxxer web app
Run: python app.py
Then open: http://localhost:5000
"""
import json
import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, render_template, g

app = Flask(__name__)

DB_PATH = Path(os.environ.get("TOKENMAXXER_DB", ".claude/tokenmaxxer.db"))
CONTEXT_WINDOW = 200_000


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def _components_from_json(raw: str) -> tuple[dict, int]:
    try:
        c = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        c = {}
    return c, sum(c.values())


@app.route("/api/current")
def api_current():
    db = get_db()
    row = db.execute(
        "SELECT * FROM sessions WHERE is_active=1 ORDER BY last_active DESC LIMIT 1"
    ).fetchone()
    if not row:
        return jsonify({"active": False})

    session = dict(row)
    components, total = _components_from_json(session.get("components_json"))
    return jsonify({
        "active":         True,
        "session":        session,
        "components":     [
            {"label": k, "tokens": v, "pct": round(v / total * 100, 1) if total else 0}
            for k, v in components.items()
        ],
        "total":          total,
        "pct_of_context": round(total / CONTEXT_WINDOW * 100, 1),
        "context_window": CONTEXT_WINDOW,
    })


@app.route("/api/sessions")
def api_sessions():
    db = get_db()
    rows = db.execute(
        """SELECT s.*,
                  COALESCE(
                          (SELECT SUM(tokens) FROM context_files
                           WHERE session_id=s.session_id AND group_name IS NULL),
                          0
                  ) AS total_tokens
           FROM sessions s
           ORDER BY s.last_active DESC"""
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/sessions/<session_id>")
def api_session_detail(session_id):
    db = get_db()
    session = db.execute(
        "SELECT * FROM sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    if not session:
        return jsonify({"error": "not found"}), 404

    # Top-level components (CC Baseline, Memory Files, Global Skills, etc.)
    component_rows = db.execute(
        """SELECT file_path AS label, tokens
           FROM context_files
           WHERE session_id=? AND group_name IS NULL
           ORDER BY tokens DESC""",
        (session_id,),
    ).fetchall()

    # Individual skills stored under a group
    skill_rows = db.execute(
        """SELECT group_name, file_path AS label, tokens
           FROM context_files
           WHERE session_id=? AND group_name IS NOT NULL
           ORDER BY group_name, tokens DESC""",
        (session_id,),
    ).fetchall()

    # Assemble skill_groups: [{group, total, skills: [{label, tokens}]}]
    groups: dict[str, list] = {}
    for r in skill_rows:
        groups.setdefault(r["group_name"], []).append({
            "label":  r["label"],
            "tokens": r["tokens"],
        })
    skill_groups = [
        {
            "group":  g,
            "total":  sum(s["tokens"] for s in skills),
            "skills": skills,
        }
        for g, skills in sorted(groups.items(), key=lambda x: sum(s["tokens"] for s in x[1]), reverse=True)
    ]

    return jsonify({
        "session":      dict(session),
        "components":   [dict(r) for r in component_rows],
        "skill_groups": skill_groups,
    })


@app.route("/api/burners")
def api_burners():
    db = get_db()
    rows = db.execute(
        """SELECT file_path                    AS label,
                  SUM(tokens)                  AS total_tokens,
                  COUNT(DISTINCT session_id)   AS session_count,
                  CAST(AVG(tokens) AS INTEGER) AS avg_tokens
           FROM context_files
           WHERE group_name IS NULL
           GROUP BY file_path
           ORDER BY total_tokens DESC
               LIMIT 20"""
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
def api_stats():
    db = get_db()
    totals = db.execute(
        """SELECT COUNT(DISTINCT session_id)     AS session_count,
                  COALESCE(SUM(tokens), 0)        AS total_tokens
           FROM context_files
           WHERE group_name IS NULL"""
    ).fetchone()
    return jsonify(dict(totals))


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    app.run(debug=True, port=5000)