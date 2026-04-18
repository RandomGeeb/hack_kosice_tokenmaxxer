#!/usr/bin/env python3
"""
tokenmaxxer CLI — show token breakdown for the current Claude Code session.

Usage:
    python3 tokenmaxxer/cli.py [--cwd PATH] [--no-api]
"""

import argparse
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenmaxxer.session_state import load_state
from tokenmaxxer.analyzer import analyze
from tokenmaxxer.visualizer import render
from tokenmaxxer.db import init_db


def main():
    parser = argparse.ArgumentParser(description="Show Claude Code token usage breakdown")
    parser.add_argument("--cwd", default=os.getcwd(), help="Project root directory")
    parser.add_argument("--no-api", action="store_true", help="Skip Anthropic API calls (use estimates)")
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    use_api = not args.no_api and bool(os.environ.get("ANTHROPIC_API_KEY"))

    init_db()

    state = load_state(cwd)
    components, _ = analyze(cwd, state, use_api=use_api)

    if not components:
        print("No context components found. Make sure you're running from the project root.")
        sys.exit(1)

    output = render(components, using_estimates=not use_api)
    print(output)


if __name__ == "__main__":
    main()
