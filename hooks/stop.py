#!/usr/bin/env python3
"""
Stop hook — captures transcript_path and triggers a background token re-count.
Reads JSON from stdin, updates .claude/token_state.json.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.session_state import load_state, save_state


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

        save_state(state, cwd)
    except Exception:
        pass  # Never interrupt the session


if __name__ == "__main__":
    main()
