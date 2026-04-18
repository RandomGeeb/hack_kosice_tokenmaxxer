#!/usr/bin/env python3
"""
Setup script for the tokenmaxxer Claude Code plugin.

Installs Python dependencies and writes hook configuration to
.claude/settings.json (or .claude/settings.local.json).
"""

import json
import os
import subprocess
import sys
from pathlib import Path


HOOKS_CONFIG = {
    "UserPromptSubmit": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 {Path(__file__).parent}/hooks/user_prompt_submit.py",
                    "timeout": 5,
                }
            ]
        }
    ],
    "PostToolUse": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 {Path(__file__).parent}/hooks/post_tool_use.py",
                    "timeout": 5,
                }
            ]
        }
    ],
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 {Path(__file__).parent}/hooks/stop.py",
                    "timeout": 30,
                }
            ]
        }
    ],
}


def install_dependencies():
    print("Installing Python dependencies...")
    req_file = Path(__file__).parent / "requirements.txt"

    # Try plain pip first, then --user (works on macOS managed environments)
    for extra_flags in [[], ["--user"], ["--break-system-packages"]]:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)] + extra_flags,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("  OK")
            return

    # Fall back to uv if available
    uv = subprocess.run(["which", "uv"], capture_output=True, text=True)
    if uv.returncode == 0:
        result = subprocess.run(
            ["uv", "pip", "install", "-r", str(req_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("  OK (via uv)")
            return

    print(
        "  Warning: could not auto-install dependencies.\n"
        f"  Run manually: pip3 install -r {req_file}"
    )


def merge_hooks(existing: dict, new_hooks: dict) -> dict:
    """Merge new hook entries into existing config without overwriting unrelated settings."""
    hooks = existing.get("hooks", {})
    for event, entries in new_hooks.items():
        existing_entries = hooks.get(event, [])
        # Remove any stale tokenmaxxer entries (identified by command path containing 'tokenmaxxer')
        existing_entries = [
            e for e in existing_entries
            if not any("tokenmaxxer" in h.get("command", "") for h in e.get("hooks", []))
        ]
        hooks[event] = existing_entries + entries
    existing["hooks"] = hooks
    return existing


def write_hooks(settings_path: Path):
    existing = {}
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    merged = merge_hooks(existing, HOOKS_CONFIG)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"  Hooks written to {settings_path}")


def check_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        print(f"  ANTHROPIC_API_KEY detected ({key[:8]}...)")
    else:
        print(
            "  Warning: ANTHROPIC_API_KEY not set.\n"
            "  Token counts will use character-based estimates.\n"
            "  For exact counts, add ANTHROPIC_API_KEY to your environment."
        )


def demo_output(cwd: str):
    print("\nRunning a quick demo (estimates only)...\n")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "tokenmaxxer" / "cli.py"), "--no-api", "--cwd", cwd],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0 and result.stderr:
        print(f"Demo failed: {result.stderr}")


def main():
    print("=== tokenmaxxer setup ===\n")

    # 1. Install deps
    install_dependencies()
    print()

    # 2. Check API key
    print("Checking ANTHROPIC_API_KEY...")
    check_api_key()
    print()

    # 3. Write hook config
    print("Configuring Claude Code hooks...")
    cwd = os.getcwd()
    # Use settings.local.json so it doesn't get committed
    settings_path = Path(cwd) / ".claude" / "settings.local.json"
    write_hooks(settings_path)
    print()

    # 4. Demo
    demo_output(cwd)

    print("\n=== Setup complete ===")
    print("Type  /tokenmaxxer  in Claude Code to view your token breakdown.")


if __name__ == "__main__":
    main()
