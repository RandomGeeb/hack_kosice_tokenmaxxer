#!/usr/bin/env python3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.db import add_tool_tokens, get_tool_tokens, update_session_snapshot
from tokenmaxxer.analyzer import analyze, write_token_summary, with_remainder


def _extract_text(tool_response) -> str:
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, list):
        return " ".join(_extract_text(i) for i in tool_response)
    if isinstance(tool_response, dict):
        return " ".join(str(v) for v in tool_response.values())
    return str(tool_response)


def main():
    try:
        data = json.load(sys.stdin)
        session_id = data.get("session_id", "")
        cwd = data.get("cwd", os.getcwd())
        tool_response = data.get("tool_response", data.get("output", ""))

        if not session_id:
            return

        estimated_tokens = max(0, len(_extract_text(tool_response)) // 4)
        add_tool_tokens(session_id, estimated_tokens, cwd)

        tool_tokens = get_tool_tokens(session_id, cwd)
        state = {
            "session_id": session_id,
            "transcript_path": None,
            "last_user_message": "",
            "last_user_message_tokens": 0,
            "tool_calls": [],
            "tool_output_tokens": tool_tokens,
        }
        components, _, actual_total, transcript_breakdown = analyze(cwd, state, use_api=True)
        components_full = with_remainder(components, actual_total)
        update_session_snapshot(session_id, components_full, cwd)
        write_token_summary(cwd, session_id, components, actual_total, transcript_breakdown)
    except Exception:
        pass


if __name__ == "__main__":
    main()
