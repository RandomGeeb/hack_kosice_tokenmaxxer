#!/usr/bin/env python3
"""
UserPromptSubmit hook — captures the user's message for later token counting.
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
        prompt = data.get("prompt", "")
        session_id = data.get("session_id", "")
        cwd = data.get("cwd", os.getcwd())

        state = load_state(cwd)

        if session_id and state.get("session_id") != session_id:
            state["tool_calls"] = []
            state["tool_output_tokens"] = 0

        state["session_id"] = session_id
        state["last_user_message"] = prompt
        # Rough estimate here; Stop hook will recalculate with API
        state["last_user_message_tokens"] = max(1, len(prompt) // 4)
        save_state(state, cwd)
    except Exception:
        pass  # Never interrupt the session


if __name__ == "__main__":
    main()
