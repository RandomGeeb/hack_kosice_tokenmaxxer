"""Core token analysis: discover context components and measure their token counts."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


# ── API client ──────────────────────────────────────────────────────────────

def _load_api_client(cwd: str):
    """Return an Anthropic client using the key from config or env, or None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        config_path = Path(cwd) / ".claude" / "tokenmaxxer_config.json"
        try:
            api_key = json.loads(config_path.read_text()).get("api_key", "")
        except Exception:
            pass
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


# ── Local token counting (plain text / static files) ───────────────────────

def count_text(text: str) -> int:
    """Estimate token count for plain text. ~4 chars per token for markdown."""
    if not text.strip():
        return 0
    return max(1, len(text) // 4)


def count_file(path: str | Path) -> int:
    try:
        return count_text(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return 0


def count_directory(dirpath: str | Path, glob: str = "**/*.md") -> int:
    total = 0
    p = Path(dirpath)
    if not p.is_dir():
        return 0
    for f in p.glob(glob):
        if f.is_file():
            total += count_file(f)
    return total


# ── Transcript parsing ──────────────────────────────────────────────────────

def parse_transcript_as_messages(transcript_path: str) -> tuple[list[dict], str]:
    """
    Parse transcript JSONL into a proper Anthropic messages array.

    Preserves all content blocks (text, tool_use, tool_result) rather than
    extracting plain text, so count_tokens gets accurate block-level overhead.

    Returns (messages, model).
    """
    messages: list[dict] = []
    model = "claude-sonnet-4-6"
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Extract model from any line that has it
            if obj.get("model"):
                model = obj["model"]
            msg = obj.get("message", obj)
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", "")
            if not content:
                continue
            messages.append({"role": role, "content": content})
    except OSError:
        pass
    return messages, model


# ── count_tokens API wrappers ───────────────────────────────────────────────

def count_tokens_api(client, model: str, messages: list[dict]) -> Optional[int]:
    """Call Anthropic count_tokens for a messages array. Returns None on failure."""
    if not client or not messages:
        return None
    try:
        response = client.messages.count_tokens(model=model, messages=messages)
        return response.input_tokens
    except Exception:
        return None


def count_tokens_per_category(client, model: str, messages: list[dict]) -> dict:
    """
    Count tokens per category by calling count_tokens on subsets.

    Returns {"tool_outputs": N, "tool_calls": N, "user_text": N, "assistant_text": N}.
    Any subset that fails returns 0.
    """
    tool_output_msgs: list[dict] = []
    tool_call_msgs: list[dict] = []
    user_text_msgs: list[dict] = []
    assistant_text_msgs: list[dict] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else []

        has_tool_result = any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks
        )
        has_tool_use = any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks
        )

        if has_tool_result:
            tool_output_msgs.append(msg)
        elif has_tool_use:
            tool_call_msgs.append(msg)
        elif role == "user":
            user_text_msgs.append(msg)
        else:
            assistant_text_msgs.append(msg)

    def _safe_count(subset):
        if not subset:
            return 0
        return count_tokens_api(client, model, subset) or 0

    return {
        "tool_outputs":   _safe_count(tool_output_msgs),
        "tool_calls":     _safe_count(tool_call_msgs),
        "user_text":      _safe_count(user_text_msgs),
        "assistant_text": _safe_count(assistant_text_msgs),
    }


# ── Memory & project path helpers ──────────────────────────────────────────

def _memory_dir(cwd: str) -> Path:
    home = Path.home()
    project_id = cwd.replace("/", "-")
    return home / ".claude" / "projects" / project_id / "memory"


