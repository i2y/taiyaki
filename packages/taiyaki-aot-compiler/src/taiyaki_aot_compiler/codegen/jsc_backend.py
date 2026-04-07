"""JavaScriptCore backend: LLVM IR -> standalone binary.

Compiles LLVM IR to object code, generates a C init wrapper with JavaScriptCore
runtime initialization, and links everything into a standalone executable.
"""

from __future__ import annotations

import platform
import subprocess

from taiyaki_aot_compiler.codegen.backend_base import BackendBase
from taiyaki_aot_compiler.hir.nodes import HIRModule, HIRFunction
from taiyaki_aot_compiler.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType, ObjectType, ArrayType,
    FunctionType, MonoType,
)


class JSCBackend(BackendBase):
    """Compiles LLVM IR + C init wrapper + JavaScriptCore into a standalone binary."""

    def _engine_headers(self) -> list[str]:
        return ['#include <JavaScriptCore/JavaScript.h>']

    def _engine_include_flags(self) -> list[str]:
        if platform.system() == "Darwin":
            return []
        # Linux: try pkg-config for WebKitGTK's JSC
        try:
            result = subprocess.run(
                ["pkg-config", "--cflags", "javascriptcoregtk-4.1"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.strip().split()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []

    def _engine_link_flags(self) -> list[str]:
        if platform.system() == "Darwin":
            return ["-framework", "JavaScriptCore"]
        # Linux: try pkg-config
        try:
            result = subprocess.run(
                ["pkg-config", "--libs", "javascriptcoregtk-4.1"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.strip().split()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ["-ljavascriptcoregtk-4.1"]

    def _engine_global_state(self, has_fallbacks: bool) -> list[str]:
        lines = []
        if has_fallbacks:
            lines.extend(['static JSGlobalContextRef tsuchi_ctx = NULL;', ''])
        # Helper used by console.log, CLI bindings, wrappers, etc.
        lines.extend([
            '/* Helper: convert JSValueRef to a malloc\'d C string (caller must free) */',
            'static char* jsc_to_cstring(JSContextRef ctx, JSValueRef val) {',
            '    JSStringRef jsStr = JSValueToStringCopy(ctx, val, NULL);',
            '    size_t bufSize = JSStringGetMaximumUTF8CStringSize(jsStr);',
            '    char *buf = (char*)malloc(bufSize);',
            '    JSStringGetUTF8CString(jsStr, buf, bufSize);',
            '    JSStringRelease(jsStr);',
            '    return buf;',
            '}',
            '',
        ])
        return lines

    def _engine_console_log(self) -> list[str]:
        return [
            '/* console.log implementation */',
            'static JSValueRef jsc_console_log(JSContextRef ctx, JSObjectRef function,',
            '        JSObjectRef thisObject, size_t argumentCount,',
            '        const JSValueRef arguments[], JSValueRef* exception) {',
            '    for (size_t i = 0; i < argumentCount; i++) {',
            '        if (i > 0) putchar(\' \');',
            '        if (JSValueIsBoolean(ctx, arguments[i])) {',
            '            printf("%s", JSValueToBoolean(ctx, arguments[i]) ? "true" : "false");',
            '        } else if (JSValueIsNumber(ctx, arguments[i])) {',
            '            double val = JSValueToNumber(ctx, arguments[i], NULL);',
            '            if (val == (double)(long long)val && val >= -1e15 && val <= 1e15)',
            '                printf("%lld", (long long)val);',
            '            else',
            '                printf("%g", val);',
            '        } else {',
            '            char *str = jsc_to_cstring(ctx, arguments[i]);',
            '            if (str) { printf("%s", str); free(str); }',
            '        }',
            '    }',
            '    putchar(\'\\n\');',
            '    return JSValueMakeUndefined(ctx);',
            '}',
            '',
            'static void jsc_add_console(JSGlobalContextRef ctx) {',
            '    JSObjectRef global = JSContextGetGlobalObject(ctx);',
            '',
            '    /* Create console object */',
            '    JSObjectRef console = JSObjectMake(ctx, NULL, NULL);',
            '',
            '    /* Add log method */',
            '    JSStringRef logName = JSStringCreateWithUTF8CString("log");',
            '    JSObjectRef logFn = JSObjectMakeFunctionWithCallback(ctx, logName, jsc_console_log);',
            '    JSObjectSetProperty(ctx, console, logName, logFn, 0, NULL);',
            '    JSStringRelease(logName);',
            '',
            '    /* Add error method */',
            '    JSStringRef errorName = JSStringCreateWithUTF8CString("error");',
            '    JSObjectRef errorFn = JSObjectMakeFunctionWithCallback(ctx, errorName, jsc_console_log);',
            '    JSObjectSetProperty(ctx, console, errorName, errorFn, 0, NULL);',
            '    JSStringRelease(errorName);',
            '',
            '    /* Add warn method */',
            '    JSStringRef warnName = JSStringCreateWithUTF8CString("warn");',
            '    JSObjectRef warnFn = JSObjectMakeFunctionWithCallback(ctx, warnName, jsc_console_log);',
            '    JSObjectSetProperty(ctx, console, warnName, warnFn, 0, NULL);',
            '    JSStringRelease(warnName);',
            '',
            '    /* Register console on global */',
            '    JSStringRef consoleName = JSStringCreateWithUTF8CString("console");',
            '    JSObjectSetProperty(ctx, global, consoleName, console, 0, NULL);',
            '    JSStringRelease(consoleName);',
            '}',
            '',
        ]

    def _generate_wrapper(self, func: HIRFunction) -> list[str]:
        """Generate a wrapper function bridging native <-> JSC calling convention."""
        lines = []
        lines.append(
            f'static JSValueRef tsuchi_wrap_{func.name}(JSContextRef ctx, JSObjectRef function,'
        )
        lines.append(
            f'        JSObjectRef thisObject, size_t argumentCount,'
        )
        lines.append(
            f'        const JSValueRef arguments[], JSValueRef* exception) {{'
        )

        # Unbox arguments
        for i, p in enumerate(func.params):
            if isinstance(p.type, NumberType):
                lines.append(f'    double arg_{i} = JSValueToNumber(ctx, arguments[{i}], NULL);')
            elif isinstance(p.type, BooleanType):
                lines.append(f'    int arg_{i} = JSValueToBoolean(ctx, arguments[{i}]);')
            elif isinstance(p.type, StringType):
                lines.append(f'    char *arg_{i} = jsc_to_cstring(ctx, arguments[{i}]);')
            elif isinstance(p.type, ArrayType):
                lines.append(f'    TsuchiArray *arg_{i};')
                lines.append('    {')
                lines.append(f'        JSStringRef lenName = JSStringCreateWithUTF8CString("length");')
                lines.append(f'        JSValueRef len_val = JSObjectGetProperty(ctx, (JSObjectRef)arguments[{i}], lenName, NULL);')
                lines.append(f'        JSStringRelease(lenName);')
                lines.append(f'        int len = (int)JSValueToNumber(ctx, len_val, NULL);')
                lines.append(f'        arg_{i} = tsuchi_array_new(len);')
                lines.append(f'        for (int j = 0; j < len; j++) {{')
                lines.append(f'            JSValueRef elem = JSObjectGetPropertyAtIndex(ctx, (JSObjectRef)arguments[{i}], j, NULL);')
                lines.append(f'            double v = JSValueToNumber(ctx, elem, NULL);')
                lines.append(f'            tsuchi_array_set(arg_{i}, j, v);')
                lines.append(f'        }}')
                lines.append('    }')
            elif isinstance(p.type, ObjectType):
                struct_name = self._struct_c_name(p.type)
                lines.append(f'    {struct_name} arg_{i};')
                lines.append('    {')
                for fname, ftype in sorted(p.type.fields.items()):
                    lines.append(f'        JSStringRef prop_{fname} = JSStringCreateWithUTF8CString("{fname}");')
                    lines.append(f'        JSValueRef val_{fname} = JSObjectGetProperty(ctx, (JSObjectRef)arguments[{i}], prop_{fname}, NULL);')
                    lines.append(f'        JSStringRelease(prop_{fname});')
                    if isinstance(ftype, NumberType):
                        lines.append(f'        arg_{i}.{fname} = JSValueToNumber(ctx, val_{fname}, NULL);')
                    elif isinstance(ftype, BooleanType):
                        lines.append(f'        arg_{i}.{fname} = JSValueToBoolean(ctx, val_{fname});')
                lines.append('    }')
            else:
                lines.append(f'    double arg_{i} = JSValueToNumber(ctx, arguments[{i}], NULL);')

        # Call native function
        args_str = ", ".join(f'arg_{i}' for i in range(len(func.params)))

        if isinstance(func.return_type, VoidType):
            lines.append(f'    _tsuchi_{func.name}({args_str});')
            # Free string arguments
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            lines.append('    return JSValueMakeUndefined(ctx);')
        elif isinstance(func.return_type, NumberType):
            lines.append(f'    double result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            lines.append('    return JSValueMakeNumber(ctx, result);')
        elif isinstance(func.return_type, BooleanType):
            lines.append(f'    int result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            lines.append('    return JSValueMakeBoolean(ctx, result);')
        elif isinstance(func.return_type, StringType):
            lines.append(f'    const char *result = _tsuchi_{func.name}({args_str});')
            # Box result BEFORE freeing args (result may alias an arg pointer)
            lines.append('    JSStringRef resultStr = JSStringCreateWithUTF8CString(result);')
            lines.append('    JSValueRef retVal = JSValueMakeString(ctx, resultStr);')
            lines.append('    JSStringRelease(resultStr);')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            lines.append('    return retVal;')
        elif isinstance(func.return_type, ObjectType):
            struct_name = self._struct_c_name(func.return_type)
            lines.append(f'    {struct_name} result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            lines.append('    JSObjectRef ret = JSObjectMake(ctx, NULL, NULL);')
            for fname, ftype in sorted(func.return_type.fields.items()):
                if isinstance(ftype, NumberType):
                    lines.append(f'    {{')
                    lines.append(f'        JSStringRef pname = JSStringCreateWithUTF8CString("{fname}");')
                    lines.append(f'        JSObjectSetProperty(ctx, ret, pname, JSValueMakeNumber(ctx, result.{fname}), 0, NULL);')
                    lines.append(f'        JSStringRelease(pname);')
                    lines.append(f'    }}')
                elif isinstance(ftype, BooleanType):
                    lines.append(f'    {{')
                    lines.append(f'        JSStringRef pname = JSStringCreateWithUTF8CString("{fname}");')
                    lines.append(f'        JSObjectSetProperty(ctx, ret, pname, JSValueMakeBoolean(ctx, result.{fname}), 0, NULL);')
                    lines.append(f'        JSStringRelease(pname);')
                    lines.append(f'    }}')
            lines.append('    return ret;')
        elif isinstance(func.return_type, ArrayType):
            lines.append(f'    TsuchiArray *result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            # Convert TsuchiArray* to JS array
            lines.append('    JSObjectRef ret = JSObjectMakeArray(ctx, 0, NULL, NULL);')
            lines.append('    for (int i = 0; i < result->length; i++) {')
            lines.append('        JSObjectSetPropertyAtIndex(ctx, ret, i, JSValueMakeNumber(ctx, result->data[i]), NULL);')
            lines.append('    }')
            lines.append('    return ret;')
        else:
            lines.append(f'    double result = _tsuchi_{func.name}({args_str});')
            for i, p in enumerate(func.params):
                if isinstance(p.type, StringType):
                    lines.append(f'    free(arg_{i});')
            lines.append('    return JSValueMakeNumber(ctx, result);')

        lines.append('}')
        return lines

    def _generate_fallback_bridges(self, hir_module: HIRModule) -> list[str]:
        """Generate C bridge functions that call JSC-evaluated fallback functions."""
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
            lines.append('    JSObjectRef global = JSContextGetGlobalObject(tsuchi_ctx);')
            lines.append(f'    JSStringRef fnName = JSStringCreateWithUTF8CString("{name}");')
            lines.append(f'    JSValueRef fnVal = JSObjectGetProperty(tsuchi_ctx, global, fnName, NULL);')
            lines.append(f'    JSStringRelease(fnName);')
            lines.append(f'    JSObjectRef fn = JSValueToObject(tsuchi_ctx, fnVal, NULL);')

            if info.param_count > 0:
                lines.append(f'    JSValueRef args[{info.param_count}];')
                for i in range(info.param_count):
                    lines.append(f'    args[{i}] = JSValueMakeNumber(tsuchi_ctx, arg{i});')
                lines.append(f'    JSValueRef result = JSObjectCallAsFunction(tsuchi_ctx, fn, NULL, {info.param_count}, args, NULL);')
            else:
                lines.append('    JSValueRef result = JSObjectCallAsFunction(tsuchi_ctx, fn, NULL, 0, NULL, NULL);')

            if ret_hint == "void":
                pass  # no return value to extract
            elif ret_hint == "string":
                lines.append('    const char *s = "";')
                lines.append('    if (result && !JSValueIsUndefined(tsuchi_ctx, result)) {')
                lines.append('        char *tmp = jsc_to_cstring(tsuchi_ctx, result);')
                lines.append('        if (tmp) {')
                lines.append('            s = tmp;')
                lines.append('        }')
                lines.append('    }')
            elif ret_hint == "boolean":
                lines.append('    int ret = 0;')
                lines.append('    if (result && !JSValueIsUndefined(tsuchi_ctx, result))')
                lines.append('        ret = JSValueToBoolean(tsuchi_ctx, result);')
            else:
                lines.append('    double ret = 0.0;')
                lines.append('    if (result && !JSValueIsUndefined(tsuchi_ctx, result))')
                lines.append('        ret = JSValueToNumber(tsuchi_ctx, result, NULL);')

            if ret_hint == "void":
                pass
            elif ret_hint == "string":
                lines.append('    return s;')
            else:
                lines.append('    return ret;')

            lines.append('}')
            lines.append('')
        return lines

    def _generate_resize_callback(self, exported_funcs: list[HIRFunction]) -> list[str]:
        """Generate the resize frame callback (Clay live resize support)."""
        lines: list[str] = []
        if self._uses_clay:
            lines.append('/* Resize frame: called from GLFW refresh callback during live resize */')
            lines.append('extern void tsuchi_clay_set_resize_frame(void (*fn)(void));')
            lines.append('static JSGlobalContextRef _tsuchi_resize_ctx = NULL;')
            lines.append('static void _tsuchi_resize_frame(void) {')
            lines.append('    if (!_tsuchi_resize_ctx) return;')
            lines.append('    JSObjectRef global = JSContextGetGlobalObject(_tsuchi_resize_ctx);')
            lines.append('    JSStringRef fnName = JSStringCreateWithUTF8CString("_resizeFrame");')
            lines.append('    JSValueRef fnVal = JSObjectGetProperty(_tsuchi_resize_ctx, global, fnName, NULL);')
            lines.append('    JSStringRelease(fnName);')
            lines.append('    if (JSValueIsObject(_tsuchi_resize_ctx, fnVal)) {')
            lines.append('        JSObjectRef fn = JSValueToObject(_tsuchi_resize_ctx, fnVal, NULL);')
            lines.append('        JSValueRef exc = NULL;')
            lines.append('        JSObjectCallAsFunction(_tsuchi_resize_ctx, fn, NULL, 0, NULL, &exc);')
            lines.append('    }')
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

        # Build set of async function names for detecting async entry calls
        async_func_names = {f.name for f in async_funcs}

        lines.append('int main(int argc, char *argv[]) {')
        lines.append('    tsuchi_argc = argc;')
        lines.append('    tsuchi_argv = argv;')
        lines.append('')

        # Initialize event loop if async functions are present
        if has_async:
            lines.append('    tsuchi_loop_init();')
            lines.append('')

        # Determine which entry statements are async direct calls vs JS eval
        async_entry_calls, js_entry_stmts = self._split_entry_statements(
            hir_module.entry_statements, async_func_names
        )

        # Check if there are any entry statements or fallbacks that need JSC
        needs_jsc = bool(js_entry_stmts) or has_fallbacks

        if needs_jsc:
            lines.append('    JSGlobalContextRef ctx = JSGlobalContextCreate(NULL);')
            if has_fallbacks:
                lines.append('    tsuchi_ctx = ctx;')
            lines.append('    jsc_add_console(ctx);')
            lines.append('    jsc_add_cli_builtins(ctx);')
            lines.append('')

            # Register compiled functions as global JS functions
            lines.append('    JSObjectRef global = JSContextGetGlobalObject(ctx);')
            for func in exported_funcs:
                fname = func.name
                lines.append('    {')
                lines.append(f'        JSStringRef name = JSStringCreateWithUTF8CString("{fname}");')
                lines.append(f'        JSObjectRef fn = JSObjectMakeFunctionWithCallback(ctx, name, tsuchi_wrap_{fname});')
                lines.append(f'        JSObjectSetProperty(ctx, global, name, fn, 0, NULL);')
                lines.append(f'        JSStringRelease(name);')
                lines.append('    }')

            # Register import aliases so entry statements can use original names
            if hir_module.func_aliases:
                reverse_aliases: dict[str, list[str]] = {}
                for alias, canonical in hir_module.func_aliases.items():
                    reverse_aliases.setdefault(canonical, []).append(alias)
                for func in exported_funcs:
                    for alias in reverse_aliases.get(func.name, []):
                        lines.append('    {')
                        lines.append(f'        JSStringRef name = JSStringCreateWithUTF8CString("{alias}");')
                        lines.append(f'        JSObjectRef fn = JSObjectMakeFunctionWithCallback(ctx, name, tsuchi_wrap_{func.name});')
                        lines.append(f'        JSObjectSetProperty(ctx, global, name, fn, 0, NULL);')
                        lines.append(f'        JSStringRelease(name);')
                        lines.append('    }')

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
                    lines.append(f'        JSStringRef script = JSStringCreateWithUTF8CString("{escaped}");')
                    lines.append(f'        JSValueRef exc = NULL;')
                    lines.append(f'        JSValueRef _r = JSEvaluateScript(ctx, script, NULL, NULL, 0, &exc);')
                    lines.append(f'        JSStringRelease(script);')
                    lines.append(f'        if (exc) {{')
                    lines.append(f'            char *errStr = jsc_to_cstring(ctx, exc);')
                    lines.append(f'            if (errStr) {{ fprintf(stderr, "Fallback eval error: %s\\n", errStr); free(errStr); }}')
                    lines.append(f'        }}')
                    lines.append('    }')
                lines.append('')

            # Execute JS entry statements (non-async)
            for idx, entry_src in enumerate(js_entry_stmts):
                escaped = self._escape_c_string(entry_src)
                lines.append('    {')
                lines.append(f'        JSStringRef script = JSStringCreateWithUTF8CString("{escaped}");')
                lines.append(f'        JSValueRef exc = NULL;')
                lines.append(f'        JSValueRef _r = JSEvaluateScript(ctx, script, NULL, NULL, 0, &exc);')
                lines.append(f'        JSStringRelease(script);')
                lines.append(f'        if (exc) {{')
                lines.append(f'            char *errStr = jsc_to_cstring(ctx, exc);')
                lines.append(f'            if (errStr) {{ fprintf(stderr, "Error: %s\\n", errStr); free(errStr); }}')
                lines.append(f'        }}')
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
            lines.append('    JSGlobalContextRelease(ctx);')
        else:
            if has_async:
                # Async-only mode — no JSC needed, just call async entry points
                lines.append('    /* Async native mode -- no JSC runtime */')
                for fname in async_entry_calls:
                    lines.append(f'    _tsuchi_{fname}();')
                lines.append('')
                lines.append('    tsuchi_loop_run();')
                lines.append('    tsuchi_loop_close();')
            else:
                # Pure native mode -- no JSC runtime needed
                lines.append('    /* Pure native mode -- no JSC runtime */')
                for func in exported_funcs:
                    if func.name == "main":
                        lines.append(f'    _tsuchi_main();')

        lines.append('    return 0;')
        lines.append('}')

        return lines

    # ---------------------------------------------------------------
    # Stub methods -- return [] for now (Phase 2 minimal)
    # ---------------------------------------------------------------

    def _generate_cli_bindings(self) -> list[str]:
        return [
            '/* JSC bindings for CLI builtins */',
            'static JSValueRef jsc_readFile(JSContextRef ctx, JSObjectRef function,',
            '        JSObjectRef thisObject, size_t argumentCount,',
            '        const JSValueRef arguments[], JSValueRef* exception) {',
            '    char *path = jsc_to_cstring(ctx, arguments[0]);',
            '    if (!path) return JSValueMakeUndefined(ctx);',
            '    char *content = tsuchi_readFile(path);',
            '    free(path);',
            '    JSStringRef str = JSStringCreateWithUTF8CString(content);',
            '    JSValueRef result = JSValueMakeString(ctx, str);',
            '    JSStringRelease(str);',
            '    free(content);',
            '    return result;',
            '}',
            '',
            'static JSValueRef jsc_writeFile(JSContextRef ctx, JSObjectRef function,',
            '        JSObjectRef thisObject, size_t argumentCount,',
            '        const JSValueRef arguments[], JSValueRef* exception) {',
            '    char *path = jsc_to_cstring(ctx, arguments[0]);',
            '    char *content = jsc_to_cstring(ctx, arguments[1]);',
            '    if (path && content) tsuchi_writeFile(path, content);',
            '    if (path) free(path);',
            '    if (content) free(content);',
            '    return JSValueMakeUndefined(ctx);',
            '}',
            '',
            'static JSValueRef jsc_getenv(JSContextRef ctx, JSObjectRef function,',
            '        JSObjectRef thisObject, size_t argumentCount,',
            '        const JSValueRef arguments[], JSValueRef* exception) {',
            '    char *name = jsc_to_cstring(ctx, arguments[0]);',
            '    if (!name) return JSValueMakeUndefined(ctx);',
            '    const char *val = tsuchi_getenv(name);',
            '    free(name);',
            '    JSStringRef str = JSStringCreateWithUTF8CString(val);',
            '    JSValueRef result = JSValueMakeString(ctx, str);',
            '    JSStringRelease(str);',
            '    return result;',
            '}',
            '',
            'static void jsc_add_cli_builtins(JSGlobalContextRef ctx) {',
            '    JSObjectRef global = JSContextGetGlobalObject(ctx);',
            '',
            '    // readFile, writeFile',
            '    JSStringRef rfName = JSStringCreateWithUTF8CString("readFile");',
            '    JSObjectRef rfFn = JSObjectMakeFunctionWithCallback(ctx, rfName, jsc_readFile);',
            '    JSObjectSetProperty(ctx, global, rfName, rfFn, 0, NULL);',
            '    JSStringRelease(rfName);',
            '',
            '    JSStringRef wfName = JSStringCreateWithUTF8CString("writeFile");',
            '    JSObjectRef wfFn = JSObjectMakeFunctionWithCallback(ctx, wfName, jsc_writeFile);',
            '    JSObjectSetProperty(ctx, global, wfName, wfFn, 0, NULL);',
            '    JSStringRelease(wfName);',
            '',
            '    // process object: argv + env proxy',
            '    JSObjectRef process = JSObjectMake(ctx, NULL, NULL);',
            '',
            '    // process.argv',
            '    JSValueRef *argv_vals = (JSValueRef*)malloc(tsuchi_argc * sizeof(JSValueRef));',
            '    for (int i = 0; i < tsuchi_argc; i++) {',
            '        JSStringRef s = JSStringCreateWithUTF8CString(tsuchi_argv[i]);',
            '        argv_vals[i] = JSValueMakeString(ctx, s);',
            '        JSStringRelease(s);',
            '    }',
            '    JSObjectRef argv_arr = JSObjectMakeArray(ctx, tsuchi_argc, argv_vals, NULL);',
            '    free(argv_vals);',
            '    JSStringRef argvName = JSStringCreateWithUTF8CString("argv");',
            '    JSObjectSetProperty(ctx, process, argvName, argv_arr, 0, NULL);',
            '    JSStringRelease(argvName);',
            '',
            '    // __tsuchi_jsc_getenv helper',
            '    JSStringRef geName = JSStringCreateWithUTF8CString("__tsuchi_jsc_getenv");',
            '    JSObjectRef geFn = JSObjectMakeFunctionWithCallback(ctx, geName, jsc_getenv);',
            '    JSObjectSetProperty(ctx, global, geName, geFn, 0, NULL);',
            '    JSStringRelease(geName);',
            '',
            '    JSStringRef procName = JSStringCreateWithUTF8CString("process");',
            '    JSObjectSetProperty(ctx, global, procName, process, 0, NULL);',
            '    JSStringRelease(procName);',
            '',
            '    // process.env via Proxy',
            '    const char *env_proxy_code =',
            '        "globalThis.process.env = new Proxy({}, {"',
            '        "  get(t, name) { return __tsuchi_jsc_getenv(name); }"',
            '        "});";',
            '    JSStringRef envScript = JSStringCreateWithUTF8CString(env_proxy_code);',
            '    JSEvaluateScript(ctx, envScript, NULL, NULL, 0, NULL);',
            '    JSStringRelease(envScript);',
            '}',
        ]

    def _generate_http_shell_bindings(self) -> list[str]:
        return []

    def _generate_raylib_bindings(self) -> list[str]:
        return []

    def _generate_clay_bindings(self) -> list[str]:
        return []

    def _generate_clay_tui_bindings(self) -> list[str]:
        return []

    def _generate_ui_bindings(self) -> list[str]:
        return []

    def _generate_gf_bindings(self) -> list[str]:
        return []

    def _generate_ffi_bindings(self) -> list[str]:
        return []
