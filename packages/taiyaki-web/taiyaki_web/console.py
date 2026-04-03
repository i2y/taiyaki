"""Rich console helpers for the taiyaki CLI."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.tree import Tree

THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "method.GET": "bold green",
        "method.POST": "bold blue",
        "method.PUT": "bold yellow",
        "method.DELETE": "bold red",
        "method.PATCH": "bold magenta",
        "status.2xx": "green",
        "status.3xx": "yellow",
        "status.4xx": "red",
        "status.5xx": "bold red",
        "path": "cyan",
        "timing": "dim",
    }
)

console = Console(theme=THEME)
error_console = Console(stderr=True, theme=THEME)

# ── Banner ──

_LOGO_LINE1 = "  ╺┳╸┏━┓╻╻ ╻┏━┓╻┏╸╻"
_LOGO_LINE2 = "   ┃ ┣━┫┃┗┳┛┣━┫┣┻┓┃"
_LOGO_LINE3 = "   ╹ ╹ ╹╹ ╹ ╹ ╹╹ ╹╹"


def print_banner() -> None:
    logo = Text.assemble(
        (_LOGO_LINE1, "bold magenta"),
        "\n",
        (_LOGO_LINE2, "bold magenta"),
        "\n",
        (_LOGO_LINE3, "bold magenta"),
    )
    console.print()
    console.print(logo)
    console.print("  [dim]Preact SSR + htmx + Islands[/dim]")
    console.print()


# ── Server info ──


def print_server_info(host: str, port: int, dev_mode: bool = False) -> None:
    url = f"http://{host}:{port}"
    mode = (
        "[bold yellow]dev[/bold yellow]"
        if dev_mode
        else "[bold green]production[/bold green]"
    )
    console.print()
    console.print(f"  [bold]Server:[/bold]  [cyan underline]{url}[/cyan underline]")
    console.print(f"  [bold]Mode:[/bold]    {mode}")
    console.print()


# ── Route table ──

_METHOD_STYLES: dict[str, str] = {
    "GET": "method.GET",
    "POST": "method.POST",
    "PUT": "method.PUT",
    "DELETE": "method.DELETE",
    "PATCH": "method.PATCH",
}


def print_route_table(route_meta: list[dict[str, Any]]) -> None:
    if not route_meta:
        return
    table = Table(
        title="Routes",
        title_style="bold",
        border_style="dim",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Method", style="bold", width=8)
    table.add_column("Path", style="path")
    table.add_column("Component", style="dim")

    for meta in route_meta:
        method = meta.get("method", "?")
        style = _METHOD_STYLES.get(method, "bold")
        table.add_row(
            Text(method, style=style),
            meta.get("path", "?"),
            meta.get("component") or "-",
        )

    console.print(table)
    console.print()


# ── Project tree ──


def print_project_tree(name: str) -> None:
    tree = Tree(f"[bold]{name}/[/bold]", guide_style="dim")
    tree.add("[dim]pyproject.toml[/dim]")
    tree.add("[bold]app.py[/bold]")
    tree.add("[cyan]components/[/cyan]")
    tree.add("[cyan]islands/[/cyan]")
    tree.add("[cyan]static/[/cyan]")

    console.print()
    console.print(tree)
    console.print()
    console.print(f"  [dim]cd {name} && python -m dark run[/dim]")
    console.print()


# ── Messages ──


def print_success(msg: str) -> None:
    console.print(f"  [success]\u2713[/success] {msg}")


def print_error(msg: str) -> None:
    error_console.print(Panel(msg, title="Error", border_style="red", padding=(0, 1)))


# ── Request log ──


def log_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    method_style = _METHOD_STYLES.get(method, "bold")
    if status_code < 300:
        sc_style = "status.2xx"
    elif status_code < 400:
        sc_style = "status.3xx"
    elif status_code < 500:
        sc_style = "status.4xx"
    else:
        sc_style = "status.5xx"

    console.print(
        Text.assemble(
            ("  ", ""),
            (f"{method:<7}", method_style),
            (" ", ""),
            (path, "path"),
            (" ", ""),
            (str(status_code), sc_style),
            (" ", ""),
            (f"{duration_ms:.1f}ms", "timing"),
        )
    )


# ── Syntax highlight ──


def print_html(html: str) -> None:
    syntax = Syntax(html, "html", theme="monokai", padding=1)
    console.print(syntax)