def _find_transcript(cwd: str, session_id: Optional[str]) -> Optional[str]:
    home = Path.home()
    projects_root = home / ".claude" / "projects"
    candidates = {
        cwd.lstrip("/").replace("/", "-"),
        cwd.lstrip("/").replace("/", "-").replace("_", "-"),
    }
    for project_id in candidates:
        project_dir = projects_root / f"-{project_id}"
        if not project_dir.is_dir():
            project_dir = projects_root / project_id
        if not project_dir.is_dir():
            continue
        if session_id:
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return str(candidate)
        jsonl_files = sorted(
            project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if jsonl_files:
            return str(jsonl_files[0])
    return None


def read_actual_usage(transcript_path: str) -> Optional[dict]:
    """Fallback: read latest assistant message usage field from transcript."""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in reversed(lines):
            try:
                obj = json.loads(line)
                msg = obj.get("message", {})
                if msg.get("role") == "assistant" and "usage" in msg:
                    return msg["usage"]
            except Exception:
                continue
    except OSError:
        pass
    return None


# ── Main analyze function ───────────────────────────────────────────────────

CC_BASELINE_TOKENS = 2000


def analyze(cwd: str, state: dict, use_api: bool = True) -> tuple:
    """
    Measure token usage for each context component.

    Uses Anthropic count_tokens API for the conversation portion when an API
    key is available in config or environment. Falls back to reading the usage
    field from the transcript if the API is unavailable.

    Returns (components, skill_groups, actual_total, transcript_breakdown).
    """
    components: dict[str, int] = {}

    # 1. Static components — local tokenizer is identical to API for plain text
    components["CC Baseline"] = CC_BASELINE_TOKENS

    claude_md = Path(cwd) / "CLAUDE.md"
    if claude_md.exists():
        components["CLAUDE.md"] = count_file(claude_md)

    memory_dir = _memory_dir(cwd)
    mem_tokens = count_directory(memory_dir, "**/*.md")
    if mem_tokens > 0:
        components["Memory Files"] = mem_tokens

    commands_dir = Path(cwd) / ".claude" / "commands"
    skill_tokens = count_directory(commands_dir, "**/*.md")
    if skill_tokens > 0:
        components["Skills/Commands"] = skill_tokens

    global_commands = Path.home() / ".claude" / "commands"
    skill_groups: list[dict] = []
    if global_commands.is_dir():
        _groups: dict[str, list[dict]] = {}
        for f in sorted(global_commands.glob("**/*.md")):
            if not f.is_file():
                continue
            name = f.stem
            prefix = name.split(":")[0] if ":" in name else "other"
            tokens = count_file(f)
            _groups.setdefault(prefix, []).append({"name": name, "tokens": tokens})
        for prefix, skills in sorted(
            _groups.items(),
            key=lambda x: sum(s["tokens"] for s in x[1]),
            reverse=True,
        ):
            skills.sort(key=lambda s: s["tokens"], reverse=True)
            skill_groups.append({
                "prefix": prefix,
                "total": sum(s["tokens"] for s in skills),
                "skills": skills,
            })
    global_skill_tokens = sum(g["total"] for g in skill_groups)
    if global_skill_tokens > 0:
        components["Global Skills"] = global_skill_tokens

    # 2. Conversation portion — use count_tokens API when available
    transcript_path = state.get("transcript_path") or _find_transcript(cwd, state.get("session_id"))
    actual_total: Optional[int] = None
    transcript_breakdown: dict = {}

    if transcript_path and Path(transcript_path).exists():
        messages, model = parse_transcript_as_messages(transcript_path)
        client = _load_api_client(cwd) if use_api else None

        if client and messages:
            conversation_tokens = count_tokens_api(client, model, messages)
            if conversation_tokens is not None:
                actual_total = sum(components.values()) + conversation_tokens
                transcript_breakdown = count_tokens_per_category(client, model, messages)

        # Fallback to usage field if API unavailable or failed
        if actual_total is None:
            usage = read_actual_usage(transcript_path)
            if usage:
                actual_total = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )

    return components, skill_groups, actual_total, transcript_breakdown


# ── Formatting & writing ────────────────────────────────────────────────────

def format_summary(
    session_id: str,
    components: dict,
    actual_total: Optional[int] = None,
    transcript_breakdown: Optional[dict] = None,
) -> str:
    from datetime import datetime, timezone

    display_components = {k: v for k, v in components.items() if k != "Conversation + Tools"}
    known_static = sum(display_components.values())
    total = actual_total or known_static
    tb = transcript_breakdown or {}
    tool_outputs = tb.get("tool_outputs", 0)
    tool_calls = tb.get("tool_calls", 0)
    all_labels = list(display_components.keys()) + ["Tool Outputs", "Tool Calls", "Messages"]
    width = max((len(k) for k in all_labels), default=20) + 2
    source = "API" if actual_total else "est"
    lines = [
        f"Active session: {session_id[:16]}...",
        f"Last updated:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
    ]
    for label, tokens in display_components.items():
        lines.append(f"  {label:<{width}} {tokens:>8,}")
    if actual_total:
        remainder = actual_total - known_static
        if remainder > 0:
            if tool_outputs > 0 or tool_calls > 0:
                local_total = (
                    tool_outputs + tool_calls
                    + tb.get("user_text", 0) + tb.get("assistant_text", 0)
                )
                if local_total > 0:
                    scaled_outputs = int(remainder * tool_outputs / local_total)
                    scaled_calls = int(remainder * tool_calls / local_total)
                    scaled_messages = remainder - scaled_outputs - scaled_calls
                    if scaled_outputs > 0:
                        lines.append(f"  {'Tool Outputs':<{width}} {scaled_outputs:>8,}")
                    if scaled_calls > 0:
                        lines.append(f"  {'Tool Calls':<{width}} {scaled_calls:>8,}")
                    if scaled_messages > 0:
                        lines.append(f"  {'Messages':<{width}} {scaled_messages:>8,}")
                else:
                    lines.append(f"  {'Conversation + Tools':<{width}} {remainder:>8,}")
            else:
                lines.append(f"  {'Conversation + Tools':<{width}} {remainder:>8,}")
    lines.append(f"  {'─' * (width + 10)}")
    lines.append(f"  {'Total (' + source + ')':<{width}} {total:>8,}")
    lines.append("")
    return "\n".join(lines)


def with_remainder(components: dict, actual_total: Optional[int]) -> dict:
    """Return components dict with 'Conversation + Tools' remainder included."""
    result = dict(components)
    if actual_total:
        remainder = actual_total - sum(
            v for k, v in components.items() if k != "Conversation + Tools"
        )
        if remainder > 0:
            result["Conversation + Tools"] = remainder
    return result


def write_token_summary(
    cwd: str,
    session_id: str,
    components: dict,
    actual_total: Optional[int] = None,
    transcript_breakdown: Optional[dict] = None,
) -> None:
    summary_path = Path(cwd) / ".claude" / "token_summary.txt"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(format_summary(session_id, components, actual_total, transcript_breakdown))


def write_no_session_summary(cwd: str) -> None:
    summary_path = Path(cwd) / ".claude" / "token_summary.txt"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("No active session.\n")
