"""CLI entry point: python -m dark run [app_path]"""

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from taiyaki_web.console import (
    console,
    error_console,
    print_banner,
    print_error,
    print_html,
    print_project_tree,
    print_route_table,
    print_server_info,
    print_success,
)


# ── Templates ──

_PYPROJECT_TEMPLATE = """\
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["dark"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
"""

_APP_TEMPLATE = """\
from taiyaki_web import Taiyaki, Context

app = Taiyaki()

app.load_component("Home", '''
import {{ h }} from "preact";
export default function Home({{ title }}) {{
    return h("div", null,
        h("h1", null, title),
        h("p", null, "Welcome to Taiyaki!")
    );
}}
''')


@app.get("/", component="Home")
async def index(ctx: Context):
    ctx.set_title("{name}")
    return {{"title": "Hello, {name}!"}}
"""

_COMPONENT_TEMPLATE = """\
import {{ h }} from "preact";

export default function {name}({{ children }}) {{
    return h("div", null, children);
}}
"""

_ISLAND_TEMPLATE = """\
import {{ h }} from "preact";
import {{ useState }} from "preact/hooks";

export default function {name}({{ initial }}) {{
    const [count, setCount] = useState(initial || 0);
    return h("button", {{ onClick: () => setCount(count + 1) }},
        "{name}: " + count
    );
}}
"""


# ── Helpers ──


def _load_app_module(app_path: Path) -> ModuleType:
    """Load and return a Python module from a file path."""
    if not app_path.exists():
        print_error(f"{app_path} not found")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("__dark_app__", str(app_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_dark_instance(mod: ModuleType):
    """Find the first Dark instance in a module."""
    from taiyaki_web.app import Taiyaki

    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, Taiyaki):
            return obj
    print_error(f"No Taiyaki instance found in {mod.__name__}")
    sys.exit(1)


def _load_dark_app(app_path_str: str):
    """Load a Taiyaki instance from a Python file."""
    app_path = Path(app_path_str).resolve()
    mod = _load_app_module(app_path)
    return _find_dark_instance(mod), mod


# ── Commands ──


def _cmd_new(args: argparse.Namespace) -> None:
    """Create a new Taiyaki project."""
    name = args.name
    project_dir = Path(name)
    if project_dir.exists():
        print_error(f"directory '{name}' already exists")
        sys.exit(1)

    project_dir.mkdir()
    (project_dir / "components").mkdir()
    (project_dir / "islands").mkdir()
    (project_dir / "static").mkdir()

    (project_dir / "pyproject.toml").write_text(_PYPROJECT_TEMPLATE.format(name=name))
    (project_dir / "app.py").write_text(_APP_TEMPLATE.format(name=name))

    print_project_tree(name)


def _cmd_generate(args: argparse.Namespace) -> None:
    """Generate a component or island file."""
    kind = args.kind
    name = args.name

    if kind == "component":
        out_dir = Path("components")
        template = _COMPONENT_TEMPLATE
    elif kind == "island":
        out_dir = Path("islands")
        template = _ISLAND_TEMPLATE
    else:
        print_error(f"unknown kind '{kind}'. Use 'component' or 'island'.")
        sys.exit(1)

    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{name}.tsx"
    if out_path.exists():
        print_error(f"{out_path} already exists")
        sys.exit(1)

    out_path.write_text(template.format(name=name))
    print_success(f"Created [bold]{out_path}[/bold]")


def _cmd_run(args: argparse.Namespace) -> None:
    """Start the dev server."""
    dark_app, _ = _load_dark_app(args.app)
    if args.dev:
        dark_app._dev_mode = True

    print_banner()
    print_server_info(args.host, args.port, args.dev)
    print_route_table(dark_app._route_meta)

    import uvicorn

    uvicorn.run(dark_app.asgi, host=args.host, port=args.port, log_level="warning")


def _cmd_build(args: argparse.Namespace) -> None:
    """Generate static site."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    dark_app, mod = _load_dark_app(args.app)
    routes = getattr(mod, "SSG_ROUTES", ["/"])

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building...", total=None)
        count = 0

        def on_progress(path: str) -> None:
            nonlocal count
            count += 1
            progress.update(
                task, completed=count, description=f"Built [cyan]{path}[/cyan]"
            )

        import asyncio

        asyncio.run(
            dark_app.generate_static_site(args.out, routes, on_progress=on_progress)
        )
        progress.update(task, description="[bold green]Done[/bold green]")

    print_success(f"Static site generated in [bold]{args.out}/[/bold]")


def _cmd_typegen(args: argparse.Namespace) -> None:
    """Generate TypeScript type definitions."""
    dark_app, _ = _load_dark_app(args.app)
    from taiyaki_web.typegen import generate_types

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_types(dark_app))
    print_success(f"Types generated: [bold]{out_path}[/bold]")


# ── Main ──


def main() -> None:
    parser = argparse.ArgumentParser(prog="dark")
    sub = parser.add_subparsers(dest="command")

    # run
    run_p = sub.add_parser("run", help="Start the dev server")
    run_p.add_argument("app", nargs="?", default="app.py", help="App module path")
    run_p.add_argument("--host", default="127.0.0.1")
    run_p.add_argument("--port", type=int, default=8000)
    run_p.add_argument("--dev", action="store_true", help="Enable dev mode")

    # build
    build_p = sub.add_parser("build", help="Generate static site")
    build_p.add_argument("app", nargs="?", default="app.py", help="App module path")
    build_p.add_argument("--out", default="dist", help="Output directory")

    # new
    new_p = sub.add_parser("new", help="Create a new Taiyaki project")
    new_p.add_argument("name", help="Project name")

    # generate
    gen_p = sub.add_parser("generate", help="Generate a component or island")
    gen_p.add_argument("kind", choices=["component", "island"], help="What to generate")
    gen_p.add_argument("name", help="Component/island name")

    # typegen
    tg_p = sub.add_parser("typegen", help="Generate TypeScript type definitions")
    tg_p.add_argument("app", nargs="?", default="app.py", help="App module path")
    tg_p.add_argument("--out", default="types/dark.d.ts", help="Output file path")

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "build":
        _cmd_build(args)
    elif args.command == "new":
        _cmd_new(args)
    elif args.command == "generate":
        _cmd_generate(args)
    elif args.command == "typegen":
        _cmd_typegen(args)
    else:
        print_banner()
        console.print("[dim]Usage: dark <command>[/dim]\n")
        parser.print_help()


if __name__ == "__main__":
    main()
