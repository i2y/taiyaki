"""Abstract base for JavaScript runtime backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
import subprocess
import tempfile
from pathlib import Path

from llvmlite import binding as llvm

from taiyaki_aot_compiler.hir.nodes import (
    HIRModule, HIRFunction, HIRConst, HIRParam, HIRBinaryOp, HIRUnaryOp,
    HIRCompare, HIRCall, HIRAssign, HIRReturn, HIRBranch, HIRJump, HIRPhi,
    HIRAwait, BasicBlock,
)
from taiyaki_aot_compiler.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType, ObjectType, ArrayType,
    FunctionType, MonoType, PromiseType,
)

llvm.initialize_native_target()
llvm.initialize_native_asmprinter()

def _find_project_root() -> Path:
    """Find project root by looking for vendor/ directory."""
    p = Path(__file__).resolve().parent
    for _ in range(6):
        if (p / "vendor").is_dir():
            return p
        p = p.parent
    # Fallback: assume src layout (4 levels up from codegen/backend_base.py)
    return Path(__file__).resolve().parent.parent.parent.parent

_PROJECT_ROOT = _find_project_root()


class BackendBase(ABC):
    """Abstract base class for JavaScript runtime backends (QuickJS, JSC, etc.)."""

    # ---------------------------------------------------------------
    # Abstract methods — each subclass must implement
    # ---------------------------------------------------------------

    @abstractmethod
    def _engine_headers(self) -> list[str]:
        """Return C #include lines for the engine (e.g. '#include "quickjs.h"')."""
        ...

    @abstractmethod
    def _engine_include_flags(self) -> list[str]:
        """Return compiler -I flags for the engine headers."""
        ...

    @abstractmethod
    def _engine_link_flags(self) -> list[str]:
        """Return linker flags for the engine library (e.g. ['-L...', '-lqjs'])."""
        ...

    @abstractmethod
    def _engine_global_state(self, has_fallbacks: bool) -> list[str]:
        """Return C lines for engine-specific global state (e.g. 'static JSContext *tsuchi_ctx = NULL;')."""
        ...

    @abstractmethod
    def _engine_console_log(self) -> list[str]:
        """Return C lines implementing console.log for the engine."""
        ...

    @abstractmethod
    def _generate_wrapper(self, func: HIRFunction) -> list[str]:
        """Generate a wrapper function that bridges native ↔ engine calling convention."""
        ...

    @abstractmethod
    def _generate_fallback_bridges(self, hir_module: HIRModule) -> list[str]:
        """Generate C bridge functions that call engine-evaluated fallback functions."""
        ...

    @abstractmethod
    def _generate_engine_main(self, hir_module: HIRModule, exported_funcs: list[HIRFunction],
                              has_fallbacks: bool,
                              has_async: bool = False,
                              async_funcs: list[HIRFunction] | None = None) -> list[str]:
        """Generate the engine-specific main() body (runtime init, register funcs, eval entries, cleanup)."""
        ...

    @abstractmethod
    def _generate_resize_callback(self, exported_funcs: list[HIRFunction]) -> list[str]:
        """Generate the resize frame callback (Clay live resize support)."""
        ...

    @abstractmethod
    def _generate_cli_bindings(self) -> list[str]:
        """Generate engine-side bindings for CLI builtins (readFile, writeFile, process.env)."""
        ...

    @abstractmethod
    def _generate_http_shell_bindings(self) -> list[str]:
        """Generate engine-side bindings for exec/httpGet/httpPost."""
        ...

    @abstractmethod
    def _generate_raylib_bindings(self) -> list[str]:
        """Generate engine-side bindings for raylib functions."""
        ...

    @abstractmethod
    def _generate_clay_bindings(self) -> list[str]:
        """Generate engine-side bindings for Clay UI."""
        ...

    @abstractmethod
    def _generate_clay_tui_bindings(self) -> list[str]:
        """Generate engine-side bindings for Clay TUI."""
        ...

    @abstractmethod
    def _generate_ui_bindings(self) -> list[str]:
        """Generate engine-side bindings for UI widgets."""
        ...

    @abstractmethod
    def _generate_gf_bindings(self) -> list[str]:
        """Generate engine-side bindings for game framework."""
        ...

    @abstractmethod
    def _generate_ffi_bindings(self) -> list[str]:
        """Generate engine-side bindings for FFI functions."""
        ...

    # ---------------------------------------------------------------
    # Concrete shared methods
    # ---------------------------------------------------------------

    def emit_binary(
        self, llvm_ir: str, module_name: str, hir_module: HIRModule,
        output_dir: str = ".", source: str = "", input_dir: str = ".",
    ) -> str:
        """Compile LLVM IR + C wrapper → standalone binary.

        Returns the path to the generated executable.
        """
        # Detect if raylib/clay/clay-tui is used by checking for function calls in LLVM IR
        self._uses_clay_tui = "tsuchi_clay_tui_" in llvm_ir
        # TUI and GUI are mutually exclusive — TUI does not use raylib
        self._uses_clay = "tsuchi_clay_" in llvm_ir and not self._uses_clay_tui
        self._uses_raylib = ("tsuchi_rl_" in llvm_ir or self._uses_clay) and not self._uses_clay_tui
        has_fetch = any(
            hasattr(instr, 'func_name') and 'fetch_async' in getattr(instr, 'func_name', '')
            for f in hir_module.functions
            for bb in f.blocks
            for instr in bb.instructions
        )
        self._uses_curl = ("tsuchi_httpGet" in llvm_ir or "tsuchi_httpPost" in llvm_ir
                            or has_fetch)
        self._uses_ui = "tsuchi_ui_" in llvm_ir
        self._uses_gf = "tsuchi_gf_" in llvm_ir
        self._uses_async = ("tsuchi_promise_" in llvm_ir
                             or "tsuchi_setTimeout" in llvm_ir
                             or "tsuchi_fs_readFile_async" in llvm_ir
                             or "tsuchi_fs_writeFile_async" in llvm_ir
                             or "tsuchi_fetch" in llvm_ir
                             or has_fetch
                             or any(f.is_async for f in hir_module.functions))
        self._ffi_info = hir_module.ffi_info
        output_path = str(Path(output_dir) / module_name)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Step 1: Compile LLVM IR to object file
            obj_path = tmpdir / f"{module_name}.o"
            self._compile_ir_to_object(llvm_ir, str(obj_path))

            # Step 2: Generate and compile C main wrapper
            main_c_path = tmpdir / f"{module_name}_main.c"
            main_o_path = tmpdir / f"{module_name}_main.o"
            c_source = self._generate_main_c(module_name, hir_module, source)
            main_c_path.write_text(c_source)
            self._compile_c(str(main_c_path), str(main_o_path))

            # Step 2.5: Compile FFI C source files
            extra_objs: list[str] = []
            if self._ffi_info is not None:
                input_base = Path(input_dir)
                for c_src in self._ffi_info.c_sources:
                    c_path = input_base / c_src
                    if not c_path.exists():
                        c_path = Path(c_src)
                    ffi_o = tmpdir / (Path(c_src).stem + "_ffi.o")
                    self._compile_c(str(c_path), str(ffi_o))
                    extra_objs.append(str(ffi_o))

            # Step 3: Link into standalone binary
            self._link_binary(str(obj_path), str(main_o_path), output_path,
                              extra_objs=extra_objs)

        return output_path

    def _compile_ir_to_object(self, llvm_ir: str, output_path: str):
        mod = llvm.parse_assembly(llvm_ir)
        mod.verify()

        target = llvm.Target.from_default_triple()
        target_machine = target.create_target_machine(
            cpu=llvm.get_host_cpu_name(),
            opt=3,
            reloc="pic",
            codemodel="default",
        )

        # Run LLVM optimization passes
        pto = llvm.PipelineTuningOptions(speed_level=3, size_level=0)
        pto.loop_unrolling = True
        pto.loop_vectorization = True
        pto.slp_vectorization = True
        pto.loop_interleaving = True
        pb = llvm.create_pass_builder(target_machine, pto)
        pb.getModulePassManager().run(mod, pb)

        obj_data = target_machine.emit_object(mod)
        Path(output_path).write_bytes(obj_data)

    def _compile_c(self, c_path: str, output_path: str):
        cmd = [
            "cc", "-c", "-O3", "-march=native",
        ]
        cmd.extend(self._engine_include_flags())
        cmd.extend(["-o", output_path, c_path])
        if self._uses_raylib:
            try:
                rl_cflags = subprocess.run(
                    ["pkg-config", "--cflags", "raylib"],
                    capture_output=True, text=True, check=True
                ).stdout.strip().split()
                cmd[1:1] = rl_cflags
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        if self._uses_clay:
            _CLAY_INCLUDE = _PROJECT_ROOT / "vendor" / "clay"
            cmd[1:1] = [f"-I{_CLAY_INCLUDE}"]
        if self._uses_clay_tui:
            _CLAY_INCLUDE = _PROJECT_ROOT / "vendor" / "clay"
            _TB2_INCLUDE = _PROJECT_ROOT / "vendor" / "termbox2"
            cmd[1:1] = [f"-I{_CLAY_INCLUDE}", f"-I{_TB2_INCLUDE}"]
        if self._uses_async:
            try:
                uv_cflags = subprocess.run(
                    ["pkg-config", "--cflags", "libuv"],
                    capture_output=True, text=True, check=True
                ).stdout.strip().split()
                cmd[1:1] = uv_cflags
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"C compile failed:\n{result.stderr}"
            raise RuntimeError(msg)

    def _link_binary(self, obj_path: str, main_obj_path: str, output_path: str,
                     extra_objs: list[str] | None = None):
        import platform
        cmd = [
            "cc",
            "-O2", "-march=native",
            "-o", output_path,
            obj_path, main_obj_path,
        ]
        if extra_objs:
            cmd.extend(extra_objs)
        cmd.extend(self._engine_link_flags())
        cmd.extend(["-lm", "-lpthread"])
        # Link raylib if the source uses it (static lib for GLFW symbol access)
        if self._uses_raylib:
            try:
                rl_cflags = subprocess.run(
                    ["pkg-config", "--cflags", "raylib"],
                    capture_output=True, text=True, check=True
                ).stdout.strip().split()
                rl_libdir = subprocess.run(
                    ["pkg-config", "--variable=libdir", "raylib"],
                    capture_output=True, text=True, check=True
                ).stdout.strip()
                cmd.extend(rl_cflags)
                # Prefer static lib to expose GLFW symbols (needed for resize callback)
                static_lib = Path(rl_libdir) / "libraylib.a"
                if static_lib.exists():
                    cmd.append(str(static_lib))
                else:
                    cmd.extend([f"-L{rl_libdir}", "-lraylib"])
            except (subprocess.CalledProcessError, FileNotFoundError):
                cmd.extend(["-lraylib"])
            if platform.system() == "Darwin":
                cmd.extend([
                    "-framework", "IOKit",
                    "-framework", "Cocoa",
                    "-framework", "OpenGL",
                ])
        # Link libcurl if HTTP functions are used
        if self._uses_curl:
            try:
                curl_flags = subprocess.run(
                    ["pkg-config", "--libs", "libcurl"],
                    capture_output=True, text=True, check=True
                ).stdout.strip().split()
                cmd.extend(curl_flags)
            except (subprocess.CalledProcessError, FileNotFoundError):
                cmd.append("-lcurl")
        # FFI link flags
        if self._ffi_info is not None:
            for lib in self._ffi_info.link_libs:
                cmd.append(lib)
            for lp in self._ffi_info.lib_paths:
                cmd.append(f"-L{lp}")
        # Link libuv if async features are used
        if self._uses_async:
            try:
                uv_flags = subprocess.run(
                    ["pkg-config", "--libs", "libuv"],
                    capture_output=True, text=True, check=True
                ).stdout.strip().split()
                cmd.extend(uv_flags)
            except (subprocess.CalledProcessError, FileNotFoundError):
                cmd.append("-luv")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = f"Link failed:\n{result.stderr}"
            raise RuntimeError(msg)

    def _struct_c_name(self, obj_type: ObjectType) -> str:
        """Get a deterministic C struct name for an ObjectType."""
        sorted_names = sorted(obj_type.fields.keys())
        return "tsuchi_s_" + "_".join(sorted_names)

    def _generate_struct_typedefs(self, hir_module: HIRModule) -> list[str]:
        """Generate C struct typedefs for ObjectTypes used in function signatures."""
        lines: list[str] = []
        seen: set[str] = set()
        for func in hir_module.functions:
            for p in func.params:
                if isinstance(p.type, ObjectType):
                    name = self._struct_c_name(p.type)
                    if name not in seen:
                        seen.add(name)
                        lines.extend(self._generate_one_struct_typedef(p.type, name))
            if isinstance(func.return_type, ObjectType):
                name = self._struct_c_name(func.return_type)
                if name not in seen:
                    seen.add(name)
                    lines.extend(self._generate_one_struct_typedef(func.return_type, name))
        return lines

    def _generate_one_struct_typedef(self, obj_type: ObjectType, name: str) -> list[str]:
        lines = [f'typedef struct {{']
        for fname, ftype in sorted(obj_type.fields.items()):
            c_type = self._c_field_type(ftype)
            lines.append(f'    {c_type} {fname};')
        lines.append(f'}} {name};')
        lines.append('')
        return lines

    def _c_field_type(self, ty: MonoType) -> str:
        return self._c_type_for_mono(ty)

    def _c_return_type(self, ty: MonoType) -> str:
        return self._c_type_for_mono(ty)

    def _c_param_type(self, ty: MonoType) -> str:
        return self._c_type_for_mono(ty)

    def _generate_string_runtime(self) -> list[str]:
        """Generate C runtime for string operations."""
        return [
            '/* String runtime */',
            '#include <ctype.h>',
            '',
            'char* tsuchi_str_concat(const char *a, const char *b) {',
            '    size_t la = strlen(a), lb = strlen(b);',
            '    char *result = (char*)malloc(la + lb + 1);',
            '    memcpy(result, a, la);',
            '    memcpy(result + la, b, lb + 1);',
            '    return result;',
            '}',
            '',
            '/* String builder: header-based growable string for amortized O(1) append */',
            '#define TSUCHI_STR_MAGIC 0x54534348u',
            'typedef struct { uint32_t magic; uint32_t _pad; size_t cap; size_t len; } TsuchiStrHdr;',
            '',
            'char* tsuchi_str_concat_owned(char *a, const char *b) {',
            '    size_t lb = strlen(b);',
            '    if (lb == 0) return a;',
            '    /* Check if a is a dynamic string we allocated (has header) */',
            '    TsuchiStrHdr *h = (TsuchiStrHdr*)(a - sizeof(TsuchiStrHdr));',
            '    if (h->magic == TSUCHI_STR_MAGIC && h->len < h->cap && h->cap < ((size_t)1 << 40)) {',
            '        size_t la = h->len;',
            '        size_t new_len = la + lb;',
            '        if (new_len + 1 <= h->cap) {',
            '            memcpy(a + la, b, lb + 1);',
            '            h->len = new_len;',
            '            return a;',
            '        }',
            '        size_t new_cap = (new_len + 1) * 2;',
            '        h = (TsuchiStrHdr*)realloc(h, sizeof(TsuchiStrHdr) + new_cap);',
            '        h->cap = new_cap;',
            '        h->len = new_len;',
            '        char *data = (char*)(h + 1);',
            '        memcpy(data + la, b, lb + 1);',
            '        return data;',
            '    }',
            '    /* First concat or non-dynamic string — allocate with header + 2x capacity */',
            '    size_t la = strlen(a);',
            '    size_t new_len = la + lb;',
            '    size_t new_cap = (new_len + 1) * 2;',
            '    TsuchiStrHdr *nh = (TsuchiStrHdr*)malloc(sizeof(TsuchiStrHdr) + new_cap);',
            '    nh->magic = TSUCHI_STR_MAGIC;',
            '    nh->_pad = 0;',
            '    nh->cap = new_cap;',
            '    nh->len = new_len;',
            '    char *data = (char*)(nh + 1);',
            '    memcpy(data, a, la);',
            '    memcpy(data + la, b, lb + 1);',
            '    return data;',
            '}',
            '',
            'char* tsuchi_num_to_str(double val) {',
            '    char *buf = (char*)malloc(64);',
            '    if (val == (double)(long long)val && val >= -1e15 && val <= 1e15)',
            '        snprintf(buf, 64, "%lld", (long long)val);',
            '    else',
            '        snprintf(buf, 64, "%g", val);',
            '    return buf;',
            '}',
            '',
            'char* tsuchi_bool_to_str(int val) {',
            '    return val ? "true" : "false";',
            '}',
            '',
            '/* String methods */',
            'double tsuchi_str_indexOf(const char *s, const char *search) {',
            '    const char *p = strstr(s, search);',
            '    if (p == NULL) return -1.0;',
            '    return (double)(p - s);',
            '}',
            '',
            'double tsuchi_str_lastIndexOf(const char *s, const char *search) {',
            '    size_t slen = strlen(s);',
            '    size_t searchlen = strlen(search);',
            '    if (searchlen > slen) return -1.0;',
            '    for (int i = (int)(slen - searchlen); i >= 0; i--) {',
            '        if (strncmp(s + i, search, searchlen) == 0) return (double)i;',
            '    }',
            '    return -1.0;',
            '}',
            '',
            'int tsuchi_str_includes(const char *s, const char *search) {',
            '    return strstr(s, search) != NULL;',
            '}',
            '',
            'char* tsuchi_str_slice(const char *s, double start_d, double end_d) {',
            '    int len = (int)strlen(s);',
            '    int start = (int)start_d;',
            '    int end = (int)end_d;',
            '    if (start < 0) start = len + start;',
            '    if (end < 0) end = len + end;',
            '    if (start < 0) start = 0;',
            '    if (end > len) end = len;',
            '    if (start >= end) {',
            '        char *r = (char*)malloc(1);',
            '        r[0] = 0;',
            '        return r;',
            '    }',
            '    int rlen = end - start;',
            '    char *r = (char*)malloc(rlen + 1);',
            '    memcpy(r, s + start, rlen);',
            '    r[rlen] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_charAt(const char *s, double index_d) {',
            '    int idx = (int)index_d;',
            '    int len = (int)strlen(s);',
            '    char *r = (char*)malloc(2);',
            '    if (idx < 0 || idx >= len) {',
            '        r[0] = 0;',
            '        return r;',
            '    }',
            '    r[0] = s[idx];',
            '    r[1] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_at(const char *s, double index_d) {',
            '    int idx = (int)index_d;',
            '    int len = (int)strlen(s);',
            '    if (idx < 0) idx = len + idx;',
            '    char *r = (char*)malloc(2);',
            '    if (idx < 0 || idx >= len) {',
            '        r[0] = 0;',
            '        return r;',
            '    }',
            '    r[0] = s[idx];',
            '    r[1] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_toUpperCase(const char *s) {',
            '    size_t len = strlen(s);',
            '    char *r = (char*)malloc(len + 1);',
            '    for (size_t i = 0; i < len; i++) r[i] = toupper((unsigned char)s[i]);',
            '    r[len] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_toLowerCase(const char *s) {',
            '    size_t len = strlen(s);',
            '    char *r = (char*)malloc(len + 1);',
            '    for (size_t i = 0; i < len; i++) r[i] = tolower((unsigned char)s[i]);',
            '    r[len] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_trim(const char *s) {',
            '    const char *start = s;',
            '    while (*start && isspace((unsigned char)*start)) start++;',
            '    const char *end = s + strlen(s);',
            '    while (end > start && isspace((unsigned char)*(end - 1))) end--;',
            '    size_t rlen = end - start;',
            '    char *r = (char*)malloc(rlen + 1);',
            '    memcpy(r, start, rlen);',
            '    r[rlen] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_trimStart(const char *s) {',
            '    const char *start = s;',
            '    while (*start && isspace((unsigned char)*start)) start++;',
            '    size_t rlen = strlen(start);',
            '    char *r = (char*)malloc(rlen + 1);',
            '    memcpy(r, start, rlen);',
            '    r[rlen] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_trimEnd(const char *s) {',
            '    size_t len = strlen(s);',
            '    const char *end = s + len;',
            '    while (end > s && isspace((unsigned char)*(end - 1))) end--;',
            '    size_t rlen = end - s;',
            '    char *r = (char*)malloc(rlen + 1);',
            '    memcpy(r, s, rlen);',
            '    r[rlen] = 0;',
            '    return r;',
            '}',
            '',
            'int tsuchi_str_startsWith(const char *s, const char *prefix) {',
            '    size_t plen = strlen(prefix);',
            '    return strncmp(s, prefix, plen) == 0;',
            '}',
            '',
            'int tsuchi_str_endsWith(const char *s, const char *suffix) {',
            '    size_t slen = strlen(s);',
            '    size_t suflen = strlen(suffix);',
            '    if (suflen > slen) return 0;',
            '    return strcmp(s + slen - suflen, suffix) == 0;',
            '}',
            '',
            'char* tsuchi_str_replace(const char *s, const char *search, const char *replacement) {',
            '    const char *p = strstr(s, search);',
            '    if (!p) {',
            '        char *r = (char*)malloc(strlen(s) + 1);',
            '        strcpy(r, s);',
            '        return r;',
            '    }',
            '    size_t slen = strlen(search);',
            '    size_t rlen = strlen(replacement);',
            '    size_t total = strlen(s) - slen + rlen;',
            '    char *r = (char*)malloc(total + 1);',
            '    size_t before = p - s;',
            '    memcpy(r, s, before);',
            '    memcpy(r + before, replacement, rlen);',
            '    strcpy(r + before + rlen, p + slen);',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_repeat(const char *s, double count_d) {',
            '    int count = (int)count_d;',
            '    if (count <= 0) {',
            '        char *r = (char*)malloc(1);',
            '        r[0] = 0;',
            '        return r;',
            '    }',
            '    size_t len = strlen(s);',
            '    char *r = (char*)malloc(len * count + 1);',
            '    for (int i = 0; i < count; i++)',
            '        memcpy(r + i * len, s, len);',
            '    r[len * count] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_substring(const char *s, double start_d, double end_d) {',
            '    int len = (int)strlen(s);',
            '    int start = (int)start_d;',
            '    int end = (int)end_d;',
            '    if (start < 0) start = 0;',
            '    if (end < 0) end = 0;',
            '    if (start > len) start = len;',
            '    if (end > len) end = len;',
            '    if (start > end) { int tmp = start; start = end; end = tmp; }',
            '    int rlen = end - start;',
            '    char *r = (char*)malloc(rlen + 1);',
            '    memcpy(r, s + start, rlen);',
            '    r[rlen] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_padStart(const char *s, double target_d, const char *pad) {',
            '    int target = (int)target_d;',
            '    int slen = (int)strlen(s);',
            '    if (slen >= target) {',
            '        char *r = (char*)malloc(slen + 1);',
            '        strcpy(r, s);',
            '        return r;',
            '    }',
            '    int padlen = (int)strlen(pad);',
            '    if (padlen == 0) padlen = 1;',
            '    char *r = (char*)malloc(target + 1);',
            '    int fill = target - slen;',
            '    for (int i = 0; i < fill; i++)',
            '        r[i] = pad[i % padlen];',
            '    memcpy(r + fill, s, slen);',
            '    r[target] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_replaceAll(const char *s, const char *search, const char *replacement) {',
            '    size_t slen = strlen(search);',
            '    size_t rlen = strlen(replacement);',
            '    if (slen == 0) {',
            '        char *r = (char*)malloc(strlen(s) + 1);',
            '        strcpy(r, s);',
            '        return r;',
            '    }',
            '    /* Count occurrences */',
            '    int count = 0;',
            '    const char *p = s;',
            '    while ((p = strstr(p, search)) != NULL) { count++; p += slen; }',
            '    size_t total = strlen(s) + count * ((int)rlen - (int)slen);',
            '    char *r = (char*)malloc(total + 1);',
            '    char *w = r;',
            '    p = s;',
            '    while (1) {',
            '        const char *f = strstr(p, search);',
            '        if (!f) { strcpy(w, p); break; }',
            '        size_t before = f - p;',
            '        memcpy(w, p, before);',
            '        w += before;',
            '        memcpy(w, replacement, rlen);',
            '        w += rlen;',
            '        p = f + slen;',
            '    }',
            '    return r;',
            '}',
            '',
            'char* tsuchi_str_padEnd(const char *s, double target_d, const char *pad) {',
            '    int target = (int)target_d;',
            '    int slen = (int)strlen(s);',
            '    if (slen >= target) {',
            '        char *r = (char*)malloc(slen + 1);',
            '        strcpy(r, s);',
            '        return r;',
            '    }',
            '    int padlen = (int)strlen(pad);',
            '    if (padlen == 0) padlen = 1;',
            '    char *r = (char*)malloc(target + 1);',
            '    memcpy(r, s, slen);',
            '    int fill = target - slen;',
            '    for (int i = 0; i < fill; i++)',
            '        r[slen + i] = pad[i % padlen];',
            '    r[target] = 0;',
            '    return r;',
            '}',
            '',
            'double tsuchi_str_charCodeAt(const char *s, double index_d) {',
            '    int idx = (int)index_d;',
            '    int len = (int)strlen(s);',
            '    if (idx < 0 || idx >= len) return NAN;',
            '    return (double)(unsigned char)s[idx];',
            '}',
            '',
            'char* tsuchi_fromCharCode(double code_d) {',
            '    int code = (int)code_d;',
            '    char *r = (char*)malloc(2);',
            '    r[0] = (char)code;',
            '    r[1] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_num_toString(double val) {',
            '    char buf[64];',
            '    if (val == (int)val) {',
            '        snprintf(buf, sizeof(buf), "%d", (int)val);',
            '    } else {',
            '        snprintf(buf, sizeof(buf), "%g", val);',
            '    }',
            '    char *r = (char*)malloc(strlen(buf) + 1);',
            '    strcpy(r, buf);',
            '    return r;',
            '}',
            '',
            'char* tsuchi_num_toFixed(double val, double digits_d) {',
            '    int digits = (int)digits_d;',
            '    if (digits < 0) digits = 0;',
            '    if (digits > 100) digits = 100;',
            '    char buf[128];',
            '    snprintf(buf, sizeof(buf), "%.*f", digits, val);',
            '    char *r = (char*)malloc(strlen(buf) + 1);',
            '    strcpy(r, buf);',
            '    return r;',
            '}',
        ]

    def _module_uses_arrays(self, hir_module: HIRModule) -> bool:
        """Check if any function uses array operations."""
        from taiyaki_aot_compiler.hir.nodes import HIRAllocArray, HIRArrayGet, HIRArraySet, HIRArrayPush, HIRArrayLen, HIRCall
        for func in hir_module.functions:
            for p in func.params:
                if isinstance(p.type, ArrayType):
                    return True
            if isinstance(func.return_type, ArrayType):
                return True
            for bb in func.blocks:
                for instr in bb.instructions:
                    if isinstance(instr, (HIRAllocArray, HIRArrayGet, HIRArraySet, HIRArrayPush, HIRArrayLen)):
                        return True
                    # Also detect function calls that return arrays (e.g., split)
                    if isinstance(instr, HIRCall) and isinstance(instr.type, ArrayType):
                        return True
        return False

    def _generate_array_runtime(self) -> list[str]:
        """Generate C runtime for heap-allocated number arrays."""
        return [
            '/* Array runtime: heap-allocated { double* data, int len, int cap } */',
            'typedef struct {',
            '    double *data;',
            '    int length;',
            '    int capacity;',
            '} TsuchiArray;',
            '',
            'TsuchiArray* tsuchi_array_new(int capacity) {',
            '    if (capacity < 4) capacity = 4;',
            '    TsuchiArray *arr = (TsuchiArray*)malloc(sizeof(TsuchiArray));',
            '    arr->data = (double*)calloc(capacity, sizeof(double));',
            '    arr->length = 0;',
            '    arr->capacity = capacity;',
            '    return arr;',
            '}',
            '',
            'void tsuchi_array_set(TsuchiArray *arr, int index, double value) {',
            '    if (index >= 0 && index < arr->capacity) {',
            '        arr->data[index] = value;',
            '        if (index >= arr->length) arr->length = index + 1;',
            '    }',
            '}',
            '',
            'double tsuchi_array_get(TsuchiArray *arr, int index) {',
            '    if (index >= 0 && index < arr->length) return arr->data[index];',
            '    return 0.0;',
            '}',
            '',
            'double tsuchi_array_push(TsuchiArray *arr, double value) {',
            '    if (arr->length >= arr->capacity) {',
            '        arr->capacity *= 2;',
            '        arr->data = (double*)realloc(arr->data, arr->capacity * sizeof(double));',
            '    }',
            '    arr->data[arr->length] = value;',
            '    arr->length++;',
            '    return (double)arr->length;',
            '}',
            '',
            'int tsuchi_array_len(TsuchiArray *arr) {',
            '    return arr->length;',
            '}',
            '',
            'double tsuchi_array_indexOf(TsuchiArray *arr, double value) {',
            '    for (int i = 0; i < arr->length; i++) {',
            '        if (arr->data[i] == value) return (double)i;',
            '    }',
            '    return -1.0;',
            '}',
            '',
            'double tsuchi_array_lastIndexOf(TsuchiArray *arr, double value) {',
            '    for (int i = arr->length - 1; i >= 0; i--) {',
            '        if (arr->data[i] == value) return (double)i;',
            '    }',
            '    return -1.0;',
            '}',
            '',
            'double tsuchi_array_includes(TsuchiArray *arr, double value) {',
            '    for (int i = 0; i < arr->length; i++) {',
            '        if (arr->data[i] == value) return 1.0;',
            '    }',
            '    return 0.0;',
            '}',
            '',
            'TsuchiArray* tsuchi_array_slice(TsuchiArray *arr, int start, int end) {',
            '    if (start < 0) start = arr->length + start;',
            '    if (end < 0) end = arr->length + end;',
            '    if (start < 0) start = 0;',
            '    if (end > arr->length) end = arr->length;',
            '    if (start >= end) return tsuchi_array_new(4);',
            '    int len = end - start;',
            '    TsuchiArray *result = tsuchi_array_new(len);',
            '    for (int i = 0; i < len; i++) {',
            '        result->data[i] = arr->data[start + i];',
            '    }',
            '    result->length = len;',
            '    return result;',
            '}',
            '',
            'TsuchiArray* tsuchi_array_concat(TsuchiArray *a, TsuchiArray *b) {',
            '    int total = a->length + b->length;',
            '    TsuchiArray *result = tsuchi_array_new(total);',
            '    for (int i = 0; i < a->length; i++) result->data[i] = a->data[i];',
            '    for (int i = 0; i < b->length; i++) result->data[a->length + i] = b->data[i];',
            '    result->length = total;',
            '    return result;',
            '}',
            '',
            'void tsuchi_array_reverse(TsuchiArray *arr) {',
            '    for (int i = 0; i < arr->length / 2; i++) {',
            '        double tmp = arr->data[i];',
            '        arr->data[i] = arr->data[arr->length - 1 - i];',
            '        arr->data[arr->length - 1 - i] = tmp;',
            '    }',
            '}',
            '',
            'void tsuchi_array_fill(TsuchiArray *arr, double val) {',
            '    for (int i = 0; i < arr->length; i++) {',
            '        arr->data[i] = val;',
            '    }',
            '}',
            '',
            'double tsuchi_array_pop(TsuchiArray *arr) {',
            '    if (arr->length == 0) return 0.0/0.0;',
            '    arr->length--;',
            '    return arr->data[arr->length];',
            '}',
            '',
            'double tsuchi_array_shift(TsuchiArray *arr) {',
            '    if (arr->length == 0) return 0.0/0.0;',
            '    double first = arr->data[0];',
            '    for (int i = 0; i < arr->length - 1; i++) {',
            '        arr->data[i] = arr->data[i + 1];',
            '    }',
            '    arr->length--;',
            '    return first;',
            '}',
            '',
            'double tsuchi_array_unshift(TsuchiArray *arr, double val) {',
            '    if (arr->length >= arr->capacity) {',
            '        arr->capacity *= 2;',
            '        arr->data = (double*)realloc(arr->data, arr->capacity * sizeof(double));',
            '    }',
            '    for (int i = arr->length; i > 0; i--) {',
            '        arr->data[i] = arr->data[i - 1];',
            '    }',
            '    arr->data[0] = val;',
            '    arr->length++;',
            '    return (double)arr->length;',
            '}',
            '',
            'TsuchiArray* tsuchi_array_splice(TsuchiArray *arr, int start, int deleteCount) {',
            '    if (start < 0) start = arr->length + start;',
            '    if (start < 0) start = 0;',
            '    if (start > arr->length) start = arr->length;',
            '    if (deleteCount < 0) deleteCount = 0;',
            '    if (start + deleteCount > arr->length) deleteCount = arr->length - start;',
            '    TsuchiArray *removed = tsuchi_array_new(deleteCount > 0 ? deleteCount : 1);',
            '    for (int i = 0; i < deleteCount; i++) {',
            '        removed->data[i] = arr->data[start + i];',
            '    }',
            '    removed->length = deleteCount;',
            '    int tail = arr->length - start - deleteCount;',
            '    for (int i = 0; i < tail; i++) {',
            '        arr->data[start + i] = arr->data[start + deleteCount + i];',
            '    }',
            '    arr->length -= deleteCount;',
            '    return removed;',
            '}',
            '',
            'double tsuchi_array_at(TsuchiArray *arr, int index) {',
            '    if (index < 0) index = arr->length + index;',
            '    if (index < 0 || index >= arr->length) return 0.0/0.0;',
            '    return arr->data[index];',
            '}',
            '',
            'void tsuchi_array_print(TsuchiArray *arr) {',
            '    printf("[");',
            '    for (int i = 0; i < arr->length; i++) {',
            '        if (i > 0) printf(", ");',
            '        double v = arr->data[i];',
            '        if (v == (double)(long long)v) {',
            '            printf("%lld", (long long)v);',
            '        } else {',
            '            printf("%g", v);',
            '        }',
            '    }',
            '    printf("]");',
            '}',
            '',
            '// Array.join(separator) → string',
            'char* tsuchi_array_join(TsuchiArray *arr, const char *sep) {',
            '    if (arr->length == 0) {',
            '        char *r = (char*)malloc(1);',
            '        r[0] = 0;',
            '        return r;',
            '    }',
            '    int sep_len = strlen(sep);',
            '    // Estimate buffer size',
            '    int buf_size = arr->length * 24 + (arr->length - 1) * sep_len + 1;',
            '    char *buf = (char*)malloc(buf_size);',
            '    int pos = 0;',
            '    for (int i = 0; i < arr->length; i++) {',
            '        if (i > 0) {',
            '            memcpy(buf + pos, sep, sep_len);',
            '            pos += sep_len;',
            '        }',
            '        double v = arr->data[i];',
            '        if (v == (double)(long long)v) {',
            '            pos += sprintf(buf + pos, "%lld", (long long)v);',
            '        } else {',
            '            pos += sprintf(buf + pos, "%g", v);',
            '        }',
            '    }',
            '    buf[pos] = 0;',
            '    return buf;',
            '}',
            '',
            '/* String array accessors — reuse TsuchiArray since both double and char* are 8 bytes */',
            'void tsuchi_sarray_set(TsuchiArray *arr, int index, const char *value) {',
            '    if (index >= 0 && index < arr->capacity) {',
            '        ((const char**)arr->data)[index] = value;',
            '        if (index >= arr->length) arr->length = index + 1;',
            '    }',
            '}',
            '',
            'const char* tsuchi_sarray_get(TsuchiArray *arr, int index) {',
            '    if (index < 0 || index >= arr->length) return "";',
            '    return ((const char**)arr->data)[index];',
            '}',
            '',
            'double tsuchi_sarray_push(TsuchiArray *arr, const char *value) {',
            '    if (arr->length >= arr->capacity) {',
            '        arr->capacity *= 2;',
            '        arr->data = (double*)realloc(arr->data, arr->capacity * sizeof(double));',
            '    }',
            '    ((const char**)arr->data)[arr->length] = value;',
            '    arr->length++;',
            '    return (double)arr->length;',
            '}',
            '',
            'void tsuchi_sarray_print(TsuchiArray *arr) {',
            '    printf("[");',
            '    for (int i = 0; i < arr->length; i++) {',
            '        if (i > 0) printf(", ");',
            '        const char *s = ((const char**)arr->data)[i];',
            '        printf("\'%s\'", s ? s : "");',
            '    }',
            '    printf("]");',
            '}',
            '',
            '// String array join',
            'char* tsuchi_sarray_join(TsuchiArray *arr, const char *sep) {',
            '    if (arr->length == 0) {',
            '        char *r = (char*)malloc(1);',
            '        r[0] = 0;',
            '        return r;',
            '    }',
            '    int sep_len = strlen(sep);',
            '    int total = 0;',
            '    for (int i = 0; i < arr->length; i++) {',
            '        const char *s = ((const char**)arr->data)[i];',
            '        total += s ? strlen(s) : 0;',
            '    }',
            '    total += (arr->length - 1) * sep_len;',
            '    char *buf = (char*)malloc(total + 1);',
            '    int pos = 0;',
            '    for (int i = 0; i < arr->length; i++) {',
            '        if (i > 0) { memcpy(buf + pos, sep, sep_len); pos += sep_len; }',
            '        const char *s = ((const char**)arr->data)[i];',
            '        if (s) { int l = strlen(s); memcpy(buf + pos, s, l); pos += l; }',
            '    }',
            '    buf[pos] = 0;',
            '    return buf;',
            '}',
            '',
            '// String split',
            'TsuchiArray* tsuchi_str_split(const char *s, const char *sep) {',
            '    TsuchiArray *arr = tsuchi_array_new(8);',
            '    size_t sep_len = strlen(sep);',
            '    if (sep_len == 0) {',
            '        /* Split into individual characters */',
            '        size_t len = strlen(s);',
            '        for (size_t i = 0; i < len; i++) {',
            '            char *ch = (char*)malloc(2);',
            '            ch[0] = s[i]; ch[1] = 0;',
            '            tsuchi_sarray_push(arr, ch);',
            '        }',
            '        return arr;',
            '    }',
            '    const char *p = s;',
            '    while (1) {',
            '        const char *f = strstr(p, sep);',
            '        if (!f) {',
            '            size_t len = strlen(p);',
            '            char *part = (char*)malloc(len + 1);',
            '            memcpy(part, p, len + 1);',
            '            tsuchi_sarray_push(arr, part);',
            '            break;',
            '        }',
            '        size_t len = f - p;',
            '        char *part = (char*)malloc(len + 1);',
            '        memcpy(part, p, len);',
            '        part[len] = 0;',
            '        tsuchi_sarray_push(arr, part);',
            '        p = f + sep_len;',
            '    }',
            '    return arr;',
            '}',
            '',
            'TsuchiArray* tsuchi_str_to_char_array(const char *s) {',
            '    TsuchiArray *arr = tsuchi_array_new(8);',
            '    size_t len = strlen(s);',
            '    for (size_t i = 0; i < len; i++) {',
            '        char *ch = (char*)malloc(2);',
            '        ch[0] = s[i]; ch[1] = 0;',
            '        tsuchi_sarray_push(arr, ch);',
            '    }',
            '    return arr;',
            '}',
        ]

    def _generate_promise_runtime(self) -> list[str]:
        """Generate C runtime for Promise support (state machine continuations)."""
        return [
            '/* Promise runtime */',
            'typedef enum { TSUCHI_PENDING, TSUCHI_RESOLVED, TSUCHI_REJECTED } TsuchiPromiseState;',
            '',
            'typedef struct TsuchiPromise {',
            '    TsuchiPromiseState state;',
            '    int value_type;      /* 0=number, 1=string, 2=boolean, 3=void */',
            '    double num_value;',
            '    const char *str_value;',
            '    int bool_value;',
            '    /* Continuation callbacks (state machine resume functions) */',
            '    struct { void (*fn)(void*); void *data; } continuations[8];',
            '    int cont_count;',
            '} TsuchiPromise;',
            '',
            'TsuchiPromise* tsuchi_promise_new(void) {',
            '    TsuchiPromise *p = (TsuchiPromise*)calloc(1, sizeof(TsuchiPromise));',
            '    p->state = TSUCHI_PENDING;',
            '    p->value_type = 3; /* void by default */',
            '    p->cont_count = 0;',
            '    return p;',
            '}',
            '',
            'void tsuchi_promise_resolve_num(TsuchiPromise *p, double val) {',
            '    p->state = TSUCHI_RESOLVED;',
            '    p->value_type = 0;',
            '    p->num_value = val;',
            '    for (int i = 0; i < p->cont_count; i++) {',
            '        p->continuations[i].fn(p->continuations[i].data);',
            '    }',
            '    p->cont_count = 0;',
            '}',
            '',
            'void tsuchi_promise_resolve_str(TsuchiPromise *p, const char *val) {',
            '    p->state = TSUCHI_RESOLVED;',
            '    p->value_type = 1;',
            '    p->str_value = val;',
            '    for (int i = 0; i < p->cont_count; i++) {',
            '        p->continuations[i].fn(p->continuations[i].data);',
            '    }',
            '    p->cont_count = 0;',
            '}',
            '',
            'void tsuchi_promise_resolve_bool(TsuchiPromise *p, int val) {',
            '    p->state = TSUCHI_RESOLVED;',
            '    p->value_type = 2;',
            '    p->bool_value = val;',
            '    for (int i = 0; i < p->cont_count; i++) {',
            '        p->continuations[i].fn(p->continuations[i].data);',
            '    }',
            '    p->cont_count = 0;',
            '}',
            '',
            'void tsuchi_promise_resolve_void(TsuchiPromise *p) {',
            '    p->state = TSUCHI_RESOLVED;',
            '    p->value_type = 3;',
            '    for (int i = 0; i < p->cont_count; i++) {',
            '        p->continuations[i].fn(p->continuations[i].data);',
            '    }',
            '    p->cont_count = 0;',
            '}',
            '',
            'void tsuchi_promise_then(TsuchiPromise *p, void (*fn)(void*), void *data) {',
            '    if (p->state == TSUCHI_RESOLVED) {',
            '        fn(data);',
            '        return;',
            '    }',
            '    if (p->cont_count < 8) {',
            '        p->continuations[p->cont_count].fn = fn;',
            '        p->continuations[p->cont_count].data = data;',
            '        p->cont_count++;',
            '    }',
            '}',
        ]

    def _generate_event_loop_runtime(self) -> list[str]:
        """Generate C runtime for libuv event loop and async APIs."""
        return [
            '/* Event loop runtime (libuv) */',
            '#include <uv.h>',
            '',
            'static uv_loop_t *tsuchi_loop = NULL;',
            '',
            'void tsuchi_loop_init(void) {',
            '    tsuchi_loop = uv_default_loop();',
            '}',
            '',
            'void tsuchi_loop_run(void) {',
            '    uv_run(tsuchi_loop, UV_RUN_DEFAULT);',
            '}',
            '',
            'void tsuchi_loop_close(void) {',
            '    uv_loop_close(tsuchi_loop);',
            '}',
            '',
            'static void _tsuchi_handle_free(uv_handle_t *handle) { free(handle); }',
            '',
            '/* setTimeout timer callback — declared before tsuchi_setTimeout_async */',
            'static void _tsuchi_timer_cb(uv_timer_t *handle) {',
            '    TsuchiPromise *p = (TsuchiPromise*)handle->data;',
            '    tsuchi_promise_resolve_void(p);',
            '    uv_close((uv_handle_t*)handle, _tsuchi_handle_free);',
            '}',
            '',
            '/* setTimeout(ms) -> Promise<void> */',
            'TsuchiPromise* tsuchi_setTimeout_async(double ms) {',
            '    TsuchiPromise *p = tsuchi_promise_new();',
            '    uv_timer_t *timer = (uv_timer_t*)malloc(sizeof(uv_timer_t));',
            '    timer->data = p;',
            '    uv_timer_init(tsuchi_loop, timer);',
            '    uv_timer_start(timer, _tsuchi_timer_cb, (uint64_t)ms, 0);',
            '    return p;',
            '}',
            '',
            '/* Async file read context */',
            'typedef struct {',
            '    uv_work_t req;',
            '    TsuchiPromise *promise;',
            '    char *path;',
            '    char *result;',
            '} tsuchi_async_read_ctx;',
            '',
            'static void _tsuchi_read_work(uv_work_t *req) {',
            '    tsuchi_async_read_ctx *ctx = (tsuchi_async_read_ctx*)req->data;',
            '    ctx->result = tsuchi_readFile(ctx->path);',
            '}',
            '',
            'static void _tsuchi_read_done(uv_work_t *req, int status) {',
            '    tsuchi_async_read_ctx *ctx = (tsuchi_async_read_ctx*)req->data;',
            '    if (status == 0 && ctx->result != NULL) {',
            '        tsuchi_promise_resolve_str(ctx->promise, ctx->result);',
            '    } else {',
            '        tsuchi_promise_resolve_str(ctx->promise, "");',
            '    }',
            '    free(ctx->path);',
            '    free(ctx);',
            '}',
            '',
            '/* fs.readFile async -> Promise<string> */',
            'TsuchiPromise* tsuchi_fs_readFile_async(const char *path) {',
            '    TsuchiPromise *p = tsuchi_promise_new();',
            '    tsuchi_async_read_ctx *ctx = (tsuchi_async_read_ctx*)malloc(sizeof(tsuchi_async_read_ctx));',
            '    ctx->promise = p;',
            '    ctx->path = strdup(path);',
            '    ctx->result = NULL;',
            '    ctx->req.data = ctx;',
            '    uv_queue_work(tsuchi_loop, &ctx->req, _tsuchi_read_work, _tsuchi_read_done);',
            '    return p;',
            '}',
            '',
            '/* Async file write context */',
            'typedef struct {',
            '    uv_work_t req;',
            '    TsuchiPromise *promise;',
            '    char *path;',
            '    char *content;',
            '    int success;',
            '} tsuchi_async_write_ctx;',
            '',
            'static void _tsuchi_write_work(uv_work_t *req) {',
            '    tsuchi_async_write_ctx *ctx = (tsuchi_async_write_ctx*)req->data;',
            '    FILE *f = fopen(ctx->path, "w");',
            '    if (f) {',
            '        fputs(ctx->content, f);',
            '        fclose(f);',
            '        ctx->success = 1;',
            '    } else {',
            '        ctx->success = 0;',
            '    }',
            '}',
            '',
            'static void _tsuchi_write_done(uv_work_t *req, int status) {',
            '    tsuchi_async_write_ctx *ctx = (tsuchi_async_write_ctx*)req->data;',
            '    tsuchi_promise_resolve_void(ctx->promise);',
            '    free(ctx->path);',
            '    free(ctx->content);',
            '    free(ctx);',
            '}',
            '',
            '/* fs.writeFile async -> Promise<void> */',
            'TsuchiPromise* tsuchi_fs_writeFile_async(const char *path, const char *content) {',
            '    TsuchiPromise *p = tsuchi_promise_new();',
            '    tsuchi_async_write_ctx *ctx = (tsuchi_async_write_ctx*)malloc(sizeof(tsuchi_async_write_ctx));',
            '    ctx->promise = p;',
            '    ctx->path = strdup(path);',
            '    ctx->content = strdup(content);',
            '    ctx->success = 0;',
            '    ctx->req.data = ctx;',
            '    uv_queue_work(tsuchi_loop, &ctx->req, _tsuchi_write_work, _tsuchi_write_done);',
            '    return p;',
            '}',
            '',
            '/* fetch(url) -> Promise<string> using libcurl + libuv */',
            '// Forward declaration — tsuchi_httpGet defined in HTTP runtime section',
            'char* tsuchi_httpGet(const char* url);',
            'typedef struct {',
            '    uv_work_t req;',
            '    TsuchiPromise *promise;',
            '    char *url;',
            '    char *result;',
            '} tsuchi_fetch_ctx;',
            '',
            'static void _tsuchi_fetch_work(uv_work_t *req) {',
            '    tsuchi_fetch_ctx *ctx = (tsuchi_fetch_ctx*)req->data;',
            '    ctx->result = tsuchi_httpGet(ctx->url);',
            '}',
            '',
            'static void _tsuchi_fetch_done(uv_work_t *req, int status) {',
            '    tsuchi_fetch_ctx *ctx = (tsuchi_fetch_ctx*)req->data;',
            '    if (status == 0 && ctx->result != NULL) {',
            '        tsuchi_promise_resolve_str(ctx->promise, ctx->result);',
            '    } else {',
            '        tsuchi_promise_resolve_str(ctx->promise, "");',
            '    }',
            '    free(ctx->url);',
            '    free(ctx);',
            '}',
            '',
            'TsuchiPromise* tsuchi_fetch_async(const char *url) {',
            '    TsuchiPromise *p = tsuchi_promise_new();',
            '    tsuchi_fetch_ctx *ctx = (tsuchi_fetch_ctx*)malloc(sizeof(tsuchi_fetch_ctx));',
            '    ctx->promise = p;',
            '    ctx->url = strdup(url);',
            '    ctx->result = NULL;',
            '    ctx->req.data = ctx;',
            '    uv_queue_work(tsuchi_loop, &ctx->req, _tsuchi_fetch_work, _tsuchi_fetch_done);',
            '    return p;',
            '}',
        ]

    def _generate_path_runtime(self) -> list[str]:
        """Generate C runtime for path module."""
        return [
            '/* path module runtime */',
            '#include <unistd.h>',
            '#include <limits.h>',
            '',
            'char* tsuchi_path_join(const char *a, const char *b) {',
            '    if (!a || !b) return strdup("");',
            '    size_t la = strlen(a), lb = strlen(b);',
            '    /* Handle empty parts */',
            '    if (la == 0) return strdup(b);',
            '    if (lb == 0) return strdup(a);',
            '    int need_sep = (a[la-1] != \'/\' && b[0] != \'/\');',
            '    int skip_sep = (a[la-1] == \'/\' && b[0] == \'/\');',
            '    size_t total = la + lb + (need_sep ? 1 : 0) - (skip_sep ? 1 : 0);',
            '    char *r = (char*)malloc(total + 1);',
            '    memcpy(r, a, la);',
            '    if (need_sep) { r[la] = \'/\'; memcpy(r + la + 1, b, lb + 1); }',
            '    else if (skip_sep) { memcpy(r + la, b + 1, lb); r[total] = 0; }',
            '    else { memcpy(r + la, b, lb + 1); }',
            '    return r;',
            '}',
            '',
            'char* tsuchi_path_resolve(const char *p) {',
            '    if (!p) return strdup("");',
            '    if (p[0] == \'/\') return strdup(p);',
            '    char cwd[PATH_MAX];',
            '    if (!getcwd(cwd, sizeof(cwd))) return strdup(p);',
            '    return tsuchi_path_join(cwd, p);',
            '}',
            '',
            'char* tsuchi_path_dirname(const char *p) {',
            '    if (!p || !*p) return strdup(".");',
            '    size_t len = strlen(p);',
            '    /* Skip trailing slashes */',
            '    while (len > 1 && p[len-1] == \'/\') len--;',
            '    /* Find last slash */',
            '    while (len > 0 && p[len-1] != \'/\') len--;',
            '    if (len == 0) return strdup(".");',
            '    /* Skip trailing slashes of result */',
            '    while (len > 1 && p[len-1] == \'/\') len--;',
            '    char *r = (char*)malloc(len + 1);',
            '    memcpy(r, p, len);',
            '    r[len] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_path_basename(const char *p) {',
            '    if (!p || !*p) return strdup("");',
            '    size_t len = strlen(p);',
            '    while (len > 1 && p[len-1] == \'/\') len--;',
            '    size_t start = len;',
            '    while (start > 0 && p[start-1] != \'/\') start--;',
            '    size_t rlen = len - start;',
            '    char *r = (char*)malloc(rlen + 1);',
            '    memcpy(r, p + start, rlen);',
            '    r[rlen] = 0;',
            '    return r;',
            '}',
            '',
            'char* tsuchi_path_extname(const char *p) {',
            '    if (!p) return strdup("");',
            '    const char *base = strrchr(p, \'/\');',
            '    base = base ? base + 1 : p;',
            '    const char *dot = strrchr(base, \'.\');',
            '    if (!dot || dot == base) return strdup("");',
            '    return strdup(dot);',
            '}',
            '',
            'char* tsuchi_path_normalize(const char *p) {',
            '    if (!p || !*p) return strdup(".");',
            '    size_t len = strlen(p);',
            '    char *r = (char*)malloc(len + 1);',
            '    const char *s = p; char *d = r;',
            '    int prev_slash = 0;',
            '    while (*s) {',
            '        if (*s == \'/\') {',
            '            if (!prev_slash) *d++ = \'/\';',
            '            prev_slash = 1; s++;',
            '            while (*s == \'.\' && (*(s+1) == \'/\' || *(s+1) == 0)) { s++; if (*s == \'/\') s++; }',
            '        } else { *d++ = *s++; prev_slash = 0; }',
            '    }',
            '    if (d > r + 1 && *(d-1) == \'/\') d--;',
            '    *d = 0;',
            '    return r;',
            '}',
            '',
            'int tsuchi_path_isAbsolute(const char *p) {',
            '    return p && p[0] == \'/\';',
            '}',
            '',
        ]

    def _generate_fs_runtime(self) -> list[str]:
        """Generate C runtime for fs module."""
        return [
            '/* fs module runtime */',
            '#include <sys/stat.h>',
            '#include <dirent.h>',
            '',
            'char* tsuchi_fs_readFileSync(const char *path) { return tsuchi_readFile(path); }',
            'void tsuchi_fs_writeFileSync(const char *path, const char *content) { tsuchi_writeFile(path, content); }',
            '',
            'int tsuchi_fs_existsSync(const char *path) {',
            '    if (!path) return 0;',
            '    return access(path, F_OK) == 0;',
            '}',
            '',
            'void tsuchi_fs_mkdirSync(const char *path) {',
            '    if (path) mkdir(path, 0755);',
            '}',
            '',
            'void tsuchi_fs_rmdirSync(const char *path) {',
            '    if (path) rmdir(path);',
            '}',
            '',
            'void tsuchi_fs_unlinkSync(const char *path) {',
            '    if (path) unlink(path);',
            '}',
            '',
            'void tsuchi_fs_renameSync(const char *oldp, const char *newp) {',
            '    if (oldp && newp) rename(oldp, newp);',
            '}',
            '',
            'void tsuchi_fs_appendFileSync(const char *path, const char *data) {',
            '    if (!path || !data) return;',
            '    FILE *f = fopen(path, "a");',
            '    if (!f) return;',
            '    fwrite(data, 1, strlen(data), f);',
            '    fclose(f);',
            '}',
            '',
            'void tsuchi_fs_copyFileSync(const char *src, const char *dst) {',
            '    if (!src || !dst) return;',
            '    char *content = tsuchi_readFile(src);',
            '    tsuchi_writeFile(dst, content);',
            '    free(content);',
            '}',
            '',
            '#ifdef TSUCHI_HAS_ARRAYS',
            'TsuchiArray* tsuchi_fs_readdirSync(const char *path) {',
            '    TsuchiArray *arr = tsuchi_array_new(16);',
            '    if (!path) return arr;',
            '    DIR *d = opendir(path);',
            '    if (!d) return arr;',
            '    struct dirent *ent;',
            '    while ((ent = readdir(d)) != NULL) {',
            '        if (ent->d_name[0] == \'.\' && (ent->d_name[1] == 0 || (ent->d_name[1] == \'.\' && ent->d_name[2] == 0))) continue;',
            '        char *name = (char*)malloc(strlen(ent->d_name) + 1);',
            '        strcpy(name, ent->d_name);',
            '        tsuchi_sarray_push(arr, name);',
            '    }',
            '    closedir(d);',
            '    return arr;',
            '}',
            '#endif',
            '',
        ]

    def _generate_os_runtime(self) -> list[str]:
        """Generate C runtime for os module."""
        import platform as _plat
        os_name = "darwin" if _plat.system() == "Darwin" else "linux"
        arch = "arm64" if _plat.machine() == "arm64" else "x64"
        return [
            '/* os module runtime */',
            '#include <unistd.h>',
            '#ifdef __APPLE__',
            '#include <mach/mach.h>',
            '#endif',
            '',
            f'const char* tsuchi_os_platform(void) {{ return "{os_name}"; }}',
            f'const char* tsuchi_os_arch(void) {{ return "{arch}"; }}',
            '',
            'const char* tsuchi_os_homedir(void) {',
            '    const char *h = getenv("HOME");',
            '    return h ? h : "";',
            '}',
            '',
            'const char* tsuchi_os_tmpdir(void) {',
            '    const char *t = getenv("TMPDIR");',
            '    return t ? t : "/tmp";',
            '}',
            '',
            'const char* tsuchi_os_hostname(void) {',
            '    static char buf[256];',
            '    if (gethostname(buf, sizeof(buf)) != 0) return "";',
            '    return buf;',
            '}',
            '',
            '#ifdef __APPLE__',
            '#include <sys/sysctl.h>',
            '#endif',
            'double tsuchi_os_cpus(void) {',
            '    return (double)sysconf(_SC_NPROCESSORS_ONLN);',
            '}',
            '',
            'double tsuchi_os_totalmem(void) {',
            '#ifdef __APPLE__',
            '    int mib[2] = {CTL_HW, HW_MEMSIZE};',
            '    int64_t mem = 0;',
            '    size_t len = sizeof(mem);',
            '    sysctl(mib, 2, &mem, &len, NULL, 0);',
            '    return (double)mem;',
            '#else',
            '    long pages = sysconf(_SC_PHYS_PAGES);',
            '    long page_size = sysconf(_SC_PAGE_SIZE);',
            '    return (double)pages * (double)page_size;',
            '#endif',
            '}',
            '',
            'double tsuchi_os_freemem(void) {',
            '#ifdef __APPLE__',
            '    vm_statistics64_data_t vm_stat;',
            '    mach_port_t host = mach_host_self();',
            '    mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;',
            '    if (host_statistics64(host, HOST_VM_INFO64, (host_info64_t)&vm_stat, &count) == KERN_SUCCESS) {',
            '        return (double)vm_stat.free_count * (double)sysconf(_SC_PAGE_SIZE);',
            '    }',
            '    return 0.0;',
            '#else',
            '    long pages = sysconf(_SC_AVPHYS_PAGES);',
            '    long page_size = sysconf(_SC_PAGE_SIZE);',
            '    return (double)pages * (double)page_size;',
            '#endif',
            '}',
            '',
        ]

    def _generate_cli_runtime(self, uses_arrays: bool) -> list[str]:
        """Generate CLI runtime: process.argv, readFile, writeFile, getenv."""
        lines = []
        # process.argv (only if arrays are available)
        if uses_arrays:
            lines.extend([
                '// process.argv → TsuchiArray of strings',
                'TsuchiArray* tsuchi_process_argv(void) {',
                '    TsuchiArray *arr = tsuchi_array_new(tsuchi_argc);',
                '    for (int i = 0; i < tsuchi_argc; i++) {',
                '        tsuchi_sarray_push(arr, tsuchi_argv[i]);',
                '    }',
                '    return arr;',
                '}',
                '',
            ])
        else:
            lines.extend([
                '// process.argv stub (no array runtime)',
                'void* tsuchi_process_argv(void) { return (void*)0; }',
                '',
            ])
        lines.extend([
            '// readFile(path) → string contents',
            'char* tsuchi_readFile(const char* path) {',
            '    if (!path) return strdup("");',
            '    FILE *f = fopen(path, "rb");',
            '    if (!f) return strdup("");',
            '    fseek(f, 0, SEEK_END);',
            '    long len = ftell(f);',
            '    fseek(f, 0, SEEK_SET);',
            '    char *buf = (char*)malloc(len + 1);',
            '    if (!buf) { fclose(f); return strdup(""); }',
            '    fread(buf, 1, len, f);',
            '    buf[len] = \'\\0\';',
            '    fclose(f);',
            '    return buf;',
            '}',
            '',
            '// writeFile(path, content)',
            'void tsuchi_writeFile(const char* path, const char* content) {',
            '    if (!path || !content) return;',
            '    FILE *f = fopen(path, "w");',
            '    if (!f) return;',
            '    size_t len = strlen(content);',
            '    fwrite(content, 1, len, f);',
            '    fclose(f);',
            '}',
            '',
            '// process.env.VARNAME → getenv with null safety',
            'const char* tsuchi_getenv(const char* name) {',
            '    const char* val = getenv(name);',
            '    return val ? val : "";',
            '}',
        ])
        return lines

    def _generate_raylib_runtime(self) -> list[str]:
        """Generate C wrapper functions for raylib bindings."""
        if not self._uses_raylib:
            return []
        return [
            '#include <raylib.h>',
            '',
            '// Global custom font state (shared with Clay wrapper)',
            'Font _tsuchi_custom_font = {0};',
            'int _tsuchi_has_custom_font = 0;',
            '',
            '// Unpack packed RGBA color (number → Color struct)',
            'static Color _unpack_color(int packed) {',
            '    Color c;',
            '    c.r = (packed >> 24) & 0xFF;',
            '    c.g = (packed >> 16) & 0xFF;',
            '    c.b = (packed >> 8) & 0xFF;',
            '    c.a = packed & 0xFF;',
            '    return c;',
            '}',
            '',
            '// Pack RGBA into single int',
            'int tsuchi_rl_color(int r, int g, int b, int a) {',
            '    return (r << 24) | (g << 16) | (b << 8) | a;',
            '}',
            '',
            '// === Core window ===',
            'void tsuchi_rl_initWindow(int w, int h, const char *title) {',
            '    InitWindow(w, h, title);',
            '}',
            'void tsuchi_rl_closeWindow(void) { CloseWindow(); }',
            'int tsuchi_rl_windowShouldClose(void) { return WindowShouldClose(); }',
            'void tsuchi_rl_setTargetFPS(int fps) { SetTargetFPS(fps); }',
            'int tsuchi_rl_getScreenWidth(void) { return GetScreenWidth(); }',
            'int tsuchi_rl_getScreenHeight(void) { return GetScreenHeight(); }',
            'double tsuchi_rl_getFrameTime(void) { return (double)GetFrameTime(); }',
            'double tsuchi_rl_getTime(void) { return GetTime(); }',
            'int tsuchi_rl_getFPS(void) { return GetFPS(); }',
            '',
            '// === Drawing ===',
            'void tsuchi_rl_beginDrawing(void) { BeginDrawing(); }',
            'void tsuchi_rl_endDrawing(void) { EndDrawing(); }',
            'void tsuchi_rl_clearBackground(int c) { ClearBackground(_unpack_color(c)); }',
            'void tsuchi_rl_drawRectangle(int x, int y, int w, int h, int c) {',
            '    DrawRectangle(x, y, w, h, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawRectangleLines(int x, int y, int w, int h, int c) {',
            '    DrawRectangleLines(x, y, w, h, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawCircle(int cx, int cy, double radius, int c) {',
            '    DrawCircle(cx, cy, (float)radius, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawCircleLines(int cx, int cy, double radius, int c) {',
            '    DrawCircleLines(cx, cy, (float)radius, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawLine(int x1, int y1, int x2, int y2, int c) {',
            '    DrawLine(x1, y1, x2, y2, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawText(const char *text, int x, int y, int size, int c) {',
            '    if (_tsuchi_has_custom_font) {',
            '        DrawTextEx(_tsuchi_custom_font, text, (Vector2){(float)x,(float)y}, (float)size, 1.0f, _unpack_color(c));',
            '    } else {',
            '        DrawText(text, x, y, size, _unpack_color(c));',
            '    }',
            '}',
            'void tsuchi_rl_drawTriangle(double x1, double y1, double x2, double y2,',
            '                            double x3, double y3, int c) {',
            '    DrawTriangle((Vector2){(float)x1,(float)y1}, (Vector2){(float)x2,(float)y2},',
            '                 (Vector2){(float)x3,(float)y3}, _unpack_color(c));',
            '}',
            'int tsuchi_rl_measureText(const char *text, int size) {',
            '    return MeasureText(text, size);',
            '}',
            '',
            '// === Font ===',
            'void tsuchi_rl_loadFont(const char *path, int size) {',
            '    _tsuchi_custom_font = LoadFontEx(path, size, NULL, 0);',
            '    SetTextureFilter(_tsuchi_custom_font.texture, TEXTURE_FILTER_BILINEAR);',
            '    _tsuchi_has_custom_font = 1;',
            '}',
            '',
            '// === Textures (handle-based) ===',
            'static Texture2D _textures[256];',
            'static int _tex_count = 0;',
            'int tsuchi_rl_loadTexture(const char *path) {',
            '    if (_tex_count >= 256) return -1;',
            '    _textures[_tex_count] = LoadTexture(path);',
            '    return _tex_count++;',
            '}',
            'void tsuchi_rl_drawTexture(int id, int x, int y, int c) {',
            '    if (id >= 0 && id < _tex_count)',
            '        DrawTexture(_textures[id], x, y, _unpack_color(c));',
            '}',
            'void tsuchi_rl_unloadTexture(int id) {',
            '    if (id >= 0 && id < _tex_count)',
            '        UnloadTexture(_textures[id]);',
            '}',
            '',
            '// === Extended shapes (Phase 3) ===',
            'void tsuchi_rl_drawRectanglePro(double x, double y, double w, double h,',
            '                               double originX, double originY, double rotation, int c) {',
            '    DrawRectanglePro((Rectangle){(float)x,(float)y,(float)w,(float)h},',
            '                    (Vector2){(float)originX,(float)originY}, (float)rotation, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawRectangleRounded(int x, int y, int w, int h, double roundness, int segments, int c) {',
            '    DrawRectangleRounded((Rectangle){(float)x,(float)y,(float)w,(float)h},',
            '                        (float)roundness, segments, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawRectangleGradientV(int x, int y, int w, int h, int c1, int c2) {',
            '    DrawRectangleGradientV(x, y, w, h, _unpack_color(c1), _unpack_color(c2));',
            '}',
            'void tsuchi_rl_drawRectangleGradientH(int x, int y, int w, int h, int c1, int c2) {',
            '    DrawRectangleGradientH(x, y, w, h, _unpack_color(c1), _unpack_color(c2));',
            '}',
            'void tsuchi_rl_drawLineEx(double x1, double y1, double x2, double y2, double thick, int c) {',
            '    DrawLineEx((Vector2){(float)x1,(float)y1}, (Vector2){(float)x2,(float)y2},',
            '               (float)thick, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawPixel(int x, int y, int c) {',
            '    DrawPixel(x, y, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawCircleSector(double cx, double cy, double radius,',
            '                               double startAngle, double endAngle, int segments, int c) {',
            '    DrawCircleSector((Vector2){(float)cx,(float)cy}, (float)radius,',
            '                    (float)startAngle, (float)endAngle, segments, _unpack_color(c));',
            '}',
            '',
            '// === Texture Pro (Phase 3) ===',
            'void tsuchi_rl_drawTextureRec(int id, double srcX, double srcY, double srcW, double srcH,',
            '                             int destX, int destY, int c) {',
            '    if (id >= 0 && id < _tex_count)',
            '        DrawTextureRec(_textures[id],',
            '            (Rectangle){(float)srcX,(float)srcY,(float)srcW,(float)srcH},',
            '            (Vector2){(float)destX,(float)destY}, _unpack_color(c));',
            '}',
            'void tsuchi_rl_drawTexturePro(int id, double srcX, double srcY, double srcW, double srcH,',
            '                             double destX, double destY, double destW, double destH,',
            '                             double originX, double originY, double rotation, int c) {',
            '    if (id >= 0 && id < _tex_count)',
            '        DrawTexturePro(_textures[id],',
            '            (Rectangle){(float)srcX,(float)srcY,(float)srcW,(float)srcH},',
            '            (Rectangle){(float)destX,(float)destY,(float)destW,(float)destH},',
            '            (Vector2){(float)originX,(float)originY}, (float)rotation, _unpack_color(c));',
            '}',
            'int tsuchi_rl_getTextureWidth(int id) {',
            '    if (id >= 0 && id < _tex_count) return _textures[id].width;',
            '    return 0;',
            '}',
            'int tsuchi_rl_getTextureHeight(int id) {',
            '    if (id >= 0 && id < _tex_count) return _textures[id].height;',
            '    return 0;',
            '}',
            '',
            '// === Text Pro (Phase 3) ===',
            'void tsuchi_rl_drawTextEx(const char *text, double x, double y, double fontSize, double spacing, int c) {',
            '    if (_tsuchi_has_custom_font) {',
            '        DrawTextEx(_tsuchi_custom_font, text, (Vector2){(float)x,(float)y},',
            '                   (float)fontSize, (float)spacing, _unpack_color(c));',
            '    } else {',
            '        DrawText(text, (int)x, (int)y, (int)fontSize, _unpack_color(c));',
            '    }',
            '}',
            'int tsuchi_rl_measureTextEx(const char *text, double fontSize, double spacing) {',
            '    if (_tsuchi_has_custom_font) {',
            '        Vector2 sz = MeasureTextEx(_tsuchi_custom_font, text, (float)fontSize, (float)spacing);',
            '        return (int)sz.x;',
            '    }',
            '    return MeasureText(text, (int)fontSize);',
            '}',
            '',
            '// === Input: keyboard ===',
            'int tsuchi_rl_isKeyDown(int key) { return IsKeyDown(key); }',
            'int tsuchi_rl_isKeyPressed(int key) { return IsKeyPressed(key); }',
            'int tsuchi_rl_isKeyReleased(int key) { return IsKeyReleased(key); }',
            'int tsuchi_rl_getKeyPressed(void) { return GetKeyPressed(); }',
            'int tsuchi_rl_getCharPressed(void) { return GetCharPressed(); }',
            'int tsuchi_rl_isKeyUp(int key) { return IsKeyUp(key); }',
            '',
            '// === Input: mouse ===',
            'int tsuchi_rl_getMouseX(void) { return GetMouseX(); }',
            'int tsuchi_rl_getMouseY(void) { return GetMouseY(); }',
            'int tsuchi_rl_isMouseButtonDown(int btn) { return IsMouseButtonDown(btn); }',
            'int tsuchi_rl_isMouseButtonPressed(int btn) { return IsMouseButtonPressed(btn); }',
            'int tsuchi_rl_isMouseButtonReleased(int btn) { return IsMouseButtonReleased(btn); }',
            'double tsuchi_rl_getMouseWheelMove(void) { return (double)GetMouseWheelMove(); }',
            '',
            '// === Color extended (Phase 3) ===',
            'int tsuchi_rl_colorAlpha(int packed, double alpha) {',
            '    return (packed & 0xFFFFFF00) | ((int)(alpha * 255.0) & 0xFF);',
            '}',
            '',
            '// === Window extended (Phase 3) ===',
            'void tsuchi_rl_toggleFullscreen(void) { ToggleFullscreen(); }',
            'void tsuchi_rl_setWindowSize(int w, int h) { SetWindowSize(w, h); }',
            'void tsuchi_rl_setWindowTitle(const char *title) { SetWindowTitle(title); }',
            'void tsuchi_rl_setConfigFlags(int flags) { SetConfigFlags(flags); }',
            'int tsuchi_rl_isWindowFocused(void) { return IsWindowFocused(); }',
            'int tsuchi_rl_isWindowResized(void) { return IsWindowResized(); }',
            '',
            '// === Audio device (Phase 1) ===',
            'void tsuchi_rl_initAudioDevice(void) { InitAudioDevice(); }',
            'void tsuchi_rl_closeAudioDevice(void) { CloseAudioDevice(); }',
            'void tsuchi_rl_setMasterVolume(double vol) { SetMasterVolume((float)vol); }',
            'double tsuchi_rl_getMasterVolume(void) { return (double)GetMasterVolume(); }',
            '',
            '// === Sound (Phase 1) — handle-based ===',
            'static Sound _sounds[256];',
            'static int _snd_count = 0;',
            'int tsuchi_rl_loadSound(const char *path) {',
            '    if (_snd_count >= 256) return -1;',
            '    _sounds[_snd_count] = LoadSound(path);',
            '    return _snd_count++;',
            '}',
            'void tsuchi_rl_playSound(int id) { if (id >= 0 && id < _snd_count) PlaySound(_sounds[id]); }',
            'void tsuchi_rl_stopSound(int id) { if (id >= 0 && id < _snd_count) StopSound(_sounds[id]); }',
            'void tsuchi_rl_pauseSound(int id) { if (id >= 0 && id < _snd_count) PauseSound(_sounds[id]); }',
            'void tsuchi_rl_resumeSound(int id) { if (id >= 0 && id < _snd_count) ResumeSound(_sounds[id]); }',
            'void tsuchi_rl_setSoundVolume(int id, double vol) {',
            '    if (id >= 0 && id < _snd_count) SetSoundVolume(_sounds[id], (float)vol);',
            '}',
            'void tsuchi_rl_setSoundPitch(int id, double pitch) {',
            '    if (id >= 0 && id < _snd_count) SetSoundPitch(_sounds[id], (float)pitch);',
            '}',
            'int tsuchi_rl_isSoundPlaying(int id) {',
            '    if (id >= 0 && id < _snd_count) return IsSoundPlaying(_sounds[id]);',
            '    return 0;',
            '}',
            'void tsuchi_rl_unloadSound(int id) {',
            '    if (id >= 0 && id < _snd_count) UnloadSound(_sounds[id]);',
            '}',
            '',
            '// === Music (Phase 1) — handle-based ===',
            'static Music _musics[64];',
            'static int _mus_count = 0;',
            'int tsuchi_rl_loadMusic(const char *path) {',
            '    if (_mus_count >= 64) return -1;',
            '    _musics[_mus_count] = LoadMusicStream(path);',
            '    return _mus_count++;',
            '}',
            'void tsuchi_rl_playMusic(int id) { if (id >= 0 && id < _mus_count) PlayMusicStream(_musics[id]); }',
            'void tsuchi_rl_stopMusic(int id) { if (id >= 0 && id < _mus_count) StopMusicStream(_musics[id]); }',
            'void tsuchi_rl_pauseMusic(int id) { if (id >= 0 && id < _mus_count) PauseMusicStream(_musics[id]); }',
            'void tsuchi_rl_resumeMusic(int id) { if (id >= 0 && id < _mus_count) ResumeMusicStream(_musics[id]); }',
            'void tsuchi_rl_updateMusic(int id) { if (id >= 0 && id < _mus_count) UpdateMusicStream(_musics[id]); }',
            'void tsuchi_rl_setMusicVolume(int id, double vol) {',
            '    if (id >= 0 && id < _mus_count) SetMusicVolume(_musics[id], (float)vol);',
            '}',
            'int tsuchi_rl_isMusicPlaying(int id) {',
            '    if (id >= 0 && id < _mus_count) return IsMusicStreamPlaying(_musics[id]);',
            '    return 0;',
            '}',
            'double tsuchi_rl_getMusicTimeLength(int id) {',
            '    if (id >= 0 && id < _mus_count) return (double)GetMusicTimeLength(_musics[id]);',
            '    return 0.0;',
            '}',
            'double tsuchi_rl_getMusicTimePlayed(int id) {',
            '    if (id >= 0 && id < _mus_count) return (double)GetMusicTimePlayed(_musics[id]);',
            '    return 0.0;',
            '}',
            'void tsuchi_rl_unloadMusic(int id) {',
            '    if (id >= 0 && id < _mus_count) UnloadMusicStream(_musics[id]);',
            '}',
            '',
            '// === Camera2D (Phase 2) ===',
            'void tsuchi_rl_beginMode2D(double offsetX, double offsetY, double targetX, double targetY,',
            '                          double rotation, double zoom) {',
            '    Camera2D cam = {0};',
            '    cam.offset = (Vector2){(float)offsetX, (float)offsetY};',
            '    cam.target = (Vector2){(float)targetX, (float)targetY};',
            '    cam.rotation = (float)rotation;',
            '    cam.zoom = (float)zoom;',
            '    BeginMode2D(cam);',
            '}',
            'void tsuchi_rl_endMode2D(void) { EndMode2D(); }',
            '',
            '// === Collision detection (Phase 2) ===',
            'int tsuchi_rl_checkCollisionRecs(double x1, double y1, double w1, double h1,',
            '                                double x2, double y2, double w2, double h2) {',
            '    return CheckCollisionRecs((Rectangle){(float)x1,(float)y1,(float)w1,(float)h1},',
            '                             (Rectangle){(float)x2,(float)y2,(float)w2,(float)h2});',
            '}',
            'int tsuchi_rl_checkCollisionCircles(double cx1, double cy1, double r1,',
            '                                   double cx2, double cy2, double r2) {',
            '    return CheckCollisionCircles((Vector2){(float)cx1,(float)cy1}, (float)r1,',
            '                                (Vector2){(float)cx2,(float)cy2}, (float)r2);',
            '}',
            'int tsuchi_rl_checkCollisionCircleRec(double cx, double cy, double r,',
            '                                     double rx, double ry, double rw, double rh) {',
            '    return CheckCollisionCircleRec((Vector2){(float)cx,(float)cy}, (float)r,',
            '                                  (Rectangle){(float)rx,(float)ry,(float)rw,(float)rh});',
            '}',
            'int tsuchi_rl_checkCollisionPointRec(double px, double py,',
            '                                    double rx, double ry, double rw, double rh) {',
            '    return CheckCollisionPointRec((Vector2){(float)px,(float)py},',
            '                                 (Rectangle){(float)rx,(float)ry,(float)rw,(float)rh});',
            '}',
            'int tsuchi_rl_checkCollisionPointCircle(double px, double py,',
            '                                       double cx, double cy, double r) {',
            '    return CheckCollisionPointCircle((Vector2){(float)px,(float)py},',
            '                                    (Vector2){(float)cx,(float)cy}, (float)r);',
            '}',
            '',
            '// === Random (Phase 2) ===',
            'int tsuchi_rl_getRandomValue(int min, int max) { return GetRandomValue(min, max); }',
            '',
            '// === Gamepad (Phase 5) ===',
            'int tsuchi_rl_isGamepadAvailable(int gp) { return IsGamepadAvailable(gp); }',
            'int tsuchi_rl_isGamepadButtonDown(int gp, int btn) { return IsGamepadButtonDown(gp, btn); }',
            'int tsuchi_rl_isGamepadButtonPressed(int gp, int btn) { return IsGamepadButtonPressed(gp, btn); }',
            'int tsuchi_rl_isGamepadButtonReleased(int gp, int btn) { return IsGamepadButtonReleased(gp, btn); }',
            'double tsuchi_rl_getGamepadAxisMovement(int gp, int axis) {',
            '    return (double)GetGamepadAxisMovement(gp, axis);',
            '}',
            'int tsuchi_rl_getGamepadAxisCount(int gp) { return GetGamepadAxisCount(gp); }',
            'int tsuchi_rl_getGamepadButtonPressed(void) { return GetGamepadButtonPressed(); }',
            'int tsuchi_rl_getGamepadName(int gp) { return IsGamepadAvailable(gp); }',
            '',
            '// === Music extended ===',
            'void tsuchi_rl_seekMusic(int id, double position) {',
            '    if (id >= 0 && id < _mus_count) SeekMusicStream(_musics[id], (float)position);',
            '}',
            'void tsuchi_rl_setMusicPitch(int id, double pitch) {',
            '    if (id >= 0 && id < _mus_count) SetMusicPitch(_musics[id], (float)pitch);',
            '}',
            '',
            '// === Audio device extended ===',
            'int tsuchi_rl_isAudioDeviceReady(void) { return IsAudioDeviceReady(); }',
            '',
            '// === Font extended ===',
            'void tsuchi_rl_unloadFont(void) {',
            '    if (_tsuchi_has_custom_font) {',
            '        UnloadFont(_tsuchi_custom_font);',
            '        _tsuchi_has_custom_font = 0;',
            '    }',
            '}',
            '',
            '// === Text measurement extended ===',
            'int tsuchi_rl_measureTextExY(const char *text, double fontSize, double spacing) {',
            '    if (_tsuchi_has_custom_font) {',
            '        Vector2 sz = MeasureTextEx(_tsuchi_custom_font, text, (float)fontSize, (float)spacing);',
            '        return (int)sz.y;',
            '    }',
            '    return (int)fontSize;',
            '}',
            '',
            '// === Texture extended ===',
            'void tsuchi_rl_drawTextureScaled(int id, int x, int y, double scale, int c) {',
            '    if (id >= 0 && id < _tex_count)',
            '        DrawTextureEx(_textures[id], (Vector2){(float)x,(float)y}, 0.0f, (float)scale, _unpack_color(c));',
            '}',
            'int tsuchi_rl_isTextureValid(int id) {',
            '    return (id >= 0 && id < _tex_count && _textures[id].id > 0) ? 1 : 0;',
            '}',
            '',
            '// === Camera2D extended ===',
            'int tsuchi_rl_getWorldToScreen2DX(double worldX, double worldY,',
            '                                  double camOX, double camOY,',
            '                                  double camTX, double camTY,',
            '                                  double camRot, double camZoom) {',
            '    Camera2D cam = {0};',
            '    cam.offset = (Vector2){(float)camOX, (float)camOY};',
            '    cam.target = (Vector2){(float)camTX, (float)camTY};',
            '    cam.rotation = (float)camRot;',
            '    cam.zoom = (float)camZoom;',
            '    Vector2 s = GetWorldToScreen2D((Vector2){(float)worldX,(float)worldY}, cam);',
            '    return (int)s.x;',
            '}',
            'int tsuchi_rl_getWorldToScreen2DY(double worldX, double worldY,',
            '                                  double camOX, double camOY,',
            '                                  double camTX, double camTY,',
            '                                  double camRot, double camZoom) {',
            '    Camera2D cam = {0};',
            '    cam.offset = (Vector2){(float)camOX, (float)camOY};',
            '    cam.target = (Vector2){(float)camTX, (float)camTY};',
            '    cam.rotation = (float)camRot;',
            '    cam.zoom = (float)camZoom;',
            '    Vector2 s = GetWorldToScreen2D((Vector2){(float)worldX,(float)worldY}, cam);',
            '    return (int)s.y;',
            '}',
            '',
            '// === Gamepad extended ===',
            'int tsuchi_rl_isGamepadButtonUp(int gp, int btn) { return IsGamepadButtonUp(gp, btn); }',
            '',
            '// === File system ===',
            '#include <sys/stat.h>',
            'int tsuchi_rl_fileExists(const char *path) {',
            '    struct stat st;',
            '    return (stat(path, &st) == 0 && S_ISREG(st.st_mode)) ? 1 : 0;',
            '}',
            'int tsuchi_rl_directoryExists(const char *path) {',
            '    struct stat st;',
            '    return (stat(path, &st) == 0 && S_ISDIR(st.st_mode)) ? 1 : 0;',
            '}',
        ]

    def _generate_http_shell_runtime(self) -> list[str]:
        """Generate C implementations for exec() and httpGet()/httpPost()."""
        lines = [
            '// Shell execution: exec(cmd) → stdout',
            'char* tsuchi_exec(const char* cmd) {',
            '    if (!cmd) return strdup("");',
            '    FILE *fp = popen(cmd, "r");',
            '    if (!fp) return strdup("");',
            '    size_t cap = 1024, len = 0;',
            '    char *buf = (char *)malloc(cap);',
            '    if (!buf) { pclose(fp); return strdup(""); }',
            '    size_t n;',
            '    while ((n = fread(buf + len, 1, cap - len - 1, fp)) > 0) {',
            '        len += n;',
            '        if (len + 1 >= cap) {',
            '            cap *= 2;',
            '            char *newbuf = (char *)realloc(buf, cap);',
            '            if (!newbuf) break;',
            '            buf = newbuf;',
            '        }',
            '    }',
            '    buf[len] = \'\\0\';',
            '    pclose(fp);',
            '    return buf;',
            '}',
        ]
        if not self._uses_curl:
            # Stub implementations when libcurl is not linked
            lines.extend([
                '',
                '// Stub HTTP functions (no libcurl linked)',
                'char* tsuchi_httpGet(const char* url) { (void)url; return strdup(""); }',
                'char* tsuchi_httpPost(const char* url, const char* body, const char* ct) {',
                '    (void)url; (void)body; (void)ct; return strdup("");',
                '}',
            ])
        else:
            lines.extend([
                '',
                '#include <curl/curl.h>',
                '',
                'typedef struct { char *data; size_t size; } TsuchiHttpBuf;',
                '',
                'static size_t _tsuchi_http_write_cb(void *contents, size_t size, size_t nmemb, void *userp) {',
                '    size_t realsize = size * nmemb;',
                '    TsuchiHttpBuf *buf = (TsuchiHttpBuf *)userp;',
                '    char *ptr = (char *)realloc(buf->data, buf->size + realsize + 1);',
                '    if (!ptr) return 0;',
                '    buf->data = ptr;',
                '    memcpy(&(buf->data[buf->size]), contents, realsize);',
                '    buf->size += realsize;',
                '    buf->data[buf->size] = \'\\0\';',
                '    return realsize;',
                '}',
                '',
                'char* tsuchi_httpGet(const char* url) {',
                '    if (!url) return strdup("");',
                '    CURL *curl = curl_easy_init();',
                '    if (!curl) return strdup("");',
                '    TsuchiHttpBuf buf = {0};',
                '    buf.data = (char *)malloc(1);',
                '    buf.data[0] = \'\\0\';',
                '    curl_easy_setopt(curl, CURLOPT_URL, url);',
                '    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, _tsuchi_http_write_cb);',
                '    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&buf);',
                '    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);',
                '    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);',
                '    CURLcode res = curl_easy_perform(curl);',
                '    curl_easy_cleanup(curl);',
                '    if (res != CURLE_OK) { free(buf.data); return strdup(""); }',
                '    return buf.data;',
                '}',
                '',
                'char* tsuchi_httpPost(const char* url, const char* body, const char* content_type) {',
                '    if (!url) return strdup("");',
                '    CURL *curl = curl_easy_init();',
                '    if (!curl) return strdup("");',
                '    TsuchiHttpBuf buf = {0};',
                '    buf.data = (char *)malloc(1);',
                '    buf.data[0] = \'\\0\';',
                '    curl_easy_setopt(curl, CURLOPT_URL, url);',
                '    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body ? body : "");',
                '    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, _tsuchi_http_write_cb);',
                '    curl_easy_setopt(curl, CURLOPT_WRITEDATA, (void *)&buf);',
                '    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);',
                '    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);',
                '    struct curl_slist *headers = NULL;',
                '    char ct_header[256];',
                '    snprintf(ct_header, sizeof(ct_header), "Content-Type: %s",',
                '             content_type ? content_type : "application/json");',
                '    headers = curl_slist_append(headers, ct_header);',
                '    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);',
                '    CURLcode res = curl_easy_perform(curl);',
                '    curl_slist_free_all(headers);',
                '    curl_easy_cleanup(curl);',
                '    if (res != CURLE_OK) { free(buf.data); return strdup(""); }',
                '    return buf.data;',
                '}',
            ])
        return lines

    def _generate_clay_runtime(self) -> list[str]:
        """Generate Clay UI C wrapper (includes clay.h implementation + raylib renderer)."""
        clay_wrapper = (_PROJECT_ROOT / "vendor" / "clay" / "tsuchi_clay_wrapper.c").read_text()
        return [clay_wrapper]

    def _generate_clay_tui_runtime(self) -> list[str]:
        """Generate Clay TUI C wrapper (includes clay.h implementation + termbox2 renderer)."""
        tui_wrapper = (_PROJECT_ROOT / "vendor" / "clay" / "tsuchi_clay_tui_wrapper.c").read_text()
        return [tui_wrapper]

    def _generate_ui_runtime(self) -> list[str]:
        """Generate UI widget runtime C code (interactive IMGUI-style widgets)."""
        ui_runtime = (_PROJECT_ROOT / "vendor" / "clay" / "tsuchi_ui_runtime.c").read_text()
        return [ui_runtime]

    def _generate_gf_runtime(self) -> list[str]:
        """Generate game framework C runtime code."""
        gf_runtime = (_PROJECT_ROOT / "vendor" / "tsuchi_game_framework.c").read_text()
        return [gf_runtime]

    def _generate_ffi_declarations(self) -> list[str]:
        """Generate C struct typedefs and extern forward declarations for FFI."""
        from taiyaki_aot_compiler.type_checker.types import FFIStructType, OpaquePointerType
        lines = ['// FFI struct typedefs']

        # Emit struct typedefs for all FFI structs
        for st in self._ffi_info.structs.values():
            lines.append(f'struct tsuchi_ffi_{st.name} {{')
            for fname, ftype in st.fields:
                lines.append(f'    {self._ffi_c_type(ftype)} {fname};')
            lines.append('};')
            lines.append('')

        lines.append('// FFI extern declarations')
        seen_c_names: set[str] = set()

        # Plain FFI functions (skip Class.method / Class#method keys)
        for name, ffi_fn in self._ffi_info.functions.items():
            if '.' in name or '#' in name:
                continue
            if ffi_fn.c_name in seen_c_names:
                continue
            seen_c_names.add(ffi_fn.c_name)
            c_ret = self._ffi_c_type(ffi_fn.return_type)
            c_params = ', '.join(
                self._ffi_c_type(pt) for pt in ffi_fn.param_types
            ) or 'void'
            lines.append(f'extern {c_ret} {ffi_fn.c_name}({c_params});')

        # Opaque class method declarations
        for oc in self._ffi_info.opaque_classes.values():
            for mfn in oc.static_methods.values():
                if mfn.c_name in seen_c_names:
                    continue
                seen_c_names.add(mfn.c_name)
                c_ret = self._ffi_c_type(mfn.return_type)
                c_params = ', '.join(
                    self._ffi_c_type(pt) for pt in mfn.param_types
                ) or 'void'
                lines.append(f'extern {c_ret} {mfn.c_name}({c_params});')
            for mfn in oc.instance_methods.values():
                if mfn.c_name in seen_c_names:
                    continue
                seen_c_names.add(mfn.c_name)
                c_ret = self._ffi_c_type(mfn.return_type)
                # Instance methods take opaque ptr as first arg
                all_params = ['void*'] + [self._ffi_c_type(pt) for pt in mfn.param_types]
                lines.append(f'extern {c_ret} {mfn.c_name}({", ".join(all_params)});')
        return lines

    def _ffi_c_type(self, ty: MonoType) -> str:
        """Convert MonoType to C type string for FFI declarations."""
        from taiyaki_aot_compiler.type_checker.types import (
            NumberType, BooleanType, StringType, VoidType,
            FFIStructType, OpaquePointerType,
        )
        if isinstance(ty, NumberType):
            return 'double'
        elif isinstance(ty, BooleanType):
            return 'int'
        elif isinstance(ty, StringType):
            return 'const char*'
        elif isinstance(ty, VoidType):
            return 'void'
        elif isinstance(ty, FFIStructType):
            return f'struct tsuchi_ffi_{ty.name}'
        elif isinstance(ty, OpaquePointerType):
            return 'void*'
        return 'double'

    def _generate_global_runtime(self) -> list[str]:
        """Generate global conversion functions: parseInt, parseFloat."""
        return [
            '// parseInt(str) → double',
            'double tsuchi_parseInt(const char *str) {',
            '    if (!str) return 0.0/0.0;',
            '    char *end;',
            '    long long val = strtoll(str, &end, 10);',
            '    if (end == str) return 0.0/0.0;',
            '    return (double)val;',
            '}',
            '',
            '// parseFloat(str) → double',
            'double tsuchi_parseFloat(const char *str) {',
            '    if (!str) return 0.0/0.0;',
            '    char *end;',
            '    double val = strtod(str, &end);',
            '    if (end == str) return 0.0/0.0;',
            '    return val;',
            '}',
            '',
            '// Exception handling via setjmp/longjmp',
            '#include <setjmp.h>',
            '#define TSUCHI_MAX_TRY_DEPTH 32',
            'static jmp_buf *tsuchi_jmp_stack[TSUCHI_MAX_TRY_DEPTH];',
            'static int tsuchi_jmp_top = 0;',
            'static const char *tsuchi_error_msg = NULL;',
            '',
            'void tsuchi_throw(const char *msg) {',
            '    tsuchi_error_msg = msg ? msg : "Unknown error";',
            '    if (tsuchi_jmp_top > 0) {',
            '        tsuchi_jmp_top--;',
            '        longjmp(*tsuchi_jmp_stack[tsuchi_jmp_top], 1);',
            '    }',
            '    fprintf(stderr, "Error: %s\\n", tsuchi_error_msg);',
            '    exit(1);',
            '}',
            '',
            'const char *tsuchi_get_error_msg(void) {',
            '    return tsuchi_error_msg ? tsuchi_error_msg : "";',
            '}',
            '',
            'void tsuchi_try_push(jmp_buf *buf) {',
            '    if (tsuchi_jmp_top < TSUCHI_MAX_TRY_DEPTH)',
            '        tsuchi_jmp_stack[tsuchi_jmp_top++] = buf;',
            '}',
            '',
            'void tsuchi_try_pop(void) {',
            '    if (tsuchi_jmp_top > 0) tsuchi_jmp_top--;',
            '}',
            '',
            '// Math.random() → [0, 1) random number',
            '#include <time.h>',
            'static int tsuchi_rng_seeded = 0;',
            'double tsuchi_math_random(void) {',
            '    if (!tsuchi_rng_seeded) { srand((unsigned)time(NULL)); tsuchi_rng_seeded = 1; }',
            '    return (double)rand() / ((double)RAND_MAX + 1.0);',
            '}',
            '',
            '// Math.clz32(x) → count leading zeros of 32-bit int',
            'double tsuchi_math_clz32(double x) {',
            '    unsigned int v = (unsigned int)(int)x;',
            '    if (v == 0) return 32.0;',
            '    return (double)__builtin_clz(v);',
            '}',
            '',
            '// Date.now() → milliseconds since epoch',
            '#include <sys/time.h>',
            'double tsuchi_date_now(void) {',
            '    struct timeval tv;',
            '    gettimeofday(&tv, NULL);',
            '    return (double)tv.tv_sec * 1000.0 + (double)tv.tv_usec / 1000.0;',
            '}',
            '',
            '// JSON.stringify for number',
            'char *tsuchi_json_stringify(double val) {',
            '    char *buf = (char *)malloc(64);',
            '    if (!buf) return "";',
            '    if (val != val) { strcpy(buf, "null"); return buf; }',
            '    if (val == 1.0/0.0 || val == -1.0/0.0) { strcpy(buf, "null"); return buf; }',
            '    if (val == (double)(long long)val && val >= -1e15 && val <= 1e15)',
            '        snprintf(buf, 64, "%lld", (long long)val);',
            '    else',
            '        snprintf(buf, 64, "%.17g", val);',
            '    return buf;',
            '}',
            '',
            '// JSON.stringify for string',
            'char *tsuchi_json_stringify_str(const char *s) {',
            '    if (!s) return strdup("null");',
            '    size_t slen = strlen(s);',
            '    char *buf = (char *)malloc(slen * 2 + 3);',
            '    if (!buf) return strdup("\\"\\"");',
            '    char *p = buf;',
            '    *p++ = \'\\"\';',
            '    for (size_t i = 0; i < slen; i++) {',
            '        char c = s[i];',
            '        if (c == \'\\"\') { *p++ = \'\\\\\'; *p++ = \'\\"\'; }',
            '        else if (c == \'\\\\\') { *p++ = \'\\\\\'; *p++ = \'\\\\\'; }',
            '        else if (c == \'\\n\') { *p++ = \'\\\\\'; *p++ = \'n\'; }',
            '        else if (c == \'\\t\') { *p++ = \'\\\\\'; *p++ = \'t\'; }',
            '        else if (c == \'\\r\') { *p++ = \'\\\\\'; *p++ = \'r\'; }',
            '        else *p++ = c;',
            '    }',
            '    *p++ = \'\\"\';',
            '    *p = \'\\0\';',
            '    return buf;',
            '}',
            '',
            '// JSON.stringify for boolean',
            'char *tsuchi_json_stringify_bool(int val) {',
            '    return strdup(val ? "true" : "false");',
            '}',
            '',
            '// JSON.parse for number',
            'double tsuchi_json_parse_num(const char *s) {',
            '    if (!s) return 0.0/0.0;',
            '    while (*s == \' \' || *s == \'\\t\' || *s == \'\\n\' || *s == \'\\r\') s++;',
            '    if (*s == \'\\"\') {',
            '        s++;',
            '        char *end;',
            '        double val = strtod(s, &end);',
            '        if (end != s) return val;',
            '        return 0.0/0.0;',
            '    }',
            '    char *end;',
            '    double val = strtod(s, &end);',
            '    if (end == s) return 0.0/0.0;',
            '    return val;',
            '}',
            '',
            '// JSON.parse for string',
            'char* tsuchi_json_parse_str(const char *s) {',
            '    if (!s) return strdup("");',
            '    while (*s == \' \' || *s == \'\\t\' || *s == \'\\n\' || *s == \'\\r\') s++;',
            '    if (*s != \'\\"\') return strdup(s);',
            '    s++;',
            '    size_t len = strlen(s);',
            '    char *result = (char*)malloc(len + 1);',
            '    char *w = result;',
            '    while (*s && *s != \'\\"\') {',
            '        if (*s == \'\\\\\' && *(s+1)) {',
            '            s++;',
            '            switch (*s) {',
            '                case \'\\"\': *w++ = \'\\"\'; break;',
            '                case \'\\\\\': *w++ = \'\\\\\'; break;',
            '                case \'/\': *w++ = \'/\'; break;',
            '                case \'n\': *w++ = \'\\n\'; break;',
            '                case \'t\': *w++ = \'\\t\'; break;',
            '                case \'r\': *w++ = \'\\r\'; break;',
            '                case \'b\': *w++ = \'\\b\'; break;',
            '                case \'f\': *w++ = \'\\f\'; break;',
            '                default: *w++ = *s; break;',
            '            }',
            '        } else {',
            '            *w++ = *s;',
            '        }',
            '        s++;',
            '    }',
            '    *w = \'\\0\';',
            '    return result;',
            '}',
            '',
            '// JSON.parse for boolean',
            'int tsuchi_json_parse_bool(const char *s) {',
            '    if (!s) return 0;',
            '    while (*s == \' \' || *s == \'\\t\' || *s == \'\\n\' || *s == \'\\r\') s++;',
            '    if (strncmp(s, "true", 4) == 0) return 1;',
            '    return 0;',
            '}',
        ]

    def _split_entry_statements(self, entry_stmts: list[str], async_func_names: set[str]) -> tuple[list[str], list[str]]:
        """Split entry statements into async direct calls and JS eval statements."""
        async_entry_calls: list[str] = []
        js_entry_stmts: list[str] = []
        for entry_src in entry_stmts:
            stripped = entry_src.strip().rstrip(";").strip()
            if stripped.endswith("()"):
                called_name = stripped[:-2].strip()
                if called_name in async_func_names:
                    async_entry_calls.append(called_name)
                    continue
            js_entry_stmts.append(entry_src)
        return async_entry_calls, js_entry_stmts

    def _escape_c_string(self, s: str) -> str:
        result = []
        for ch in s:
            if ch == '\\':
                result.append('\\\\')
            elif ch == '"':
                result.append('\\"')
            elif ch == '\n':
                result.append('\\n')
            elif ch == '\r':
                result.append('\\r')
            elif ch == '\t':
                result.append('\\t')
            else:
                result.append(ch)
        return ''.join(result)

    # ---------------------------------------------------------------
    # Async function C state machine generation
    # ---------------------------------------------------------------

    def _c_type_for_mono(self, ty: MonoType) -> str:
        """Map a MonoType to a C type string for state machine fields."""
        if isinstance(ty, NumberType):
            return "double"
        elif isinstance(ty, BooleanType):
            return "int"
        elif isinstance(ty, StringType):
            return "const char*"
        elif isinstance(ty, VoidType):
            return "void"
        elif isinstance(ty, PromiseType):
            return "TsuchiPromise*"
        elif isinstance(ty, ArrayType):
            return "TsuchiArray*"
        elif isinstance(ty, ObjectType):
            return self._struct_c_name(ty)
        return "double"

    def _c_binop(self, op: str) -> str:
        """Map HIR binary op name to C operator."""
        return {
            "add": "+", "sub": "-", "mul": "*", "div": "/",
            "mod": "%", "pow": "**",  # pow handled specially
            "eq": "==", "ne": "!=", "lt": "<", "le": "<=",
            "gt": ">", "ge": ">=",
            "and": "&&", "or": "||",
            "bitand": "&", "bitor": "|", "bitxor": "^",
            "shl": "<<", "shr": ">>",
        }.get(op, op)

    def _c_compare_op(self, op: str) -> str:
        """Map HIR compare op name to C operator."""
        return {
            "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
            "eq": "==", "ne": "!=",
        }.get(op, op)

    def _c_unary_op(self, op: str) -> str:
        """Map HIR unary op name to C operator."""
        return {"neg": "-", "pos": "+", "not": "!"}.get(op, op)

    def _sm_var_ref(self, var_name: str, struct_fields: set[str]) -> str:
        """Return 'sm->varname' if the variable is a struct field, else just 'varname'."""
        if var_name in struct_fields:
            return f"sm->{self._sanitize_c_name(var_name)}"
        return self._sanitize_c_name(var_name)

    def _sanitize_c_name(self, name: str) -> str:
        """Sanitize an SSA variable name for use as a C identifier."""
        return name.replace("%", "v").replace(".", "_").replace("-", "_").replace("$", "_")

    def _collect_ssa_types(self, func: HIRFunction) -> dict[str, MonoType]:
        """Collect SSA variable names and their types from an HIR function."""
        var_types: dict[str, MonoType] = {}
        for p in func.params:
            var_types[p.result] = p.type
        for bb in func.blocks:
            for instr in bb.instructions:
                if isinstance(instr, HIRConst):
                    var_types[instr.result] = instr.type
                elif isinstance(instr, HIRBinaryOp):
                    var_types[instr.result] = instr.type
                elif isinstance(instr, HIRUnaryOp):
                    var_types[instr.result] = instr.type
                elif isinstance(instr, HIRCompare):
                    var_types[instr.result] = BooleanType()
                elif isinstance(instr, HIRCall):
                    var_types[instr.result] = instr.type
                elif isinstance(instr, HIRAwait):
                    var_types[instr.result] = instr.result_type
                elif isinstance(instr, HIRPhi):
                    var_types[instr.result] = instr.type
                elif isinstance(instr, HIRAssign):
                    # Inherits type from the source variable if known
                    if instr.value in var_types:
                        var_types[instr.target] = var_types[instr.value]
            # Check terminator
            if isinstance(bb.terminator, HIRReturn) and bb.terminator.value:
                pass  # return value already tracked
        return var_types

    def _generate_async_functions(self, hir_module: HIRModule) -> list[str]:
        """Generate C state machine code for all async functions in the module."""
        lines: list[str] = []
        async_funcs = [f for f in hir_module.functions if f.is_async]
        if not async_funcs:
            return lines

        lines.append('/* ===== Async function state machines ===== */')
        lines.append('')

        for func in async_funcs:
            lines.extend(self._generate_one_async_function(func, hir_module))
            lines.append('')

        return lines

    def _generate_one_async_function(self, func: HIRFunction, hir_module: HIRModule) -> list[str]:
        """Generate a complete C state machine for one async function."""
        lines: list[str] = []
        fname = func.name
        sm_name = f"SM_{fname}"

        # Collect all SSA variable types
        var_types = self._collect_ssa_types(func)

        # Flatten all instructions from all basic blocks into a linear sequence
        all_instrs: list = []
        for bb in func.blocks:
            for instr in bb.instructions:
                all_instrs.append(instr)
            if bb.terminator is not None:
                all_instrs.append(bb.terminator)

        # Split the instruction stream at HIRAwait points into segments (states)
        segments: list[list] = []
        current_segment: list = []
        await_instrs: list[HIRAwait] = []

        for instr in all_instrs:
            if isinstance(instr, HIRAwait):
                # The await itself ends the current segment
                current_segment.append(instr)
                segments.append(current_segment)
                await_instrs.append(instr)
                current_segment = []
            else:
                current_segment.append(instr)
        # Final segment (code after last await, or all code if no awaits)
        if current_segment:
            segments.append(current_segment)

        # Identify variables that cross state boundaries (defined before an await,
        # used after it) — these must be struct fields
        # For simplicity in V1, we make ALL params and ALL await results struct fields,
        # plus any variable assigned before an await that is used after
        struct_field_vars: set[str] = set()

        # All params are struct fields
        for p in func.params:
            struct_field_vars.add(p.result)

        # All await result vars are struct fields
        for aw in await_instrs:
            struct_field_vars.add(aw.result)

        # Track which variables are defined in which segment
        defined_in_segment: dict[int, set[str]] = {}
        used_in_segment: dict[int, set[str]] = {}
        for seg_idx, seg in enumerate(segments):
            defined_in_segment[seg_idx] = set()
            used_in_segment[seg_idx] = set()
            for instr in seg:
                # Collect definitions
                if hasattr(instr, 'result') and instr.result:
                    defined_in_segment[seg_idx].add(instr.result)
                if isinstance(instr, HIRAssign):
                    defined_in_segment[seg_idx].add(instr.target)
                # Collect uses
                if isinstance(instr, HIRBinaryOp):
                    used_in_segment[seg_idx].update([instr.left, instr.right])
                elif isinstance(instr, HIRUnaryOp):
                    used_in_segment[seg_idx].add(instr.operand)
                elif isinstance(instr, HIRCompare):
                    used_in_segment[seg_idx].update([instr.left, instr.right])
                elif isinstance(instr, HIRCall):
                    used_in_segment[seg_idx].update(instr.args)
                elif isinstance(instr, HIRReturn) and instr.value:
                    used_in_segment[seg_idx].add(instr.value)
                elif isinstance(instr, HIRAssign):
                    used_in_segment[seg_idx].add(instr.value)
                elif isinstance(instr, HIRAwait):
                    used_in_segment[seg_idx].add(instr.promise)
                elif isinstance(instr, HIRBranch):
                    used_in_segment[seg_idx].add(instr.condition)

        # A variable crosses a state boundary if it's defined in segment i and used in segment j (j > i)
        for seg_idx in range(len(segments)):
            for later_seg in range(seg_idx + 1, len(segments)):
                cross = defined_in_segment[seg_idx] & used_in_segment[later_seg]
                struct_field_vars.update(cross)

        # Determine return type (unwrap PromiseType)
        ret_type = func.return_type
        if isinstance(ret_type, PromiseType):
            inner_type = ret_type.inner_type
        else:
            inner_type = ret_type

        # --- Generate the struct ---
        lines.append(f'/* Async state machine for {fname} */')
        lines.append(f'typedef struct {{')
        lines.append(f'    int state;')
        lines.append(f'    TsuchiPromise *result_promise;')

        # Parameter fields
        for p in func.params:
            c_type = self._c_type_for_mono(p.type)
            c_name = self._sanitize_c_name(p.result)
            lines.append(f'    {c_type} {c_name};')

        # Cross-state local variable fields (excluding params, which are already added)
        # Also skip void-typed variables (e.g. await results of Promise<void>)
        param_names = {p.result for p in func.params}
        for var in sorted(struct_field_vars - param_names):
            ty = var_types.get(var, NumberType())
            if isinstance(ty, VoidType):
                continue  # void cannot be a C struct field
            c_type = self._c_type_for_mono(ty)
            c_name = self._sanitize_c_name(var)
            lines.append(f'    {c_type} {c_name};')

        # Awaited promise pointer
        lines.append(f'    TsuchiPromise *awaited;')
        lines.append(f'}} {sm_name};')
        lines.append(f'')

        # --- Forward declare moveNext ---
        lines.append(f'static void {sm_name}_moveNext(void *data);')
        lines.append(f'')

        # --- Generate entry function ---
        param_parts = []
        for i, p in enumerate(func.params):
            c_type = self._c_type_for_mono(p.type)
            param_parts.append(f'{c_type} param_{i}')
        params_str = ", ".join(param_parts) if param_parts else "void"

        lines.append(f'TsuchiPromise* _tsuchi_{fname}({params_str}) {{')
        lines.append(f'    {sm_name} *sm = ({sm_name}*)calloc(1, sizeof({sm_name}));')
        lines.append(f'    sm->state = 0;')
        for i, p in enumerate(func.params):
            c_name = self._sanitize_c_name(p.result)
            lines.append(f'    sm->{c_name} = param_{i};')
        lines.append(f'    sm->result_promise = tsuchi_promise_new();')
        lines.append(f'    {sm_name}_moveNext(sm);')
        lines.append(f'    return sm->result_promise;')
        lines.append(f'}}')
        lines.append(f'')

        # --- Generate moveNext ---
        lines.append(f'static void {sm_name}_moveNext(void *data) {{')
        lines.append(f'    {sm_name} *sm = ({sm_name}*)data;')
        lines.append(f'    switch (sm->state) {{')

        for state_idx, seg in enumerate(segments):
            lines.append(f'    case {state_idx}: {{')

            # If this state follows an await, extract the resolved value from sm->awaited
            if state_idx > 0 and (state_idx - 1) < len(await_instrs):
                prev_await = await_instrs[state_idx - 1]
                result_var = prev_await.result
                result_type = prev_await.result_type
                rv = self._sm_var_ref(result_var, struct_field_vars)
                if isinstance(result_type, NumberType):
                    lines.append(f'        {rv} = sm->awaited->num_value;')
                elif isinstance(result_type, StringType):
                    lines.append(f'        {rv} = sm->awaited->str_value;')
                elif isinstance(result_type, BooleanType):
                    lines.append(f'        {rv} = sm->awaited->bool_value;')
                # For void, no value extraction needed

            for instr in seg:
                lines.extend(self._gen_async_instr(
                    instr, func, struct_field_vars, var_types,
                    sm_name, state_idx, inner_type,
                ))
            lines.append(f'    }}')

        # Ensure the state machine is cleaned up even if no explicit return
        # Check if the last segment already ended with HIRReturn
        last_seg = segments[-1] if segments else []
        has_explicit_return = any(isinstance(i, HIRReturn) for i in last_seg)
        if not has_explicit_return:
            lines.append(f'    /* implicit return — resolve promise and free SM */')
            if isinstance(inner_type, VoidType):
                lines.append(f'    tsuchi_promise_resolve_void(sm->result_promise);')
            elif isinstance(inner_type, NumberType):
                lines.append(f'    tsuchi_promise_resolve_num(sm->result_promise, 0.0);')
            elif isinstance(inner_type, StringType):
                lines.append(f'    tsuchi_promise_resolve_str(sm->result_promise, "");')
            elif isinstance(inner_type, BooleanType):
                lines.append(f'    tsuchi_promise_resolve_bool(sm->result_promise, 0);')
            else:
                lines.append(f'    tsuchi_promise_resolve_void(sm->result_promise);')
            lines.append(f'    free(sm);')
            lines.append(f'    return;')

        lines.append(f'    }}')  # end switch
        lines.append(f'}}')

        return lines

    def _gen_async_instr(
        self, instr, func: HIRFunction, struct_fields: set[str],
        var_types: dict[str, MonoType], sm_name: str,
        state_idx: int, inner_type: MonoType,
    ) -> list[str]:
        """Generate C code for a single HIR instruction inside a state machine case."""
        lines: list[str] = []

        def vref(name: str) -> str:
            return self._sm_var_ref(name, struct_fields)

        def declare_local(name: str, ty: MonoType) -> str:
            """Declare a local C variable if it's not a struct field."""
            if name in struct_fields:
                return ""  # Already a struct field, no local declaration needed
            c_type = self._c_type_for_mono(ty)
            c_name = self._sanitize_c_name(name)
            return f"        {c_type} {c_name}"

        if isinstance(instr, HIRConst):
            ty = instr.type
            val = instr.result
            if isinstance(instr.value, bool):
                c_val = "1" if instr.value else "0"
            elif isinstance(instr.value, (int, float)):
                c_val = repr(float(instr.value))
                # Ensure valid C double literal
                if c_val == "inf":
                    c_val = "(1.0/0.0)"
                elif c_val == "-inf":
                    c_val = "(-1.0/0.0)"
                elif c_val == "nan":
                    c_val = "(0.0/0.0)"
            elif isinstance(instr.value, str):
                escaped = instr.value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                c_val = f'"{escaped}"'
            elif instr.value is None:
                c_val = "0.0"
            else:
                c_val = repr(instr.value)

            if val in struct_fields:
                lines.append(f'        {vref(val)} = {c_val};')
            else:
                decl = declare_local(val, ty)
                if decl:
                    lines.append(f'{decl} = {c_val};')

        elif isinstance(instr, HIRBinaryOp):
            op = instr.op
            left = vref(instr.left)
            right = vref(instr.right)
            result = instr.result

            if op == "pow":
                expr = f"pow({left}, {right})"
            elif op == "mod":
                expr = f"fmod({left}, {right})"
            else:
                c_op = self._c_binop(op)
                expr = f"({left} {c_op} {right})"

            if result in struct_fields:
                lines.append(f'        {vref(result)} = {expr};')
            else:
                decl = declare_local(result, instr.type)
                if decl:
                    lines.append(f'{decl} = {expr};')

        elif isinstance(instr, HIRUnaryOp):
            c_op = self._c_unary_op(instr.op)
            operand = vref(instr.operand)
            result = instr.result

            if result in struct_fields:
                lines.append(f'        {vref(result)} = {c_op}({operand});')
            else:
                decl = declare_local(result, instr.type)
                if decl:
                    lines.append(f'{decl} = {c_op}({operand});')

        elif isinstance(instr, HIRCompare):
            c_op = self._c_compare_op(instr.op)
            left = vref(instr.left)
            right = vref(instr.right)
            result = instr.result

            if result in struct_fields:
                lines.append(f'        {vref(result)} = ({left} {c_op} {right});')
            else:
                decl = declare_local(result, BooleanType())
                if decl:
                    lines.append(f'{decl} = ({left} {c_op} {right});')

        elif isinstance(instr, HIRCall):
            args_c = ", ".join(vref(a) for a in instr.args)
            result = instr.result
            c_func = instr.func_name

            if c_func in ("console_log", "__tsuchi_console_log"):
                # Special case: console.log maps to printf
                # For async state machines, emit a simple printf call
                if instr.args:
                    arg = vref(instr.args[0])
                    arg_type = var_types.get(instr.args[0], NumberType())
                    if isinstance(arg_type, StringType):
                        lines.append(f'        printf("%s\\n", {arg});')
                    elif isinstance(arg_type, BooleanType):
                        lines.append(f'        printf("%s\\n", {arg} ? "true" : "false");')
                    else:
                        lines.append(f'        if ({arg} == (double)(long long){arg} && {arg} >= -1e15 && {arg} <= 1e15)')
                        lines.append(f'            printf("%lld\\n", (long long){arg});')
                        lines.append(f'        else')
                        lines.append(f'            printf("%g\\n", {arg});')
                return lines

            _ASYNC_API_MAP = {
                "__tsuchi_fs_readFile": "tsuchi_fs_readFile_async",
                "__tsuchi_fs_writeFile": "tsuchi_fs_writeFile_async",
                "__tsuchi_setTimeout_async": "tsuchi_setTimeout_async",
                "__tsuchi_fetch_async": "tsuchi_fetch_async",
                "__tsuchi_strlen": "strlen",
            }
            if c_func in _ASYNC_API_MAP:
                c_func = _ASYNC_API_MAP[c_func]
            elif c_func.startswith("__tsuchi_"):
                # C runtime function — strip __ prefix (e.g. __tsuchi_fs_writeFileSync → tsuchi_fs_writeFileSync)
                c_func = c_func[2:]
            else:
                # User-defined function — prepend _tsuchi_ prefix
                c_func = f"_tsuchi_{c_func}"

            if isinstance(instr.type, VoidType):
                lines.append(f'        {c_func}({args_c});')
            elif result in struct_fields:
                lines.append(f'        {vref(result)} = {c_func}({args_c});')
            else:
                decl = declare_local(result, instr.type)
                if decl:
                    lines.append(f'{decl} = {c_func}({args_c});')

        elif isinstance(instr, HIRAssign):
            src = vref(instr.value)
            dst = vref(instr.target)
            if instr.target in struct_fields:
                lines.append(f'        {dst} = {src};')
            else:
                ty = var_types.get(instr.value, NumberType())
                decl = declare_local(instr.target, ty)
                if decl:
                    lines.append(f'{decl} = {src};')

        elif isinstance(instr, HIRAwait):
            promise_var = vref(instr.promise)
            result_var = instr.result
            next_state = state_idx + 1

            lines.append(f'        sm->awaited = {promise_var};')
            lines.append(f'        if (sm->awaited->state == TSUCHI_PENDING) {{')
            lines.append(f'            sm->state = {next_state};')
            lines.append(f'            tsuchi_promise_then(sm->awaited, {sm_name}_moveNext, sm);')
            lines.append(f'            return;')
            lines.append(f'        }}')
            # If already resolved, fall through to next state (extract value inline)
            result_type = instr.result_type
            if isinstance(result_type, NumberType):
                lines.append(f'        {vref(result_var)} = sm->awaited->num_value;')
            elif isinstance(result_type, StringType):
                lines.append(f'        {vref(result_var)} = sm->awaited->str_value;')
            elif isinstance(result_type, BooleanType):
                lines.append(f'        {vref(result_var)} = sm->awaited->bool_value;')
            # For void, no value extraction needed

        elif isinstance(instr, HIRReturn):
            if instr.value:
                val = vref(instr.value)
                if isinstance(inner_type, NumberType):
                    lines.append(f'        tsuchi_promise_resolve_num(sm->result_promise, {val});')
                elif isinstance(inner_type, StringType):
                    lines.append(f'        tsuchi_promise_resolve_str(sm->result_promise, {val});')
                elif isinstance(inner_type, BooleanType):
                    lines.append(f'        tsuchi_promise_resolve_bool(sm->result_promise, {val});')
                else:
                    lines.append(f'        tsuchi_promise_resolve_void(sm->result_promise);')
            else:
                lines.append(f'        tsuchi_promise_resolve_void(sm->result_promise);')
            lines.append(f'        free(sm);')
            lines.append(f'        return;')

        elif isinstance(instr, HIRParam):
            # Params are already stored in struct fields from entry function; nothing to do
            pass

        elif isinstance(instr, HIRJump):
            # For linear control flow, jumps within a single state are no-ops
            # (the state machine flattens the block structure)
            pass

        elif isinstance(instr, HIRBranch):
            # For V1 (linear control flow only), branches are simplified
            # We emit a comment noting this limitation
            lines.append(f'        /* TODO: branch {instr.condition} -> {instr.true_block}/{instr.false_block} (not yet supported in async SM) */')

        elif isinstance(instr, HIRPhi):
            # Phi nodes don't translate directly in linear C code
            # For V1 with linear control flow, this shouldn't normally appear across await boundaries
            lines.append(f'        /* phi node {instr.result} (not yet supported in async SM) */')

        else:
            # Unknown instruction — emit a comment
            instr_name = type(instr).__name__
            lines.append(f'        /* {instr_name}: not yet supported in async state machine */')

        return lines

    # ---------------------------------------------------------------
    # Template method: _generate_main_c
    # ---------------------------------------------------------------

    def _generate_main_c(self, module_name: str, hir_module: HIRModule, source: str) -> str:
        """Generate the C main() source — template method that delegates to subclass hooks."""
        exported_funcs = [
            f for f in hir_module.functions
            if f.is_exported
            and not f.is_async
            and not f.name.startswith("__anon_")
            and not any(isinstance(p.type, FunctionType) for p in f.params)
            and not isinstance(f.return_type, FunctionType)
        ]

        # Collect async exported functions separately
        async_exported_funcs = [
            f for f in hir_module.functions
            if f.is_exported and f.is_async
        ]

        # Check if any function uses arrays
        uses_arrays = self._module_uses_arrays(hir_module)
        has_fallbacks = bool(hir_module.fallback_sources)

        lines: list[str] = []

        # Engine-specific headers
        lines.extend(self._engine_headers())

        # Standard headers and global argc/argv
        lines.extend([
            '#include <stdio.h>',
            '#include <string.h>',
            '#include <stdlib.h>',
            '#include <math.h>',
            '',
            '// Global argc/argv for process.argv',
            'static int tsuchi_argc = 0;',
            'static char **tsuchi_argv = NULL;',
            '',
        ])

        # Engine-specific global state
        lines.extend(self._engine_global_state(has_fallbacks))

        # String runtime (always include — small footprint)
        lines.extend(self._generate_string_runtime())
        lines.append('')

        # Global conversion functions
        lines.extend(self._generate_global_runtime())
        lines.append('')

        # Array runtime (only if needed)
        if uses_arrays:
            lines.append('#define TSUCHI_HAS_ARRAYS 1')
            lines.extend(self._generate_array_runtime())
            lines.append('')

        # CLI runtime: process.argv, readFile, writeFile, process.env
        lines.extend(self._generate_cli_runtime(uses_arrays))
        lines.append('')

        # path module runtime
        lines.extend(self._generate_path_runtime())
        lines.append('')

        # os module runtime
        lines.extend(self._generate_os_runtime())
        lines.append('')

        # Promise runtime (only if async features detected)
        if self._uses_async:
            lines.extend(self._generate_promise_runtime())
            lines.append('')

        # Event loop runtime (libuv — only if async features used)
        if self._uses_async:
            lines.extend(self._generate_event_loop_runtime())
            lines.append('')

        # fs module runtime (after array runtime, uses TsuchiArray for readdirSync)
        lines.extend(self._generate_fs_runtime())
        lines.append('')

        # Engine-side bindings for CLI builtins (used by entry-level statements)
        lines.extend(self._generate_cli_bindings())
        lines.append('')

        # Shell exec + HTTP runtime
        lines.extend(self._generate_http_shell_runtime())
        lines.append('')
        lines.extend(self._generate_http_shell_bindings())
        lines.append('')

        # Raylib C runtime wrappers
        lines.extend(self._generate_raylib_runtime())
        lines.append('')

        # Engine-side bindings for raylib (used by entry-level statements)
        lines.extend(self._generate_raylib_bindings())
        lines.append('')

        # Clay UI wrappers (includes clay.h implementation + raylib renderer)
        if self._uses_clay:
            lines.extend(self._generate_clay_runtime())
            lines.append('')
            lines.extend(self._generate_clay_bindings())
            lines.append('')

        # Clay TUI wrappers (includes clay.h implementation + termbox2 renderer)
        if self._uses_clay_tui:
            lines.extend(self._generate_clay_tui_runtime())
            lines.append('')
            lines.extend(self._generate_clay_tui_bindings())
            lines.append('')

        # UI widget runtime (interactive IMGUI-style widgets on top of Clay)
        if self._uses_ui:
            lines.extend(self._generate_ui_runtime())
            lines.append('')
            lines.extend(self._generate_ui_bindings())
            lines.append('')

        # Game framework runtime (2D game utilities on top of raylib)
        if self._uses_gf:
            lines.extend(self._generate_gf_runtime())
            lines.append('')
            lines.extend(self._generate_gf_bindings())
            lines.append('')

        # FFI C forward declarations and engine bindings
        if self._ffi_info is not None and (self._ffi_info.functions or self._ffi_info.structs or self._ffi_info.opaque_classes):
            lines.extend(self._generate_ffi_declarations())
            lines.append('')
            lines.extend(self._generate_ffi_bindings())
            lines.append('')

        # Generate struct typedefs before extern declarations
        struct_defs = self._generate_struct_typedefs(hir_module)
        if struct_defs:
            lines.extend(struct_defs)

        # console.log implementation (engine-specific)
        lines.extend(self._engine_console_log())

        # Generate fallback bridge functions
        if has_fallbacks:
            lines.extend(self._generate_fallback_bridges(hir_module))
            lines.append('')

        # Generate C state machine code for async functions
        if async_exported_funcs:
            lines.extend(self._generate_async_functions(hir_module))
            lines.append('')

        # Forward declare native functions
        for func in exported_funcs:
            ret_c = self._c_return_type(func.return_type)
            params_c = ", ".join(self._c_param_type(p.type) for p in func.params)
            if not params_c:
                params_c = "void"
            lines.append(f'extern {ret_c} _tsuchi_{func.name}({params_c});')

        lines.append('')

        # Generate wrapper functions for each exported function
        for func in exported_funcs:
            lines.extend(self._generate_wrapper(func))
            lines.append('')

        # Resize frame callback
        lines.extend(self._generate_resize_callback(exported_funcs))

        has_async = bool(async_exported_funcs)

        # Generate engine-specific main()
        lines.extend(self._generate_engine_main(
            hir_module, exported_funcs, has_fallbacks,
            has_async=has_async, async_funcs=async_exported_funcs,
        ))

        return '\n'.join(lines)
