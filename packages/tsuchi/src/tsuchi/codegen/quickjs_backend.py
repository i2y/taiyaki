"""QuickJS-NG backend: LLVM IR → standalone binary.

Compiles LLVM IR to object code, generates a C init wrapper with QuickJS-NG
runtime initialization, and links everything into a standalone executable.
"""

from __future__ import annotations

from pathlib import Path

from tsuchi.codegen.backend_base import BackendBase, _PROJECT_ROOT
from tsuchi.hir.nodes import HIRModule, HIRFunction
from tsuchi.type_checker.types import NumberType, BooleanType, StringType, VoidType, ObjectType, ArrayType, FunctionType, MonoType

# QuickJS-NG paths (relative to project root)
_QJS_INCLUDE = _PROJECT_ROOT / "vendor" / "quickjs-ng"
_QJS_LIB = _PROJECT_ROOT / "vendor" / "quickjs-ng" / "build"


class QuickJSBackend(BackendBase):
    """Compiles LLVM IR + C init wrapper + QuickJS-NG into a standalone binary."""

    def _engine_headers(self) -> list[str]:
        return ['#include "quickjs.h"']

    def _engine_include_flags(self) -> list[str]:
        return [f"-I{_QJS_INCLUDE}"]

    def _engine_link_flags(self) -> list[str]:
        return [f"-L{_QJS_LIB}", "-lqjs"]

    def _engine_global_state(self, has_fallbacks: bool) -> list[str]:
        if has_fallbacks:
            return ['static JSContext *tsuchi_ctx = NULL;', '']
        return []

    def _engine_console_log(self) -> list[str]:
        return [
            '/* console.log implementation */',
            'static JSValue js_console_log(JSContext *ctx, JSValueConst this_val,',
            '                              int argc, JSValueConst *argv) {',
            '    for (int i = 0; i < argc; i++) {',
            '        if (i > 0) putchar(\' \');',
            '        if (JS_IsBool(argv[i])) {',
            '            printf("%s", JS_ToBool(ctx, argv[i]) ? "true" : "false");',
            '        } else if (JS_IsNumber(argv[i])) {',
            '            double val;',
            '            JS_ToFloat64(ctx, &val, argv[i]);',
            '            if (val == (double)(long long)val && val >= -1e15 && val <= 1e15)',
            '                printf("%lld", (long long)val);',
            '            else',
            '                printf("%g", val);',
            '        } else {',
            '            const char *str = JS_ToCString(ctx, argv[i]);',
            '            if (str) { printf("%s", str); JS_FreeCString(ctx, str); }',
            '        }',
            '    }',
            '    putchar(\'\\n\');',
            '    return JS_UNDEFINED;',
            '}',
            '',
            'static void js_add_console(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '    JSValue console = JS_NewObject(ctx);',
            '    JS_SetPropertyStr(ctx, console, "log",',
            '        JS_NewCFunction(ctx, js_console_log, "log", 1));',
            '    JS_SetPropertyStr(ctx, console, "error",',
            '        JS_NewCFunction(ctx, js_console_log, "error", 1));',
            '    JS_SetPropertyStr(ctx, console, "warn",',
            '        JS_NewCFunction(ctx, js_console_log, "warn", 1));',
            '    JS_SetPropertyStr(ctx, global, "console", console);',
            '    JS_FreeValue(ctx, global);',
            '}',
            '',
        ]

    def _generate_fallback_bridges(self, hir_module: HIRModule) -> list[str]:
        """Generate C bridge functions that call QuickJS-evaluated fallback functions."""
        lines = ['/* Fallback bridge functions for non-compilable functions */']
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

            # All params are double (numeric bridge)
            params_c = ", ".join(f"double arg{i}" for i in range(info.param_count))
            if not params_c:
                params_c = "void"

            lines.append(f'{c_ret} _tsuchi_fb_{name}({params_c}) {{')
            lines.append('    JSValue global = JS_GetGlobalObject(tsuchi_ctx);')
            lines.append(f'    JSValue fn = JS_GetPropertyStr(tsuchi_ctx, global, "{name}");')

            if info.param_count > 0:
                lines.append(f'    JSValue args[{info.param_count}];')
                for i in range(info.param_count):
                    lines.append(f'    args[{i}] = JS_NewFloat64(tsuchi_ctx, arg{i});')
                lines.append(f'    JSValue result = JS_Call(tsuchi_ctx, fn, JS_UNDEFINED, {info.param_count}, args);')
            else:
                lines.append('    JSValue result = JS_Call(tsuchi_ctx, fn, JS_UNDEFINED, 0, NULL);')

            if ret_hint == "void":
                pass  # no return value to extract
            elif ret_hint == "string":
                lines.append('    const char *s = "";')
                lines.append('    if (!JS_IsException(result)) {')
                lines.append('        const char *tmp = JS_ToCString(tsuchi_ctx, result);')
                lines.append('        if (tmp) {')
                lines.append('            char *copy = (char*)malloc(strlen(tmp) + 1);')
                lines.append('            strcpy(copy, tmp);')
                lines.append('            s = copy;')
                lines.append('            JS_FreeCString(tsuchi_ctx, tmp);')
                lines.append('        }')
                lines.append('    }')
            elif ret_hint == "boolean":
                lines.append('    int ret = 0;')
                lines.append('    if (!JS_IsException(result)) ret = JS_ToBool(tsuchi_ctx, result);')
            else:
                lines.append('    double ret = 0.0;')
                lines.append('    if (!JS_IsException(result)) JS_ToFloat64(tsuchi_ctx, &ret, result);')

            lines.append('    JS_FreeValue(tsuchi_ctx, result);')
            lines.append('    JS_FreeValue(tsuchi_ctx, fn);')
            lines.append('    JS_FreeValue(tsuchi_ctx, global);')

            if ret_hint == "void":
                pass
            elif ret_hint == "string":
                lines.append('    return s;')
            else:
                lines.append('    return ret;')

            lines.append('}')
            lines.append('')
        return lines

    def _generate_wrapper(self, func: HIRFunction) -> list[str]:
        """Generate a wrapper function bridging native <-> QuickJS calling convention for a native function."""
        lines = []
        lines.append(
            f'static JSValue tsuchi_wrap_{func.name}(JSContext *ctx, JSValueConst this_val, '
            f'int argc, JSValueConst *argv) {{'
        )

        # Unbox arguments
        for i, p in enumerate(func.params):
            if isinstance(p.type, NumberType):
                lines.append(f'    double arg_{i};')
                lines.append(f'    JS_ToFloat64(ctx, &arg_{i}, argv[{i}]);')
            elif isinstance(p.type, BooleanType):
                lines.append(f'    int arg_{i} = JS_ToBool(ctx, argv[{i}]);')
            elif isinstance(p.type, StringType):
                lines.append(f'    const char *arg_{i} = JS_ToCString(ctx, argv[{i}]);')
            elif isinstance(p.type, ArrayType):
                lines.append(f'    TsuchiArray *arg_{i};')
                lines.append('    {')
                lines.append(f'        JSValue len_val = JS_GetPropertyStr(ctx, argv[{i}], "length");')
                lines.append(f'        int len; JS_ToInt32(ctx, &len, len_val);')
                lines.append(f'        JS_FreeValue(ctx, len_val);')
                lines.append(f'        arg_{i} = tsuchi_array_new(len);')
                lines.append(f'        for (int j = 0; j < len; j++) {{')
                lines.append(f'            JSValue elem = JS_GetPropertyUint32(ctx, argv[{i}], j);')
                lines.append(f'            double v; JS_ToFloat64(ctx, &v, elem);')
                lines.append(f'            tsuchi_array_set(arg_{i}, j, v);')
                lines.append(f'            JS_FreeValue(ctx, elem);')
                lines.append(f'        }}')
                lines.append('    }')
            elif isinstance(p.type, ObjectType):
                struct_name = self._struct_c_name(p.type)
                lines.append(f'    {struct_name} arg_{i};')
                lines.append('    {')
                lines.append('        JSValue prop;')
                for fname, ftype in sorted(p.type.fields.items()):
                    lines.append(f'        prop = JS_GetPropertyStr(ctx, argv[{i}], "{fname}");')
                    if isinstance(ftype, NumberType):
                        lines.append(f'        JS_ToFloat64(ctx, &arg_{i}.{fname}, prop);')
                    elif isinstance(ftype, BooleanType):
                        lines.append(f'        arg_{i}.{fname} = JS_ToBool(ctx, prop);')
                    lines.append(f'        JS_FreeValue(ctx, prop);')
                lines.append('    }')
            else:
                lines.append(f'    double arg_{i};')
                lines.append(f'    JS_ToFloat64(ctx, &arg_{i}, argv[{i}]);')

        # Call native function
        args_str = ", ".join(f'arg_{i}' for i in range(len(func.params)))

        if isinstance(func.return_type, VoidType):
            lines.append(f'    _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            lines.append('    return JS_UNDEFINED;')
        elif isinstance(func.return_type, NumberType):
            lines.append(f'    double result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            lines.append('    return JS_NewFloat64(ctx, result);')
        elif isinstance(func.return_type, BooleanType):
            lines.append(f'    int result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            lines.append('    return JS_NewBool(ctx, result);')
        elif isinstance(func.return_type, StringType):
            lines.append(f'    const char *result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            lines.append('    return JS_NewString(ctx, result);')
        elif isinstance(func.return_type, ObjectType):
            struct_name = self._struct_c_name(func.return_type)
            lines.append(f'    {struct_name} result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            lines.append('    JSValue ret = JS_NewObject(ctx);')
            for fname, ftype in sorted(func.return_type.fields.items()):
                if isinstance(ftype, NumberType):
                    lines.append(f'    JS_SetPropertyStr(ctx, ret, "{fname}", JS_NewFloat64(ctx, result.{fname}));')
                elif isinstance(ftype, BooleanType):
                    lines.append(f'    JS_SetPropertyStr(ctx, ret, "{fname}", JS_NewBool(ctx, result.{fname}));')
            lines.append('    return ret;')
        elif isinstance(func.return_type, ArrayType):
            lines.append(f'    TsuchiArray *result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            # Convert TsuchiArray* to JS array
            lines.append('    JSValue ret = JS_NewArray(ctx);')
            lines.append('    for (int i = 0; i < result->length; i++) {')
            lines.append('        JS_SetPropertyUint32(ctx, ret, i, JS_NewFloat64(ctx, result->data[i]));')
            lines.append('    }')
            lines.append('    return ret;')
        else:
            lines.append(f'    double result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    JS_FreeCString(ctx, arg_{i});')
            lines.append('    return JS_NewFloat64(ctx, result);')

        lines.append('}')
        return lines

    def _generate_resize_callback(self, exported_funcs: list[HIRFunction]) -> list[str]:
        """Generate the resize frame callback (Clay live resize support)."""
        lines: list[str] = []
        # Resize frame callback (calls JS _resizeFrame if defined)
        if self._uses_clay:
            lines.append('/* Resize frame: called from GLFW refresh callback during live resize */')
            lines.append('extern void tsuchi_clay_set_resize_frame(void (*fn)(void));')
            lines.append('static JSContext *_tsuchi_resize_ctx = NULL;')
            lines.append('static void _tsuchi_resize_frame(void) {')
            lines.append('    if (!_tsuchi_resize_ctx) return;')
            lines.append('    JSValue global = JS_GetGlobalObject(_tsuchi_resize_ctx);')
            lines.append('    JSValue fn = JS_GetPropertyStr(_tsuchi_resize_ctx, global, "_resizeFrame");')
            lines.append('    if (JS_IsFunction(_tsuchi_resize_ctx, fn)) {')
            lines.append('        JSValue ret = JS_Call(_tsuchi_resize_ctx, fn, JS_UNDEFINED, 0, NULL);')
            lines.append('        if (JS_IsException(ret)) {')
            lines.append('            JSValue exc = JS_GetException(_tsuchi_resize_ctx);')
            lines.append('            JS_FreeValue(_tsuchi_resize_ctx, exc);')
            lines.append('        }')
            lines.append('        JS_FreeValue(_tsuchi_resize_ctx, ret);')
            lines.append('    }')
            lines.append('    JS_FreeValue(_tsuchi_resize_ctx, fn);')
            lines.append('    JS_FreeValue(_tsuchi_resize_ctx, global);')
            lines.append('}')
            lines.append('')
        return lines

    def _generate_engine_main(self, hir_module: HIRModule, exported_funcs: list[HIRFunction],
                              has_fallbacks: bool,
                              has_async: bool = False,
                              async_funcs: list[HIRFunction] | None = None) -> list[str]:
        """Generate the engine-specific main() body."""
        lines: list[str] = []
        if async_funcs is None:
            async_funcs = []

        # Note: global variables are defined directly in the LLVM module (load/store)

        # Build set of async function names for detecting async entry calls
        async_func_names = {f.name for f in async_funcs}

        # Generate main()
        lines.append('int main(int argc, char *argv[]) {')
        lines.append('    tsuchi_argc = argc;')
        lines.append('    tsuchi_argv = argv;')
        lines.append('')

        # Initialize event loop if async functions are present
        if has_async:
            lines.append('    tsuchi_loop_init();')
            lines.append('')

        # Check if there are any entry statements or fallbacks that need QuickJS
        # Async entry calls (e.g. main()) are handled directly in C, not via JS eval
        async_entry_calls, js_entry_stmts = self._split_entry_statements(
            hir_module.entry_statements, async_func_names
        )

        needs_qjs = bool(js_entry_stmts) or has_fallbacks

        if needs_qjs:
            lines.append('    JSRuntime *rt = JS_NewRuntime();')
            lines.append('    JSContext *ctx = JS_NewContext(rt);')
            if has_fallbacks:
                lines.append('    tsuchi_ctx = ctx;')
            lines.append('    js_add_console(ctx);')
            lines.append('    js_add_cli_builtins(ctx);')
            lines.append('    js_add_http_shell_builtins(ctx);')
            if self._uses_raylib:
                lines.append('    js_add_raylib_builtins(ctx);')
            if self._uses_clay:
                lines.append('    js_add_clay_builtins(ctx);')
            if self._uses_clay_tui:
                lines.append('    js_add_clay_tui_builtins(ctx);')
            if self._uses_ui:
                lines.append('    js_add_ui_builtins(ctx);')
            if self._uses_gf:
                lines.append('    js_add_gf_builtins(ctx);')
            if self._ffi_info is not None and (self._ffi_info.functions or self._ffi_info.structs or self._ffi_info.opaque_classes):
                lines.append('    js_add_ffi_builtins(ctx);')
            lines.append('')

            # Register compiled functions as global JS functions
            lines.append('    JSValue global = JS_GetGlobalObject(ctx);')
            for func in exported_funcs:
                nparams = len(func.params)
                lines.append(
                    f'    JS_SetPropertyStr(ctx, global, "{func.name}", '
                    f'JS_NewCFunction(ctx, tsuchi_wrap_{func.name}, "{func.name}", {nparams}));'
                )

            # Register import aliases so entry statements can use original names
            if hir_module.func_aliases:
                # Build reverse map: prefixed_name → alias for wrapper lookup
                reverse_aliases: dict[str, list[str]] = {}
                for alias, canonical in hir_module.func_aliases.items():
                    reverse_aliases.setdefault(canonical, []).append(alias)
                for func in exported_funcs:
                    for alias in reverse_aliases.get(func.name, []):
                        nparams = len(func.params)
                        lines.append(
                            f'    JS_SetPropertyStr(ctx, global, "{alias}", '
                            f'JS_NewCFunction(ctx, tsuchi_wrap_{func.name}, "{alias}", {nparams}));'
                        )

            lines.append('    JS_FreeValue(ctx, global);')
            lines.append('')

            # Register resize frame callback for live resize on macOS
            if self._uses_clay:
                lines.append('    _tsuchi_resize_ctx = ctx;')
                lines.append('    tsuchi_clay_set_resize_frame(_tsuchi_resize_frame);')
                lines.append('')

            # Eval fallback function sources
            if has_fallbacks:
                for name, fb_src in hir_module.fallback_sources.items():
                    escaped = self._escape_c_string(fb_src)
                    lines.append('    {')
                    lines.append(f'        JSValue _r = JS_Eval(ctx, "{escaped}", {len(fb_src.encode("utf-8"))}, "<fallback>", JS_EVAL_TYPE_GLOBAL);')
                    lines.append('        if (JS_IsException(_r)) {')
                    lines.append('            JSValue exc = JS_GetException(ctx);')
                    lines.append('            const char *str = JS_ToCString(ctx, exc);')
                    lines.append('            if (str) { fprintf(stderr, "Fallback eval error: %s\\n", str); JS_FreeCString(ctx, str); }')
                    lines.append('            JS_FreeValue(ctx, exc);')
                    lines.append('        }')
                    lines.append('        JS_FreeValue(ctx, _r);')
                    lines.append('    }')
                lines.append('')

            # Execute JS entry statements (non-async)
            for idx, entry_src in enumerate(js_entry_stmts):
                escaped = self._escape_c_string(entry_src)
                lines.append('    {')
                lines.append(f'        JSValue _r = JS_Eval(ctx, "{escaped}", {len(entry_src.encode("utf-8"))}, "<tsuchi>", JS_EVAL_TYPE_GLOBAL);')
                lines.append('        if (JS_IsException(_r)) {')
                lines.append('            JSValue exc = JS_GetException(ctx);')
                lines.append('            const char *str = JS_ToCString(ctx, exc);')
                lines.append('            if (str) { fprintf(stderr, "Error: %s\\n", str); JS_FreeCString(ctx, str); }')
                lines.append('            JS_FreeValue(ctx, exc);')
                lines.append('        }')
                lines.append('        JS_FreeValue(ctx, _r);')
                lines.append('    }')

            # Call async entry functions directly in C
            if async_entry_calls:
                lines.append('')
                lines.append('    /* Async entry calls (direct C invocation) */')
                for fname in async_entry_calls:
                    lines.append(f'    _tsuchi_{fname}();')

            # Run event loop if async
            if has_async:
                lines.append('')
                lines.append('    tsuchi_loop_run();')
                lines.append('    tsuchi_loop_close();')

            lines.append('')
            if has_fallbacks:
                lines.append('    tsuchi_ctx = NULL;')
            lines.append('    JS_FreeContext(ctx);')
            lines.append('    JS_FreeRuntime(rt);')
        else:
            if has_async:
                # Async-only mode — no QuickJS needed, just call async entry points
                lines.append('    /* Async native mode — no QuickJS runtime */')
                for fname in async_entry_calls:
                    lines.append(f'    _tsuchi_{fname}();')
                lines.append('')
                lines.append('    tsuchi_loop_run();')
                lines.append('    tsuchi_loop_close();')
            else:
                # Pure native mode — no QuickJS runtime needed
                # Directly call the entry function if there is one, or emit a comment
                lines.append('    /* Pure native mode — no QuickJS runtime */')
                # If there's a main() or entry function, call it
                for func in exported_funcs:
                    if func.name == "main":
                        lines.append(f'    _tsuchi_main();')

        lines.append('    return 0;')
        lines.append('}')

        return lines

    def _generate_cli_bindings(self) -> list[str]:
        """Generate QuickJS-side C functions for CLI builtins (entry statement support)."""
        return [
            '/* QuickJS bindings for CLI builtins */',
            'static JSValue js_readFile(JSContext *ctx, JSValueConst this_val,',
            '                           int argc, JSValueConst *argv) {',
            '    const char *path = JS_ToCString(ctx, argv[0]);',
            '    if (!path) return JS_EXCEPTION;',
            '    char *content = tsuchi_readFile(path);',
            '    JS_FreeCString(ctx, path);',
            '    JSValue result = JS_NewString(ctx, content);',
            '    free(content);',
            '    return result;',
            '}',
            '',
            'static JSValue js_writeFile(JSContext *ctx, JSValueConst this_val,',
            '                            int argc, JSValueConst *argv) {',
            '    const char *path = JS_ToCString(ctx, argv[0]);',
            '    const char *content = JS_ToCString(ctx, argv[1]);',
            '    if (path && content) tsuchi_writeFile(path, content);',
            '    if (path) JS_FreeCString(ctx, path);',
            '    if (content) JS_FreeCString(ctx, content);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            'static JSValue js_getenv(JSContext *ctx, JSValueConst this_val,',
            '                         int argc, JSValueConst *argv) {',
            '    const char *name = JS_ToCString(ctx, argv[0]);',
            '    if (!name) return JS_EXCEPTION;',
            '    const char *val = tsuchi_getenv(name);',
            '    JS_FreeCString(ctx, name);',
            '    return JS_NewString(ctx, val);',
            '}',
            '',
            'static void js_add_cli_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '',
            '    // readFile, writeFile',
            '    JS_SetPropertyStr(ctx, global, "readFile",',
            '        JS_NewCFunction(ctx, js_readFile, "readFile", 1));',
            '    JS_SetPropertyStr(ctx, global, "writeFile",',
            '        JS_NewCFunction(ctx, js_writeFile, "writeFile", 2));',
            '',
            '    // process object: argv + env proxy',
            '    JSValue process = JS_NewObject(ctx);',
            '',
            '    // process.argv',
            '    JSValue argv_arr = JS_NewArray(ctx);',
            '    for (int i = 0; i < tsuchi_argc; i++) {',
            '        JS_SetPropertyUint32(ctx, argv_arr, i, JS_NewString(ctx, tsuchi_argv[i]));',
            '    }',
            '    JS_SetPropertyStr(ctx, process, "argv", argv_arr);',
            '',
            '    // process.exit',
            '    // (already works via compiled path, but add for entry statement use)',
            '',
            '    // process.env via Proxy',
            '    JS_SetPropertyStr(ctx, global, "__tsuchi_qjs_getenv",',
            '        JS_NewCFunction(ctx, js_getenv, "__tsuchi_qjs_getenv", 1));',
            '    const char *env_proxy_code = ',
            '        "globalThis.process.env = new Proxy({}, {"',
            '        "  get(t, name) { return __tsuchi_qjs_getenv(name); }"',
            '        "});";',
            '    JS_SetPropertyStr(ctx, global, "process", process);',
            '    JS_Eval(ctx, env_proxy_code, strlen(env_proxy_code), "<env>", JS_EVAL_TYPE_GLOBAL);',
            '',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]

    def _generate_raylib_bindings(self) -> list[str]:
        """Generate QuickJS-side bindings for raylib (entry-level statement support)."""
        if not self._uses_raylib:
            return []
        return [
            '// QuickJS raylib bindings for entry statements',
            '#define RL_QJS_FUNC(name, cname, argc) \\',
            '    static JSValue js_rl_##name(JSContext *ctx, JSValueConst this_val, \\',
            '                                int _argc, JSValueConst *argv)',
            '',
            '// Helper: get int arg',
            'static int _rl_int(JSContext *ctx, JSValueConst v) {',
            '    double d; JS_ToFloat64(ctx, &d, v); return (int)d;',
            '}',
            'static double _rl_dbl(JSContext *ctx, JSValueConst v) {',
            '    double d; JS_ToFloat64(ctx, &d, v); return d;',
            '}',
            '',
            '// Core window',
            'static JSValue js_rl_initWindow(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    int w = _rl_int(ctx, argv[0]), h = _rl_int(ctx, argv[1]);',
            '    const char *t = JS_ToCString(ctx, argv[2]);',
            '    tsuchi_rl_initWindow(w, h, t);',
            '    JS_FreeCString(ctx, t);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_closeWindow(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_closeWindow(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_windowShouldClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_windowShouldClose());',
            '}',
            'static JSValue js_rl_setTargetFPS(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setTargetFPS(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_getScreenWidth(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getScreenWidth());',
            '}',
            'static JSValue js_rl_getScreenHeight(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getScreenHeight());',
            '}',
            'static JSValue js_rl_getFrameTime(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getFrameTime());',
            '}',
            'static JSValue js_rl_getTime(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getTime());',
            '}',
            'static JSValue js_rl_getFPS(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getFPS());',
            '}',
            '',
            '// Drawing',
            'static JSValue js_rl_beginDrawing(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_beginDrawing(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_endDrawing(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_endDrawing(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_clearBackground(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_clearBackground(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawRectangle(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawRectangle(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '                           _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawRectangleLines(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawRectangleLines(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '                                _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawCircle(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawCircle(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '                        _rl_dbl(ctx, argv[2]), _rl_int(ctx, argv[3]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawCircleLines(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawCircleLines(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '                             _rl_dbl(ctx, argv[2]), _rl_int(ctx, argv[3]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawLine(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawLine(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '                      _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawText(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *t = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_rl_drawText(t, _rl_int(ctx, argv[1]), _rl_int(ctx, argv[2]),',
            '                       _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    JS_FreeCString(ctx, t);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_measureText(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *t = JS_ToCString(ctx, argv[0]);',
            '    int w = tsuchi_rl_measureText(t, _rl_int(ctx, argv[1]));',
            '    JS_FreeCString(ctx, t);',
            '    return JS_NewFloat64(ctx, w);',
            '}',
            '',
            '// Input: keyboard',
            'static JSValue js_rl_isKeyDown(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isKeyDown(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_isKeyPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isKeyPressed(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_isKeyReleased(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isKeyReleased(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getKeyPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getKeyPressed());',
            '}',
            '',
            '// Input: mouse',
            'static JSValue js_rl_getMouseX(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getMouseX());',
            '}',
            'static JSValue js_rl_getMouseY(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getMouseY());',
            '}',
            'static JSValue js_rl_isMouseButtonDown(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isMouseButtonDown(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_isMouseButtonPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isMouseButtonPressed(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_isMouseButtonReleased(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isMouseButtonReleased(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getMouseWheelMove(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getMouseWheelMove());',
            '}',
            '',
            '// Extended input (Phase 3)',
            'static JSValue js_rl_getCharPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getCharPressed());',
            '}',
            'static JSValue js_rl_isKeyUp(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isKeyUp(_rl_int(ctx, argv[0])));',
            '}',
            '',
            '// Font',
            'static JSValue js_rl_loadFont(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *p = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_rl_loadFont(p, _rl_int(ctx, argv[1]));',
            '    JS_FreeCString(ctx, p);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Color helper',
            'static JSValue js_rl_color(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_color(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '                                              _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3])));',
            '}',
            'static JSValue js_rl_colorAlpha(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_colorAlpha(_rl_int(ctx, argv[0]), _rl_dbl(ctx, argv[1])));',
            '}',
            '',
            '// Window extended (Phase 3)',
            'static JSValue js_rl_toggleFullscreen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_toggleFullscreen(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setWindowSize(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setWindowSize(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setWindowTitle(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *t = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_rl_setWindowTitle(t);',
            '    JS_FreeCString(ctx, t);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setConfigFlags(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setConfigFlags(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_isWindowFocused(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isWindowFocused());',
            '}',
            'static JSValue js_rl_isWindowResized(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isWindowResized());',
            '}',
            '',
            '// Extended shapes (Phase 3)',
            'static JSValue js_rl_drawRectanglePro(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawRectanglePro(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5]),',
            '        _rl_dbl(ctx, argv[6]), _rl_int(ctx, argv[7]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawRectangleRounded(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawRectangleRounded(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawRectangleGradientV(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawRectangleGradientV(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]),',
            '        _rl_int(ctx, argv[4]), _rl_int(ctx, argv[5]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawRectangleGradientH(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawRectangleGradientH(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]),',
            '        _rl_int(ctx, argv[4]), _rl_int(ctx, argv[5]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawLineEx(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawLineEx(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_int(ctx, argv[5]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawPixel(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawPixel(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]), _rl_int(ctx, argv[2]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawCircleSector(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawCircleSector(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]));',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Text Pro (Phase 3)',
            'static JSValue js_rl_drawTextEx(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *t = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_rl_drawTextEx(t, _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]),',
            '                        _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4]), _rl_int(ctx, argv[5]));',
            '    JS_FreeCString(ctx, t);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_measureTextEx(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *t = JS_ToCString(ctx, argv[0]);',
            '    int w = tsuchi_rl_measureTextEx(t, _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]));',
            '    JS_FreeCString(ctx, t);',
            '    return JS_NewFloat64(ctx, w);',
            '}',
            '',
            '// Audio (Phase 1)',
            'static JSValue js_rl_initAudioDevice(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_initAudioDevice(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_closeAudioDevice(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_closeAudioDevice(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setMasterVolume(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setMasterVolume(_rl_dbl(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_getMasterVolume(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getMasterVolume());',
            '}',
            'static JSValue js_rl_loadSound(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *p = JS_ToCString(ctx, argv[0]);',
            '    int id = tsuchi_rl_loadSound(p);',
            '    JS_FreeCString(ctx, p);',
            '    return JS_NewFloat64(ctx, id);',
            '}',
            'static JSValue js_rl_playSound(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_playSound(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_stopSound(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_stopSound(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_pauseSound(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_pauseSound(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_resumeSound(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_resumeSound(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setSoundVolume(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setSoundVolume(_rl_int(ctx, argv[0]), _rl_dbl(ctx, argv[1])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setSoundPitch(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setSoundPitch(_rl_int(ctx, argv[0]), _rl_dbl(ctx, argv[1])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_isSoundPlaying(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isSoundPlaying(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_unloadSound(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_unloadSound(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_loadMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *p = JS_ToCString(ctx, argv[0]);',
            '    int id = tsuchi_rl_loadMusic(p);',
            '    JS_FreeCString(ctx, p);',
            '    return JS_NewFloat64(ctx, id);',
            '}',
            'static JSValue js_rl_playMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_playMusic(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_stopMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_stopMusic(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_pauseMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_pauseMusic(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_resumeMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_resumeMusic(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_updateMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_updateMusic(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setMusicVolume(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setMusicVolume(_rl_int(ctx, argv[0]), _rl_dbl(ctx, argv[1])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_isMusicPlaying(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isMusicPlaying(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getMusicTimeLength(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getMusicTimeLength(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getMusicTimePlayed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getMusicTimePlayed(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_unloadMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_unloadMusic(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            '',
            '// Camera2D (Phase 2)',
            'static JSValue js_rl_beginMode2D(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_beginMode2D(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_endMode2D(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_endMode2D(); return JS_UNDEFINED;',
            '}',
            '',
            '// Collision (Phase 2)',
            'static JSValue js_rl_checkCollisionRecs(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_checkCollisionRecs(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5]), _rl_dbl(ctx, argv[6]), _rl_dbl(ctx, argv[7])));',
            '}',
            'static JSValue js_rl_checkCollisionCircles(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_checkCollisionCircles(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]),',
            '        _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5])));',
            '}',
            'static JSValue js_rl_checkCollisionCircleRec(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_checkCollisionCircleRec(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]),',
            '        _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5]), _rl_dbl(ctx, argv[6])));',
            '}',
            'static JSValue js_rl_checkCollisionPointRec(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_checkCollisionPointRec(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5])));',
            '}',
            'static JSValue js_rl_checkCollisionPointCircle(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_checkCollisionPointCircle(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4])));',
            '}',
            'static JSValue js_rl_getRandomValue(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getRandomValue(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])));',
            '}',
            '',
            '// Gamepad (Phase 5)',
            'static JSValue js_rl_isGamepadAvailable(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isGamepadAvailable(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_isGamepadButtonDown(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isGamepadButtonDown(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])));',
            '}',
            'static JSValue js_rl_isGamepadButtonPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isGamepadButtonPressed(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])));',
            '}',
            'static JSValue js_rl_isGamepadButtonReleased(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isGamepadButtonReleased(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])));',
            '}',
            'static JSValue js_rl_getGamepadAxisMovement(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getGamepadAxisMovement(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])));',
            '}',
            'static JSValue js_rl_getGamepadAxisCount(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getGamepadAxisCount(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getGamepadButtonPressedQJS(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getGamepadButtonPressed());',
            '}',
            '',
            '// Music extended',
            'static JSValue js_rl_seekMusic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_seekMusic(_rl_int(ctx, argv[0]), _rl_dbl(ctx, argv[1])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_setMusicPitch(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_setMusicPitch(_rl_int(ctx, argv[0]), _rl_dbl(ctx, argv[1])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_isAudioDeviceReady(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isAudioDeviceReady());',
            '}',
            'static JSValue js_rl_unloadFont(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_unloadFont(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_measureTextExY(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *t = JS_ToCString(ctx, argv[0]);',
            '    int h = tsuchi_rl_measureTextExY(t, _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]));',
            '    JS_FreeCString(ctx, t);',
            '    return JS_NewFloat64(ctx, h);',
            '}',
            'static JSValue js_rl_drawTextureScaled(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawTextureScaled(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_dbl(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_isTextureValid(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isTextureValid(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_loadTexture(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *p = JS_ToCString(ctx, argv[0]);',
            '    int id = tsuchi_rl_loadTexture(p);',
            '    JS_FreeCString(ctx, p);',
            '    return JS_NewFloat64(ctx, id);',
            '}',
            'static JSValue js_rl_drawTexture(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawTexture(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawTextureRec(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawTextureRec(_rl_int(ctx, argv[0]),',
            '        _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4]),',
            '        _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]), _rl_int(ctx, argv[7]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_drawTexturePro(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_drawTexturePro(_rl_int(ctx, argv[0]),',
            '        _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]), _rl_dbl(ctx, argv[4]),',
            '        _rl_dbl(ctx, argv[5]), _rl_dbl(ctx, argv[6]), _rl_dbl(ctx, argv[7]), _rl_dbl(ctx, argv[8]),',
            '        _rl_dbl(ctx, argv[9]), _rl_dbl(ctx, argv[10]), _rl_dbl(ctx, argv[11]), _rl_int(ctx, argv[12]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_unloadTexture(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_rl_unloadTexture(_rl_int(ctx, argv[0]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_rl_getTextureWidth(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getTextureWidth(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getTextureHeight(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getTextureHeight(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_rl_getWorldToScreen2DX(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getWorldToScreen2DX(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5]),',
            '        _rl_dbl(ctx, argv[6]), _rl_dbl(ctx, argv[7])));',
            '}',
            'static JSValue js_rl_getWorldToScreen2DY(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_rl_getWorldToScreen2DY(',
            '        _rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_dbl(ctx, argv[4]), _rl_dbl(ctx, argv[5]),',
            '        _rl_dbl(ctx, argv[6]), _rl_dbl(ctx, argv[7])));',
            '}',
            'static JSValue js_rl_isGamepadButtonUp(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_rl_isGamepadButtonUp(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1])));',
            '}',
            'static JSValue js_rl_fileExists(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *p = JS_ToCString(ctx, argv[0]);',
            '    int r = tsuchi_rl_fileExists(p);',
            '    JS_FreeCString(ctx, p);',
            '    return JS_NewBool(ctx, r);',
            '}',
            'static JSValue js_rl_directoryExists(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *p = JS_ToCString(ctx, argv[0]);',
            '    int r = tsuchi_rl_directoryExists(p);',
            '    JS_FreeCString(ctx, p);',
            '    return JS_NewBool(ctx, r);',
            '}',
            '',
            '// Register all raylib bindings in QuickJS context',
            'static void js_add_raylib_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '',
            '    // Predefined color constants (packed RGBA)',
            '    JS_SetPropertyStr(ctx, global, "WHITE",     JS_NewFloat64(ctx, 0xFFFFFFFF));',
            '    JS_SetPropertyStr(ctx, global, "BLACK",     JS_NewFloat64(ctx, 0x000000FF));',
            '    JS_SetPropertyStr(ctx, global, "RED",       JS_NewFloat64(ctx, 0xFF0000FF));',
            '    JS_SetPropertyStr(ctx, global, "GREEN",     JS_NewFloat64(ctx, 0x00FF00FF));',
            '    JS_SetPropertyStr(ctx, global, "BLUE",      JS_NewFloat64(ctx, 0x0000FFFF));',
            '    JS_SetPropertyStr(ctx, global, "YELLOW",    JS_NewFloat64(ctx, 0xFFFF00FF));',
            '    JS_SetPropertyStr(ctx, global, "ORANGE",    JS_NewFloat64(ctx, 0xFF8000FF));',
            '    JS_SetPropertyStr(ctx, global, "PURPLE",    JS_NewFloat64(ctx, 0x8000FFFF));',
            '    JS_SetPropertyStr(ctx, global, "GRAY",      JS_NewFloat64(ctx, 0x808080FF));',
            '    JS_SetPropertyStr(ctx, global, "DARKGRAY",  JS_NewFloat64(ctx, 0x505050FF));',
            '    JS_SetPropertyStr(ctx, global, "LIGHTGRAY", JS_NewFloat64(ctx, 0xC8C8C8FF));',
            '    JS_SetPropertyStr(ctx, global, "RAYWHITE",  JS_NewFloat64(ctx, 0xF5F5F5FF));',
            '    JS_SetPropertyStr(ctx, global, "BROWN",     JS_NewFloat64(ctx, 0x7F6347FF));',
            '    JS_SetPropertyStr(ctx, global, "PINK",      JS_NewFloat64(ctx, 0xFF6B9DFF));',
            '    JS_SetPropertyStr(ctx, global, "MAROON",    JS_NewFloat64(ctx, 0xBE2137FF));',
            '    JS_SetPropertyStr(ctx, global, "LIME",      JS_NewFloat64(ctx, 0x00E430FF));',
            '    JS_SetPropertyStr(ctx, global, "SKYBLUE",   JS_NewFloat64(ctx, 0x66BFFFFF));',
            '    JS_SetPropertyStr(ctx, global, "DARKBLUE",  JS_NewFloat64(ctx, 0x0082C8FF));',
            '    JS_SetPropertyStr(ctx, global, "VIOLET",    JS_NewFloat64(ctx, 0x7B69E0FF));',
            '    JS_SetPropertyStr(ctx, global, "BEIGE",     JS_NewFloat64(ctx, 0xD3B694FF));',
            '    JS_SetPropertyStr(ctx, global, "MAGENTA",   JS_NewFloat64(ctx, 0xFF00FFFF));',
            '    JS_SetPropertyStr(ctx, global, "GOLD",      JS_NewFloat64(ctx, 0xFFCB00FF));',
            '    JS_SetPropertyStr(ctx, global, "BLANK",     JS_NewFloat64(ctx, 0x00000000));',
            '    JS_SetPropertyStr(ctx, global, "DARKGREEN", JS_NewFloat64(ctx, 0x006400FF));',
            '    JS_SetPropertyStr(ctx, global, "DARKPURPLE",JS_NewFloat64(ctx, 0x702090FF));',
            '    JS_SetPropertyStr(ctx, global, "DARKBROWN", JS_NewFloat64(ctx, 0x4C3224FF));',
            '',
            '    // Key codes (raylib)',
            '    JS_SetPropertyStr(ctx, global, "KEY_RIGHT", JS_NewFloat64(ctx, 262));',
            '    JS_SetPropertyStr(ctx, global, "KEY_LEFT",  JS_NewFloat64(ctx, 263));',
            '    JS_SetPropertyStr(ctx, global, "KEY_DOWN",  JS_NewFloat64(ctx, 264));',
            '    JS_SetPropertyStr(ctx, global, "KEY_UP",    JS_NewFloat64(ctx, 265));',
            '    JS_SetPropertyStr(ctx, global, "KEY_SPACE", JS_NewFloat64(ctx, 32));',
            '    JS_SetPropertyStr(ctx, global, "KEY_ENTER", JS_NewFloat64(ctx, 257));',
            '    JS_SetPropertyStr(ctx, global, "KEY_ESCAPE",JS_NewFloat64(ctx, 256));',
            '    JS_SetPropertyStr(ctx, global, "KEY_A",     JS_NewFloat64(ctx, 65));',
            '    JS_SetPropertyStr(ctx, global, "KEY_B",     JS_NewFloat64(ctx, 66));',
            '    JS_SetPropertyStr(ctx, global, "KEY_C",     JS_NewFloat64(ctx, 67));',
            '    JS_SetPropertyStr(ctx, global, "KEY_D",     JS_NewFloat64(ctx, 68));',
            '    JS_SetPropertyStr(ctx, global, "KEY_E",     JS_NewFloat64(ctx, 69));',
            '    JS_SetPropertyStr(ctx, global, "KEY_F",     JS_NewFloat64(ctx, 70));',
            '    JS_SetPropertyStr(ctx, global, "KEY_G",     JS_NewFloat64(ctx, 71));',
            '    JS_SetPropertyStr(ctx, global, "KEY_H",     JS_NewFloat64(ctx, 72));',
            '    JS_SetPropertyStr(ctx, global, "KEY_I",     JS_NewFloat64(ctx, 73));',
            '    JS_SetPropertyStr(ctx, global, "KEY_J",     JS_NewFloat64(ctx, 74));',
            '    JS_SetPropertyStr(ctx, global, "KEY_K",     JS_NewFloat64(ctx, 75));',
            '    JS_SetPropertyStr(ctx, global, "KEY_L",     JS_NewFloat64(ctx, 76));',
            '    JS_SetPropertyStr(ctx, global, "KEY_M",     JS_NewFloat64(ctx, 77));',
            '    JS_SetPropertyStr(ctx, global, "KEY_N",     JS_NewFloat64(ctx, 78));',
            '    JS_SetPropertyStr(ctx, global, "KEY_O",     JS_NewFloat64(ctx, 79));',
            '    JS_SetPropertyStr(ctx, global, "KEY_P",     JS_NewFloat64(ctx, 80));',
            '    JS_SetPropertyStr(ctx, global, "KEY_Q",     JS_NewFloat64(ctx, 81));',
            '    JS_SetPropertyStr(ctx, global, "KEY_R",     JS_NewFloat64(ctx, 82));',
            '    JS_SetPropertyStr(ctx, global, "KEY_S",     JS_NewFloat64(ctx, 83));',
            '    JS_SetPropertyStr(ctx, global, "KEY_T",     JS_NewFloat64(ctx, 84));',
            '    JS_SetPropertyStr(ctx, global, "KEY_U",     JS_NewFloat64(ctx, 85));',
            '    JS_SetPropertyStr(ctx, global, "KEY_V",     JS_NewFloat64(ctx, 86));',
            '    JS_SetPropertyStr(ctx, global, "KEY_W",     JS_NewFloat64(ctx, 87));',
            '    JS_SetPropertyStr(ctx, global, "KEY_X",     JS_NewFloat64(ctx, 88));',
            '    JS_SetPropertyStr(ctx, global, "KEY_Y",     JS_NewFloat64(ctx, 89));',
            '    JS_SetPropertyStr(ctx, global, "KEY_Z",     JS_NewFloat64(ctx, 90));',
            '    JS_SetPropertyStr(ctx, global, "KEY_0",     JS_NewFloat64(ctx, 48));',
            '    JS_SetPropertyStr(ctx, global, "KEY_1",     JS_NewFloat64(ctx, 49));',
            '    JS_SetPropertyStr(ctx, global, "KEY_2",     JS_NewFloat64(ctx, 50));',
            '    JS_SetPropertyStr(ctx, global, "KEY_3",     JS_NewFloat64(ctx, 51));',
            '    JS_SetPropertyStr(ctx, global, "KEY_4",     JS_NewFloat64(ctx, 52));',
            '    JS_SetPropertyStr(ctx, global, "KEY_5",     JS_NewFloat64(ctx, 53));',
            '    JS_SetPropertyStr(ctx, global, "KEY_6",     JS_NewFloat64(ctx, 54));',
            '    JS_SetPropertyStr(ctx, global, "KEY_7",     JS_NewFloat64(ctx, 55));',
            '    JS_SetPropertyStr(ctx, global, "KEY_8",     JS_NewFloat64(ctx, 56));',
            '    JS_SetPropertyStr(ctx, global, "KEY_9",     JS_NewFloat64(ctx, 57));',
            '',
            '    // Mouse buttons',
            '    JS_SetPropertyStr(ctx, global, "MOUSE_LEFT",   JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "MOUSE_RIGHT",  JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "MOUSE_MIDDLE", JS_NewFloat64(ctx, 2));',
            '',
            '    // Gamepad button constants (Phase 5)',
            '    {int i; for(i=0;i<16;i++){',
            '        char name[32]; snprintf(name,sizeof(name),"GAMEPAD_BUTTON_%d",i);',
            '        JS_SetPropertyStr(ctx, global, name, JS_NewFloat64(ctx, i));',
            '    }}',
            '    {int i; for(i=0;i<6;i++){',
            '        char name[32]; snprintf(name,sizeof(name),"GAMEPAD_AXIS_%d",i);',
            '        JS_SetPropertyStr(ctx, global, name, JS_NewFloat64(ctx, i));',
            '    }}',
            '',
            '    // Window config flags (Phase 3)',
            '    JS_SetPropertyStr(ctx, global, "FLAG_FULLSCREEN_MODE",   JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "FLAG_WINDOW_RESIZABLE",  JS_NewFloat64(ctx, 4));',
            '    JS_SetPropertyStr(ctx, global, "FLAG_WINDOW_UNDECORATED",JS_NewFloat64(ctx, 8));',
            '    JS_SetPropertyStr(ctx, global, "FLAG_WINDOW_TRANSPARENT",JS_NewFloat64(ctx, 16));',
            '    JS_SetPropertyStr(ctx, global, "FLAG_MSAA_4X_HINT",     JS_NewFloat64(ctx, 32));',
            '    JS_SetPropertyStr(ctx, global, "FLAG_VSYNC_HINT",       JS_NewFloat64(ctx, 64));',
            '    JS_SetPropertyStr(ctx, global, "FLAG_WINDOW_HIGHDPI",  JS_NewFloat64(ctx, 8192));',
            '',
            '    // Functions',
            '#define RL_REG(jsName, cFunc, nargs) \\',
            '    JS_SetPropertyStr(ctx, global, #jsName, JS_NewCFunction(ctx, js_rl_##cFunc, #jsName, nargs))',
            '',
            '    // Core window',
            '    RL_REG(initWindow, initWindow, 3);',
            '    RL_REG(closeWindow, closeWindow, 0);',
            '    RL_REG(windowShouldClose, windowShouldClose, 0);',
            '    RL_REG(setTargetFPS, setTargetFPS, 1);',
            '    RL_REG(getScreenWidth, getScreenWidth, 0);',
            '    RL_REG(getScreenHeight, getScreenHeight, 0);',
            '    RL_REG(getFrameTime, getFrameTime, 0);',
            '    RL_REG(getTime, getTime, 0);',
            '    RL_REG(getFPS, getFPS, 0);',
            '    // Window extended (Phase 3)',
            '    RL_REG(toggleFullscreen, toggleFullscreen, 0);',
            '    RL_REG(setWindowSize, setWindowSize, 2);',
            '    RL_REG(setWindowTitle, setWindowTitle, 1);',
            '    RL_REG(setConfigFlags, setConfigFlags, 1);',
            '    RL_REG(isWindowFocused, isWindowFocused, 0);',
            '    RL_REG(isWindowResized, isWindowResized, 0);',
            '    // Drawing',
            '    RL_REG(beginDrawing, beginDrawing, 0);',
            '    RL_REG(endDrawing, endDrawing, 0);',
            '    RL_REG(clearBackground, clearBackground, 1);',
            '    RL_REG(drawRectangle, drawRectangle, 5);',
            '    RL_REG(drawRectangleLines, drawRectangleLines, 5);',
            '    RL_REG(drawCircle, drawCircle, 4);',
            '    RL_REG(drawCircleLines, drawCircleLines, 4);',
            '    RL_REG(drawLine, drawLine, 5);',
            '    RL_REG(drawText, drawText, 5);',
            '    RL_REG(measureText, measureText, 2);',
            '    // Extended shapes (Phase 3)',
            '    RL_REG(drawRectanglePro, drawRectanglePro, 8);',
            '    RL_REG(drawRectangleRounded, drawRectangleRounded, 7);',
            '    RL_REG(drawRectangleGradientV, drawRectangleGradientV, 6);',
            '    RL_REG(drawRectangleGradientH, drawRectangleGradientH, 6);',
            '    RL_REG(drawLineEx, drawLineEx, 6);',
            '    RL_REG(drawPixel, drawPixel, 3);',
            '    RL_REG(drawCircleSector, drawCircleSector, 7);',
            '    // Text Pro (Phase 3)',
            '    RL_REG(drawTextEx, drawTextEx, 6);',
            '    RL_REG(measureTextEx, measureTextEx, 3);',
            '    // Input',
            '    RL_REG(isKeyDown, isKeyDown, 1);',
            '    RL_REG(isKeyPressed, isKeyPressed, 1);',
            '    RL_REG(isKeyReleased, isKeyReleased, 1);',
            '    RL_REG(getKeyPressed, getKeyPressed, 0);',
            '    RL_REG(getCharPressed, getCharPressed, 0);',
            '    RL_REG(isKeyUp, isKeyUp, 1);',
            '    RL_REG(getMouseX, getMouseX, 0);',
            '    RL_REG(getMouseY, getMouseY, 0);',
            '    RL_REG(isMouseButtonDown, isMouseButtonDown, 1);',
            '    RL_REG(isMouseButtonPressed, isMouseButtonPressed, 1);',
            '    RL_REG(isMouseButtonReleased, isMouseButtonReleased, 1);',
            '    RL_REG(getMouseWheelMove, getMouseWheelMove, 0);',
            '    // Font & Color',
            '    RL_REG(loadFont, loadFont, 2);',
            '    RL_REG(color, color, 4);',
            '    RL_REG(colorAlpha, colorAlpha, 2);',
            '    // Audio (Phase 1)',
            '    RL_REG(initAudioDevice, initAudioDevice, 0);',
            '    RL_REG(closeAudioDevice, closeAudioDevice, 0);',
            '    RL_REG(setMasterVolume, setMasterVolume, 1);',
            '    RL_REG(getMasterVolume, getMasterVolume, 0);',
            '    RL_REG(loadSound, loadSound, 1);',
            '    RL_REG(playSound, playSound, 1);',
            '    RL_REG(stopSound, stopSound, 1);',
            '    RL_REG(pauseSound, pauseSound, 1);',
            '    RL_REG(resumeSound, resumeSound, 1);',
            '    RL_REG(setSoundVolume, setSoundVolume, 2);',
            '    RL_REG(setSoundPitch, setSoundPitch, 2);',
            '    RL_REG(isSoundPlaying, isSoundPlaying, 1);',
            '    RL_REG(unloadSound, unloadSound, 1);',
            '    RL_REG(loadMusic, loadMusic, 1);',
            '    RL_REG(playMusic, playMusic, 1);',
            '    RL_REG(stopMusic, stopMusic, 1);',
            '    RL_REG(pauseMusic, pauseMusic, 1);',
            '    RL_REG(resumeMusic, resumeMusic, 1);',
            '    RL_REG(updateMusic, updateMusic, 1);',
            '    RL_REG(setMusicVolume, setMusicVolume, 2);',
            '    RL_REG(isMusicPlaying, isMusicPlaying, 1);',
            '    RL_REG(getMusicTimeLength, getMusicTimeLength, 1);',
            '    RL_REG(getMusicTimePlayed, getMusicTimePlayed, 1);',
            '    RL_REG(unloadMusic, unloadMusic, 1);',
            '    // Camera2D (Phase 2)',
            '    RL_REG(beginMode2D, beginMode2D, 6);',
            '    RL_REG(endMode2D, endMode2D, 0);',
            '    // Collision (Phase 2)',
            '    RL_REG(checkCollisionRecs, checkCollisionRecs, 8);',
            '    RL_REG(checkCollisionCircles, checkCollisionCircles, 6);',
            '    RL_REG(checkCollisionCircleRec, checkCollisionCircleRec, 7);',
            '    RL_REG(checkCollisionPointRec, checkCollisionPointRec, 6);',
            '    RL_REG(checkCollisionPointCircle, checkCollisionPointCircle, 5);',
            '    RL_REG(getRandomValue, getRandomValue, 2);',
            '    // Gamepad (Phase 5)',
            '    RL_REG(isGamepadAvailable, isGamepadAvailable, 1);',
            '    RL_REG(isGamepadButtonDown, isGamepadButtonDown, 2);',
            '    RL_REG(isGamepadButtonPressed, isGamepadButtonPressed, 2);',
            '    RL_REG(isGamepadButtonReleased, isGamepadButtonReleased, 2);',
            '    RL_REG(getGamepadAxisMovement, getGamepadAxisMovement, 2);',
            '    RL_REG(getGamepadAxisCount, getGamepadAxisCount, 1);',
            '    JS_SetPropertyStr(ctx, global, "getGamepadButtonPressed",',
            '        JS_NewCFunction(ctx, js_rl_getGamepadButtonPressedQJS, "getGamepadButtonPressed", 0));',
            '    // Music extended',
            '    RL_REG(seekMusic, seekMusic, 2);',
            '    RL_REG(setMusicPitch, setMusicPitch, 2);',
            '    RL_REG(isAudioDeviceReady, isAudioDeviceReady, 0);',
            '    RL_REG(unloadFont, unloadFont, 0);',
            '    RL_REG(measureTextExY, measureTextExY, 3);',
            '    RL_REG(drawTextureScaled, drawTextureScaled, 5);',
            '    RL_REG(isTextureValid, isTextureValid, 1);',
            '    RL_REG(loadTexture, loadTexture, 1);',
            '    RL_REG(drawTexture, drawTexture, 4);',
            '    RL_REG(drawTextureRec, drawTextureRec, 8);',
            '    RL_REG(drawTexturePro, drawTexturePro, 13);',
            '    RL_REG(unloadTexture, unloadTexture, 1);',
            '    RL_REG(getTextureWidth, getTextureWidth, 1);',
            '    RL_REG(getTextureHeight, getTextureHeight, 1);',
            '    RL_REG(getWorldToScreen2DX, getWorldToScreen2DX, 8);',
            '    RL_REG(getWorldToScreen2DY, getWorldToScreen2DY, 8);',
            '    RL_REG(isGamepadButtonUp, isGamepadButtonUp, 2);',
            '    RL_REG(fileExists, fileExists, 1);',
            '    RL_REG(directoryExists, directoryExists, 1);',
            '',
            '#undef RL_REG',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]


    def _generate_http_shell_bindings(self) -> list[str]:
        """Generate QuickJS-side bindings for exec/httpGet/httpPost."""
        return [
            '// QuickJS exec/HTTP bindings for entry statements',
            'static JSValue js_exec(JSContext *ctx, JSValueConst this_val,',
            '                       int argc, JSValueConst *argv) {',
            '    const char *cmd = JS_ToCString(ctx, argv[0]);',
            '    if (!cmd) return JS_EXCEPTION;',
            '    char *result = tsuchi_exec(cmd);',
            '    JS_FreeCString(ctx, cmd);',
            '    JSValue ret = JS_NewString(ctx, result);',
            '    free(result);',
            '    return ret;',
            '}',
            'static JSValue js_httpGet(JSContext *ctx, JSValueConst this_val,',
            '                          int argc, JSValueConst *argv) {',
            '    const char *url = JS_ToCString(ctx, argv[0]);',
            '    if (!url) return JS_EXCEPTION;',
            '    char *result = tsuchi_httpGet(url);',
            '    JS_FreeCString(ctx, url);',
            '    JSValue ret = JS_NewString(ctx, result);',
            '    free(result);',
            '    return ret;',
            '}',
            'static JSValue js_httpPost(JSContext *ctx, JSValueConst this_val,',
            '                           int argc, JSValueConst *argv) {',
            '    const char *url = JS_ToCString(ctx, argv[0]);',
            '    const char *body = argc > 1 ? JS_ToCString(ctx, argv[1]) : NULL;',
            '    const char *ct = argc > 2 ? JS_ToCString(ctx, argv[2]) : NULL;',
            '    if (!url) return JS_EXCEPTION;',
            '    char *result = tsuchi_httpPost(url, body ? body : "", ct ? ct : "application/json");',
            '    JS_FreeCString(ctx, url);',
            '    if (body) JS_FreeCString(ctx, body);',
            '    if (ct) JS_FreeCString(ctx, ct);',
            '    JSValue ret = JS_NewString(ctx, result);',
            '    free(result);',
            '    return ret;',
            '}',
            '',
            'static void js_add_http_shell_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '    JS_SetPropertyStr(ctx, global, "exec",',
            '        JS_NewCFunction(ctx, js_exec, "exec", 1));',
            '    JS_SetPropertyStr(ctx, global, "httpGet",',
            '        JS_NewCFunction(ctx, js_httpGet, "httpGet", 1));',
            '    JS_SetPropertyStr(ctx, global, "httpPost",',
            '        JS_NewCFunction(ctx, js_httpPost, "httpPost", 3));',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]


    def _generate_clay_bindings(self) -> list[str]:
        """Generate QuickJS-side bindings for Clay UI (entry-level statement support)."""
        return [
            '// QuickJS Clay bindings for entry statements',
            'static JSValue js_clay_init(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_init(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_loadFont(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *path = JS_ToCString(ctx, argv[0]);',
            '    int id = tsuchi_clay_load_font(path, _rl_int(ctx, argv[1]));',
            '    JS_FreeCString(ctx, path);',
            '    return JS_NewFloat64(ctx, id);',
            '}',
            'static JSValue js_clay_setDimensions(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_set_dimensions(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_setPointer(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_set_pointer(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_int(ctx, argv[2]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_updateScroll(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_update_scroll(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_beginLayout(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_begin_layout(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_endLayout(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_end_layout(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_render(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_render(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_open(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_open(id, _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]),',
            '                    _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '                    _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]),',
            '                    _rl_int(ctx, argv[7]), _rl_int(ctx, argv[8]),',
            '                    _rl_int(ctx, argv[9]), _rl_int(ctx, argv[10]),',
            '                    _rl_int(ctx, argv[11]), _rl_int(ctx, argv[12]),',
            '                    _rl_dbl(ctx, argv[13]));',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_openAligned(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_open_aligned(id, _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]),',
            '                    _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '                    _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]),',
            '                    _rl_int(ctx, argv[7]), _rl_int(ctx, argv[8]),',
            '                    _rl_int(ctx, argv[9]), _rl_int(ctx, argv[10]),',
            '                    _rl_int(ctx, argv[11]), _rl_int(ctx, argv[12]),',
            '                    _rl_dbl(ctx, argv[13]),',
            '                    _rl_int(ctx, argv[14]), _rl_int(ctx, argv[15]));',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_close(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_close(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_text(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *text = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_text(text, _rl_int(ctx, argv[1]), _rl_int(ctx, argv[2]),',
            '                    _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '                    _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]));',
            '    JS_FreeCString(ctx, text);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_pointerOver(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int over = tsuchi_clay_pointer_over(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, over);',
            '}',
            '',
            'static void js_add_clay_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '',
            '    // Clay sizing constants',
            '    JS_SetPropertyStr(ctx, global, "CLAY_FIT",  JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "CLAY_GROW", JS_NewFloat64(ctx, -1));',
            '    JS_SetPropertyStr(ctx, global, "CLAY_LEFT_TO_RIGHT", JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "CLAY_TOP_TO_BOTTOM", JS_NewFloat64(ctx, 1));',
            '',
            '#define CLAY_REG(jsName, cFunc, nargs) \\',
            '    JS_SetPropertyStr(ctx, global, #jsName, JS_NewCFunction(ctx, js_clay_##cFunc, #jsName, nargs))',
            '',
            '    CLAY_REG(clayInit, init, 2);',
            '    CLAY_REG(clayLoadFont, loadFont, 2);',
            '    CLAY_REG(claySetDimensions, setDimensions, 2);',
            '    CLAY_REG(claySetPointer, setPointer, 3);',
            '    CLAY_REG(clayUpdateScroll, updateScroll, 3);',
            '    CLAY_REG(clayBeginLayout, beginLayout, 0);',
            '    CLAY_REG(clayEndLayout, endLayout, 0);',
            '    CLAY_REG(clayRender, render, 0);',
            '    CLAY_REG(clayOpen, open, 14);',
            '    CLAY_REG(clayOpenAligned, openAligned, 16);',
            '    CLAY_REG(clayClose, close, 0);',
            '    CLAY_REG(clayText, text, 7);',
            '    CLAY_REG(clayPointerOver, pointerOver, 1);',
            '',
            '#undef CLAY_REG',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]


    def _generate_clay_tui_bindings(self) -> list[str]:
        """Generate QuickJS-side bindings for Clay TUI (entry-level statement support)."""
        lines: list[str] = []
        # If raylib is not used, we need to define the helper functions
        if not self._uses_raylib:
            lines.extend([
                '// Helper: get int/double arg from JSValue',
                'static int _rl_int(JSContext *ctx, JSValueConst v) {',
                '    double d; JS_ToFloat64(ctx, &d, v); return (int)d;',
                '}',
                'static double _rl_dbl(JSContext *ctx, JSValueConst v) {',
                '    double d; JS_ToFloat64(ctx, &d, v); return d;',
                '}',
                '',
            ])
        lines += [
            '// QuickJS Clay TUI bindings for entry statements',
            'static JSValue js_clay_tui_init(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_init(_rl_int(ctx, argv[0]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_destroy(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_destroy(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_setDimensions(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_set_dimensions(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_beginLayout(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_begin_layout(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_endLayout(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_end_layout(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_render(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_render(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_open(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_tui_open(id, _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]),',
            '                    _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '                    _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]),',
            '                    _rl_int(ctx, argv[7]), _rl_int(ctx, argv[8]),',
            '                    _rl_int(ctx, argv[9]), _rl_int(ctx, argv[10]),',
            '                    _rl_int(ctx, argv[11]), _rl_int(ctx, argv[12]),',
            '                    _rl_dbl(ctx, argv[13]));',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_closeElement(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_close_element(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_text(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *text = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_tui_text(text, _rl_int(ctx, argv[1]), _rl_int(ctx, argv[2]),',
            '                    _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '                    _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]));',
            '    JS_FreeCString(ctx, text);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_setPointer(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_set_pointer(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_int(ctx, argv[2]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_pointerOver(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int over = tsuchi_clay_tui_pointer_over(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, over);',
            '}',
            'static JSValue js_clay_tui_peekEvent(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_peek_event(_rl_int(ctx, argv[0])));',
            '}',
            'static JSValue js_clay_tui_pollEvent(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_poll_event());',
            '}',
            'static JSValue js_clay_tui_eventType(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_type());',
            '}',
            'static JSValue js_clay_tui_eventKey(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_key());',
            '}',
            'static JSValue js_clay_tui_eventCh(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_ch());',
            '}',
            'static JSValue js_clay_tui_eventW(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_w());',
            '}',
            'static JSValue js_clay_tui_eventH(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_h());',
            '}',
            'static JSValue js_clay_tui_termWidth(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_term_width());',
            '}',
            'static JSValue js_clay_tui_termHeight(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_term_height());',
            '}',
            'static JSValue js_clay_tui_eventMod(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_mod());',
            '}',
            '',
            '// Phase 4 extensions',
            'static JSValue js_clay_tui_border(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_border(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]),',
            '        _rl_int(ctx, argv[4]), _rl_int(ctx, argv[5]),',
            '        _rl_int(ctx, argv[6]), _rl_int(ctx, argv[7]),',
            '        _rl_dbl(ctx, argv[8]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_align(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_align(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_scroll(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_scroll(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_updateScroll(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_update_scroll(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]), _rl_dbl(ctx, argv[2]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_openI(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_tui_openI(id, _rl_int(ctx, argv[1]),',
            '        _rl_dbl(ctx, argv[2]), _rl_dbl(ctx, argv[3]),',
            '        _rl_int(ctx, argv[4]), _rl_int(ctx, argv[5]),',
            '        _rl_int(ctx, argv[6]), _rl_int(ctx, argv[7]),',
            '        _rl_int(ctx, argv[8]), _rl_int(ctx, argv[9]),',
            '        _rl_int(ctx, argv[10]), _rl_int(ctx, argv[11]),',
            '        _rl_int(ctx, argv[12]), _rl_int(ctx, argv[13]),',
            '        _rl_dbl(ctx, argv[14]));',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Text buffer (Phase 4)',
            'static JSValue js_clay_tui_textbufClear(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_clear(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufPutchar(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_putchar(_rl_int(ctx, argv[0])); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufBackspace(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_backspace(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufDelete(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_delete(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufCursorLeft(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_cursor_left(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufCursorRight(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_cursor_right(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufHome(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_home(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufEnd(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_end(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textbufLen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_textbuf_len());',
            '}',
            'static JSValue js_clay_tui_textbufCursor(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_textbuf_cursor());',
            '}',
            'static JSValue js_clay_tui_textbufRender(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_render(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]),',
            '        _rl_int(ctx, argv[4]), _rl_int(ctx, argv[5]));',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Phase B extensions',
            'static JSValue js_clay_tui_textbufCopy(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *s = tsuchi_clay_tui_textbuf_copy();',
            '    JSValue ret = JS_NewString(ctx, s ? s : "");',
            '    return ret;',
            '}',
            'static JSValue js_clay_tui_textbufRenderRange(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_textbuf_render_range(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]),',
            '        _rl_int(ctx, argv[4]), _rl_int(ctx, argv[5]),',
            '        _rl_int(ctx, argv[6]), _rl_int(ctx, argv[7]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textChar(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_text_char(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]),',
            '        _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '        _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_pointerOverI(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int over = tsuchi_clay_tui_pointer_over_i(id, _rl_int(ctx, argv[1]));',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, over);',
            '}',
            'static JSValue js_clay_tui_eventMouseX(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_mouse_x());',
            '}',
            'static JSValue js_clay_tui_eventMouseY(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_event_mouse_y());',
            '}',
            'static JSValue js_clay_tui_rgb(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_clay_tui_rgb(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]), _rl_int(ctx, argv[2])));',
            '}',
            'static JSValue js_clay_tui_bgEx(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_bg_ex(_rl_int(ctx, argv[0]), _rl_int(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_textEx(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *text = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_clay_tui_text_ex(text, _rl_int(ctx, argv[1]), _rl_int(ctx, argv[2]),',
            '        _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]),',
            '        _rl_int(ctx, argv[5]), _rl_int(ctx, argv[6]),',
            '        _rl_int(ctx, argv[7]), _rl_int(ctx, argv[8]),',
            '        _rl_int(ctx, argv[9]), _rl_int(ctx, argv[10]),',
            '        _rl_int(ctx, argv[11]));',
            '    JS_FreeCString(ctx, text);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_clay_tui_floating(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_clay_tui_floating(_rl_dbl(ctx, argv[0]), _rl_dbl(ctx, argv[1]),',
            '        _rl_int(ctx, argv[2]), _rl_int(ctx, argv[3]), _rl_int(ctx, argv[4]));',
            '    return JS_UNDEFINED;',
            '}',
            '',
            'static void js_add_clay_tui_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '',
            '    // Clay sizing constants (shared with GUI)',
            '    JS_SetPropertyStr(ctx, global, "CLAY_FIT",  JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "CLAY_GROW", JS_NewFloat64(ctx, -1));',
            '    JS_SetPropertyStr(ctx, global, "CLAY_LEFT_TO_RIGHT", JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "CLAY_TOP_TO_BOTTOM", JS_NewFloat64(ctx, 1));',
            '',
            '    // termbox2 event type constants',
            '    JS_SetPropertyStr(ctx, global, "TB_EVENT_KEY",    JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "TB_EVENT_RESIZE", JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "TB_EVENT_MOUSE",  JS_NewFloat64(ctx, 3));',
            '',
            '    // termbox2 key constants (resolved at runtime)',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_ESC",         JS_NewFloat64(ctx, tsuchi_clay_tui_key_esc()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_ENTER",       JS_NewFloat64(ctx, tsuchi_clay_tui_key_enter()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_TAB",         JS_NewFloat64(ctx, tsuchi_clay_tui_key_tab()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_BACKSPACE",   JS_NewFloat64(ctx, tsuchi_clay_tui_key_backspace()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_ARROW_UP",    JS_NewFloat64(ctx, tsuchi_clay_tui_key_arrow_up()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_ARROW_DOWN",  JS_NewFloat64(ctx, tsuchi_clay_tui_key_arrow_down()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_ARROW_LEFT",  JS_NewFloat64(ctx, tsuchi_clay_tui_key_arrow_left()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_ARROW_RIGHT", JS_NewFloat64(ctx, tsuchi_clay_tui_key_arrow_right()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_SPACE",       JS_NewFloat64(ctx, tsuchi_clay_tui_key_space()));',
            '    // Phase 4 key constants',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_DELETE",      JS_NewFloat64(ctx, tsuchi_clay_tui_key_delete()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_HOME",        JS_NewFloat64(ctx, tsuchi_clay_tui_key_home()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_END",         JS_NewFloat64(ctx, tsuchi_clay_tui_key_end()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_PGUP",        JS_NewFloat64(ctx, tsuchi_clay_tui_key_pgup()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_PGDN",        JS_NewFloat64(ctx, tsuchi_clay_tui_key_pgdn()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F1",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f1()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F2",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f2()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F3",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f3()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F4",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f4()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F5",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f5()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F6",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f6()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F7",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f7()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F8",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f8()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F9",          JS_NewFloat64(ctx, tsuchi_clay_tui_key_f9()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F10",         JS_NewFloat64(ctx, tsuchi_clay_tui_key_f10()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F11",         JS_NewFloat64(ctx, tsuchi_clay_tui_key_f11()));',
            '    JS_SetPropertyStr(ctx, global, "TB_KEY_F12",         JS_NewFloat64(ctx, tsuchi_clay_tui_key_f12()));',
            '    // Modifier constants',
            '    JS_SetPropertyStr(ctx, global, "TB_MOD_ALT",         JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "TB_MOD_CTRL",        JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "TB_MOD_SHIFT",       JS_NewFloat64(ctx, 4));',
            '    // TUI color constants',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_DEFAULT",  JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_BLACK",    JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_RED",      JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_GREEN",    JS_NewFloat64(ctx, 3));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_YELLOW",   JS_NewFloat64(ctx, 4));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_BLUE",     JS_NewFloat64(ctx, 5));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_MAGENTA",  JS_NewFloat64(ctx, 6));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_CYAN",     JS_NewFloat64(ctx, 7));',
            '    JS_SetPropertyStr(ctx, global, "TB_COLOR_WHITE",    JS_NewFloat64(ctx, 8));',
            '    // Text attributes',
            '    JS_SetPropertyStr(ctx, global, "TB_ATTR_BOLD",      JS_NewFloat64(ctx, 256));',
            '    JS_SetPropertyStr(ctx, global, "TB_ATTR_UNDERLINE", JS_NewFloat64(ctx, 512));',
            '    JS_SetPropertyStr(ctx, global, "TB_ATTR_REVERSE",   JS_NewFloat64(ctx, 1024));',
            '',
            '#define CTUI_REG(jsName, cFunc, nargs) \\',
            '    JS_SetPropertyStr(ctx, global, #jsName, JS_NewCFunction(ctx, js_clay_tui_##cFunc, #jsName, nargs))',
            '',
            '    CTUI_REG(clayTuiInit, init, 1);',
            '    CTUI_REG(clayTuiDestroy, destroy, 0);',
            '    CTUI_REG(clayTuiSetDimensions, setDimensions, 2);',
            '    CTUI_REG(clayTuiBeginLayout, beginLayout, 0);',
            '    CTUI_REG(clayTuiEndLayout, endLayout, 0);',
            '    CTUI_REG(clayTuiRender, render, 0);',
            '    CTUI_REG(clayTuiOpen, open, 14);',
            '    CTUI_REG(clayTuiCloseElement, closeElement, 0);',
            '    CTUI_REG(clayTuiText, text, 7);',
            '    CTUI_REG(clayTuiSetPointer, setPointer, 3);',
            '    CTUI_REG(clayTuiPointerOver, pointerOver, 1);',
            '    CTUI_REG(clayTuiPeekEvent, peekEvent, 1);',
            '    CTUI_REG(clayTuiPollEvent, pollEvent, 0);',
            '    CTUI_REG(clayTuiEventType, eventType, 0);',
            '    CTUI_REG(clayTuiEventKey, eventKey, 0);',
            '    CTUI_REG(clayTuiEventCh, eventCh, 0);',
            '    CTUI_REG(clayTuiEventW, eventW, 0);',
            '    CTUI_REG(clayTuiEventH, eventH, 0);',
            '    CTUI_REG(clayTuiTermWidth, termWidth, 0);',
            '    CTUI_REG(clayTuiTermHeight, termHeight, 0);',
            '    CTUI_REG(clayTuiEventMod, eventMod, 0);',
            '    // Phase 4 extensions',
            '    CTUI_REG(clayTuiBorder, border, 9);',
            '    CTUI_REG(clayTuiAlign, align, 2);',
            '    CTUI_REG(clayTuiScroll, scroll, 2);',
            '    CTUI_REG(clayTuiUpdateScroll, updateScroll, 3);',
            '    CTUI_REG(clayTuiOpenI, openI, 15);',
            '    CTUI_REG(clayTuiTextbufClear, textbufClear, 0);',
            '    CTUI_REG(clayTuiTextbufPutchar, textbufPutchar, 1);',
            '    CTUI_REG(clayTuiTextbufBackspace, textbufBackspace, 0);',
            '    CTUI_REG(clayTuiTextbufDelete, textbufDelete, 0);',
            '    CTUI_REG(clayTuiTextbufCursorLeft, textbufCursorLeft, 0);',
            '    CTUI_REG(clayTuiTextbufCursorRight, textbufCursorRight, 0);',
            '    CTUI_REG(clayTuiTextbufHome, textbufHome, 0);',
            '    CTUI_REG(clayTuiTextbufEnd, textbufEnd, 0);',
            '    CTUI_REG(clayTuiTextbufLen, textbufLen, 0);',
            '    CTUI_REG(clayTuiTextbufCursor, textbufCursor, 0);',
            '    CTUI_REG(clayTuiTextbufRender, textbufRender, 6);',
            '    // Phase B extensions',
            '    CTUI_REG(clayTuiTextbufCopy, textbufCopy, 0);',
            '    CTUI_REG(clayTuiTextbufRenderRange, textbufRenderRange, 8);',
            '    CTUI_REG(clayTuiTextChar, textChar, 7);',
            '    CTUI_REG(clayTuiPointerOverI, pointerOverI, 2);',
            '    CTUI_REG(clayTuiEventMouseX, eventMouseX, 0);',
            '    CTUI_REG(clayTuiEventMouseY, eventMouseY, 0);',
            '    CTUI_REG(clayTuiRgb, rgb, 3);',
            '    CTUI_REG(clayTuiBgEx, bgEx, 5);',
            '    CTUI_REG(clayTuiTextEx, textEx, 12);',
            '    CTUI_REG(clayTuiFloating, floating, 5);',
            '',
            '#undef CTUI_REG',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]
        return lines


    def _generate_ui_bindings(self) -> list[str]:
        """Generate QuickJS-side bindings for UI widgets (entry-level statement support)."""
        return [
            '// QuickJS UI bindings for entry statements',
            '',
            '// Frame lifecycle',
            'static JSValue js_ui_beginFrame(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_beginFrame(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_endFrame(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_endFrame(); return JS_UNDEFINED;',
            '}',
            '',
            '// Widget state queries',
            'static JSValue js_ui_clicked(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int result = tsuchi_ui_clicked(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, result);',
            '}',
            'static JSValue js_ui_hovered(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int result = tsuchi_ui_hovered(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, result);',
            '}',
            'static JSValue js_ui_toggled(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int result = tsuchi_ui_toggled(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, result);',
            '}',
            'static JSValue js_ui_sliderValue(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double result = tsuchi_ui_sliderValue(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewFloat64(ctx, result);',
            '}',
            '',
            '// Focus management',
            'static JSValue js_ui_focusNext(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_focusNext(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_focusPrev(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_focusPrev(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_keyPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_ui_keyPressed());',
            '}',
            'static JSValue js_ui_charPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_ui_charPressed());',
            '}',
            '',
            '// Button',
            'static JSValue js_ui_buttonOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double kind, size, grow_flag;',
            '    JS_ToFloat64(ctx, &kind, argv[1]);',
            '    JS_ToFloat64(ctx, &size, argv[2]);',
            '    JS_ToFloat64(ctx, &grow_flag, argv[3]);',
            '    tsuchi_ui_buttonOpen(id, kind, size, grow_flag);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_buttonClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_buttonClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Checkbox',
            'static JSValue js_ui_checkboxOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double checked, size;',
            '    JS_ToFloat64(ctx, &checked, argv[1]);',
            '    JS_ToFloat64(ctx, &size, argv[2]);',
            '    tsuchi_ui_checkboxOpen(id, checked, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_checkboxClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_checkboxClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Radio',
            'static JSValue js_ui_radioOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double index, selected, size;',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    JS_ToFloat64(ctx, &selected, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_radioOpen(id, index, selected, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_radioClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_radioClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Toggle',
            'static JSValue js_ui_toggleOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double on, size;',
            '    JS_ToFloat64(ctx, &on, argv[1]);',
            '    JS_ToFloat64(ctx, &size, argv[2]);',
            '    tsuchi_ui_toggleOpen(id, on, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_toggleClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_toggleClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Text Input',
            'static JSValue js_ui_textInput(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double buf_id, w, size;',
            '    JS_ToFloat64(ctx, &buf_id, argv[1]);',
            '    JS_ToFloat64(ctx, &w, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_textInput(id, buf_id, w, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Slider',
            'static JSValue js_ui_slider(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double value, min_val, max_val, w;',
            '    JS_ToFloat64(ctx, &value, argv[1]);',
            '    JS_ToFloat64(ctx, &min_val, argv[2]);',
            '    JS_ToFloat64(ctx, &max_val, argv[3]);',
            '    JS_ToFloat64(ctx, &w, argv[4]);',
            '    tsuchi_ui_slider(id, value, min_val, max_val, w);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Menu Item',
            'static JSValue js_ui_menuItemOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double index, cursor, size;',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    JS_ToFloat64(ctx, &cursor, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_menuItemOpen(id, index, cursor, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_menuItemClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_menuItemClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Tab Button',
            'static JSValue js_ui_tabButtonOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double index, active, size;',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    JS_ToFloat64(ctx, &active, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_tabButtonOpen(id, index, active, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_tabButtonClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_tabButtonClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Number Stepper',
            'static JSValue js_ui_numberStepper(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double value, min_val, max_val, size;',
            '    JS_ToFloat64(ctx, &value, argv[1]);',
            '    JS_ToFloat64(ctx, &min_val, argv[2]);',
            '    JS_ToFloat64(ctx, &max_val, argv[3]);',
            '    JS_ToFloat64(ctx, &size, argv[4]);',
            '    tsuchi_ui_numberStepper(id, value, min_val, max_val, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Search Bar',
            'static JSValue js_ui_searchBar(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double buf_id, w, size;',
            '    JS_ToFloat64(ctx, &buf_id, argv[1]);',
            '    JS_ToFloat64(ctx, &w, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_searchBar(id, buf_id, w, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// List Item',
            'static JSValue js_ui_listItemOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double index, selected, size;',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    JS_ToFloat64(ctx, &selected, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_listItemOpen(id, index, selected, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_listItemClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_listItemClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Part 2B - Forms',
            'static JSValue js_ui_textareaInput(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double buf_id, w, h, size;',
            '    JS_ToFloat64(ctx, &buf_id, argv[1]);',
            '    JS_ToFloat64(ctx, &w, argv[2]);',
            '    JS_ToFloat64(ctx, &h, argv[3]);',
            '    JS_ToFloat64(ctx, &size, argv[4]);',
            '    tsuchi_ui_textareaInput(id, buf_id, w, h, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_switchOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double on, size;',
            '    JS_ToFloat64(ctx, &on, argv[1]);',
            '    JS_ToFloat64(ctx, &size, argv[2]);',
            '    tsuchi_ui_switchOpen(id, on, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_switchClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_switchClose(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_ratingOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double value, max_val, size;',
            '    JS_ToFloat64(ctx, &value, argv[1]);',
            '    JS_ToFloat64(ctx, &max_val, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_ratingOpen(id, value, max_val, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_ratingClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_ratingClose(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_segmentButtonOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double index, active, size;',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    JS_ToFloat64(ctx, &active, argv[2]);',
            '    JS_ToFloat64(ctx, &size, argv[3]);',
            '    tsuchi_ui_segmentButtonOpen(id, index, active, size);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_segmentButtonClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_segmentButtonClose(); return JS_UNDEFINED;',
            '}',
            '',
            '// Part 2C - Navigation',
            'static JSValue js_ui_navPush(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double scene; JS_ToFloat64(ctx, &scene, argv[0]);',
            '    tsuchi_ui_navPush(scene); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_navPop(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_navPop(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_navCurrent(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_ui_navCurrent());',
            '}',
            'static JSValue js_ui_navDepth(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_ui_navDepth());',
            '}',
            '',
            '// Part 2D - Overlay',
            'static JSValue js_ui_accordionOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double expanded; JS_ToFloat64(ctx, &expanded, argv[1]);',
            '    tsuchi_ui_accordionOpen(id, expanded);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_accordionClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_accordionClose(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_dropdownOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_ui_dropdownOpen(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_dropdownClose(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_dropdownClose(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_dropdownIsOpen(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    int result = tsuchi_ui_dropdownIsOpen(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_NewBool(ctx, result);',
            '}',
            'static JSValue js_ui_tooltipBegin(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    tsuchi_ui_tooltipBegin(id);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_tooltipEnd(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_tooltipEnd(); return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_toastShow(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *msg = JS_ToCString(ctx, argv[0]);',
            '    double kind, dur; JS_ToFloat64(ctx, &kind, argv[1]); JS_ToFloat64(ctx, &dur, argv[2]);',
            '    tsuchi_ui_toastShow(msg, kind, dur);',
            '    JS_FreeCString(ctx, msg);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_toastRender(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_ui_toastRender(); return JS_UNDEFINED;',
            '}',
            '',
            '// Part 2E - Charts',
            'static JSValue js_ui_chartInit(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double type, count, max_val;',
            '    JS_ToFloat64(ctx, &type, argv[1]); JS_ToFloat64(ctx, &count, argv[2]); JS_ToFloat64(ctx, &max_val, argv[3]);',
            '    tsuchi_ui_chartInit(id, type, count, max_val);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_chartSet(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double idx, val; JS_ToFloat64(ctx, &idx, argv[1]); JS_ToFloat64(ctx, &val, argv[2]);',
            '    tsuchi_ui_chartSet(id, idx, val);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_chartColor(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double idx, r, g, b;',
            '    JS_ToFloat64(ctx, &idx, argv[1]); JS_ToFloat64(ctx, &r, argv[2]);',
            '    JS_ToFloat64(ctx, &g, argv[3]); JS_ToFloat64(ctx, &b, argv[4]);',
            '    tsuchi_ui_chartColor(id, idx, r, g, b);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_ui_chartRender(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *id = JS_ToCString(ctx, argv[0]);',
            '    double type, count, max_val, w, h;',
            '    JS_ToFloat64(ctx, &type, argv[1]); JS_ToFloat64(ctx, &count, argv[2]);',
            '    JS_ToFloat64(ctx, &max_val, argv[3]); JS_ToFloat64(ctx, &w, argv[4]); JS_ToFloat64(ctx, &h, argv[5]);',
            '    tsuchi_ui_chartRender(id, type, count, max_val, w, h);',
            '    JS_FreeCString(ctx, id);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Part 2F - Markdown',
            'static JSValue js_ui_markdownRender(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    const char *text = JS_ToCString(ctx, argv[0]);',
            '    double w, size; JS_ToFloat64(ctx, &w, argv[1]); JS_ToFloat64(ctx, &size, argv[2]);',
            '    tsuchi_ui_markdownRender(text, w, size);',
            '    JS_FreeCString(ctx, text);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Part 2G - Other',
            'static JSValue js_ui_spinnerChar(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewString(ctx, tsuchi_ui_spinnerChar());',
            '}',
            'static JSValue js_ui_frameCount(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_ui_frameCount());',
            '}',
            '',
            '// Style composition',
            'static JSValue js_ui_style(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double size, kind, flex;',
            '    JS_ToFloat64(ctx, &size, argv[0]); JS_ToFloat64(ctx, &kind, argv[1]); JS_ToFloat64(ctx, &flex, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_ui_style(size, kind, flex));',
            '}',
            'static JSValue js_ui_styleMerge(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double a, b; JS_ToFloat64(ctx, &a, argv[0]); JS_ToFloat64(ctx, &b, argv[1]);',
            '    return JS_NewFloat64(ctx, tsuchi_ui_styleMerge(a, b));',
            '}',
            'static JSValue js_ui_styleSize(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double s; JS_ToFloat64(ctx, &s, argv[0]); return JS_NewFloat64(ctx, tsuchi_ui_styleSize(s));',
            '}',
            'static JSValue js_ui_styleKind(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double s; JS_ToFloat64(ctx, &s, argv[0]); return JS_NewFloat64(ctx, tsuchi_ui_styleKind(s));',
            '}',
            'static JSValue js_ui_styleFlex(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double s; JS_ToFloat64(ctx, &s, argv[0]); return JS_NewFloat64(ctx, tsuchi_ui_styleFlex(s));',
            '}',
            '',
            'static void js_add_ui_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '',
            '    // Key constants (matching raylib)',
            '    JS_SetPropertyStr(ctx, global, "KEY_ENTER",     JS_NewFloat64(ctx, 257));',
            '    JS_SetPropertyStr(ctx, global, "KEY_TAB",       JS_NewFloat64(ctx, 258));',
            '    JS_SetPropertyStr(ctx, global, "KEY_BACKSPACE", JS_NewFloat64(ctx, 259));',
            '    JS_SetPropertyStr(ctx, global, "KEY_DELETE",    JS_NewFloat64(ctx, 261));',
            '    JS_SetPropertyStr(ctx, global, "KEY_RIGHT",     JS_NewFloat64(ctx, 262));',
            '    JS_SetPropertyStr(ctx, global, "KEY_LEFT",      JS_NewFloat64(ctx, 263));',
            '    JS_SetPropertyStr(ctx, global, "KEY_DOWN",      JS_NewFloat64(ctx, 264));',
            '    JS_SetPropertyStr(ctx, global, "KEY_UP",        JS_NewFloat64(ctx, 265));',
            '    JS_SetPropertyStr(ctx, global, "KEY_HOME",      JS_NewFloat64(ctx, 268));',
            '    JS_SetPropertyStr(ctx, global, "KEY_END",       JS_NewFloat64(ctx, 269));',
            '    JS_SetPropertyStr(ctx, global, "KEY_ESCAPE",    JS_NewFloat64(ctx, 256));',
            '    JS_SetPropertyStr(ctx, global, "KEY_SPACE",     JS_NewFloat64(ctx, 32));',
            '',
            '    // Theme color constants (kind values)',
            '    JS_SetPropertyStr(ctx, global, "THEME_DEFAULT", JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "THEME_PRIMARY", JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "THEME_SUCCESS", JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "THEME_WARNING", JS_NewFloat64(ctx, 3));',
            '    JS_SetPropertyStr(ctx, global, "THEME_DANGER",  JS_NewFloat64(ctx, 4));',
            '',
            '#define UI_REG(jsName, cFunc, nargs) \\',
            '    JS_SetPropertyStr(ctx, global, #jsName, JS_NewCFunction(ctx, js_ui_##cFunc, #jsName, nargs))',
            '',
            '    UI_REG(beginFrame, beginFrame, 0);',
            '    UI_REG(endFrame, endFrame, 0);',
            '    UI_REG(clicked, clicked, 1);',
            '    UI_REG(hovered, hovered, 1);',
            '    UI_REG(toggled, toggled, 1);',
            '    UI_REG(sliderValue, sliderValue, 1);',
            '    UI_REG(focusNext, focusNext, 0);',
            '    UI_REG(focusPrev, focusPrev, 0);',
            '    UI_REG(uiKeyPressed, keyPressed, 0);',
            '    UI_REG(uiCharPressed, charPressed, 0);',
            '    UI_REG(buttonOpen, buttonOpen, 4);',
            '    UI_REG(buttonClose, buttonClose, 0);',
            '    UI_REG(checkboxOpen, checkboxOpen, 3);',
            '    UI_REG(checkboxClose, checkboxClose, 0);',
            '    UI_REG(radioOpen, radioOpen, 4);',
            '    UI_REG(radioClose, radioClose, 0);',
            '    UI_REG(toggleOpen, toggleOpen, 3);',
            '    UI_REG(toggleClose, toggleClose, 0);',
            '    UI_REG(textInput, textInput, 4);',
            '    UI_REG(slider, slider, 5);',
            '    UI_REG(menuItemOpen, menuItemOpen, 4);',
            '    UI_REG(menuItemClose, menuItemClose, 0);',
            '    UI_REG(tabButtonOpen, tabButtonOpen, 4);',
            '    UI_REG(tabButtonClose, tabButtonClose, 0);',
            '    UI_REG(numberStepper, numberStepper, 5);',
            '    UI_REG(searchBar, searchBar, 4);',
            '    UI_REG(listItemOpen, listItemOpen, 4);',
            '    UI_REG(listItemClose, listItemClose, 0);',
            '    // Part 2B',
            '    UI_REG(textareaInput, textareaInput, 5);',
            '    UI_REG(switchOpen, switchOpen, 3);',
            '    UI_REG(switchClose, switchClose, 0);',
            '    UI_REG(ratingOpen, ratingOpen, 4);',
            '    UI_REG(ratingClose, ratingClose, 0);',
            '    UI_REG(ratingValue, sliderValue, 1);',
            '    UI_REG(segmentButtonOpen, segmentButtonOpen, 4);',
            '    UI_REG(segmentButtonClose, segmentButtonClose, 0);',
            '    // Part 2C',
            '    UI_REG(navPush, navPush, 1);',
            '    UI_REG(navPop, navPop, 0);',
            '    UI_REG(navCurrent, navCurrent, 0);',
            '    UI_REG(navDepth, navDepth, 0);',
            '    // Part 2D',
            '    UI_REG(accordionOpen, accordionOpen, 2);',
            '    UI_REG(accordionClose, accordionClose, 0);',
            '    UI_REG(accordionToggled, toggled, 1);',
            '    UI_REG(dropdownOpen, dropdownOpen, 1);',
            '    UI_REG(dropdownClose, dropdownClose, 0);',
            '    UI_REG(dropdownIsOpen, dropdownIsOpen, 1);',
            '    UI_REG(tooltipBegin, tooltipBegin, 1);',
            '    UI_REG(tooltipEnd, tooltipEnd, 0);',
            '    UI_REG(toastShow, toastShow, 3);',
            '    UI_REG(toastRender, toastRender, 0);',
            '    // Part 2E',
            '    UI_REG(chartInit, chartInit, 4);',
            '    UI_REG(chartSet, chartSet, 3);',
            '    UI_REG(chartColor, chartColor, 5);',
            '    UI_REG(chartRender, chartRender, 6);',
            '    // Part 2F',
            '    UI_REG(markdownRender, markdownRender, 3);',
            '    // Part 2G',
            '    UI_REG(uiSpinnerChar, spinnerChar, 0);',
            '    UI_REG(uiFrameCount, frameCount, 0);',
            '    // Style composition',
            '    UI_REG(uiStyle, style, 3);',
            '    UI_REG(uiStyleMerge, styleMerge, 2);',
            '    UI_REG(uiStyleSize, styleSize, 1);',
            '    UI_REG(uiStyleKind, styleKind, 1);',
            '    UI_REG(uiStyleFlex, styleFlex, 1);',
            '',
            '#undef UI_REG',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]


    def _generate_gf_bindings(self) -> list[str]:
        """Generate QuickJS-side bindings for game framework (entry-level statement support)."""
        return [
            '// QuickJS Game Framework bindings for entry statements',
            '',
            '// Math helpers',
            'static JSValue js_gf_clamp(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double v, lo, hi;',
            '    JS_ToFloat64(ctx, &v, argv[0]);',
            '    JS_ToFloat64(ctx, &lo, argv[1]);',
            '    JS_ToFloat64(ctx, &hi, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_clamp(v, lo, hi));',
            '}',
            'static JSValue js_gf_lerp(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double a, b, t;',
            '    JS_ToFloat64(ctx, &a, argv[0]);',
            '    JS_ToFloat64(ctx, &b, argv[1]);',
            '    JS_ToFloat64(ctx, &t, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_lerp(a, b, t));',
            '}',
            'static JSValue js_gf_rand(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double max_val;',
            '    JS_ToFloat64(ctx, &max_val, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_rand(max_val));',
            '}',
            'static JSValue js_gf_randRange(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double min_val, max_val;',
            '    JS_ToFloat64(ctx, &min_val, argv[0]);',
            '    JS_ToFloat64(ctx, &max_val, argv[1]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_randRange(min_val, max_val));',
            '}',
            'static JSValue js_gf_rgba(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double r, g, b, a;',
            '    JS_ToFloat64(ctx, &r, argv[0]);',
            '    JS_ToFloat64(ctx, &g, argv[1]);',
            '    JS_ToFloat64(ctx, &b, argv[2]);',
            '    JS_ToFloat64(ctx, &a, argv[3]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_rgba(r, g, b, a));',
            '}',
            '',
            '// Drawing helpers',
            'static JSValue js_gf_drawBar(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, w, h, val, max_val, fg, bg;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &w, argv[2]);',
            '    JS_ToFloat64(ctx, &h, argv[3]);',
            '    JS_ToFloat64(ctx, &val, argv[4]);',
            '    JS_ToFloat64(ctx, &max_val, argv[5]);',
            '    JS_ToFloat64(ctx, &fg, argv[6]);',
            '    JS_ToFloat64(ctx, &bg, argv[7]);',
            '    tsuchi_gf_drawBar(x, y, w, h, val, max_val, fg, bg);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_drawBox(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, w, h, bg, border;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &w, argv[2]);',
            '    JS_ToFloat64(ctx, &h, argv[3]);',
            '    JS_ToFloat64(ctx, &bg, argv[4]);',
            '    JS_ToFloat64(ctx, &border, argv[5]);',
            '    tsuchi_gf_drawBox(x, y, w, h, bg, border);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_drawNum(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, n, sz, col;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &n, argv[2]);',
            '    JS_ToFloat64(ctx, &sz, argv[3]);',
            '    JS_ToFloat64(ctx, &col, argv[4]);',
            '    tsuchi_gf_drawNum(x, y, n, sz, col);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_drawFPS(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, sz, col;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &sz, argv[2]);',
            '    JS_ToFloat64(ctx, &col, argv[3]);',
            '    tsuchi_gf_drawFPS(x, y, sz, col);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_drawTile(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double texId, tileId, cols, srcSz, dstSz, dx, dy;',
            '    JS_ToFloat64(ctx, &texId, argv[0]);',
            '    JS_ToFloat64(ctx, &tileId, argv[1]);',
            '    JS_ToFloat64(ctx, &cols, argv[2]);',
            '    JS_ToFloat64(ctx, &srcSz, argv[3]);',
            '    JS_ToFloat64(ctx, &dstSz, argv[4]);',
            '    JS_ToFloat64(ctx, &dx, argv[5]);',
            '    JS_ToFloat64(ctx, &dy, argv[6]);',
            '    tsuchi_gf_drawTile(texId, tileId, cols, srcSz, dstSz, dx, dy);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_drawSprite(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double texId, frame, srcW, srcH, dx, dy, dstW, dstH;',
            '    JS_ToFloat64(ctx, &texId, argv[0]);',
            '    JS_ToFloat64(ctx, &frame, argv[1]);',
            '    JS_ToFloat64(ctx, &srcW, argv[2]);',
            '    JS_ToFloat64(ctx, &srcH, argv[3]);',
            '    JS_ToFloat64(ctx, &dx, argv[4]);',
            '    JS_ToFloat64(ctx, &dy, argv[5]);',
            '    JS_ToFloat64(ctx, &dstW, argv[6]);',
            '    JS_ToFloat64(ctx, &dstH, argv[7]);',
            '    tsuchi_gf_drawSprite(texId, frame, srcW, srcH, dx, dy, dstW, dstH);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_drawFade(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double alpha, w, h;',
            '    JS_ToFloat64(ctx, &alpha, argv[0]);',
            '    JS_ToFloat64(ctx, &w, argv[1]);',
            '    JS_ToFloat64(ctx, &h, argv[2]);',
            '    tsuchi_gf_drawFade(alpha, w, h);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Input helpers',
            'static JSValue js_gf_getDirection(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_gf_getDirection());',
            '}',
            'static JSValue js_gf_confirmPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_gf_confirmPressed());',
            '}',
            'static JSValue js_gf_cancelPressed(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_gf_cancelPressed());',
            '}',
            'static JSValue js_gf_menuCursor(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double cursor, count;',
            '    JS_ToFloat64(ctx, &cursor, argv[0]);',
            '    JS_ToFloat64(ctx, &count, argv[1]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_menuCursor(cursor, count));',
            '}',
            '',
            '// Animation',
            'static JSValue js_gf_animate(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double counter, maxFrames, speed;',
            '    JS_ToFloat64(ctx, &counter, argv[0]);',
            '    JS_ToFloat64(ctx, &maxFrames, argv[1]);',
            '    JS_ToFloat64(ctx, &speed, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_animate(counter, maxFrames, speed));',
            '}',
            '',
            '// Timer system',
            'static JSValue js_gf_timerSet(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot, duration;',
            '    JS_ToFloat64(ctx, &slot, argv[0]);',
            '    JS_ToFloat64(ctx, &duration, argv[1]);',
            '    tsuchi_gf_timerSet(slot, duration);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_timerRepeat(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot, interval;',
            '    JS_ToFloat64(ctx, &slot, argv[0]);',
            '    JS_ToFloat64(ctx, &interval, argv[1]);',
            '    tsuchi_gf_timerRepeat(slot, interval);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_timerTick(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double dt;',
            '    JS_ToFloat64(ctx, &dt, argv[0]);',
            '    tsuchi_gf_timerTick(dt);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_timerActive(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot;',
            '    JS_ToFloat64(ctx, &slot, argv[0]);',
            '    return JS_NewBool(ctx, tsuchi_gf_timerActive(slot));',
            '}',
            'static JSValue js_gf_timerDone(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot;',
            '    JS_ToFloat64(ctx, &slot, argv[0]);',
            '    return JS_NewBool(ctx, tsuchi_gf_timerDone(slot));',
            '}',
            'static JSValue js_gf_timerCancel(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot;',
            '    JS_ToFloat64(ctx, &slot, argv[0]);',
            '    tsuchi_gf_timerCancel(slot);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            '// Easing functions',
            'static JSValue js_gf_easeLinear(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeLinear(t));',
            '}',
            'static JSValue js_gf_easeInQuad(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeInQuad(t));',
            '}',
            'static JSValue js_gf_easeOutQuad(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeOutQuad(t));',
            '}',
            'static JSValue js_gf_easeInOutQuad(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeInOutQuad(t));',
            '}',
            'static JSValue js_gf_easeInCubic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeInCubic(t));',
            '}',
            'static JSValue js_gf_easeOutCubic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeOutCubic(t));',
            '}',
            'static JSValue js_gf_easeInOutCubic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeInOutCubic(t));',
            '}',
            'static JSValue js_gf_easeOutBounce(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeOutBounce(t));',
            '}',
            'static JSValue js_gf_easeOutElastic(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double t; JS_ToFloat64(ctx, &t, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_easeOutElastic(t));',
            '}',
            'static JSValue js_gf_interpolate(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double start, end, t;',
            '    JS_ToFloat64(ctx, &start, argv[0]);',
            '    JS_ToFloat64(ctx, &end, argv[1]);',
            '    JS_ToFloat64(ctx, &t, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_interpolate(start, end, t));',
            '}',
            '',
            '// Tween system',
            'static JSValue js_gf_tweenStart(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot, duration, easing;',
            '    JS_ToFloat64(ctx, &slot, argv[0]);',
            '    JS_ToFloat64(ctx, &duration, argv[1]);',
            '    JS_ToFloat64(ctx, &easing, argv[2]);',
            '    tsuchi_gf_tweenStart(slot, duration, easing);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_tweenTick(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double dt; JS_ToFloat64(ctx, &dt, argv[0]);',
            '    tsuchi_gf_tweenTick(dt);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_tweenValue(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot; JS_ToFloat64(ctx, &slot, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_tweenValue(slot));',
            '}',
            'static JSValue js_gf_tweenActive(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot; JS_ToFloat64(ctx, &slot, argv[0]);',
            '    return JS_NewBool(ctx, tsuchi_gf_tweenActive(slot));',
            '}',
            'static JSValue js_gf_tweenDone(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double slot; JS_ToFloat64(ctx, &slot, argv[0]);',
            '    return JS_NewBool(ctx, tsuchi_gf_tweenDone(slot));',
            '}',
            '',
            '// Screen shake',
            'static JSValue js_gf_shakeStart(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double intensity, duration;',
            '    JS_ToFloat64(ctx, &intensity, argv[0]);',
            '    JS_ToFloat64(ctx, &duration, argv[1]);',
            '    tsuchi_gf_shakeStart(intensity, duration);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_shakeUpdate(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double dt; JS_ToFloat64(ctx, &dt, argv[0]);',
            '    tsuchi_gf_shakeUpdate(dt);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_shakeX(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_gf_shakeX());',
            '}',
            'static JSValue js_gf_shakeY(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_gf_shakeY());',
            '}',
            'static JSValue js_gf_shakeActive(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_gf_shakeActive());',
            '}',
            '',
            '// Scene transitions',
            'static JSValue js_gf_transitionStart(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double duration, nextScene;',
            '    JS_ToFloat64(ctx, &duration, argv[0]);',
            '    JS_ToFloat64(ctx, &nextScene, argv[1]);',
            '    tsuchi_gf_transitionStart(duration, nextScene);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_transitionUpdate(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double dt; JS_ToFloat64(ctx, &dt, argv[0]);',
            '    tsuchi_gf_transitionUpdate(dt);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_transitionAlpha(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_gf_transitionAlpha());',
            '}',
            'static JSValue js_gf_transitionDone(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewBool(ctx, tsuchi_gf_transitionDone());',
            '}',
            'static JSValue js_gf_transitionNextScene(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_gf_transitionNextScene());',
            '}',
            '',
            '// Physics helpers',
            'static JSValue js_gf_physGravity(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double vy, g, dt;',
            '    JS_ToFloat64(ctx, &vy, argv[0]);',
            '    JS_ToFloat64(ctx, &g, argv[1]);',
            '    JS_ToFloat64(ctx, &dt, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_physGravity(vy, g, dt));',
            '}',
            'static JSValue js_gf_physFriction(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double v, friction, dt;',
            '    JS_ToFloat64(ctx, &v, argv[0]);',
            '    JS_ToFloat64(ctx, &friction, argv[1]);',
            '    JS_ToFloat64(ctx, &dt, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_physFriction(v, friction, dt));',
            '}',
            'static JSValue js_gf_physClamp(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double val, min_val, max_val;',
            '    JS_ToFloat64(ctx, &val, argv[0]);',
            '    JS_ToFloat64(ctx, &min_val, argv[1]);',
            '    JS_ToFloat64(ctx, &max_val, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_physClamp(val, min_val, max_val));',
            '}',
            '',
            '// Particle system',
            'static JSValue js_gf_particleEmit(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, vx, vy, life, color;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &vx, argv[2]);',
            '    JS_ToFloat64(ctx, &vy, argv[3]);',
            '    JS_ToFloat64(ctx, &life, argv[4]);',
            '    JS_ToFloat64(ctx, &color, argv[5]);',
            '    tsuchi_gf_particleEmit(x, y, vx, vy, life, color);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_particleUpdate(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double dt, gravity;',
            '    JS_ToFloat64(ctx, &dt, argv[0]);',
            '    JS_ToFloat64(ctx, &gravity, argv[1]);',
            '    tsuchi_gf_particleUpdate(dt, gravity);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_particleDraw(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double size; JS_ToFloat64(ctx, &size, argv[0]);',
            '    tsuchi_gf_particleDraw(size);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_particleCount(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    return JS_NewFloat64(ctx, tsuchi_gf_particleCount());',
            '}',
            'static JSValue js_gf_particleClear(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    tsuchi_gf_particleClear(); return JS_UNDEFINED;',
            '}',
            '',
            '// Grid / Tilemap',
            'static JSValue js_gf_gridToPx(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double grid, tileSize;',
            '    JS_ToFloat64(ctx, &grid, argv[0]);',
            '    JS_ToFloat64(ctx, &tileSize, argv[1]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_gridToPx(grid, tileSize));',
            '}',
            'static JSValue js_gf_pxToGrid(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double px, tileSize;',
            '    JS_ToFloat64(ctx, &px, argv[0]);',
            '    JS_ToFloat64(ctx, &tileSize, argv[1]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_pxToGrid(px, tileSize));',
            '}',
            'static JSValue js_gf_gridIndex(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, cols;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &cols, argv[2]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_gridIndex(x, y, cols));',
            '}',
            'static JSValue js_gf_gridInBounds(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x, y, cols, rows;',
            '    JS_ToFloat64(ctx, &x, argv[0]);',
            '    JS_ToFloat64(ctx, &y, argv[1]);',
            '    JS_ToFloat64(ctx, &cols, argv[2]);',
            '    JS_ToFloat64(ctx, &rows, argv[3]);',
            '    return JS_NewBool(ctx, tsuchi_gf_gridInBounds(x, y, cols, rows));',
            '}',
            'static JSValue js_gf_manhattan(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x1, y1, x2, y2;',
            '    JS_ToFloat64(ctx, &x1, argv[0]);',
            '    JS_ToFloat64(ctx, &y1, argv[1]);',
            '    JS_ToFloat64(ctx, &x2, argv[2]);',
            '    JS_ToFloat64(ctx, &y2, argv[3]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_manhattan(x1, y1, x2, y2));',
            '}',
            'static JSValue js_gf_chebyshev(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double x1, y1, x2, y2;',
            '    JS_ToFloat64(ctx, &x1, argv[0]);',
            '    JS_ToFloat64(ctx, &y1, argv[1]);',
            '    JS_ToFloat64(ctx, &x2, argv[2]);',
            '    JS_ToFloat64(ctx, &y2, argv[3]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_chebyshev(x1, y1, x2, y2));',
            '}',
            '',
            '// FSM',
            'static JSValue js_gf_fsmInit(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id, state;',
            '    JS_ToFloat64(ctx, &id, argv[0]);',
            '    JS_ToFloat64(ctx, &state, argv[1]);',
            '    tsuchi_gf_fsmInit(id, state);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_fsmSet(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id, state;',
            '    JS_ToFloat64(ctx, &id, argv[0]);',
            '    JS_ToFloat64(ctx, &state, argv[1]);',
            '    tsuchi_gf_fsmSet(id, state);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_fsmTick(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id; JS_ToFloat64(ctx, &id, argv[0]);',
            '    tsuchi_gf_fsmTick(id);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_fsmState(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id; JS_ToFloat64(ctx, &id, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_fsmState(id));',
            '}',
            'static JSValue js_gf_fsmPrev(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id; JS_ToFloat64(ctx, &id, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_fsmPrev(id));',
            '}',
            'static JSValue js_gf_fsmFrames(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id; JS_ToFloat64(ctx, &id, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_fsmFrames(id));',
            '}',
            'static JSValue js_gf_fsmJustEntered(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double id; JS_ToFloat64(ctx, &id, argv[0]);',
            '    return JS_NewBool(ctx, tsuchi_gf_fsmJustEntered(id));',
            '}',
            '',
            '// Object pool',
            'static JSValue js_gf_poolAlloc(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double poolId; JS_ToFloat64(ctx, &poolId, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_poolAlloc(poolId));',
            '}',
            'static JSValue js_gf_poolFree(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double poolId, index;',
            '    JS_ToFloat64(ctx, &poolId, argv[0]);',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    tsuchi_gf_poolFree(poolId, index);',
            '    return JS_UNDEFINED;',
            '}',
            'static JSValue js_gf_poolActive(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double poolId, index;',
            '    JS_ToFloat64(ctx, &poolId, argv[0]);',
            '    JS_ToFloat64(ctx, &index, argv[1]);',
            '    return JS_NewBool(ctx, tsuchi_gf_poolActive(poolId, index));',
            '}',
            'static JSValue js_gf_poolCount(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double poolId; JS_ToFloat64(ctx, &poolId, argv[0]);',
            '    return JS_NewFloat64(ctx, tsuchi_gf_poolCount(poolId));',
            '}',
            'static JSValue js_gf_poolClear(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {',
            '    double poolId; JS_ToFloat64(ctx, &poolId, argv[0]);',
            '    tsuchi_gf_poolClear(poolId);',
            '    return JS_UNDEFINED;',
            '}',
            '',
            'static void js_add_gf_builtins(JSContext *ctx) {',
            '    JSValue global = JS_GetGlobalObject(ctx);',
            '',
            '    // Easing type constants',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_LINEAR",       JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_IN_QUAD",      JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_OUT_QUAD",     JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_IN_OUT_QUAD",  JS_NewFloat64(ctx, 3));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_IN_CUBIC",     JS_NewFloat64(ctx, 4));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_OUT_CUBIC",    JS_NewFloat64(ctx, 5));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_IN_OUT_CUBIC", JS_NewFloat64(ctx, 6));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_OUT_BOUNCE",   JS_NewFloat64(ctx, 7));',
            '    JS_SetPropertyStr(ctx, global, "GF_EASE_OUT_ELASTIC",  JS_NewFloat64(ctx, 8));',
            '',
            '    // Direction constants',
            '    JS_SetPropertyStr(ctx, global, "GF_DIR_RIGHT", JS_NewFloat64(ctx, 0));',
            '    JS_SetPropertyStr(ctx, global, "GF_DIR_UP",    JS_NewFloat64(ctx, 1));',
            '    JS_SetPropertyStr(ctx, global, "GF_DIR_LEFT",  JS_NewFloat64(ctx, 2));',
            '    JS_SetPropertyStr(ctx, global, "GF_DIR_DOWN",  JS_NewFloat64(ctx, 3));',
            '    JS_SetPropertyStr(ctx, global, "GF_DIR_NONE",  JS_NewFloat64(ctx, -1));',
            '',
            '#define GF_REG(jsName, cFunc, nargs) \\',
            '    JS_SetPropertyStr(ctx, global, #jsName, JS_NewCFunction(ctx, js_gf_##cFunc, #jsName, nargs))',
            '',
            '    // Math',
            '    GF_REG(gfClamp, clamp, 3);',
            '    GF_REG(gfLerp, lerp, 3);',
            '    GF_REG(gfRand, rand, 1);',
            '    GF_REG(gfRandRange, randRange, 2);',
            '    GF_REG(gfRgba, rgba, 4);',
            '',
            '    // Drawing',
            '    GF_REG(gfDrawBar, drawBar, 8);',
            '    GF_REG(gfDrawBox, drawBox, 6);',
            '    GF_REG(gfDrawNum, drawNum, 5);',
            '    GF_REG(gfDrawFPS, drawFPS, 4);',
            '    GF_REG(gfDrawTile, drawTile, 7);',
            '    GF_REG(gfDrawSprite, drawSprite, 8);',
            '    GF_REG(gfDrawFade, drawFade, 3);',
            '',
            '    // Input',
            '    GF_REG(gfGetDirection, getDirection, 0);',
            '    GF_REG(gfConfirmPressed, confirmPressed, 0);',
            '    GF_REG(gfCancelPressed, cancelPressed, 0);',
            '    GF_REG(gfMenuCursor, menuCursor, 2);',
            '',
            '    // Animation',
            '    GF_REG(gfAnimate, animate, 3);',
            '',
            '    // Timer',
            '    GF_REG(gfTimerSet, timerSet, 2);',
            '    GF_REG(gfTimerRepeat, timerRepeat, 2);',
            '    GF_REG(gfTimerTick, timerTick, 1);',
            '    GF_REG(gfTimerActive, timerActive, 1);',
            '    GF_REG(gfTimerDone, timerDone, 1);',
            '    GF_REG(gfTimerCancel, timerCancel, 1);',
            '',
            '    // Easing',
            '    GF_REG(gfEaseLinear, easeLinear, 1);',
            '    GF_REG(gfEaseInQuad, easeInQuad, 1);',
            '    GF_REG(gfEaseOutQuad, easeOutQuad, 1);',
            '    GF_REG(gfEaseInOutQuad, easeInOutQuad, 1);',
            '    GF_REG(gfEaseInCubic, easeInCubic, 1);',
            '    GF_REG(gfEaseOutCubic, easeOutCubic, 1);',
            '    GF_REG(gfEaseInOutCubic, easeInOutCubic, 1);',
            '    GF_REG(gfEaseOutBounce, easeOutBounce, 1);',
            '    GF_REG(gfEaseOutElastic, easeOutElastic, 1);',
            '    GF_REG(gfInterpolate, interpolate, 3);',
            '',
            '    // Tween',
            '    GF_REG(gfTweenStart, tweenStart, 3);',
            '    GF_REG(gfTweenTick, tweenTick, 1);',
            '    GF_REG(gfTweenValue, tweenValue, 1);',
            '    GF_REG(gfTweenActive, tweenActive, 1);',
            '    GF_REG(gfTweenDone, tweenDone, 1);',
            '',
            '    // Screen shake',
            '    GF_REG(gfShakeStart, shakeStart, 2);',
            '    GF_REG(gfShakeUpdate, shakeUpdate, 1);',
            '    GF_REG(gfShakeX, shakeX, 0);',
            '    GF_REG(gfShakeY, shakeY, 0);',
            '    GF_REG(gfShakeActive, shakeActive, 0);',
            '',
            '    // Scene transitions',
            '    GF_REG(gfTransitionStart, transitionStart, 2);',
            '    GF_REG(gfTransitionUpdate, transitionUpdate, 1);',
            '    GF_REG(gfTransitionAlpha, transitionAlpha, 0);',
            '    GF_REG(gfTransitionDone, transitionDone, 0);',
            '    GF_REG(gfTransitionNextScene, transitionNextScene, 0);',
            '',
            '    // Physics',
            '    GF_REG(gfPhysGravity, physGravity, 3);',
            '    GF_REG(gfPhysFriction, physFriction, 3);',
            '    GF_REG(gfPhysClamp, physClamp, 3);',
            '',
            '    // Particles',
            '    GF_REG(gfParticleEmit, particleEmit, 6);',
            '    GF_REG(gfParticleUpdate, particleUpdate, 2);',
            '    GF_REG(gfParticleDraw, particleDraw, 1);',
            '    GF_REG(gfParticleCount, particleCount, 0);',
            '    GF_REG(gfParticleClear, particleClear, 0);',
            '',
            '    // Grid / Tilemap',
            '    GF_REG(gfGridToPx, gridToPx, 2);',
            '    GF_REG(gfPxToGrid, pxToGrid, 2);',
            '    GF_REG(gfGridIndex, gridIndex, 3);',
            '    GF_REG(gfGridInBounds, gridInBounds, 4);',
            '    GF_REG(gfManhattan, manhattan, 4);',
            '    GF_REG(gfChebyshev, chebyshev, 4);',
            '',
            '    // FSM',
            '    GF_REG(gfFsmInit, fsmInit, 2);',
            '    GF_REG(gfFsmSet, fsmSet, 2);',
            '    GF_REG(gfFsmTick, fsmTick, 1);',
            '    GF_REG(gfFsmState, fsmState, 1);',
            '    GF_REG(gfFsmPrev, fsmPrev, 1);',
            '    GF_REG(gfFsmFrames, fsmFrames, 1);',
            '    GF_REG(gfFsmJustEntered, fsmJustEntered, 1);',
            '',
            '    // Object pool',
            '    GF_REG(gfPoolAlloc, poolAlloc, 1);',
            '    GF_REG(gfPoolFree, poolFree, 2);',
            '    GF_REG(gfPoolActive, poolActive, 2);',
            '    GF_REG(gfPoolCount, poolCount, 1);',
            '    GF_REG(gfPoolClear, poolClear, 1);',
            '',
            '#undef GF_REG',
            '    JS_FreeValue(ctx, global);',
            '}',
        ]


    def _generate_ffi_bindings(self) -> list[str]:
        """Generate QuickJS JSCFunction wrappers + registration for FFI functions."""
        from tsuchi.type_checker.types import (
            NumberType, BooleanType, StringType, VoidType,
            FFIStructType, OpaquePointerType,
        )
        lines = ['// FFI QuickJS bindings']

        # Helper: generate argument extraction code for a single parameter
        def _emit_arg_extract(pt, var, idx, lines, free_strings, call_args):
            if isinstance(pt, NumberType):
                lines.append(f'    double {var}; JS_ToFloat64(ctx, &{var}, argv[{idx}]);')
                call_args.append(var)
            elif isinstance(pt, StringType):
                lines.append(f'    const char *{var} = JS_ToCString(ctx, argv[{idx}]);')
                call_args.append(var)
                free_strings.append(var)
            elif isinstance(pt, BooleanType):
                lines.append(f'    int {var} = JS_ToBool(ctx, argv[{idx}]);')
                call_args.append(var)
            elif isinstance(pt, FFIStructType):
                # Convert JS object to C struct
                st = self._ffi_info.structs.get(pt.name)
                if st:
                    svar = f'{var}_s'
                    lines.append(f'    struct tsuchi_ffi_{pt.name} {svar};')
                    lines.append(f'    {{')
                    lines.append(f'        JSValue obj = argv[{idx}];')
                    for fi, (fname, ftype) in enumerate(st.fields):
                        lines.append(f'        JSValue f{fi} = JS_GetPropertyStr(ctx, obj, "{fname}");')
                        if isinstance(ftype, NumberType):
                            lines.append(f'        JS_ToFloat64(ctx, &{svar}.{fname}, f{fi});')
                        elif isinstance(ftype, BooleanType):
                            lines.append(f'        {svar}.{fname} = JS_ToBool(ctx, f{fi});')
                        elif isinstance(ftype, StringType):
                            lines.append(f'        {svar}.{fname} = JS_ToCString(ctx, f{fi});')
                        else:
                            lines.append(f'        JS_ToFloat64(ctx, &{svar}.{fname}, f{fi});')
                        lines.append(f'        JS_FreeValue(ctx, f{fi});')
                    lines.append(f'    }}')
                    call_args.append(svar)
                else:
                    lines.append(f'    double {var}; JS_ToFloat64(ctx, &{var}, argv[{idx}]);')
                    call_args.append(var)
            elif isinstance(pt, OpaquePointerType):
                # Opaque pointer stored as double (pointer smuggling)
                lines.append(f'    double {var}_d; JS_ToFloat64(ctx, &{var}_d, argv[{idx}]);')
                lines.append(f'    void *{var};')
                lines.append(f'    memcpy(&{var}, &{var}_d, sizeof(void*));')
                call_args.append(var)
            else:
                lines.append(f'    double {var}; JS_ToFloat64(ctx, &{var}, argv[{idx}]);')
                call_args.append(var)

        # Helper: generate return value conversion
        def _emit_return(ret_type, call_expr, lines, free_strings):
            for s in free_strings:
                lines.append(f'    JS_FreeCString(ctx, {s});')
            if isinstance(ret_type, VoidType):
                lines.append(f'    {call_expr};')
                lines.append('    return JS_UNDEFINED;')
            elif isinstance(ret_type, NumberType):
                lines.append(f'    double result = {call_expr};')
                lines.append('    return JS_NewFloat64(ctx, result);')
            elif isinstance(ret_type, StringType):
                lines.append(f'    const char *result = {call_expr};')
                lines.append('    return JS_NewString(ctx, result);')
            elif isinstance(ret_type, BooleanType):
                lines.append(f'    int result = {call_expr};')
                lines.append('    return JS_NewBool(ctx, result);')
            elif isinstance(ret_type, FFIStructType):
                # Convert C struct to JS object
                st = self._ffi_info.structs.get(ret_type.name)
                lines.append(f'    struct tsuchi_ffi_{ret_type.name} result = {call_expr};')
                lines.append(f'    JSValue obj = JS_NewObject(ctx);')
                if st:
                    for fname, ftype in st.fields:
                        if isinstance(ftype, NumberType):
                            lines.append(f'    JS_SetPropertyStr(ctx, obj, "{fname}", JS_NewFloat64(ctx, result.{fname}));')
                        elif isinstance(ftype, BooleanType):
                            lines.append(f'    JS_SetPropertyStr(ctx, obj, "{fname}", JS_NewBool(ctx, result.{fname}));')
                        elif isinstance(ftype, StringType):
                            lines.append(f'    JS_SetPropertyStr(ctx, obj, "{fname}", JS_NewString(ctx, result.{fname}));')
                        else:
                            lines.append(f'    JS_SetPropertyStr(ctx, obj, "{fname}", JS_NewFloat64(ctx, result.{fname}));')
                lines.append('    return obj;')
            elif isinstance(ret_type, OpaquePointerType):
                # Store opaque pointer as double
                lines.append(f'    void *result = {call_expr};')
                lines.append(f'    double result_d;')
                lines.append(f'    memcpy(&result_d, &result, sizeof(void*));')
                lines.append('    return JS_NewFloat64(ctx, result_d);')
            else:
                lines.append(f'    {call_expr};')
                lines.append('    return JS_UNDEFINED;')

        # Generate wrappers for plain FFI functions (skip Class.method / Class#method)
        registered_fns: list[tuple[str, str, int]] = []  # (js_name, c_fn_name, nparams)

        for name, ffi_fn in self._ffi_info.functions.items():
            if '.' in name or '#' in name:
                continue
            js_fn_name = f'js_ffi_{ffi_fn.js_name}'
            lines.append(f'static JSValue {js_fn_name}(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {{')
            free_strings: list[str] = []
            call_args: list[str] = []
            for i, (pt, pn) in enumerate(zip(ffi_fn.param_types, ffi_fn.param_names)):
                var = pn or f'arg{i}'
                _emit_arg_extract(pt, var, i, lines, free_strings, call_args)
            args_str = ', '.join(call_args)
            _emit_return(ffi_fn.return_type, f'{ffi_fn.c_name}({args_str})', lines, free_strings)
            lines.append('}')
            lines.append('')
            registered_fns.append((ffi_fn.js_name, js_fn_name, len(ffi_fn.param_types)))

        # Generate wrappers for opaque class methods
        for oc in self._ffi_info.opaque_classes.values():
            # Static methods: ClassName_methodName(args)
            for mfn in oc.static_methods.values():
                js_fn_name = f'js_ffi_{oc.name}_{mfn.js_name}'
                lines.append(f'static JSValue {js_fn_name}(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {{')
                free_strings: list[str] = []
                call_args: list[str] = []
                for i, (pt, pn) in enumerate(zip(mfn.param_types, mfn.param_names)):
                    var = pn or f'arg{i}'
                    _emit_arg_extract(pt, var, i, lines, free_strings, call_args)
                args_str = ', '.join(call_args)
                _emit_return(mfn.return_type, f'{mfn.c_name}({args_str})', lines, free_strings)
                lines.append('}')
                lines.append('')

            # Instance methods: ClassName_methodName(self_ptr, args)
            for mfn in oc.instance_methods.values():
                js_fn_name = f'js_ffi_{oc.name}_{mfn.js_name}'
                lines.append(f'static JSValue {js_fn_name}(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {{')
                # First arg is the opaque pointer (self)
                lines.append(f'    double self_d; JS_ToFloat64(ctx, &self_d, argv[0]);')
                lines.append(f'    void *self_ptr;')
                lines.append(f'    memcpy(&self_ptr, &self_d, sizeof(void*));')
                free_strings: list[str] = []
                call_args: list[str] = ['self_ptr']
                for i, (pt, pn) in enumerate(zip(mfn.param_types, mfn.param_names)):
                    var = pn or f'arg{i}'
                    _emit_arg_extract(pt, var, i + 1, lines, free_strings, call_args)
                args_str = ', '.join(call_args)
                _emit_return(mfn.return_type, f'{mfn.c_name}({args_str})', lines, free_strings)
                lines.append('}')
                lines.append('')

        # Registration function
        lines.append('static void js_add_ffi_builtins(JSContext *ctx) {')
        lines.append('    JSValue global = JS_GetGlobalObject(ctx);')

        # Register plain functions
        for js_name, c_fn_name, nparams in registered_fns:
            lines.append(
                f'    JS_SetPropertyStr(ctx, global, "{js_name}", '
                f'JS_NewCFunction(ctx, {c_fn_name}, "{js_name}", {nparams}));'
            )

        # Register opaque class methods as ClassName.methodName via a namespace object
        for oc in self._ffi_info.opaque_classes.values():
            lines.append(f'    JSValue {oc.name}_obj = JS_NewObject(ctx);')
            for mfn in oc.static_methods.values():
                js_fn_name = f'js_ffi_{oc.name}_{mfn.js_name}'
                nparams = len(mfn.param_types)
                lines.append(
                    f'    JS_SetPropertyStr(ctx, {oc.name}_obj, "{mfn.js_name}", '
                    f'JS_NewCFunction(ctx, {js_fn_name}, "{mfn.js_name}", {nparams}));'
                )
            # Instance methods registered as __inst_methodName (invoked via wrapper)
            for mfn in oc.instance_methods.values():
                js_fn_name = f'js_ffi_{oc.name}_{mfn.js_name}'
                nparams = len(mfn.param_types) + 1  # +1 for self
                lines.append(
                    f'    JS_SetPropertyStr(ctx, {oc.name}_obj, "__inst_{mfn.js_name}", '
                    f'JS_NewCFunction(ctx, {js_fn_name}, "__inst_{mfn.js_name}", {nparams}));'
                )
            lines.append(
                f'    JS_SetPropertyStr(ctx, global, "{oc.name}", {oc.name}_obj);'
            )

        lines.append('    JS_FreeValue(ctx, global);')
        lines.append('}')
        return lines
