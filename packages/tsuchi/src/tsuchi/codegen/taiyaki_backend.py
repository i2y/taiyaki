"""Taiyaki backend: LLVM IR → standalone binary with taiyaki-core runtime.

Compiles LLVM IR to object code, generates a C init wrapper using the
taiyaki C ABI, and links everything into a standalone executable.
Compiled binaries get full Node.js polyfill support via taiyaki-node-polyfill.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from tsuchi.codegen.backend_base import BackendBase, _PROJECT_ROOT
from tsuchi.hir.nodes import HIRModule, HIRFunction
from tsuchi.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType,
)


def _find_taiyaki_root() -> Path:
    """Locate the katana/taiyaki project root (two levels up from packages/tsuchi/)."""
    # packages/tsuchi/ -> packages/ -> katana/
    p = _PROJECT_ROOT.parent.parent
    if (p / "crates" / "taiyaki-core").is_dir():
        return p
    # Fallback: check TAIYAKI_ROOT env
    env = os.environ.get("TAIYAKI_ROOT")
    if env:
        return Path(env)
    raise RuntimeError(
        "Cannot locate taiyaki-core. Set TAIYAKI_ROOT env variable "
        "or ensure packages/tsuchi/ is inside the katana monorepo."
    )


def _find_taiyaki_lib() -> Path:
    """Find the taiyaki-runtime static library."""
    root = _find_taiyaki_root()
    for profile in ("release", "debug"):
        lib = root / "target" / profile / "libtaiyaki_runtime.a"
        if lib.exists():
            return lib
    raise RuntimeError(
        "Cannot find libtaiyaki_runtime.a. "
        "Run `cargo build --release -p taiyaki-runtime --no-default-features --features jsc` first."
    )


class TaiyakiBackend(BackendBase):
    """Compiles LLVM IR + C init wrapper + taiyaki-core into a standalone binary."""

    def _is_fast_f64(self, func: HIRFunction) -> bool:
        """Check if a function can use the fast f64 path (all numeric params, numeric/void return)."""
        all_numeric = all(isinstance(p.type, (NumberType, BooleanType)) for p in func.params)
        return all_numeric and isinstance(func.return_type, (NumberType, BooleanType, VoidType))

    def _engine_headers(self) -> list[str]:
        return ['#include "taiyaki_runtime.h"']

    def _engine_include_flags(self) -> list[str]:
        root = _find_taiyaki_root()
        include_dir = root / "crates" / "taiyaki-runtime" / "include"
        return [f"-I{include_dir}"]

    def _engine_link_flags(self) -> list[str]:
        lib_path = _find_taiyaki_lib()
        lib_dir = lib_path.parent
        flags = [f"-L{lib_dir}", "-ltaiyaki_runtime"]
        if platform.system() == "Darwin":
            flags.extend([
                "-framework", "JavaScriptCore",
                "-framework", "Security",
                "-framework", "CoreFoundation",
                "-framework", "CoreServices",
                "-framework", "SystemConfiguration",
                "-liconv", "-lresolv",
            ])
        return flags

    def _engine_global_state(self, has_fallbacks: bool) -> list[str]:
        lines = ['static struct TaiyakiFullRuntime *_tsuchi_rt = NULL;']
        if has_fallbacks:
            lines.append('')
        return lines

    def _engine_console_log(self) -> list[str]:
        # Full runtime provides console.log via bootstrap_engine
        return ['/* console.log provided by taiyaki full runtime */']

    def _generate_fallback_bridges(self, hir_module: HIRModule) -> list[str]:
        """Generate C bridge functions that call JS fallback via full runtime eval."""
        lines = ['/* Fallback bridge functions (eval-based, full runtime) */']

        for name, info in hir_module.fallback_signatures.items():
            ret_hint = info.return_type_hint
            if ret_hint == "string":
                c_ret = "const char*"
            elif ret_hint == "boolean":
                c_ret = "int"
            elif ret_hint == "void":
                c_ret = "void"
            else:
                c_ret = "double"

            params_c = ", ".join(f"double arg{i}" for i in range(info.param_count))
            if not params_c:
                params_c = "void"

            lines.append(f'{c_ret} _tsuchi_fb_{name}({params_c}) {{')

            # Build JS call string: "funcName(arg0, arg1, ...)"
            args_js = ", ".join(f'\" + snprintf_buf + \"' for i in range(info.param_count))
            if info.param_count > 0:
                lines.append(f'    char buf[256];')
                arg_parts = []
                for i in range(info.param_count):
                    arg_parts.append(f'arg{i}')
                # Build the call expression dynamically
                lines.append(f'    int n = snprintf(buf, sizeof(buf), "{name}('
                             + ', '.join(['%g'] * info.param_count)
                             + ')", ' + ', '.join(f'arg{i}' for i in range(info.param_count)) + ');')
            else:
                lines.append(f'    char buf[64];')
                lines.append(f'    int n = snprintf(buf, sizeof(buf), "{name}()");')

            if ret_hint == "void":
                lines.append('    taiyaki_full_runtime_eval(_tsuchi_rt, buf, (uintptr_t)n);')
            else:
                lines.append(f'    {c_ret} ret = ({c_ret})taiyaki_full_runtime_get_global(_tsuchi_rt, "__fb_result", 11);')
                # Wrap in assignment: __fb_result = funcName(...)
                if info.param_count > 0:
                    lines.append(f'    char buf2[300];')
                    lines.append(f'    int n2 = snprintf(buf2, sizeof(buf2), "__fb_result = %s", buf);')
                    lines.append('    taiyaki_full_runtime_eval(_tsuchi_rt, buf2, (uintptr_t)n2);')
                else:
                    lines.append(f'    char buf2[128];')
                    lines.append(f'    int n2 = snprintf(buf2, sizeof(buf2), "__fb_result = {name}()");')
                    lines.append('    taiyaki_full_runtime_eval(_tsuchi_rt, buf2, (uintptr_t)n2);')
                lines.append(f'    ret = ({c_ret})taiyaki_full_runtime_get_global(_tsuchi_rt, "__fb_result", 11);')
                lines.append('    return ret;')

            lines.append('}')
            lines.append('')

        return lines

    def _generate_wrapper(self, func: HIRFunction) -> list[str]:
        """Generate a TaiyakiAotFnF64 wrapper for an AOT-compiled function."""
        lines = []
        lines.append(
            f'static double tsuchi_wrap_{func.name}(const double *args, '
            f'uintptr_t argc, void *user_data) {{'
        )
        args_str = ", ".join(
            f'(int)(args[{i}])' if isinstance(p.type, BooleanType)
            else f'args[{i}]'
            for i, p in enumerate(func.params)
        )
        if isinstance(func.return_type, VoidType):
            lines.append(f'    _tsuchi_{func.name}({args_str});')
            lines.append('    return 0.0;')
        elif isinstance(func.return_type, BooleanType):
            lines.append(f'    int result = _tsuchi_{func.name}({args_str});')
            lines.append('    return (double)result;')
        else:
            lines.append(f'    return _tsuchi_{func.name}({args_str});')
        lines.append('}')
        return lines

    def _generate_resize_callback(self, exported_funcs: list[HIRFunction]) -> list[str]:
        # Not supported with taiyaki backend (Clay live resize is raylib-specific)
        return []

    def _generate_engine_main(self, hir_module: HIRModule, exported_funcs: list[HIRFunction],
                              has_fallbacks: bool,
                              has_async: bool = False,
                              async_funcs: list[HIRFunction] | None = None) -> list[str]:
        """Generate main() using taiyaki C ABI."""
        lines: list[str] = []
        if async_funcs is None:
            async_funcs = []

        async_func_names = {f.name for f in async_funcs}
        async_entry_calls, js_entry_stmts = self._split_entry_statements(
            hir_module.entry_statements, async_func_names
        )

        lines.append('int main(int argc, char *argv[]) {')
        lines.append('    tsuchi_argc = argc;')
        lines.append('    tsuchi_argv = argv;')
        lines.append('')

        # Initialize full runtime (tokio + JSC/QuickJS + all builtins + polyfills)
        lines.append('    _tsuchi_rt = taiyaki_full_runtime_new(argc, (const char *const *)argv);')
        lines.append('    if (!_tsuchi_rt) {')
        lines.append('        fprintf(stderr, "Failed to initialize taiyaki runtime\\n");')
        lines.append('        return 1;')
        lines.append('    }')
        lines.append('')

        # Evaluate fallback source code
        if has_fallbacks:
            for name, src_lines in hir_module.fallback_sources.items():
                src = "\\n".join(self._escape_c_string(line) for line in src_lines)
                lines.append('    {')
                lines.append(f'        static const char _fb_{name}[] = "{src}";')
                lines.append(f'        taiyaki_full_runtime_eval(_tsuchi_rt, _fb_{name}, sizeof(_fb_{name}) - 1);')
                lines.append('    }')
            lines.append('')

        # Register AOT-compiled functions
        for func in exported_funcs:
            nparams = len(func.params)
            lines.append(
                f'    taiyaki_full_runtime_register_fn_f64(_tsuchi_rt, "{func.name}", {len(func.name)}, '
                f'tsuchi_wrap_{func.name}, {nparams}, NULL);'
            )

        # Register import aliases
        if hir_module.func_aliases:
            reverse_aliases: dict[str, list[str]] = {}
            for alias, canonical in hir_module.func_aliases.items():
                reverse_aliases.setdefault(canonical, []).append(alias)
            for func in exported_funcs:
                for alias in reverse_aliases.get(func.name, []):
                    if alias != func.name:
                        lines.append(
                            f'    taiyaki_full_runtime_register_fn_f64(_tsuchi_rt, "{alias}", {len(alias)}, '
                            f'tsuchi_wrap_{func.name}, {len(func.params)}, NULL);'
                        )
        lines.append('')

        # Execute entry statements via full runtime eval
        for call_stmt in async_entry_calls:
            func_name = call_stmt.rstrip(';').rstrip('()')
            lines.append(f'    _tsuchi_{func_name}();')

        for i, stmt in enumerate(js_entry_stmts):
            escaped = self._escape_c_string(stmt)
            lines.append('    {')
            lines.append(f'        static const char _entry_{i}[] = "{escaped}";')
            lines.append(f'        taiyaki_full_runtime_eval(_tsuchi_rt, _entry_{i}, sizeof(_entry_{i}) - 1);')
            lines.append('    }')

        lines.append('')
        lines.append('    taiyaki_full_runtime_free(_tsuchi_rt);')
        lines.append('    return 0;')
        lines.append('}')

        return lines

    # --- Binding stubs (taiyaki provides these via polyfills) ---

    def _generate_cli_bindings(self) -> list[str]:
        return ['/* CLI builtins provided by taiyaki runtime */']

    def _generate_http_shell_bindings(self) -> list[str]:
        return ['/* HTTP/shell builtins provided by taiyaki runtime */']

    def _generate_raylib_bindings(self) -> list[str]:
        return ['/* Raylib bindings not yet supported with taiyaki backend */']

    def _generate_clay_bindings(self) -> list[str]:
        return ['/* Clay bindings not yet supported with taiyaki backend */']

    def _generate_clay_tui_bindings(self) -> list[str]:
        return ['/* Clay TUI bindings not yet supported with taiyaki backend */']

    def _generate_ui_bindings(self) -> list[str]:
        return ['/* UI widget bindings not yet supported with taiyaki backend */']

    def _generate_gf_bindings(self) -> list[str]:
        return ['/* Game framework bindings not yet supported with taiyaki backend */']

    def _generate_ffi_bindings(self) -> list[str]:
        return ['/* FFI bindings not yet supported with taiyaki backend */']
