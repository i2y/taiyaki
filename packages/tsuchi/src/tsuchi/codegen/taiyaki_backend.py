"""Taiyaki backend: LLVM IR → standalone binary with taiyaki-core runtime.

Compiles LLVM IR to object code, generates a C init wrapper using the
taiyaki C ABI, and links everything into a standalone executable.
Compiled binaries get full Node.js polyfill support via taiyaki-node-polyfill.
"""

from __future__ import annotations

import os
import re
import platform
from pathlib import Path

from tsuchi.codegen.backend_base import BackendBase, _PROJECT_ROOT
from tsuchi.hir.nodes import HIRModule, HIRFunction
from tsuchi.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType,
)


def _convert_qjs_to_taiyaki(qjs_lines: list[str]) -> list[str]:
    """Mechanically convert QuickJS-style C binding code to TaiyakiArg-style.

    Transformation rules:
    - Function signatures: JSValue js_xxx(JSContext*...) → double taiyaki_xxx(const struct TaiyakiArg*...)
    - Arg extraction: _rl_int(ctx, argv[N]) → (int)args[N].number, JS_ToCString → args[N].string
    - Returns: JS_UNDEFINED → 0.0, JS_NewFloat64 → (double), JS_NewBool → (double)
    - Registration: JS_NewCFunction/JS_SetPropertyStr → taiyaki_full_runtime_register_fn
    - Constants: JS_SetPropertyStr(ctx, global, "X", JS_NewFloat64(ctx, V)) → eval JS
    """
    out: list[str] = []
    skip_next_free = False
    const_js_parts: list[str] = []  # collect constant definitions for batch eval
    in_reg_section = False
    reg_macro_name = ""

    skip_continuation = False
    skip_helper_depth = 0

    # Preprocess: join multi-line JS_SetPropertyStr/JS_NewCFunction and return statements
    joined: list[str] = []
    buf = ""
    for line in qjs_lines:
        stripped = line.rstrip()
        if buf:
            buf += " " + stripped.lstrip()
            if stripped.endswith(';') or stripped.endswith('{') or stripped.endswith('}') or stripped.endswith('*/'):
                joined.append(buf)
                buf = ""
        elif (stripped.endswith(',') or stripped.endswith('(')) and ('JS_SetPropertyStr' in stripped or 'return JS_New' in stripped):
            buf = stripped
        else:
            joined.append(line)
    if buf:
        joined.append(buf)

    for line in joined:
        s = line

        # Skip multi-line macro continuations (lines ending with \)
        if skip_continuation:
            skip_continuation = s.rstrip().endswith('\\')
            continue

        # Skip QuickJS-specific macro defs (including multi-line)
        if re.match(r'#define\s+\w+', s):
            skip_continuation = s.rstrip().endswith('\\')
            continue
        if re.match(r'#undef\s+\w+', s):
            continue

        # Skip _rl_int/_rl_dbl helper functions and their full bodies
        if 'static int _rl_int(JSContext' in s or 'static double _rl_dbl(JSContext' in s:
            skip_helper_depth = s.count('{') - s.count('}')
            if skip_helper_depth <= 0:
                skip_helper_depth = 0
            continue
        if skip_helper_depth > 0:
            skip_helper_depth += s.count('{') - s.count('}')
            if skip_helper_depth < 0:
                skip_helper_depth = 0
            continue
        if s.strip() in ('return (int)d;', 'return d;', 'double d; JS_ToFloat64(ctx, &d, v); return (int)d;',
                         'double d; JS_ToFloat64(ctx, &d, v); return d;'):
            continue
        if '    double d; JS_ToFloat64(ctx, &d, v);' in s:
            continue

        # Skip JS_FreeValue/JS_GetGlobalObject/JS_FreeCString
        if 'JS_FreeValue(ctx,' in s:
            continue
        if 'JSValue global = JS_GetGlobalObject(ctx)' in s:
            continue
        if 'JS_FreeCString(ctx,' in s:
            continue

        # Convert function signature (single-line, with or without opening brace)
        m = re.match(
            r"static JSValue (js_\w+)\(JSContext \*ctx, JSValueConst this_val, int (?:argc|_argc), JSValueConst \*argv\)\s*\{?",
            s)
        if m:
            fname = m.group(1).replace('js_', 'taiyaki_', 1)
            out.append(f'static double {fname}(const struct TaiyakiArg *args, uintptr_t argc, void *ud) {{')
            continue

        # Convert registration function signature: static void js_add_xxx(JSContext *ctx)
        m = re.match(r"static void (js_add_\w+)\(JSContext \*ctx\)\s*\{?", s)
        if m:
            fname = m.group(1).replace('js_add_', 'taiyaki_add_', 1)
            out.append(f'static void {fname}(struct TaiyakiFullRuntime *rt) {{')
            continue

        # Convert constant: JS_SetPropertyStr(ctx, global, "NAME", JS_NewFloat64(ctx, VALUE));
        m = re.search(
            r'JS_SetPropertyStr\(ctx, global, "(\w+)",\s*JS_NewFloat64\(ctx, ([^)]+)\)\)',
            s)
        if m:
            name, value = m.group(1), m.group(2)
            const_js_parts.append(f'globalThis.{name}={value}')
            continue

        # Flush collected constants before non-constant lines if in registration
        if const_js_parts and not s.strip().startswith('JS_SetPropertyStr'):
            _flush_constants(out, const_js_parts)
            const_js_parts.clear()

        # Convert RL_REG/CLAY_REG/etc macro calls
        m = re.match(r'\s+(\w+)_REG\((\w+), (\w+), (\d+)\);', s)
        if m:
            macro_prefix = m.group(1)
            js_name, c_name, nargs = m.group(2), m.group(3), m.group(4)
            # Map macro prefix to function prefix
            _prefix_map = {'RL': 'rl', 'CLAY': 'clay', 'CTUI': 'clay_tui', 'UI': 'ui', 'GF': 'gf'}
            fn_prefix = _prefix_map.get(macro_prefix, 'rl')
            out.append(
                f'    taiyaki_full_runtime_register_fn(rt, "{js_name}", {len(js_name)}, '
                f'taiyaki_{fn_prefix}_{c_name}, {nargs}, NULL);')
            continue

        # Convert direct JS_SetPropertyStr + JS_NewCFunction registration
        m = re.search(
            r'JS_SetPropertyStr\(ctx, global, "(\w+)",\s*'
            r'JS_NewCFunction\(ctx, (js_\w+), "(\w+)", (\d+)\)\)',
            s)
        if m:
            js_name = m.group(1)
            c_func = m.group(2).replace('js_', 'taiyaki_', 1)
            nargs = m.group(4)
            out.append(
                f'    taiyaki_full_runtime_register_fn(rt, "{js_name}", {len(js_name)}, '
                f'{c_func}, {nargs}, NULL);')
            continue

        # Convert gamepad button/axis constant loops (skip all lines of C for-loops)
        if '{int i; for(i=0;i<' in s:
            if 'GAMEPAD_BUTTON' in s:
                out.append('    { static const char _gp[] = '
                           '"for(var i=0;i<16;i++)globalThis[\'GAMEPAD_BUTTON_\'+i]=i;'
                           'for(var i=0;i<6;i++)globalThis[\'GAMEPAD_AXIS_\'+i]=i";')
                out.append('      taiyaki_full_runtime_eval(rt, _gp, sizeof(_gp) - 1); }')
            continue
        # Skip orphaned loop body/close lines
        if s.strip().startswith('char name[') and 'snprintf' in s:
            continue
        if s.strip() == '}}':
            continue

        # Arg extraction: _rl_int(ctx, argv[N]) → (int)args[N].number
        s = re.sub(r'_rl_int\(ctx, argv\[(\d+)\]\)', r'(int)args[\1].number', s)
        # Arg extraction: _rl_dbl(ctx, argv[N]) → args[N].number
        s = re.sub(r'_rl_dbl\(ctx, argv\[(\d+)\]\)', r'args[\1].number', s)
        # String arg: "const char *VAR = JS_ToCString(ctx, argv[N]);" → "const char *VAR = args[N].string;"
        s = re.sub(r'const char \*(\w+) = JS_ToCString\(ctx, argv\[(\d+)\]\)',
                   r'const char *\1 = args[\2].string', s)

        # Return conversions (use .+ to match nested parens)
        s = re.sub(r'return JS_UNDEFINED;', 'return 0.0;', s)
        s = re.sub(r'return JS_NewFloat64\(ctx, (.+)\);', r'return (double)(\1);', s)
        s = re.sub(r'return JS_NewBool\(ctx, (.+)\);', r'return (double)(\1);', s)
        # Remaining JS_SetPropertyStr with dynamic name (gamepad loops) — convert to eval
        m = re.search(r'JS_SetPropertyStr\(ctx, global, (\w+), JS_NewFloat64\(ctx, (\w+)\)\)', s)
        if m:
            # This is inside a loop — already handled above, skip
            continue

        # JS_ToBool(ctx, argv[N]) → (int)args[N].number
        s = re.sub(r'JS_ToBool\(ctx, argv\[(\d+)\]\)', r'(int)args[\1].number', s)
        # JS_ToFloat64 with declaration: "double v; JS_ToFloat64(ctx, &v, argv[N]);" → "double v = args[N].number;"
        s = re.sub(r'double (\w+);\s*JS_ToFloat64\(ctx, &\1, argv\[(\d+)\]\)', r'double \1 = args[\2].number', s)
        # JS_ToFloat64 standalone: "JS_ToFloat64(ctx, &VAR, argv[N]);" → "VAR = args[N].number;"
        s = re.sub(r'\s*JS_ToFloat64\(ctx, &(\w+), argv\[(\d+)\]\);', r' \1 = args[\2].number;', s)
        # JS_NewObject/JS_NewInt32/JS_NewString etc. remaining patterns
        s = re.sub(r'JS_NewFloat64\(ctx, ([^)]+)\)', r'(double)(\1)', s)
        s = re.sub(r'JS_NewBool\(ctx, ([^)]+)\)', r'(double)(\1)', s)
        s = re.sub(r'JS_NewInt32\(ctx, ([^)]+)\)', r'(double)(\1)', s)
        # JS_NewString — string returns not supported via f64, skip and return 0.0
        if 'JS_NewString(ctx,' in s:
            if s.strip().startswith('JSValue'):
                # "JSValue ret = JS_NewString(ctx, ...);" → skip, next "return ret;" handled below
                continue
            elif s.strip().startswith('return JS_NewString'):
                s = '    return 0.0; /* string return */'
        # "return ret;" after skipped JS_NewString assignment
        if s.strip() == 'return ret;':
            s = '    return 0.0; /* string return */'
        # argv[N] → args[N].number (catch-all for any remaining argv references)
        s = re.sub(r'argv\[(\d+)\]', r'args[\1].number', s)

        out.append(s)

    # Flush any remaining constants
    if const_js_parts:
        _flush_constants(out, const_js_parts)

    return out


