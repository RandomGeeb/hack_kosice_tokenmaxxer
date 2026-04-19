"""
tokenmaxxer web app
Run: python app.py
Then open: http://localhost:5000
"""
import json
import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, render_template, g, request

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


def _period_filter(period, ts_col):
    modifiers = {"day": "-1 day", "week": "-7 days", "month": "-30 days"}
    if period in modifiers:
        return f"AND datetime({ts_col}) >= datetime('now', '{modifiers[period]}')"
    return ""


def _get_skill_groups(db, session_id):
    """Shared helper: fetch skill groups for a session from context_files."""
    skill_rows = db.execute(
        """SELECT group_name, file_path AS label, tokens
           FROM context_files
           WHERE session_id=? AND group_name IS NOT NULL
           ORDER BY group_name, tokens DESC""",
        (session_id,)
    ).fetchall()
    groups = {}
    for r in skill_rows:
        groups.setdefault(r["group_name"], []).append({
            "label":  r["label"],
            "tokens": r["tokens"],
        })
    return [
        {
            "group":  g,
            "total":  sum(s["tokens"] for s in skills),
            "skills": skills,
        }
        for g, skills in sorted(
            groups.items(),
            key=lambda x: sum(s["tokens"] for s in x[1]),
            reverse=True,
        )
    ]


