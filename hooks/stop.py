#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.db import (
    init_db, get_tool_tokens, update_session_snapshot,
    update_session_meta, replace_context_files,
)
from tokenmaxxer.analyzer import analyze


def _get_session_meta(transcript_path: str):
    started_at = last_active = model = ""
    try:
        lines = Path(transcript_path).read_text().strip().splitlines()
        if lines:
            first = json.loads(lines[0])
            last  = json.loads(lines[-1])
            started_at  = first.get("timestamp", "")
            last_active = last.get("timestamp", "")
            model       = first.get("model", "") or last.get("model", "")
    except Exception:
        pass
    return started_at, last_active, model


def main():
    try:
        data = json.load(sys.stdin)
        session_id      = data.get("session_id", "")
        transcript_path = data.get("transcript_path", "")
        cwd             = data.get("cwd", os.getcwd())

        if not session_id:
            return

        init_db(cwd)

        tool_tokens = get_tool_tokens(session_id, cwd)
        state = {
            "session_id":              session_id,
            "transcript_path":         transcript_path,
            "last_user_message":       "",
            "last_user_message_tokens": 0,
            "tool_calls":              [],
            "tool_output_tokens":      tool_tokens,
        }
        components, _ = analyze(cwd, state, use_api=False)
        update_session_snapshot(session_id, components, cwd)
        replace_context_files(session_id, components, cwd)

        if transcript_path:
            started_at, last_active, model = _get_session_meta(transcript_path)
            update_session_meta(session_id, model, started_at, last_active, cwd)

        # Keep token_summary.txt for the /tokenmaxxer skill command
        total = sum(components.values())
        pct   = total / 200_000 * 100
        biggest = max(components, key=components.get, default="")
        summary_path = Path(cwd) / ".claude" / "token_summary.txt"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            f"{total:,} / 200,000 tokens ({pct:.1f}%)"
            + (f" | biggest: {biggest} ({components[biggest]:,} tok)" if biggest else "")
            + "\nFor full breakdown: python app.py → http://localhost:5000\n"
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
