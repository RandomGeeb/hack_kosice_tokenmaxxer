#!/usr/bin/env python3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.db import init_db, save_session, set_session_active, get_tool_tokens, update_session_snapshot
from tokenmaxxer.analyzer import analyze


def main():
    try:
        data = json.load(sys.stdin)
        session_id = data.get("session_id", "")
        cwd = data.get("cwd", os.getcwd())
        prompt = data.get("prompt", "")

        if not session_id:
            return

        init_db(cwd)
        save_session(
            {"session_id": session_id, "project_path": cwd,
             "started_at": "", "last_active": "", "model": ""},
            cwd,
        )
        set_session_active(session_id, cwd, cwd)

        # Quick static analysis — transcript not available yet at prompt time
        tool_tokens = get_tool_tokens(session_id, cwd)
        state = {
            "session_id": session_id,
            "transcript_path": None,
            "last_user_message": prompt,
            "last_user_message_tokens": max(1, len(prompt) // 4),
            "tool_calls": [],
            "tool_output_tokens": tool_tokens,
        }
        components, _ = analyze(cwd, state, use_api=False)
        update_session_snapshot(session_id, components, cwd)
    except Exception:
        pass


if __name__ == "__main__":
    main()
