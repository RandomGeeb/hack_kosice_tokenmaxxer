#!/usr/bin/env python3
"""
PostToolUse hook — accumulates token estimates for tool outputs.
Reads JSON from stdin, updates .claude/token_state.json.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.session_state import load_state, save_state


def _extract_output_text(tool_response) -> str:
    """Extract string content from a tool response (may be str, list, or dict)."""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, list):
        return " ".join(_extract_output_text(item) for item in tool_response)
    if isinstance(tool_response, dict):
        return " ".join(str(v) for v in tool_response.values())
    return str(tool_response)


def main():
    try:
        data = json.load(sys.stdin)
        cwd = data.get("cwd", os.getcwd())
        tool_name = data.get("tool_name", "unknown")
        tool_response = data.get("tool_response", data.get("output", ""))

        output_text = _extract_output_text(tool_response)
        output_chars = len(output_text)
        estimated_tokens = max(0, output_chars // 4)

        state = load_state(cwd)

        # Accumulate tool calls list
        tool_calls = state.get("tool_calls", [])
        tool_calls.append({"name": tool_name, "output_chars": output_chars})
        state["tool_calls"] = tool_calls[-50:]  # keep last 50

        state["tool_output_tokens"] = state.get("tool_output_tokens", 0) + estimated_tokens
        save_state(state, cwd)
    except Exception:
        pass  # Never interrupt the session


if __name__ == "__main__":
    main()