@app.route("/api/current")
def api_current():
    db = get_db()
    row = db.execute(
        "SELECT * FROM sessions WHERE is_active=1 ORDER BY last_active DESC LIMIT 1"
    ).fetchone()
    if not row:
        return jsonify({"active": False})

    session    = dict(row)
    session_id = session["session_id"]

    # Top-level components
    component_rows = db.execute(
        """SELECT file_path AS label, tokens
           FROM context_files
           WHERE session_id=? AND group_name IS NULL
           ORDER BY tokens DESC""",
        (session_id,)
    ).fetchall()
    comp_total = sum(r["tokens"] for r in component_rows)
    components = [
        {
            "label":  r["label"],
            "tokens": r["tokens"],
            "pct":    round(r["tokens"] / comp_total * 100, 1) if comp_total else 0,
        }
        for r in component_rows
    ]

    # Skill groups
    skill_groups = _get_skill_groups(db, session_id)
    skill_total  = sum(g["total"] for g in skill_groups)
    grand_total  = comp_total + skill_total

    return jsonify({
        "active":         True,
        "session":        session,
        "components":     components,
        "skill_groups":   skill_groups,
        "total":          grand_total,
        "pct_of_context": round(grand_total / CONTEXT_WINDOW * 100, 1),
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

    component_rows = db.execute(
        """SELECT file_path AS label, tokens
           FROM context_files
           WHERE session_id=? AND group_name IS NULL
           ORDER BY tokens DESC""",
        (session_id,),
    ).fetchall()

    skill_groups = _get_skill_groups(db, session_id)

    return jsonify({
        "session":      dict(session),
        "components":   [dict(r) for r in component_rows],
        "skill_groups": skill_groups,
    })


@app.route("/api/burners")
def api_burners():
    db = get_db()
    period = request.args.get("period", "")
    period_clause = _period_filter(period, "s.last_active")
    rows = db.execute(
        f"""SELECT COALESCE(cf.group_name, cf.file_path)                          AS raw_key,
                  CASE WHEN cf.group_name = 'other' THEN 'Loaded Skills'
                       ELSE COALESCE(cf.group_name, cf.file_path) END             AS label,
                  CASE WHEN cf.group_name IS NOT NULL THEN 1 ELSE 0 END           AS is_group,
                  SUM(cf.tokens)                                                   AS total_tokens,
                  COUNT(DISTINCT cf.session_id)                                   AS session_count,
                  CAST(AVG(cf.tokens) AS INTEGER)                                 AS avg_tokens
           FROM context_files cf
           JOIN sessions s ON s.session_id = cf.session_id
           WHERE 1=1
             {period_clause}
           GROUP BY COALESCE(cf.group_name, cf.file_path)
           ORDER BY total_tokens DESC
           LIMIT 20"""
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/analytics")
def api_analytics():
    from datetime import datetime as dt
    db = get_db()
    period = request.args.get("period", "week")

    sess_clause  = _period_filter(period, "s.last_active")
    turns_clause = _period_filter(period, "t.timestamp")

    agg = db.execute(
        f"""SELECT COUNT(DISTINCT cf.session_id) AS session_count,
                   COALESCE(SUM(cf.tokens), 0)   AS total_tokens
            FROM context_files cf
            JOIN sessions s ON s.session_id = cf.session_id
            WHERE 1=1 {sess_clause}"""
    ).fetchone()

    peak_row = db.execute(
        f"""SELECT strftime('%H', t.timestamp) AS hour,
                   SUM(t.total_tokens)         AS tok_sum
            FROM turns t
            JOIN sessions s ON s.session_id = t.session_id
            WHERE t.total_tokens IS NOT NULL {turns_clause}
            GROUP BY hour ORDER BY tok_sum DESC LIMIT 1"""
    ).fetchone()
    peak_hour = int(peak_row["hour"]) if peak_row else None

    pressure_rows = db.execute(
        f"""SELECT MAX(t.total_tokens) AS peak_tok
            FROM turns t
            JOIN sessions s ON s.session_id = t.session_id
            WHERE t.total_tokens IS NOT NULL {turns_clause}
            GROUP BY t.session_id"""
    ).fetchall()
    avg_pressure = 0.0
    if pressure_rows:
        avg_pressure = round(
            sum(r["peak_tok"] / CONTEXT_WINDOW * 100 for r in pressure_rows) / len(pressure_rows), 1
        )

    bucket_expr = "strftime('%H', t.timestamp)" if period == "day" else "DATE(t.timestamp)"
    time_rows = db.execute(
        f"""SELECT bucket, SUM(peak_tok) AS tokens
            FROM (
                SELECT {bucket_expr} AS bucket, t.session_id,
                       MAX(t.total_tokens) AS peak_tok
                FROM turns t
                JOIN sessions s ON s.session_id = t.session_id
                WHERE t.total_tokens IS NOT NULL {turns_clause}
                GROUP BY {bucket_expr}, t.session_id
            ) sub
            GROUP BY bucket ORDER BY bucket ASC"""
    ).fetchall()

    def fmt_bucket(b):
        if period == "day":
            return b + "h"
        try:
            d = dt.strptime(b, "%Y-%m-%d")
            return f"{d.strftime('%b')} {d.day}"
        except Exception:
            return b

    return jsonify({
        "total_tokens":     agg["total_tokens"],
        "session_count":    agg["session_count"],
        "peak_hour":        peak_hour,
        "avg_pressure_pct": avg_pressure,
        "usage_over_time":  [{"label": fmt_bucket(r["bucket"]), "tokens": r["tokens"]} for r in time_rows],
    })


@app.route("/api/breakdown")
def api_breakdown():
    db = get_db()
    raw_key = request.args.get("raw_key", "")
    period  = request.args.get("period", "week")
    period_clause = _period_filter(period, "s.last_active")

    # If raw_key matches a group_name, return individual file_paths in that group
    group_rows = db.execute(
        f"""SELECT cf.file_path                    AS label,
                   SUM(cf.tokens)                  AS total_tokens,
                   COUNT(DISTINCT cf.session_id)   AS session_count,
                   CAST(AVG(cf.tokens) AS INTEGER) AS avg_tokens
            FROM context_files cf
            JOIN sessions s ON s.session_id = cf.session_id
            WHERE cf.group_name = ? {period_clause}
            GROUP BY cf.file_path
            ORDER BY total_tokens DESC
            LIMIT 30""",
        (raw_key,)
    ).fetchall()
    if group_rows:
        return jsonify({"type": "group", "items": [dict(r) for r in group_rows]})

    # Otherwise break down by session (per-project path)
    comp_rows = db.execute(
        f"""SELECT COALESCE(s.project_path, s.session_id) AS label,
                   cf.tokens                              AS total_tokens,
                   s.session_id,
                   s.last_active
            FROM context_files cf
            JOIN sessions s ON s.session_id = cf.session_id
            WHERE cf.file_path = ? AND cf.group_name IS NULL {period_clause}
            ORDER BY cf.tokens DESC
            LIMIT 15""",
        (raw_key,)
    ).fetchall()
    return jsonify({"type": "component", "items": [dict(r) for r in comp_rows]})


@app.route("/api/stats")
def api_stats():
    db = get_db()
    totals = db.execute(
        """SELECT COUNT(DISTINCT session_id)  AS session_count,
                  COALESCE(SUM(tokens), 0)    AS total_tokens
           FROM context_files
           WHERE group_name IS NULL"""
    ).fetchone()
    return jsonify(dict(totals))


@app.route("/api/pressure/<session_id>")
def api_pressure(session_id):
    db = get_db()
    rows = db.execute(
        """SELECT turn_index, total_tokens, timestamp
           FROM turns
           WHERE session_id=? AND total_tokens IS NOT NULL
           ORDER BY turn_index ASC""",
        (session_id,)
    ).fetchall()
    points = [
        {
            "turn":      r["turn_index"],
            "pct":       round(r["total_tokens"] / CONTEXT_WINDOW * 100, 1),
            "tokens":    r["total_tokens"],
            "timestamp": r["timestamp"],
        }
        for r in rows
    ]
    return jsonify(points)


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    app.run(debug=True, port=5001)