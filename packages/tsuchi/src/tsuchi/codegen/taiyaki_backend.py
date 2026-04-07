"""Taiyaki backend: LLVM IR → standalone binary with taiyaki-core runtime.

Compiles LLVM IR to object code, generates a C init wrapper using the
taiyaki C ABI, and links everything into a standalone executable.
Compiled binaries get full Node.js polyfill support via taiyaki-node-polyfill.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tsuchi.codegen.backend_base import BackendBase, _PROJECT_ROOT
from tsuchi.hir.nodes import HIRModule, HIRFunction
from tsuchi.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType, ObjectType,
    ArrayType, FunctionType, MonoType,
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
    """Find the taiyaki-core static library."""
    root = _find_taiyaki_root()
    # Try release first, then debug
    for profile in ("release", "debug"):
        lib = root / "target" / profile / "libtaiyaki_core.a"
        if lib.exists():
            return lib
    raise RuntimeError(
        "Cannot find libtaiyaki_core.a. Run `cargo build --release -p taiyaki-core` first."
    )


class TaiyakiBackend(BackendBase):
    """Compiles LLVM IR + C init wrapper + taiyaki-core into a standalone binary."""

    def _engine_headers(self) -> list[str]:
        return ['#include "taiyaki.h"']

    def _engine_include_flags(self) -> list[str]:
        root = _find_taiyaki_root()
        include_dir = root / "crates" / "taiyaki-core" / "include"
        return [f"-I{include_dir}"]

    def _engine_link_flags(self) -> list[str]:
        lib_path = _find_taiyaki_lib()
        lib_dir = lib_path.parent
        flags = [f"-L{lib_dir}", "-ltaiyaki_core"]
        # taiyaki-core links against system frameworks on macOS
        import platform
        if platform.system() == "Darwin":
            flags.extend(["-framework", "Security", "-framework", "CoreFoundation"])
        return flags

    def _engine_global_state(self, has_fallbacks: bool) -> list[str]:
        lines = ['static struct LibtsRuntime *_tsuchi_rt = NULL;']
        if has_fallbacks:
            lines.append('')
        return lines

    def _engine_console_log(self) -> list[str]:
        # Register a __print host function via the taiyaki C ABI
        return [
            '/* __print host function for console.log */',
            'static struct LibtsValue *_taiyaki_print_fn(',
            '    const struct LibtsValue *const *args, uintptr_t argc, void *user_data) {',
            '    for (uintptr_t i = 0; i < argc; i++) {',
            '        uintptr_t slen = 0;',
            '        const char *s = taiyaki_value_as_string((struct LibtsValue *)args[i], &slen);',
            '        if (s) printf("%s", s);',
            '    }',
            '    return taiyaki_value_undefined();',
            '}',
            '',
        ]

    def _generate_fallback_bridges(self, hir_module: HIRModule) -> list[str]:
        """Generate C bridge functions using taiyaki fast-call API."""
        lines = ['/* Fallback bridge functions (taiyaki C ABI) */']

        # Declare cached function handles
        for name in hir_module.fallback_signatures:
            lines.append(f'static struct LibtsValue *_tsuchi_fn_{name} = NULL;')
        if hir_module.fallback_signatures:
            lines.append('')

        for name, info in hir_module.fallback_signatures.items():
            ret_hint = info.return_type_hint
            # C return type
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

            if info.param_count > 0 and ret_hint not in ("string", "void"):
                # Fast path: use taiyaki_call_fast_f64
                lines.append(f'    double args[{info.param_count}];')
                for i in range(info.param_count):
                    lines.append(f'    args[{i}] = arg{i};')
                if ret_hint == "boolean":
                    lines.append(f'    double r = taiyaki_call_fast_f64(_tsuchi_rt, _tsuchi_fn_{name}, args, {info.param_count});')
                    lines.append('    return (int)r;')
                else:
                    lines.append(f'    return taiyaki_call_fast_f64(_tsuchi_rt, _tsuchi_fn_{name}, args, {info.param_count});')
            elif info.param_count == 0 and ret_hint not in ("string", "void"):
                # No args, numeric return
                if ret_hint == "boolean":
                    lines.append(f'    double r = taiyaki_call_fast_f64(_tsuchi_rt, _tsuchi_fn_{name}, NULL, 0);')
                    lines.append('    return (int)r;')
                else:
                    lines.append(f'    return taiyaki_call_fast_f64(_tsuchi_rt, _tsuchi_fn_{name}, NULL, 0);')
            else:
                # Generic path: use taiyaki_call_global for string/void returns
                lines.append(f'    struct LibtsValue *result = taiyaki_call_global(_tsuchi_rt, "{name}", {len(name)}, NULL, 0);')
                if ret_hint == "string":
                    lines.append('    const char *s = "";')
                    lines.append('    if (result) {')
                    lines.append('        uintptr_t slen = 0;')
                    lines.append('        const char *tmp = taiyaki_value_as_string(result, &slen);')
                    lines.append('        if (tmp) {')
                    lines.append('            char *copy = (char*)malloc(strlen(tmp) + 1);')
                    lines.append('            strcpy(copy, tmp);')
                    lines.append('            s = copy;')
                    lines.append('        }')
                    lines.append('        taiyaki_value_free(result);')
                    lines.append('    }')
                    lines.append('    return s;')
                elif ret_hint == "void":
                    lines.append('    if (result) taiyaki_value_free(result);')
                else:
                    lines.append('    double ret = 0.0;')
                    lines.append('    if (result) { ret = taiyaki_value_as_number(result); taiyaki_value_free(result); }')
                    lines.append('    return ret;')

            lines.append('}')
            lines.append('')

        return lines

    def _generate_wrapper(self, func: HIRFunction) -> list[str]:
        """Generate a taiyaki fast-fn wrapper for an AOT-compiled function."""
        lines = []

        # Check if we can use the fast f64 path
        all_numeric = all(
            isinstance(p.type, (NumberType, BooleanType))
            for p in func.params
        )
        numeric_return = isinstance(func.return_type, (NumberType, BooleanType, VoidType))

        if all_numeric and numeric_return:
            # Fast path: TaiyakiFastFnF64 callback
            lines.append(
                f'static double tsuchi_wrap_{func.name}(const double *args, '
                f'uintptr_t argc, void *user_data) {{'
            )
            args_str = ", ".join(
                f'({"int" if isinstance(p.type, BooleanType) else ""})(args[{i}])'
                if isinstance(p.type, BooleanType)
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
        else:
            # Generic path: LibtsHostFn callback
            lines.append(
                f'static struct LibtsValue *tsuchi_wrap_{func.name}('
                f'const struct LibtsValue *const *args, uintptr_t argc, void *user_data) {{'
            )
            # Extract args
            call_args = []
            for i, p in enumerate(func.params):
                if isinstance(p.type, NumberType):
                    lines.append(f'    double arg_{i} = taiyaki_value_as_number(args[{i}]);')
                    call_args.append(f'arg_{i}')
                elif isinstance(p.type, BooleanType):
                    lines.append(f'    int arg_{i} = taiyaki_value_as_bool(args[{i}]);')
                    call_args.append(f'arg_{i}')
                elif isinstance(p.type, StringType):
                    lines.append(f'    uintptr_t _slen_{i} = 0;')
                    lines.append(f'    const char *arg_{i} = taiyaki_value_as_string((struct LibtsValue *)args[{i}], &_slen_{i});')
                    call_args.append(f'arg_{i}')
                else:
                    lines.append(f'    double arg_{i} = taiyaki_value_as_number(args[{i}]);')
                    call_args.append(f'arg_{i}')

            args_str = ", ".join(call_args)
            if isinstance(func.return_type, VoidType):
                lines.append(f'    _tsuchi_{func.name}({args_str});')
                lines.append('    return taiyaki_value_undefined();')
            elif isinstance(func.return_type, NumberType):
                lines.append(f'    double result = _tsuchi_{func.name}({args_str});')
                lines.append('    return taiyaki_value_number(result);')
            elif isinstance(func.return_type, BooleanType):
                lines.append(f'    int result = _tsuchi_{func.name}({args_str});')
                lines.append('    return taiyaki_value_bool(result);')
            elif isinstance(func.return_type, StringType):
                lines.append(f'    const char *result = _tsuchi_{func.name}({args_str});')
                lines.append('    return taiyaki_value_string(result, strlen(result));')
            else:
                lines.append(f'    double result = _tsuchi_{func.name}({args_str});')
                lines.append('    return taiyaki_value_number(result);')
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

        if has_async:
            lines.append('    tsuchi_loop_init();')
            lines.append('')

        # Initialize taiyaki runtime
        lines.append('    _tsuchi_rt = taiyaki_runtime_new();')
        lines.append('    if (!_tsuchi_rt) {')
        lines.append('        fprintf(stderr, "Failed to initialize taiyaki runtime\\n");')
        lines.append('        return 1;')
        lines.append('    }')
        lines.append('')

        # Register console.log as a C host function
        lines.append('    taiyaki_register_fn(_tsuchi_rt, "__tsuchi_log", 12, _taiyaki_print_fn, NULL);')
        lines.append('    {')
        console_js = (
            'globalThis.console = {'
            'log: function() {'
            'var s = "";'
            'for (var i = 0; i < arguments.length; i++) {'
            'if (i > 0) s += " ";'
            'var v = arguments[i];'
            'if (typeof v === "number") {'
            'if (v === (v|0) && v >= -1e15 && v <= 1e15) s += String(v|0);'
            'else s += String(v);'
            '} else if (typeof v === "boolean") s += v ? "true" : "false";'
            'else if (v === null) s += "null";'
            'else if (v === undefined) s += "undefined";'
            'else s += String(v);'
            '}'
            '__tsuchi_log(s + "\\n");'
            '},'
            'error: function(){console.log.apply(null, arguments);},'
            'warn: function(){console.log.apply(null, arguments);}'
            '};'
        )
        # Escape for C string
        c_escaped = console_js.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'        static const char _console_js[] = "{c_escaped}";')
        lines.append('        taiyaki_eval(_tsuchi_rt, _console_js, sizeof(_console_js) - 1);')
        lines.append('    }')
        lines.append('')

        # Evaluate fallback source code
        if has_fallbacks:
            for name, src_lines in hir_module.fallback_sources.items():
                src = "\\n".join(
                    line.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                    for line in src_lines
                )
                lines.append('    {')
                lines.append(f'        static const char _fb_{name}[] = "{src}";')
                lines.append(f'        taiyaki_eval(_tsuchi_rt, _fb_{name}, sizeof(_fb_{name}) - 1);')
                lines.append('    }')
            lines.append('')

            # Cache fallback function handles
            for name in hir_module.fallback_signatures:
                lines.append(
                    f'    _tsuchi_fn_{name} = taiyaki_get_global(_tsuchi_rt, "{name}", {len(name)});'
                )
            lines.append('')

        # Register AOT-compiled functions
        for func in exported_funcs:
            nparams = len(func.params)
            all_numeric = all(isinstance(p.type, (NumberType, BooleanType)) for p in func.params)
            numeric_return = isinstance(func.return_type, (NumberType, BooleanType, VoidType))

            if all_numeric and numeric_return:
                lines.append(
                    f'    taiyaki_register_fast_fn_f64(_tsuchi_rt, "{func.name}", {len(func.name)}, '
                    f'tsuchi_wrap_{func.name}, {nparams}, NULL);'
                )
            else:
                lines.append(
                    f'    taiyaki_register_fn(_tsuchi_rt, "{func.name}", {len(func.name)}, '
                    f'tsuchi_wrap_{func.name}, NULL);'
                )

        # Register import aliases
        if hir_module.func_aliases:
            reverse_aliases: dict[str, list[str]] = {}
            for alias, canonical in hir_module.func_aliases.items():
                reverse_aliases.setdefault(canonical, []).append(alias)
            for func in exported_funcs:
                for alias in reverse_aliases.get(func.name, []):
                    if alias != func.name:
                        all_numeric = all(isinstance(p.type, (NumberType, BooleanType)) for p in func.params)
                        numeric_return = isinstance(func.return_type, (NumberType, BooleanType, VoidType))
                        if all_numeric and numeric_return:
                            lines.append(
                                f'    taiyaki_register_fast_fn_f64(_tsuchi_rt, "{alias}", {len(alias)}, '
                                f'tsuchi_wrap_{func.name}, {len(func.params)}, NULL);'
                            )
                        else:
                            lines.append(
                                f'    taiyaki_register_fn(_tsuchi_rt, "{alias}", {len(alias)}, '
                                f'tsuchi_wrap_{func.name}, NULL);'
                            )
        lines.append('')

        # Execute async entry calls directly
        for call_stmt in async_entry_calls:
            func_name = call_stmt.rstrip(';').rstrip('()')
            lines.append(f'    _tsuchi_{func_name}();')

        # Execute JS entry statements
        for i, stmt in enumerate(js_entry_stmts):
            escaped = stmt.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            lines.append('    {')
            lines.append(f'        static const char _entry_{i}[] = "{escaped}";')
            lines.append(f'        taiyaki_eval(_tsuchi_rt, _entry_{i}, sizeof(_entry_{i}) - 1);')
            lines.append('    }')

        if has_async:
            lines.append('')
            lines.append('    tsuchi_loop_run();')
            lines.append('    tsuchi_loop_close();')

        # Cleanup
        lines.append('')
        if has_fallbacks:
            for name in hir_module.fallback_signatures:
                lines.append(f'    if (_tsuchi_fn_{name}) taiyaki_value_free(_tsuchi_fn_{name});')
        lines.append('    taiyaki_runtime_free(_tsuchi_rt);')
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
