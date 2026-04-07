"""CLI entry point for the Tsuchi compiler."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time

from tsuchi.compiler import Compiler


def _get_console():
    """Get a Rich console, or None if Rich is unavailable."""
    try:
        from rich.console import Console
        return Console()
    except ImportError:
        return None


def main():
    parser = argparse.ArgumentParser(
        prog="tsuchi",
        description="JavaScript/TypeScript AOT compiler via LLVM",
    )

    subparsers = parser.add_subparsers(dest="command")

    # compile command
    compile_parser = subparsers.add_parser("compile", help="Compile a JS/TS file to a standalone binary")
    compile_parser.add_argument("file", help="JavaScript or TypeScript source file")
    compile_parser.add_argument("-o", "--output-dir", default=".", help="Output directory")
    compile_parser.add_argument("--link", action="append", default=[], help="Link C file or library flag")
    compile_parser.add_argument("--link-lib", action="append", default=[], help="Link library (adds -l prefix)")
    compile_parser.add_argument("--lib-path", action="append", default=[], help="Library search path (adds -L prefix)")
    compile_parser.add_argument("--tui", action="store_true", help="Target TUI output (Clay + termbox2)")
    compile_parser.add_argument("--backend", choices=["quickjs", "jsc", "taiyaki"], default="quickjs",
                               help="Runtime backend (default: quickjs)")
    compile_vgroup = compile_parser.add_mutually_exclusive_group()
    compile_vgroup.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    compile_vgroup.add_argument("--quiet", "-q", action="store_true", help="Suppress output")

    # check command
    check_parser = subparsers.add_parser("check", help="Type-check a JS/TS file")
    check_parser.add_argument("file", help="JavaScript or TypeScript source file")
    check_vgroup = check_parser.add_mutually_exclusive_group()
    check_vgroup.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    check_vgroup.add_argument("--quiet", "-q", action="store_true", help="Suppress output")

    # eval command
    eval_parser = subparsers.add_parser("eval", help="Compile and run JavaScript/TypeScript code")
    eval_parser.add_argument("code", nargs="?", help="JavaScript/TypeScript code to evaluate")
    eval_parser.add_argument("-e", "--expression", help="JavaScript/TypeScript expression to evaluate")
    eval_parser.add_argument("--ts", action="store_true", help="Treat input as TypeScript")
    eval_parser.add_argument("--backend", choices=["quickjs", "jsc", "taiyaki"], default="quickjs",
                             help="Runtime backend (default: quickjs)")

    # repl command
    repl_parser = subparsers.add_parser("repl", help="Interactive JavaScript/TypeScript REPL")
    repl_parser.add_argument("--ts", action="store_true", help="Enable TypeScript mode")
    repl_parser.add_argument("--backend", choices=["quickjs", "jsc", "taiyaki"], default="quickjs",
                             help="Runtime backend (default: quickjs)")

    args = parser.parse_args()

    if args.command is None:
        _print_banner()
        parser.print_help()
        sys.exit(1)

    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)
    backend = getattr(args, "backend", "quickjs")
    compiler = Compiler(verbose=verbose, backend=backend)

    if args.command == "compile":
        _cmd_compile(args, compiler, quiet)
    elif args.command == "check":
        _cmd_check(args, compiler, quiet)
    elif args.command == "eval":
        _cmd_eval(args, compiler)
    elif args.command == "repl":
        ts_mode = getattr(args, "ts", False)
        _cmd_repl(compiler, ts_mode=ts_mode)


def _format_logo():
    """Build the logo as a Rich Text object with colored segments."""
    from rich.text import Text

    # Each row: list of (text, style) pairs
    T = "bold #8B6914"
    S = "bold #9B7B24"
    U = "bold #AB8D34"
    C = "bold #6B8E23"
    H = "bold #558B2F"
    I = "bold #2E7D32"
    g  = "bold #2E7D32"
    lg = "bold #4CAF50"
    mg = "bold #66BB6A"
    dg = "bold #558B2F"
    br = "bold #8B6914"
    db = "bold #6B4C1A"

    # Sprout: small seedling with two leaves opening outward
    # TSUCHI text = 47 chars. Sprout starts at col 48.
    # Stem "||" is always at offset +2 from col 48 = col 50-51
    #   col: 48 49 50 51 52 53
    # r1:       /  /  \  \
    # r2:      /  /    \  \
    # r3:            |  |
    # r4:            |  |
    # r5:    ▒  ░  ░  |  |  ░  ░  ▒
    rows = [
        [(T,"  ████████╗"),(S,"███████╗"),(U,"██╗   ██╗"),(C," ██████╗"),(H,"██╗  ██╗"),(I,"██╗")],
        [(T,"  ╚══██╔══╝"),(S,"██╔════╝"),(U,"██║   ██║"),(C,"██╔════╝"),(H,"██║  ██║"),(I,"██║"),(lg,"  \\\\      //")],
        [(T,"     ██║   "),(S,"███████╗"),(U,"██║   ██║"),(C,"██║     "),(H,"███████║"),(I,"██║"),(mg,"   \\\\    //")],
        [(T,"     ██║   "),(S,"╚════██║"),(U,"██║   ██║"),(C,"██║     "),(H,"██╔══██║"),(I,"██║"),(g,"     \\\\//")],
        [(T,"     ██║   "),(S,"███████║"),(U,"╚██████╔╝"),(C,"╚██████╗"),(H,"██║  ██║"),(I,"██║"),(g,"      ||")],
        [(T,"     ╚═╝   "),(S,"╚══════╝"),(U," ╚═════╝ "),(C," ╚═════╝"),(H,"╚═╝  ╚═╝"),(I,"╚═╝"),(br,"    ░░"),(g,"||"),(br,"░░")],
    ]

    text = Text()
    for i, row in enumerate(rows):
        if i > 0:
            text.append("\n")
        for style, segment in row:
            text.append(segment, style=style)
    return text

def _print_banner():
    """Print a styled banner when no command is given."""
    con = _get_console()
    if con:
        con.print(_format_logo())
        con.print("  [dim]JavaScript/TypeScript AOT Compiler[/dim]")
        con.print("  [dim]Compile to standalone native binaries via LLVM[/dim]")
        con.print()
    else:
        print("Tsuchi — JavaScript/TypeScript AOT Compiler")
        print()


# ── compile ──────────────────────────────────────────────────────────

def _cmd_compile(args, compiler: Compiler, quiet: bool):
    con = _get_console()
    t0 = time.time()

    if not quiet and con:
        con.print(f"[bold cyan]Compiling[/bold cyan] {args.file} ...")
    elif not quiet:
        print(f"Compiling {args.file}...")

    result = compiler.compile_file(
        args.file, output_dir=args.output_dir,
        extra_link=args.link or None,
        extra_link_libs=getattr(args, 'link_lib', None) or None,
        extra_lib_paths=getattr(args, 'lib_path', None) or None,
        tui=getattr(args, 'tui', False),
    )

    elapsed = time.time() - t0

    if result.diagnostics and not quiet:
        if con:
            _print_diagnostics(con, result.diagnostics)
        else:
            print(result.diagnostics)

    if result.success and result.output_path:
        if not quiet:
            _print_compile_success(con, args.file, result, elapsed)
        print(result.output_path)
    if not result.success:
        if not quiet and con:
            con.print("[bold red]Compilation failed.[/bold red]")
        sys.exit(1)


def _print_compile_success(con, filename: str, result, elapsed: float):
    """Print compilation success with Rich table."""
    if not con:
        print(f"Compiled {filename} → {result.output_path}")
        return

    from rich.table import Table
    from rich.panel import Panel

    # Binary size
    try:
        size_bytes = os.path.getsize(result.output_path)
        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        elif size_bytes >= 1024:
            size_str = f"{size_bytes / 1024:.0f} KB"
        else:
            size_str = f"{size_bytes} B"
    except OSError:
        size_str = "?"

    nc = len(result.native_funcs)
    fc = len(result.fallback_funcs)

    # Summary line
    con.print(
        f"[bold green]✓[/bold green] [bold]{filename}[/bold] → "
        f"[cyan]{result.output_path}[/cyan]  "
        f"[dim]({size_str}, {elapsed:.2f}s)[/dim]"
    )

    # Function table
    if nc or fc:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Type", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Functions", style="dim")

        if nc:
            table.add_row(
                "[green]Native[/green]", str(nc),
                ", ".join(result.native_funcs)
            )
        if fc:
            table.add_row(
                "[yellow]Fallback[/yellow]", str(fc),
                ", ".join(result.fallback_funcs)
            )
        con.print(table)


def _print_diagnostics(con, diagnostics: str):
    """Print compiler diagnostics with Rich styling."""
    from rich.panel import Panel
    con.print(Panel(diagnostics.strip(), title="[yellow]Diagnostics[/yellow]",
                    border_style="yellow"))


# ── check ────────────────────────────────────────────────────────────

def _cmd_check(args, compiler: Compiler, quiet: bool):
    con = _get_console()

    if not quiet and con:
        con.print(f"[bold cyan]Checking[/bold cyan] {args.file} ...")
    elif not quiet:
        print(f"Checking {args.file}...")

    result = compiler.check_file(args.file)

    if result.diagnostics and not quiet:
        if con:
            _print_diagnostics(con, result.diagnostics)
        else:
            print(result.diagnostics)

    if result.success and not quiet:
        if con:
            con.print(f"[bold green]✓[/bold green] {args.file} — OK")
        else:
            print("OK")
    if not result.success:
        sys.exit(1)


# ── eval ─────────────────────────────────────────────────────────────

def _cmd_eval(args, compiler: Compiler):
    """Compile and run JavaScript/TypeScript code."""
    code = args.code or args.expression
    if code is None:
        if not sys.stdin.isatty():
            code = sys.stdin.read()
        else:
            con = _get_console()
            if con:
                con.print("[bold red]No code provided.[/bold red]")
                con.print("[dim]Usage: tsuchi eval 'console.log(42)'[/dim]")
            else:
                print("Usage: tsuchi eval 'console.log(42)'", file=sys.stderr)
            sys.exit(1)

    ts_mode = getattr(args, "ts", False)
    rc = _eval_and_run(code, compiler, ts_mode=ts_mode)
    if rc != 0:
        sys.exit(rc)


def _eval_and_run(code: str, compiler: Compiler, ts_mode: bool = False) -> int:
    """Compile JS/TS code to a temp binary, run it, print output. Returns exit code."""
    type_stubs = None
    if ts_mode:
        from tsuchi.parser.ts_stripper import strip_types, extract_type_hints
        from tsuchi.type_checker.types import FunctionType
        type_stubs = {}
        for name, ft in extract_type_hints(code).items():
            if isinstance(ft, FunctionType):
                type_stubs[name] = ft
        code = strip_types(code)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = compiler.compile_source(code, "__eval__", output_dir=tmpdir,
                                         type_stubs=type_stubs)
        if not result.success:
            con = _get_console()
            if result.diagnostics:
                if con:
                    _print_diagnostics(con, result.diagnostics)
                else:
                    print(result.diagnostics, file=sys.stderr)
            return 1

        proc = subprocess.run(
            [result.output_path], capture_output=True, text=True, timeout=30
        )
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return proc.returncode


# ── repl ─────────────────────────────────────────────────────────────

def _cmd_repl(compiler: Compiler, ts_mode: bool = False):
    """Interactive JavaScript/TypeScript REPL with Rich."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.syntax import Syntax
        from rich.text import Text
    except ImportError:
        print("Rich library required for REPL. Install with: pip install rich", file=sys.stderr)
        sys.exit(1)

    console = Console()
    lang = "TypeScript" if ts_mode else "JavaScript"
    syntax_lang = "typescript" if ts_mode else "javascript"

    # Setup readline history
    import readline
    history_file = os.path.expanduser("~/.tsuchi_repl_history")
    try:
        readline.read_history_file(history_file)
    except (FileNotFoundError, OSError, PermissionError):
        pass
    readline.set_history_length(1000)

    # Welcome banner
    console.print(_format_logo())
    console.print(f"  [bold cyan]{lang} REPL[/bold cyan] [dim]— AOT compile & run, every expression is native code[/dim]")
    console.print(f"  [dim]Commands:[/dim] [bold].exit[/bold]  [bold].clear[/bold]  [bold].help[/bold]  [bold].defs[/bold]")
    console.print()

    defined_functions: list[str] = []
    defined_vars: list[str] = []  # Variable declarations remembered across lines
    history_num = 1

    while True:
        try:
            # Prompt with line number
            prompt = Text()
            prompt.append(f"[{history_num}]", style="dim")
            prompt.append(" › ", style="bold cyan")
            try:
                line = console.input(prompt)
            except EOFError:
                console.print()
                break

            stripped = line.strip()
            if not stripped:
                continue

            # REPL commands
            if stripped == ".exit":
                console.print("[dim]Bye![/dim]")
                break
            if stripped == ".clear":
                defined_functions.clear()
                defined_vars.clear()
                console.print("[dim italic]Cleared all definitions.[/dim italic]")
                continue
            if stripped == ".defs":
                if defined_functions:
                    for fn_src in defined_functions:
                        console.print(Syntax(fn_src, syntax_lang, theme="monokai",
                                             padding=0))
                else:
                    console.print("[dim]No functions defined.[/dim]")
                continue
            if stripped == ".help":
                from rich.table import Table
                t = Table(show_header=False, box=None, padding=(0, 2))
                t.add_column(style="bold cyan")
                t.add_column(style="dim")
                t.add_row(".exit", "Quit the REPL")
                t.add_row(".clear", "Forget all function definitions")
                t.add_row(".defs", "Show defined functions")
                t.add_row(".help", "Show this help")
                t.add_row("", "")
                t.add_row("Expressions", "Auto-wrapped in console.log()")
                t.add_row("function ...", "Remembered across lines")
                t.add_row("Multi-line", "Detected by unbalanced { }")
                console.print(t)
                continue

            # Multi-line input: only if braces are unbalanced
            code = line
            if code.count("{") > code.count("}"):
                while True:
                    try:
                        continuation = console.input(Text("... ", style="dim"))
                    except EOFError:
                        break
                    if continuation.strip() == "":
                        break
                    code += "\n" + continuation
                    if code.count("{") <= code.count("}"):
                        break

            stripped_code = code.strip()

            # If it's a function definition, remember it
            if stripped_code.startswith(("function ", "async function ")):
                defined_functions.append(code)
                console.print(Syntax(code, syntax_lang, theme="monokai", padding=0))
                console.print("[dim italic]Function defined.[/dim italic]")
                history_num += 1
                continue

            # If it's a variable declaration, remember it
            is_var_decl = stripped_code.startswith(("const ", "let ", "var "))

            # Build full source: functions at top level, vars+code inside a wrapper function
            full_source = "\n".join(defined_functions) + "\n"

            # Build the body of the wrapper function: remembered vars + current code
            body_lines = list(defined_vars)
            if is_var_decl:
                # Variable declaration: add it, then print the value
                var_name = stripped_code.split(None, 2)[1].rstrip(":;= ")
                if ":" in var_name:
                    var_name = var_name.split(":")[0].strip()
                body_lines.append(code)
                body_lines.append(f"console.log({var_name});")
            elif (not stripped_code.startswith(("console.", "if ", "for ", "while "))
                    and "console.log" not in stripped_code
                    and not stripped_code.startswith(("function ", "async ", "class "))):
                body_lines.append(f"console.log({code});")
            else:
                body_lines.append(code)

            body = "\n  ".join(body_lines)
            full_source += f"function __repl__() {{\n  {body}\n}}\n__repl__();"

            rc = _eval_and_run(full_source, compiler, ts_mode=ts_mode)

            # If successful and was a var declaration, remember it
            if rc == 0 and is_var_decl:
                defined_vars.append(code)
            if rc != 0:
                console.print(f"[bold red]Exit code: {rc}[/bold red]")

            history_num += 1

        except KeyboardInterrupt:
            console.print()
            continue
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    # Save history on exit
    try:
        readline.write_history_file(history_file)
    except OSError:
        pass


if __name__ == "__main__":
    main()
