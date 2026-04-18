#!/usr/bin/env python3
"""
tokenmaxxer CLI — show token breakdown for the current Claude Code session.

Usage:
    python3 tokenmaxxer/cli.py [--cwd PATH] [--no-api] [--json]
"""

import argparse
import json
import os
import sys

# Support both bundled extension (package alongside cli.py) and repo invocation
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)               # bundled: tokenmaxxer/ sits next to cli.py
sys.path.insert(0, os.path.dirname(_here))  # repo: cli.py is inside tokenmaxxer/

from tokenmaxxer.session_state import load_state
from tokenmaxxer.analyzer import analyze
from tokenmaxxer.visualizer import render, CONTEXT_WINDOW


def main():
    parser = argparse.ArgumentParser(description="Show Claude Code token usage breakdown")
    parser.add_argument("--cwd", default=os.getcwd(), help="Project root directory")
    parser.add_argument("--no-api", action="store_true", help="Skip Anthropic API calls (use estimates)")
    parser.add_argument("--json", action="store_true", help="Output JSON for programmatic consumption")
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    use_api = not args.no_api and bool(os.environ.get("ANTHROPIC_API_KEY"))

    state = load_state(cwd)
    components, skill_groups = analyze(cwd, state, use_api=use_api)

    if not components:
        print("No context components found. Make sure you're running from the project root.")
        sys.exit(1)

    if args.json:
        total = sum(components.values())
        print(json.dumps({
            "components": [
                {"label": k, "tokens": v, "pct": round(v / total * 100, 2)}
                for k, v in components.items()
            ],
            "skill_groups": skill_groups,
            "total": total,
            "context_window": CONTEXT_WINDOW,
            "pct_of_context": round(total / CONTEXT_WINDOW * 100, 2),
            "using_estimates": not use_api,
        }))
        return

    output = render(components, using_estimates=not use_api)
    print(output)


if __name__ == "__main__":
    main()
