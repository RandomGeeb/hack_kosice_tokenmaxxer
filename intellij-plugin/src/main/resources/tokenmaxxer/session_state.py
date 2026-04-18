"""Thin shim kept for backwards-compatibility with any existing imports."""
# The hooks now write directly to the DB. This module is no longer the
# source of truth but is preserved so the /tokenmaxxer skill command still works.

import json
from pathlib import Path

STATE_FILENAME = "token_state.json"


def _state_path(cwd: str) -> Path:
    return Path(cwd) / ".claude" / STATE_FILENAME


def load_state(cwd: str = ".") -> dict:
    path = _state_path(cwd)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "session_id": None,
        "transcript_path": None,
        "last_user_message": "",
        "last_user_message_tokens": 0,
        "tool_calls": [],
        "tool_output_tokens": 0,
    }


def save_state(state: dict, cwd: str = ".") -> None:
    path = _state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
