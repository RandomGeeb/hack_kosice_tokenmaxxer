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

        # /clear resets context window — wipe accumulated tool state too
        if prompt.strip() in ("/clear", "/clear\n"):
            state["tool_calls"] = []
            state["tool_output_tokens"] = 0
            state["last_user_message"] = ""
            state["last_user_message_tokens"] = 0
            save_state(state, cwd)
            return

        state["last_user_message"] = prompt
        # Rough estimate here; Stop hook will recalculate with API
        state["last_user_message_tokens"] = max(1, len(prompt) // 4)
        save_state(state, cwd)
        _write_summary(state, cwd)
    except Exception:
        pass  # Never interrupt the session


def _write_summary(state: dict, cwd: str) -> None:
    """Write a compact one-liner to .claude/token_summary.txt for low-overhead reads."""
    try:
        from tokenmaxxer.analyzer import analyze
        from tokenmaxxer.visualizer import CONTEXT_WINDOW
        components, _ = analyze(cwd, state, use_api=False)
        if not components:
            return
        total = sum(components.values())
        pct = total / CONTEXT_WINDOW * 100

        def fmt(label):
            v = components.get(label, 0)
            return f"{label}: {v / total * 100:.1f}%" if v else None

        parts = [p for p in [fmt("Global Skills"), fmt("Tool Outputs"), fmt("Conversation History")] if p]
        line = f"{total:,} / {CONTEXT_WINDOW:,} tokens ({pct:.1f}%)"
        if parts:
            line += " | " + " | ".join(parts)
        line += "\nFor per-skill detail, see the VS Code Token Breakdown panel."

        summary_path = os.path.join(cwd, ".claude", "token_summary.txt")
        with open(summary_path, "w") as f:
            f.write(line + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
