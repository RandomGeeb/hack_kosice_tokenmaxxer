#!/usr/bin/env python3
"""
tokenmaxxer CLI — reads current session token breakdown from DB.
Used by VS Code / IntelliJ extensions (--json) and terminal (/tokenmaxxer skill).
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.db import init_db, get_active_session, get_all_sessions
from tokenmaxxer.analyzer import count_file
from tokenmaxxer.visualizer import render, CONTEXT_WINDOW


def _build_skill_groups() -> list:
    global_commands = Path.home() / ".claude" / "commands"
    if not global_commands.is_dir():
        return []
    groups: dict[str, list] = {}
    for f in sorted(global_commands.glob("**/*.md")):
        if not f.is_file():
            continue
        name   = f.stem
        prefix = name.split(":")[0] if ":" in name else "other"
        groups.setdefault(prefix, []).append({"name": name, "tokens": count_file(f)})
    result = []
    for prefix, skills in sorted(groups.items(), key=lambda x: sum(s["tokens"] for s in x[1]), reverse=True):
        skills.sort(key=lambda s: s["tokens"], reverse=True)
        result.append({"prefix": prefix, "total": sum(s["tokens"] for s in skills), "skills": skills})
    return result


def main():
    parser = argparse.ArgumentParser(description="Show Claude Code token usage breakdown")
    parser.add_argument("--cwd",           default=os.getcwd(), help="Project root directory")
    parser.add_argument("--no-api",        action="store_true",  help="Skip API calls (always true — DB-based)")
    parser.add_argument("--json",          action="store_true",  dest="json_out", help="Output JSON for extensions")
    parser.add_argument("--list-sessions", action="store_true",  dest="list_sessions", help="Output all sessions as JSON array")
    parser.add_argument("--session",       default=None,         help="Session ID to fetch (overrides active session lookup)")
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    init_db(cwd)

    if args.list_sessions:
        rows = get_all_sessions(cwd)
        result = []
        for row in rows:
            r = dict(row)
            result.append({
                "session_id": r.get("session_id", ""),
                "started_at": r.get("started_at") or "",
                "last_active": r.get("last_active") or "",
                "is_active": bool(r.get("is_active", 0)),
                "has_data": bool(r.get("components_json")),
            })
        print(json.dumps(result))
        return

    if args.session:
        rows = get_all_sessions(cwd)
        session = None
        for row in rows:
            r = dict(row)
            if r.get("session_id") == args.session:
                session = r
                break
    else:
        session = get_active_session(cwd, cwd)

    if args.json_out:
        if not session or not session.get("components_json"):
            print(json.dumps({"error": "No active session"}))
            return

        components: dict = json.loads(session["components_json"])
        total = sum(components.values())
        pct   = round(total / CONTEXT_WINDOW * 100, 1)

        print(json.dumps({
            "pct_of_context": pct,
            "total":          total,
            "context_window": CONTEXT_WINDOW,
            "using_estimates": True,
            "components": [
                {"label": k, "tokens": v, "pct": round(v / total * 100, 1) if total else 0}
                for k, v in components.items()
            ],
            "skill_groups": _build_skill_groups(),
        }))
    else:
        if not session or not session.get("components_json"):
            print("No active session — start a Claude Code session to see token usage.")
            sys.exit(0)
        components = json.loads(session["components_json"])
        print(render(components, using_estimates=True))


if __name__ == "__main__":
    main()
