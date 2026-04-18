#!/usr/bin/env python3
"""
Stop hook — captures transcript_path and triggers a background token re-count.
Reads JSON from stdin, updates .claude/token_state.json.
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ALL tokenmaxxer imports after the path fix
from tokenmaxxer.session_state import load_state, save_state
from tokenmaxxer.db import init_db, save_session, save_context_file
from tokenmaxxer.analyzer import analyze

def get_session_meta(transcript_path):
    """Extract started_at, last_active, and model from the transcript JSONL."""
    started_at = ""
    last_active = ""
    model = ""
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
        cwd = data.get("cwd", os.getcwd())
        session_id = data.get("session_id", "")
        transcript_path = data.get("transcript_path", "")

        state = load_state(cwd)
        if session_id:
            state["session_id"] = session_id
        if transcript_path:
            state["transcript_path"] = transcript_path

        # Recalculate user message tokens with API if available
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        last_user_message = state.get("last_user_message", "")
        if api_key and last_user_message:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                response = client.messages.count_tokens(
                    model="claude-opus-4-6",
                    messages=[{"role": "user", "content": last_user_message}],
                )
                state["last_user_message_tokens"] = response.input_tokens
            except Exception:
                pass

        # Save session snapshot to DB
        if session_id:
            try:
                started_at, last_active, model = get_session_meta(
                    state.get("transcript_path", "")
                )

                components, skill_groups = analyze(cwd, state)

                init_db()

                save_session({
                    "session_id":   session_id,
                    "project_path": cwd,
                    "started_at":   started_at,
                    "last_active":  last_active,
                    "model":        model,
                })

                for label, tokens in components.items():
                    save_context_file({
                        "session_id":    session_id,
                        "turn_id":       None,
                        "file_path":     label,
                        "tokens":        tokens,
                        "include_count": 1,
                        "is_wasteful":   0,
                        "waste_reason":  None,
                    })
            except Exception:
                pass  # Never interrupt the session

        save_state(state, cwd)
    except Exception:
        pass  # Never interrupt the session


if __name__ == "__main__":
    main()