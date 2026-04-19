#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.db import (
    init_db, get_tool_tokens, update_session_snapshot,
    update_session_meta, replace_context_files, write_turn,
)
from tokenmaxxer.analyzer import analyze, write_token_summary


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
            "session_id":               session_id,
            "transcript_path":          transcript_path,
            "last_user_message":        "",
            "last_user_message_tokens": 0,
            "tool_calls":               [],
            "tool_output_tokens":       tool_tokens,
        }
        components, skill_groups = analyze(cwd, state, use_api=True)
        update_session_snapshot(session_id, components, cwd)
        replace_context_files(session_id, components, skill_groups, cwd)
        write_turn(session_id, sum(components.values()), cwd)
        write_token_summary(cwd, session_id, components)

        if transcript_path:
            started_at, last_active, model = _get_session_meta(transcript_path)
            update_session_meta(session_id, model, started_at, last_active, cwd)
    except Exception:
        pass


if __name__ == "__main__":
    main()