"""Core token analysis: discover context components and measure their token counts."""

import json
import os
from pathlib import Path
from typing import Optional
from tokenmaxxer.db import save_session, save_turn, save_context_file

# ── Token counting ──────────────────────────────────────────────────────────

def _count_tokens_api(text: str, client) -> int:
    """Count tokens via Anthropic count_tokens endpoint."""
    if not text.strip():
        return 0
    response = client.messages.count_tokens(
        model="claude-opus-4-6",
        messages=[{"role": "user", "content": text}],
    )
    return response.input_tokens


def _count_tokens_estimate(text: str) -> int:
    """Rough estimate: ~4 chars per token."""
    return max(0, len(text) // 4)


def count_text(text: str, client=None) -> int:
    if not text.strip():
        return 0
    if client:
        try:
            return _count_tokens_api(text, client)
        except Exception:
            pass
    return _count_tokens_estimate(text)


def count_file(path: str | Path, client=None) -> int:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        return count_text(text, client)
    except OSError:
        return 0


def count_directory(dirpath: str | Path, glob: str = "**/*.md", client=None) -> int:
    total = 0
    p = Path(dirpath)
    if not p.is_dir():
        return 0
    for f in p.glob(glob):
        if f.is_file():
            total += count_file(f, client)
    return total


# ── Transcript parsing ──────────────────────────────────────────────────────

def _extract_text(content) -> str:
    """Recursively extract plain text from Anthropic message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_extract_text(item) for item in content)
    if isinstance(content, dict):
        kind = content.get("type", "")
        if kind in ("text",):
            return content.get("text", "")
        if kind == "tool_result":
            return _extract_text(content.get("content", ""))
        if kind == "tool_use":
            # Count the tool input JSON as text
            return json.dumps(content.get("input", {}))
        # Fallback: grab any string values
        return " ".join(str(v) for v in content.values() if isinstance(v, str))
    return str(content)


def parse_transcript(transcript_path: str) -> list[dict]:
    """Load a JSONL transcript and return a list of {role, text} dicts."""
    turns = []
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Handle different transcript wrapping formats
                msg = obj.get("message", obj)
                role = msg.get("role", obj.get("type", "unknown"))
                content = msg.get("content", "")
                text = _extract_text(content)
                if text.strip():
                    turns.append({"role": role, "text": text})
    except OSError:
        pass
    return turns


# ── Memory & project path helpers ──────────────────────────────────────────

def _memory_dir(cwd: str) -> Path:
    """Derive the Claude Code memory directory for the given project path."""
    home = Path.home()
    # Claude Code encodes project path as: replace / with - (drop leading /)
    project_id = cwd.replace("/", "-")
    return home / ".claude" / "projects" / project_id / "memory"


def _find_transcript(cwd: str, session_id: Optional[str]) -> Optional[str]:
    """Search for the transcript JSONL for this session."""
    home = Path.home()
    project_id = cwd.replace("/", "-")
    project_dir = home / ".claude" / "projects" / project_id

    if session_id:
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return str(candidate)

    # Fall back: pick the most recently modified .jsonl in the project dir
    if project_dir.is_dir():
        jsonl_files = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jsonl_files:
            return str(jsonl_files[0])

    return None


# ── Main analyze function ───────────────────────────────────────────────────

CC_BASELINE_TOKENS = 2000  # Estimated built-in Claude Code system overhead


def analyze(cwd: str, state: dict, use_api: bool = True) -> dict:
    """
    Measure token usage for each context component.
    Returns an ordered dict of {label: token_count}.
    """
    client = None
    if use_api:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                pass

    components: dict[str, int] = {}

    # 1. Claude Code built-in overhead (constant estimate)
    components["CC Baseline"] = CC_BASELINE_TOKENS

    # 2. CLAUDE.md
    claude_md = Path(cwd) / "CLAUDE.md"
    if claude_md.exists():
        components["CLAUDE.md"] = count_file(claude_md, client)

    # 3. Memory files
    memory_dir = _memory_dir(cwd)
    mem_tokens = count_directory(memory_dir, "**/*.md", client)
    if mem_tokens > 0:
        components["Memory Files"] = mem_tokens

    # 4. Custom skills / commands
    commands_dir = Path(cwd) / ".claude" / "commands"
    skill_tokens = count_directory(commands_dir, "**/*.md", client)
    if skill_tokens > 0:
        components["Skills/Commands"] = skill_tokens

    # Also check global skills
    global_commands = Path.home() / ".claude" / "commands"
    global_skill_tokens = count_directory(global_commands, "**/*.md", client)
    if global_skill_tokens > 0:
        components["Global Skills"] = global_skill_tokens

    # 5. Conversation history (from transcript)
    transcript_path = state.get("transcript_path") or _find_transcript(cwd, state.get("session_id"))
    history_tokens = 0
    if transcript_path and Path(transcript_path).exists():
        turns = parse_transcript(transcript_path)
        history_text = " ".join(t["text"] for t in turns)
        history_tokens = count_text(history_text, client)
    if history_tokens > 0:
        components["Conversation History"] = history_tokens

    # 6. Latest user message (from hook state)
    user_msg_tokens = state.get("last_user_message_tokens", 0)
    if not user_msg_tokens:
        # Re-count from saved text if available
        user_msg_text = state.get("last_user_message", "")
        user_msg_tokens = count_text(user_msg_text, client)
    if user_msg_tokens > 0:
        components["Current Message"] = user_msg_tokens

    # 7. Tool outputs accumulated this session
    tool_output_tokens = state.get("tool_output_tokens", 0)
    if tool_output_tokens > 0:
        components["Tool Outputs"] = tool_output_tokens

    return components