def _flush_constants(out: list[str], parts: list[str]):
    """Emit taiyaki_full_runtime_eval for batched constant definitions."""
    # Split into chunks of ~40 to avoid oversized string literals
    chunk_size = 40
    for i in range(0, len(parts), chunk_size):
        chunk = parts[i:i + chunk_size]
        js_code = ";".join(chunk)
        escaped = js_code.replace('\\', '\\\\').replace('"', '\\"')
        out.append('    {')
        out.append(f'        static const char _c[] = "{escaped}";')
        out.append(f'        taiyaki_full_runtime_eval(rt, _c, sizeof(_c) - 1);')
        out.append('    }')


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
        """Generate a wrapper for an AOT-compiled function.

        Uses TaiyakiHostFnGeneric (TaiyakiArg *) when any param is a string,
        otherwise uses TaiyakiAotFnF64 (double *) for the fast path.
        """
        has_strings = any(isinstance(p.type, StringType) for p in func.params)
        lines = []

        if has_strings:
            # Generic wrapper: receives TaiyakiArg (supports strings)
            lines.append(
                f'static double tsuchi_wrap_{func.name}(const struct TaiyakiArg *args, '
                f'uintptr_t argc, void *user_data) {{'
            )
            args_str = ", ".join(
                f'args[{i}].string' if isinstance(p.type, StringType)
                else f'(int)(args[{i}].number)' if isinstance(p.type, BooleanType)
                else f'args[{i}].number'
                for i, p in enumerate(func.params)
            )
        else:
            # Fast f64 wrapper
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
        elif isinstance(func.return_type, StringType):
            lines.append(f'    const char *result = _tsuchi_{func.name}({args_str});')
            lines.append('    return 0.0; /* string return — accessible via fallback */')
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

        # Register native bindings (raylib, clay, UI, game framework, FFI)
        if self._uses_raylib:
            lines.append('    taiyaki_add_raylib_builtins(_tsuchi_rt);')
        if self._uses_clay:
            lines.append('    taiyaki_add_clay_builtins(_tsuchi_rt);')
        if self._uses_clay_tui:
            lines.append('    taiyaki_add_clay_tui_builtins(_tsuchi_rt);')
        if self._uses_ui:
            lines.append('    taiyaki_add_ui_builtins(_tsuchi_rt);')
        if self._uses_gf:
            lines.append('    taiyaki_add_gf_builtins(_tsuchi_rt);')
        if self._ffi_info is not None and (self._ffi_info.functions or self._ffi_info.structs or self._ffi_info.opaque_classes):
            lines.append('    taiyaki_add_ffi_builtins(_tsuchi_rt);')
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
            has_strings = any(isinstance(p.type, StringType) for p in func.params)
            reg_fn = "taiyaki_full_runtime_register_fn" if has_strings else "taiyaki_full_runtime_register_fn_f64"
            lines.append(
                f'    {reg_fn}(_tsuchi_rt, "{func.name}", {len(func.name)}, '
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

    # --- Bindings (converted from QuickJS backend via _convert_qjs_to_taiyaki) ---

    def _generate_cli_bindings(self) -> list[str]:
        return ['/* CLI builtins provided by taiyaki runtime */']

    def _generate_http_shell_bindings(self) -> list[str]:
        return ['/* HTTP/shell builtins provided by taiyaki runtime */']

    def _get_qjs_backend(self):
        """Get a QuickJS backend instance to extract binding code from."""
        from tsuchi.codegen.quickjs_backend import QuickJSBackend
        qjs = QuickJSBackend.__new__(QuickJSBackend)
        # Copy relevant state
        qjs._uses_raylib = self._uses_raylib
        qjs._uses_clay = self._uses_clay
        qjs._uses_clay_tui = self._uses_clay_tui
        qjs._uses_ui = self._uses_ui
        qjs._uses_gf = self._uses_gf
        qjs._ffi_info = self._ffi_info
        return qjs

    def _convert_reg_prefix(self, lines: list[str], prefix: str) -> list[str]:
        """Fix all taiyaki_rl_ prefixes to the correct one (e.g. taiyaki_ctui_)."""
        result = []
        for line in lines:
            line = line.replace('taiyaki_rl_', f'taiyaki_{prefix}_')
            result.append(line)
        return result

    def _generate_raylib_bindings(self) -> list[str]:
        if not self._uses_raylib:
            return []
        qjs = self._get_qjs_backend()
        return _convert_qjs_to_taiyaki(qjs._generate_raylib_bindings())

    def _generate_clay_bindings(self) -> list[str]:
        if not self._uses_clay:
            return []
        qjs = self._get_qjs_backend()
        converted = _convert_qjs_to_taiyaki(qjs._generate_clay_bindings())
        return self._convert_reg_prefix(converted, 'clay')

    def _generate_clay_tui_bindings(self) -> list[str]:
        if not self._uses_clay_tui:
            return []
        qjs = self._get_qjs_backend()
        converted = _convert_qjs_to_taiyaki(qjs._generate_clay_tui_bindings())
        return self._convert_reg_prefix(converted, 'clay_tui')

    def _generate_ui_bindings(self) -> list[str]:
        if not self._uses_ui:
            return []
        qjs = self._get_qjs_backend()
        converted = _convert_qjs_to_taiyaki(qjs._generate_ui_bindings())
        return self._convert_reg_prefix(converted, 'ui')

    def _generate_gf_bindings(self) -> list[str]:
        if not self._uses_gf:
            return []
        qjs = self._get_qjs_backend()
        converted = _convert_qjs_to_taiyaki(qjs._generate_gf_bindings())
        return self._convert_reg_prefix(converted, 'gf')

    def _generate_ffi_bindings(self) -> list[str]:
        if self._ffi_info is None:
            return []
        qjs = self._get_qjs_backend()
        converted = _convert_qjs_to_taiyaki(qjs._generate_ffi_bindings())
        return self._convert_reg_prefix(converted, 'ffi')
