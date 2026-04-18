"""Render token breakdown as an ASCII bar chart (with rich color if available)."""

from typing import Optional

CONTEXT_WINDOW = 200_000  # claude-opus-4-6 context window
BAR_WIDTH = 20

# Component color palette (rich markup colors)
COLORS = [
    "cyan", "green", "yellow", "magenta", "blue", "red",
    "bright_cyan", "bright_green", "bright_yellow",
]

FILLED = "█"
EMPTY = "░"


def _bar(fraction: float, width: int = BAR_WIDTH) -> str:
    filled = round(fraction * width)
    return FILLED * filled + EMPTY * (width - filled)


def _pct(n: int, total: int) -> float:
    return (n / total * 100) if total else 0


def render_plain(components: dict[str, int], using_estimates: bool = False) -> str:
    """Plain ASCII output (no color)."""
    total = sum(components.values())
    lines = []
    lines.append("Token Breakdown — Current Session")
    lines.append("━" * 52)

    label_w = max((len(k) for k in components), default=10) + 2

    for label, tokens in components.items():
        pct = _pct(tokens, total)
        bar = _bar(pct / 100)
        lines.append(f"{label:<{label_w}} {bar}  {pct:5.1f}%  ({tokens:>6,} tok)")

    lines.append("━" * 52)
    pct_of_ctx = _pct(total, CONTEXT_WINDOW)
    lines.append(f"Total: {total:,} / {CONTEXT_WINDOW:,} tokens  ({pct_of_ctx:.1f}% of context window)")

    if using_estimates:
        lines.append("")
        lines.append("* Token counts are character-based estimates.")
        lines.append("  Set ANTHROPIC_API_KEY for exact counts.")

    return "\n".join(lines)


def render_rich(components: dict[str, int], using_estimates: bool = False) -> str:
    """Rich-formatted output with color bars."""
    from rich.console import Console
    from rich.table import Table
    from rich import box
    import io

    total = sum(components.values())
    buf = io.StringIO()
    console = Console(file=buf, highlight=False)

    table = Table(
        title="[bold]Token Breakdown — Current Session[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white",
        expand=False,
    )
    table.add_column("Component", style="bold", min_width=18)
    table.add_column("Usage", min_width=BAR_WIDTH + 2)
    table.add_column("Pct", justify="right", min_width=6)
    table.add_column("Tokens", justify="right", min_width=10)

    for i, (label, tokens) in enumerate(components.items()):
        color = COLORS[i % len(COLORS)]
        pct = _pct(tokens, total)
        filled = round(pct / 100 * BAR_WIDTH)
        bar = f"[{color}]{FILLED * filled}[/{color}]{EMPTY * (BAR_WIDTH - filled)}"
        table.add_row(label, bar, f"{pct:.1f}%", f"{tokens:,}")

    console.print(table)

    pct_of_ctx = _pct(total, CONTEXT_WINDOW)
    console.print(
        f"[bold]Total:[/bold] {total:,} / {CONTEXT_WINDOW:,} tokens  "
        f"([bold]{pct_of_ctx:.1f}%[/bold] of context window)"
    )
    if using_estimates:
        console.print(
            "\n[dim]* Counts are character-based estimates. "
            "Set ANTHROPIC_API_KEY for exact counts.[/dim]"
        )

    return buf.getvalue()


def render(components: dict[str, int], using_estimates: bool = False) -> str:
    """Render with rich if available, else plain ASCII."""
    try:
        import rich  # noqa: F401
        return render_rich(components, using_estimates)
    except ImportError:
        return render_plain(components, using_estimates)
