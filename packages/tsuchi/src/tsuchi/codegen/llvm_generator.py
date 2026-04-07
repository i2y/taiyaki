"""LLVM IR code generator for Tsuchi.

Generates two LLVM functions per compiled TypeScript function:
  _tsuchi_<name>: Unboxed native computation (f64, i1)
  tsuchi_wrap_<name>: JSCFunction wrapper (QuickJS boxing/unboxing)
"""

from __future__ import annotations

from llvmlite import ir

from tsuchi.type_checker.types import (
    MonoType, NumberType, BooleanType, StringType, VoidType, NullType,
    FunctionType, ObjectType, ArrayType, ClassType, NUMBER, BOOLEAN, STRING, VOID,
)
from tsuchi.hir.nodes import (
    HIRModule, HIRFunction, BasicBlock,
    HIRConst, HIRParam, HIRBinaryOp, HIRUnaryOp, HIRCompare,
    HIRCall, HIRAssign, HIRReturn, HIRBranch, HIRJump, HIRPhi,
    HIRAllocObj, HIRFieldGet, HIRFieldSet,
    HIRAllocArray, HIRArrayGet, HIRArraySet, HIRArrayPush, HIRArrayLen,
    HIRFuncRef, HIRIndirectCall,
    HIRMakeClosure, HIRLoadCapture, HIRStoreCapture,
    HIRArrayForEach, HIRArrayMap, HIRArrayFilter, HIRArrayReduce, HIRArrayReduceRight,
    HIRArrayFind, HIRArrayFindIndex, HIRArraySome, HIRArrayEvery, HIRArraySort,
    HIRTryCatch,
    HIRFFIStructCreate, HIRFFIStructFieldGet,
    HIRLoadGlobal, HIRStoreGlobal,
)


# QuickJS types
# JSValue is a struct { uint64_t, int64_t } on 64-bit (NaN-boxing)
# But for simplicity we'll treat it as i64 (the tag+val combo)
# Actually, QuickJS-NG uses a struct { JSValueUnion, int64_t tag } on 64-bit
# We'll pass JSValue by value as { i64, i32 } or use opaque pointers.
# For LLVM-level, we'll call C wrapper functions that handle JSValue.

def _llvm_type(ty: MonoType) -> ir.Type:
    """Map Tsuchi type to LLVM type for native (unboxed) functions."""
    if isinstance(ty, NumberType):
        return ir.DoubleType()
    elif isinstance(ty, BooleanType):
        return ir.IntType(1)
    elif isinstance(ty, StringType):
        return ir.PointerType(ir.IntType(8))  # const char*
    elif isinstance(ty, VoidType):
        return ir.VoidType()
    elif isinstance(ty, NullType):
        return ir.PointerType(ir.IntType(8))  # NULL pointer
    elif isinstance(ty, ClassType):
        # Class type → treat as ObjectType (pointer to struct)
        struct_ty = _get_struct_type(ty.instance_type())
        return ir.PointerType(struct_ty)
    elif isinstance(ty, ObjectType):
        # Object type → pointer to struct
        struct_ty = _get_struct_type(ty)
        return ir.PointerType(struct_ty)
    elif isinstance(ty, ArrayType):
        # Array → opaque pointer (TsuchiArray*)
        return ir.PointerType(ir.IntType(8))
    elif isinstance(ty, FunctionType):
        # Closure pair: {i8* fn_ptr, i8* env_ptr}
        i8p = ir.PointerType(ir.IntType(8))
        return ir.LiteralStructType([i8p, i8p])
    else:
        return ir.DoubleType()  # fallback to f64


# Cache for ObjectType → LLVM struct type
_struct_type_cache: dict[tuple, ir.LiteralStructType] = {}


def _get_struct_type(obj_type: ObjectType) -> ir.LiteralStructType:
    """Get or create LLVM struct type for an ObjectType.

    If fields have an explicit order (from class inheritance), use insertion order.
    Otherwise, sort alphabetically for deterministic layout.
    """
    if hasattr(obj_type, '_ordered') and obj_type._ordered:
        ordered_fields = list(obj_type.fields.items())
    else:
        ordered_fields = sorted(obj_type.fields.items())
    key = tuple((name, type(t).__name__) for name, t in ordered_fields)
    if key not in _struct_type_cache:
        field_types = [_llvm_type(t) for _, t in ordered_fields]
        _struct_type_cache[key] = ir.LiteralStructType(field_types)
    return _struct_type_cache[key]


def _field_index(obj_type: ObjectType, field_name: str) -> int:
    """Get the index of a field in the struct layout."""
    if hasattr(obj_type, '_ordered') and obj_type._ordered:
        names = list(obj_type.fields.keys())
    else:
        names = sorted(obj_type.fields.keys())
    return names.index(field_name)


class LLVMGenerator:
    """Generate LLVM IR from HIR."""

    def __init__(self):
        self._module: ir.Module | None = None
        self._builder: ir.IRBuilder | None = None
        self._func: ir.Function | None = None
        self._ssa_values: dict[str, ir.Value] = {}
        self._blocks: dict[str, ir.Block] = {}
        self._deferred_phis: list[tuple[ir.PhiInstr, list[tuple[str, str]]]] = []
        self._native_funcs: dict[str, ir.Function] = {}  # func_name → LLVM function
        self._struct_types: dict[tuple, ir.LiteralStructType] = {}  # ObjectType fields key → LLVM struct
        self._ptr_obj_types: dict[int, ObjectType] = {}  # id(ir.Value) → ObjectType for GEP field lookup
        self._ptr_arr_types: dict[int, ArrayType] = {}  # id(ir.Value) → ArrayType for array printing
        self._fallback_bridges: dict[str, ir.Function] = {}  # fallback func name → LLVM extern decl

        # QuickJS C API function declarations (filled lazily)
        self._qjs_funcs: dict[str, ir.Function] = {}

    def generate(self, hir_module: HIRModule) -> str:
        """Generate LLVM IR from HIR module. Returns IR string."""
        self._module = ir.Module(name="tsuchi_module")
        self._module.triple = "default"
        self._resolved_classes = hir_module.classes

        # Declare QuickJS C API functions
        self._declare_qjs_api()

        # Declare printf for console.log
        self._declare_printf()

        # Declare string runtime functions
        self._declare_string_runtime()

        # Declare math runtime functions
        self._declare_math_runtime()

        # Declare Node.js-compatible module functions (path, fs, os)
        self._declare_node_modules_runtime()

        # Declare array runtime functions
        self._declare_array_runtime()

        # Declare raylib runtime functions (only if used)
        from tsuchi.hir.nodes import HIRCall
        uses_raylib = any(
            isinstance(instr, HIRCall) and instr.func_name.startswith("__tsuchi_rl_")
            for func in hir_module.functions
            for block in func.blocks
            for instr in block.instructions
        )
        if uses_raylib:
            self._declare_raylib_runtime()

        # Declare Clay UI runtime functions (only if used)
        uses_clay = any(
            isinstance(instr, HIRCall) and instr.func_name.startswith("__tsuchi_clay_")
            for func in hir_module.functions
            for block in func.blocks
            for instr in block.instructions
        )
        if uses_clay:
            self._declare_clay_runtime()

        # Declare Clay TUI runtime functions (only if used)
        if self._hir_uses_clay_tui(hir_module):
            self._declare_clay_tui_runtime()

        # Declare UI widget runtime functions (only if used)
        uses_ui = any(
            isinstance(instr, HIRCall) and instr.func_name.startswith("__tsuchi_ui_")
            for func in hir_module.functions
            for block in func.blocks
            for instr in block.instructions
        )
        if uses_ui:
            self._declare_ui_runtime()

        # Declare game framework runtime functions (only if used)
        uses_gf = any(
            isinstance(instr, HIRCall) and instr.func_name.startswith("__tsuchi_gf_")
            for func in hir_module.functions
            for block in func.blocks
            for instr in block.instructions
        )
        if uses_gf:
            self._declare_game_framework()

        # Declare user FFI functions
        self._declare_ffi_functions(hir_module)

        # Define module-level global variables directly in LLVM module
        self._llvm_globals = {}
        from tsuchi.type_checker.types import StringType
        for gname, gtype in hir_module.global_vars.items():
            init_val = hir_module.global_var_inits.get(gname, 0.0)
            if isinstance(gtype, StringType):
                gvar = ir.GlobalVariable(self._module, ir.PointerType(ir.IntType(8)),
                                         name=f"tsuchi_global_{gname}")
                gvar.initializer = ir.Constant(ir.PointerType(ir.IntType(8)), None)
            else:
                gvar = ir.GlobalVariable(self._module, ir.DoubleType(),
                                         name=f"tsuchi_global_{gname}")
                gvar.initializer = ir.Constant(ir.DoubleType(), float(init_val))
            self._llvm_globals[gname] = gvar

        # Declare fallback bridge functions for non-compilable functions
        self._declare_fallback_bridges(hir_module)

        # Two-pass: declare all functions first, then generate bodies
        # Skip async functions — they are compiled as C state machines instead
        for hir_func in hir_module.functions:
            if hir_func.is_async:
                continue  # Async functions are compiled as C state machines
            self._declare_native_func(hir_func)

        for hir_func in hir_module.functions:
            if hir_func.is_async:
                continue  # Async functions are compiled as C state machines
            self._generate_native_func(hir_func)

        for hir_func in hir_module.functions:
            if hir_func.is_async:
                continue  # Async functions are compiled as C state machines
            self._generate_wrapper_func(hir_func)

        return str(self._module)

    def _declare_fallback_bridges(self, hir_module: HIRModule):
        """Declare external C bridge functions for non-compilable (fallback) functions."""
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        i1 = ir.IntType(1)
        void = ir.VoidType()
        for name, info in hir_module.fallback_signatures.items():
            # All params are f64 (QuickJS bridge converts JS values)
            param_types = [f64] * info.param_count
            if info.return_type_hint == "string":
                ret_type = i8p
            elif info.return_type_hint == "boolean":
                ret_type = i1
            elif info.return_type_hint == "void":
                ret_type = void
            else:
                ret_type = f64
            fn_type = ir.FunctionType(ret_type, param_types)
            fn = ir.Function(self._module, fn_type, name=f"_tsuchi_fb_{name}")
            self._fallback_bridges[name] = fn

    def _declare_qjs_api(self):
        """Declare QuickJS C API functions used by wrappers."""
        m = self._module
        i8p = ir.PointerType(ir.IntType(8))  # void* / JSContext* / JSRuntime*
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        # JSValue is complex; we use opaque struct approach
        # For the wrapper, we generate C code instead of LLVM IR
        # So these declarations are mainly for the native functions

        # JS_ToFloat64(ctx, *pval, jsval) — handled in C wrapper
        # JS_NewFloat64(ctx, val) — handled in C wrapper

    def _declare_string_runtime(self):
        """Declare C runtime functions for string operations."""
        m = self._module
        i8p = ir.PointerType(ir.IntType(8))
        f64 = ir.DoubleType()
        i1 = ir.IntType(1)
        # char* tsuchi_str_concat(const char* a, const char* b)
        self._qjs_funcs["tsuchi_str_concat"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_str_concat"
        )
        # char* tsuchi_str_concat_owned(char* a, const char* b) — takes ownership of a
        self._qjs_funcs["tsuchi_str_concat_owned"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_str_concat_owned"
        )
        # char* tsuchi_num_to_str(double val)
        self._qjs_funcs["tsuchi_num_to_str"] = ir.Function(
            m, ir.FunctionType(i8p, [f64]), name="tsuchi_num_to_str"
        )
        # char* tsuchi_bool_to_str(int val)
        self._qjs_funcs["tsuchi_bool_to_str"] = ir.Function(
            m, ir.FunctionType(i8p, [i1]), name="tsuchi_bool_to_str"
        )
        # String method runtime functions
        # double tsuchi_str_indexOf(const char* s, const char* search)
        self._qjs_funcs["tsuchi_str_indexOf"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, i8p]), name="tsuchi_str_indexOf"
        )
        # double tsuchi_str_lastIndexOf(const char* s, const char* search)
        self._qjs_funcs["tsuchi_str_lastIndexOf"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, i8p]), name="tsuchi_str_lastIndexOf"
        )
        # int tsuchi_str_includes(const char* s, const char* search) → i1
        self._qjs_funcs["tsuchi_str_includes"] = ir.Function(
            m, ir.FunctionType(i1, [i8p, i8p]), name="tsuchi_str_includes"
        )
        # char* tsuchi_str_slice(const char* s, double start, double end)
        self._qjs_funcs["tsuchi_str_slice"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64, f64]), name="tsuchi_str_slice"
        )
        # char* tsuchi_str_charAt(const char* s, double index)
        self._qjs_funcs["tsuchi_str_charAt"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64]), name="tsuchi_str_charAt"
        )
        # char* tsuchi_str_at(const char* s, double index)
        self._qjs_funcs["tsuchi_str_at"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64]), name="tsuchi_str_at"
        )
        # char* tsuchi_str_toUpperCase(const char* s)
        self._qjs_funcs["tsuchi_str_toUpperCase"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_str_toUpperCase"
        )
        # char* tsuchi_str_toLowerCase(const char* s)
        self._qjs_funcs["tsuchi_str_toLowerCase"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_str_toLowerCase"
        )
        # char* tsuchi_str_trim(const char* s)
        self._qjs_funcs["tsuchi_str_trim"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_str_trim"
        )
        # char* tsuchi_str_trimStart(const char* s)
        self._qjs_funcs["tsuchi_str_trimStart"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_str_trimStart"
        )
        # char* tsuchi_str_trimEnd(const char* s)
        self._qjs_funcs["tsuchi_str_trimEnd"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_str_trimEnd"
        )
        # int tsuchi_str_startsWith(const char* s, const char* prefix) → i1
        self._qjs_funcs["tsuchi_str_startsWith"] = ir.Function(
            m, ir.FunctionType(i1, [i8p, i8p]), name="tsuchi_str_startsWith"
        )
        # int tsuchi_str_endsWith(const char* s, const char* suffix) → i1
        self._qjs_funcs["tsuchi_str_endsWith"] = ir.Function(
            m, ir.FunctionType(i1, [i8p, i8p]), name="tsuchi_str_endsWith"
        )
        # char* tsuchi_str_replace(const char* s, const char* search, const char* replacement)
        self._qjs_funcs["tsuchi_str_replace"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p, i8p]), name="tsuchi_str_replace"
        )
        # char* tsuchi_str_replaceAll(const char* s, const char* search, const char* replacement)
        self._qjs_funcs["tsuchi_str_replaceAll"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p, i8p]), name="tsuchi_str_replaceAll"
        )
        # char* tsuchi_str_repeat(const char* s, double count)
        self._qjs_funcs["tsuchi_str_repeat"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64]), name="tsuchi_str_repeat"
        )
        # char* tsuchi_str_substring(const char* s, double start, double end)
        self._qjs_funcs["tsuchi_str_substring"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64, f64]), name="tsuchi_str_substring"
        )
        # char* tsuchi_str_padStart(const char* s, double target, const char* pad)
        self._qjs_funcs["tsuchi_str_padStart"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64, i8p]), name="tsuchi_str_padStart"
        )
        # char* tsuchi_str_padEnd(const char* s, double target, const char* pad)
        self._qjs_funcs["tsuchi_str_padEnd"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, f64, i8p]), name="tsuchi_str_padEnd"
        )
        # double tsuchi_str_charCodeAt(const char* s, double index) → char code
        self._qjs_funcs["tsuchi_str_charCodeAt"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, f64]), name="tsuchi_str_charCodeAt"
        )
        # char* tsuchi_fromCharCode(double code) → single-char string
        self._qjs_funcs["tsuchi_fromCharCode"] = ir.Function(
            m, ir.FunctionType(i8p, [f64]), name="tsuchi_fromCharCode"
        )
        # char* tsuchi_num_toString(double val)
        self._qjs_funcs["tsuchi_num_toString"] = ir.Function(
            m, ir.FunctionType(i8p, [f64]), name="tsuchi_num_toString"
        )
        # char* tsuchi_num_toFixed(double val, double digits)
        self._qjs_funcs["tsuchi_num_toFixed"] = ir.Function(
            m, ir.FunctionType(i8p, [f64, f64]), name="tsuchi_num_toFixed"
        )

        # char* tsuchi_json_stringify(double val) — JSON.stringify for numbers
        self._qjs_funcs["tsuchi_json_stringify"] = ir.Function(
            m, ir.FunctionType(i8p, [f64]), name="tsuchi_json_stringify"
        )
        # Also declare string variant
        self._qjs_funcs["tsuchi_json_stringify_str"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_json_stringify_str"
        )
        # bool variant
        self._qjs_funcs["tsuchi_json_stringify_bool"] = ir.Function(
            m, ir.FunctionType(i8p, [i1]), name="tsuchi_json_stringify_bool"
        )

        # JSON.parse variants
        self._qjs_funcs["tsuchi_json_parse_num"] = ir.Function(
            m, ir.FunctionType(f64, [i8p]), name="tsuchi_json_parse_num"
        )
        self._qjs_funcs["tsuchi_json_parse_str"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_json_parse_str"
        )
        self._qjs_funcs["tsuchi_json_parse_bool"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_json_parse_bool"
        )

    def _declare_math_runtime(self):
        """Declare C math library functions."""
        m = self._module
        f64 = ir.DoubleType()
        # 1-arg math functions
        for name in ("floor", "ceil", "fabs", "sqrt", "round", "trunc",
                      "log", "exp", "sin", "cos", "tan", "log2", "log10"):
            self._qjs_funcs[name] = ir.Function(
                m, ir.FunctionType(f64, [f64]), name=name
            )
        # 2-arg math functions
        for name in ("fmin", "fmax", "pow", "hypot"):
            self._qjs_funcs[name] = ir.Function(
                m, ir.FunctionType(f64, [f64, f64]), name=name
            )
        # Math.random() → tsuchi_math_random()
        self._qjs_funcs["tsuchi_math_random"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_math_random"
        )
        # Math.clz32(x) → tsuchi_math_clz32(x)
        self._qjs_funcs["tsuchi_math_clz32"] = ir.Function(
            m, ir.FunctionType(f64, [f64]), name="tsuchi_math_clz32"
        )
        # Date.now() → tsuchi_date_now()
        self._qjs_funcs["tsuchi_date_now"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_date_now"
        )
        # strlen for string.length
        i8p = ir.PointerType(ir.IntType(8))
        i64 = ir.IntType(64)
        self._qjs_funcs["strlen"] = ir.Function(
            m, ir.FunctionType(i64, [i8p]), name="strlen"
        )
        # process.argv → TsuchiArray* tsuchi_process_argv(void)
        self._qjs_funcs["tsuchi_process_argv"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_process_argv"
        )
        # readFile(path) → char* tsuchi_readFile(const char* path)
        self._qjs_funcs["tsuchi_readFile"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_readFile"
        )
        # writeFile(path, content) → void tsuchi_writeFile(const char* path, const char* content)
        self._qjs_funcs["tsuchi_writeFile"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p, i8p]), name="tsuchi_writeFile"
        )
        # process.env.VARNAME → const char* tsuchi_getenv(const char* name)
        self._qjs_funcs["tsuchi_getenv"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_getenv"
        )
        # exec(cmd) → char* tsuchi_exec(const char* cmd)
        self._qjs_funcs["tsuchi_exec"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_exec"
        )
        # httpGet(url) → char* tsuchi_httpGet(const char* url)
        self._qjs_funcs["tsuchi_httpGet"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_httpGet"
        )
        # httpPost(url, body, contentType) → char*
        self._qjs_funcs["tsuchi_httpPost"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p, i8p]), name="tsuchi_httpPost"
        )
        # fetch(url) → TsuchiPromise* tsuchi_fetch_async(const char* url)
        self._qjs_funcs["tsuchi_fetch_async"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_fetch_async"
        )

    def _declare_node_modules_runtime(self):
        """Declare C runtime functions for path, fs, os modules."""
        m = self._module
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        i1 = ir.IntType(1)
        void = ir.VoidType()

        # path module
        self._qjs_funcs["path_join"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_path_join")
        self._qjs_funcs["path_resolve"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_path_resolve")
        self._qjs_funcs["path_dirname"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_path_dirname")
        self._qjs_funcs["path_basename"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_path_basename")
        self._qjs_funcs["path_extname"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_path_extname")
        self._qjs_funcs["path_normalize"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_path_normalize")
        self._qjs_funcs["path_isAbsolute"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_path_isAbsolute")

        # fs module
        self._qjs_funcs["fs_readFileSync"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_fs_readFileSync")
        self._qjs_funcs["fs_writeFileSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i8p]), name="tsuchi_fs_writeFileSync")
        self._qjs_funcs["fs_existsSync"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_fs_existsSync")
        self._qjs_funcs["fs_mkdirSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p]), name="tsuchi_fs_mkdirSync")
        self._qjs_funcs["fs_rmdirSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p]), name="tsuchi_fs_rmdirSync")
        self._qjs_funcs["fs_unlinkSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p]), name="tsuchi_fs_unlinkSync")
        self._qjs_funcs["fs_renameSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i8p]), name="tsuchi_fs_renameSync")
        self._qjs_funcs["fs_appendFileSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i8p]), name="tsuchi_fs_appendFileSync")
        self._qjs_funcs["fs_copyFileSync"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i8p]), name="tsuchi_fs_copyFileSync")
        self._qjs_funcs["fs_readdirSync"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_fs_readdirSync")

        # os module
        self._qjs_funcs["os_platform"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_os_platform")
        self._qjs_funcs["os_arch"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_os_arch")
        self._qjs_funcs["os_homedir"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_os_homedir")
        self._qjs_funcs["os_tmpdir"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_os_tmpdir")
        self._qjs_funcs["os_hostname"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_os_hostname")
        self._qjs_funcs["os_cpus"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_os_cpus")
        self._qjs_funcs["os_totalmem"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_os_totalmem")
        self._qjs_funcs["os_freemem"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_os_freemem")

    def _declare_raylib_runtime(self):
        """Declare C wrapper functions for raylib bindings."""
        m = self._module
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        void = ir.VoidType()
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)

        # Core window
        self._qjs_funcs["rl_initWindow"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i8p]), name="tsuchi_rl_initWindow")
        self._qjs_funcs["rl_closeWindow"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_closeWindow")
        self._qjs_funcs["rl_windowShouldClose"] = ir.Function(
            m, ir.FunctionType(i1, []), name="tsuchi_rl_windowShouldClose")
        self._qjs_funcs["rl_setTargetFPS"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_setTargetFPS")
        self._qjs_funcs["rl_getScreenWidth"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getScreenWidth")
        self._qjs_funcs["rl_getScreenHeight"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getScreenHeight")
        self._qjs_funcs["rl_getFrameTime"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_rl_getFrameTime")
        self._qjs_funcs["rl_getTime"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_rl_getTime")
        self._qjs_funcs["rl_getFPS"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getFPS")
        # Window extended (Phase 3)
        self._qjs_funcs["rl_toggleFullscreen"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_toggleFullscreen")
        self._qjs_funcs["rl_setWindowSize"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_rl_setWindowSize")
        self._qjs_funcs["rl_setWindowTitle"] = ir.Function(
            m, ir.FunctionType(void, [i8p]), name="tsuchi_rl_setWindowTitle")
        self._qjs_funcs["rl_setConfigFlags"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_setConfigFlags")
        self._qjs_funcs["rl_isWindowFocused"] = ir.Function(
            m, ir.FunctionType(i1, []), name="tsuchi_rl_isWindowFocused")
        self._qjs_funcs["rl_isWindowResized"] = ir.Function(
            m, ir.FunctionType(i1, []), name="tsuchi_rl_isWindowResized")

        # Drawing
        self._qjs_funcs["rl_beginDrawing"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_beginDrawing")
        self._qjs_funcs["rl_endDrawing"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_endDrawing")
        self._qjs_funcs["rl_clearBackground"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_clearBackground")
        self._qjs_funcs["rl_drawRectangle"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32]), name="tsuchi_rl_drawRectangle")
        self._qjs_funcs["rl_drawRectangleLines"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32]), name="tsuchi_rl_drawRectangleLines")
        self._qjs_funcs["rl_drawCircle"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, f64, i32]), name="tsuchi_rl_drawCircle")
        self._qjs_funcs["rl_drawCircleLines"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, f64, i32]), name="tsuchi_rl_drawCircleLines")
        self._qjs_funcs["rl_drawLine"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32]), name="tsuchi_rl_drawLine")
        self._qjs_funcs["rl_drawText"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32, i32, i32, i32]), name="tsuchi_rl_drawText")
        self._qjs_funcs["rl_drawTriangle"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64, f64, f64, f64, i32]), name="tsuchi_rl_drawTriangle")
        self._qjs_funcs["rl_measureText"] = ir.Function(
            m, ir.FunctionType(i32, [i8p, i32]), name="tsuchi_rl_measureText")
        # Extended shapes (Phase 3)
        # drawRectanglePro(x, y, w, h, originX, originY, rotation, color)
        self._qjs_funcs["rl_drawRectanglePro"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64, f64, f64, f64, f64, i32]),
            name="tsuchi_rl_drawRectanglePro")
        # drawRectangleRounded(x, y, w, h, roundness, segments, color)
        self._qjs_funcs["rl_drawRectangleRounded"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, f64, i32, i32]),
            name="tsuchi_rl_drawRectangleRounded")
        # drawRectangleGradientV(x, y, w, h, color1, color2)
        self._qjs_funcs["rl_drawRectangleGradientV"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32]),
            name="tsuchi_rl_drawRectangleGradientV")
        # drawRectangleGradientH(x, y, w, h, color1, color2)
        self._qjs_funcs["rl_drawRectangleGradientH"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32]),
            name="tsuchi_rl_drawRectangleGradientH")
        # drawLineEx(x1, y1, x2, y2, thick, color)
        self._qjs_funcs["rl_drawLineEx"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64, f64, f64, i32]),
            name="tsuchi_rl_drawLineEx")
        # drawPixel(x, y, color)
        self._qjs_funcs["rl_drawPixel"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32]), name="tsuchi_rl_drawPixel")
        # drawCircleSector(cx, cy, radius, startAngle, endAngle, segments, color)
        self._qjs_funcs["rl_drawCircleSector"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64, f64, f64, i32, i32]),
            name="tsuchi_rl_drawCircleSector")

        # Font loading
        self._qjs_funcs["rl_loadFont"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32]), name="tsuchi_rl_loadFont")

        # Textures (handle-based: textureId as i32)
        self._qjs_funcs["rl_loadTexture"] = ir.Function(
            m, ir.FunctionType(i32, [i8p]), name="tsuchi_rl_loadTexture")
        self._qjs_funcs["rl_drawTexture"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32]), name="tsuchi_rl_drawTexture")
        self._qjs_funcs["rl_unloadTexture"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_unloadTexture")
        # Texture Pro (Phase 3)
        # drawTextureRec(texId, srcX, srcY, srcW, srcH, destX, destY, color)
        self._qjs_funcs["rl_drawTextureRec"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64, f64, f64, f64, i32, i32, i32]),
            name="tsuchi_rl_drawTextureRec")
        # drawTexturePro(texId, srcX,srcY,srcW,srcH, destX,destY,destW,destH, originX,originY, rotation, color)
        self._qjs_funcs["rl_drawTexturePro"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64, f64, f64, f64, f64, f64, f64, f64, f64, f64, f64, i32]),
            name="tsuchi_rl_drawTexturePro")
        # getTextureWidth(texId) → i32
        self._qjs_funcs["rl_getTextureWidth"] = ir.Function(
            m, ir.FunctionType(i32, [i32]), name="tsuchi_rl_getTextureWidth")
        # getTextureHeight(texId) → i32
        self._qjs_funcs["rl_getTextureHeight"] = ir.Function(
            m, ir.FunctionType(i32, [i32]), name="tsuchi_rl_getTextureHeight")
        # Text Pro (Phase 3)
        # drawTextEx(text, x, y, fontSize, spacing, color) — uses loaded font
        self._qjs_funcs["rl_drawTextEx"] = ir.Function(
            m, ir.FunctionType(void, [i8p, f64, f64, f64, f64, i32]),
            name="tsuchi_rl_drawTextEx")
        # measureTextEx(text, fontSize, spacing) → i32 width
        self._qjs_funcs["rl_measureTextEx"] = ir.Function(
            m, ir.FunctionType(i32, [i8p, f64, f64]),
            name="tsuchi_rl_measureTextEx")

        # Input: keyboard
        self._qjs_funcs["rl_isKeyDown"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isKeyDown")
        self._qjs_funcs["rl_isKeyPressed"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isKeyPressed")
        self._qjs_funcs["rl_isKeyReleased"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isKeyReleased")
        self._qjs_funcs["rl_getKeyPressed"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getKeyPressed")
        # Phase 3 input extensions
        self._qjs_funcs["rl_getCharPressed"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getCharPressed")
        self._qjs_funcs["rl_isKeyUp"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isKeyUp")

        # Input: mouse
        self._qjs_funcs["rl_getMouseX"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getMouseX")
        self._qjs_funcs["rl_getMouseY"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getMouseY")
        self._qjs_funcs["rl_isMouseButtonDown"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isMouseButtonDown")
        self._qjs_funcs["rl_isMouseButtonPressed"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isMouseButtonPressed")
        self._qjs_funcs["rl_isMouseButtonReleased"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isMouseButtonReleased")
        # Phase 3 mouse extensions
        self._qjs_funcs["rl_getMouseWheelMove"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_rl_getMouseWheelMove")

        # Color helper: color(r, g, b, a) → packed u32
        self._qjs_funcs["rl_color"] = ir.Function(
            m, ir.FunctionType(i32, [i32, i32, i32, i32]), name="tsuchi_rl_color")
        # colorAlpha(color, alpha) → packed u32 (Phase 3)
        self._qjs_funcs["rl_colorAlpha"] = ir.Function(
            m, ir.FunctionType(i32, [i32, f64]), name="tsuchi_rl_colorAlpha")

        # Audio device (Phase 1)
        self._qjs_funcs["rl_initAudioDevice"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_initAudioDevice")
        self._qjs_funcs["rl_closeAudioDevice"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_closeAudioDevice")
        self._qjs_funcs["rl_setMasterVolume"] = ir.Function(
            m, ir.FunctionType(void, [f64]), name="tsuchi_rl_setMasterVolume")
        self._qjs_funcs["rl_getMasterVolume"] = ir.Function(
            m, ir.FunctionType(f64, []), name="tsuchi_rl_getMasterVolume")

        # Sound (Phase 1) — handle-based
        self._qjs_funcs["rl_loadSound"] = ir.Function(
            m, ir.FunctionType(i32, [i8p]), name="tsuchi_rl_loadSound")
        self._qjs_funcs["rl_playSound"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_playSound")
        self._qjs_funcs["rl_stopSound"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_stopSound")
        self._qjs_funcs["rl_pauseSound"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_pauseSound")
        self._qjs_funcs["rl_resumeSound"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_resumeSound")
        self._qjs_funcs["rl_setSoundVolume"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64]), name="tsuchi_rl_setSoundVolume")
        self._qjs_funcs["rl_setSoundPitch"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64]), name="tsuchi_rl_setSoundPitch")
        self._qjs_funcs["rl_isSoundPlaying"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isSoundPlaying")
        self._qjs_funcs["rl_unloadSound"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_unloadSound")

        # Music (Phase 1) — handle-based
        self._qjs_funcs["rl_loadMusic"] = ir.Function(
            m, ir.FunctionType(i32, [i8p]), name="tsuchi_rl_loadMusic")
        self._qjs_funcs["rl_playMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_playMusic")
        self._qjs_funcs["rl_stopMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_stopMusic")
        self._qjs_funcs["rl_pauseMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_pauseMusic")
        self._qjs_funcs["rl_resumeMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_resumeMusic")
        self._qjs_funcs["rl_updateMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_updateMusic")
        self._qjs_funcs["rl_setMusicVolume"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64]), name="tsuchi_rl_setMusicVolume")
        self._qjs_funcs["rl_isMusicPlaying"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isMusicPlaying")
        self._qjs_funcs["rl_getMusicTimeLength"] = ir.Function(
            m, ir.FunctionType(f64, [i32]), name="tsuchi_rl_getMusicTimeLength")
        self._qjs_funcs["rl_getMusicTimePlayed"] = ir.Function(
            m, ir.FunctionType(f64, [i32]), name="tsuchi_rl_getMusicTimePlayed")
        self._qjs_funcs["rl_unloadMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_rl_unloadMusic")

        # Camera2D (Phase 2)
        # beginMode2D(offsetX, offsetY, targetX, targetY, rotation, zoom)
        self._qjs_funcs["rl_beginMode2D"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_beginMode2D")
        self._qjs_funcs["rl_endMode2D"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_endMode2D")

        # Collision detection (Phase 2)
        # checkCollisionRecs(x1,y1,w1,h1, x2,y2,w2,h2)
        self._qjs_funcs["rl_checkCollisionRecs"] = ir.Function(
            m, ir.FunctionType(i1, [f64, f64, f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_checkCollisionRecs")
        # checkCollisionCircles(cx1,cy1,r1, cx2,cy2,r2)
        self._qjs_funcs["rl_checkCollisionCircles"] = ir.Function(
            m, ir.FunctionType(i1, [f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_checkCollisionCircles")
        # checkCollisionCircleRec(cx,cy,r, rx,ry,rw,rh)
        self._qjs_funcs["rl_checkCollisionCircleRec"] = ir.Function(
            m, ir.FunctionType(i1, [f64, f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_checkCollisionCircleRec")
        # checkCollisionPointRec(px,py, rx,ry,rw,rh)
        self._qjs_funcs["rl_checkCollisionPointRec"] = ir.Function(
            m, ir.FunctionType(i1, [f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_checkCollisionPointRec")
        # checkCollisionPointCircle(px,py, cx,cy,r)
        self._qjs_funcs["rl_checkCollisionPointCircle"] = ir.Function(
            m, ir.FunctionType(i1, [f64, f64, f64, f64, f64]),
            name="tsuchi_rl_checkCollisionPointCircle")

        # Random (Phase 2)
        self._qjs_funcs["rl_getRandomValue"] = ir.Function(
            m, ir.FunctionType(i32, [i32, i32]), name="tsuchi_rl_getRandomValue")

        # Gamepad (Phase 5)
        self._qjs_funcs["rl_isGamepadAvailable"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isGamepadAvailable")
        self._qjs_funcs["rl_isGamepadButtonDown"] = ir.Function(
            m, ir.FunctionType(i1, [i32, i32]), name="tsuchi_rl_isGamepadButtonDown")
        self._qjs_funcs["rl_isGamepadButtonPressed"] = ir.Function(
            m, ir.FunctionType(i1, [i32, i32]), name="tsuchi_rl_isGamepadButtonPressed")
        self._qjs_funcs["rl_isGamepadButtonReleased"] = ir.Function(
            m, ir.FunctionType(i1, [i32, i32]), name="tsuchi_rl_isGamepadButtonReleased")
        self._qjs_funcs["rl_getGamepadAxisMovement"] = ir.Function(
            m, ir.FunctionType(f64, [i32, i32]), name="tsuchi_rl_getGamepadAxisMovement")
        self._qjs_funcs["rl_getGamepadAxisCount"] = ir.Function(
            m, ir.FunctionType(i32, [i32]), name="tsuchi_rl_getGamepadAxisCount")
        self._qjs_funcs["rl_getGamepadButtonPressed"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_rl_getGamepadButtonPressed")
        self._qjs_funcs["rl_getGamepadName"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_getGamepadName")

        # Music extended
        self._qjs_funcs["rl_seekMusic"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64]), name="tsuchi_rl_seekMusic")
        self._qjs_funcs["rl_setMusicPitch"] = ir.Function(
            m, ir.FunctionType(void, [i32, f64]), name="tsuchi_rl_setMusicPitch")

        # Audio device extended
        self._qjs_funcs["rl_isAudioDeviceReady"] = ir.Function(
            m, ir.FunctionType(i1, []), name="tsuchi_rl_isAudioDeviceReady")

        # Font extended
        self._qjs_funcs["rl_unloadFont"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_rl_unloadFont")

        # Text measurement extended
        # measureTextExY(text, fontSize, spacing) → i32 height
        self._qjs_funcs["rl_measureTextExY"] = ir.Function(
            m, ir.FunctionType(i32, [i8p, f64, f64]),
            name="tsuchi_rl_measureTextExY")

        # Texture extended
        # drawTextureScaled(texId, x, y, scale, color)
        self._qjs_funcs["rl_drawTextureScaled"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, f64, i32]),
            name="tsuchi_rl_drawTextureScaled")
        # isTextureValid(texId) → i1
        self._qjs_funcs["rl_isTextureValid"] = ir.Function(
            m, ir.FunctionType(i1, [i32]), name="tsuchi_rl_isTextureValid")

        # Camera2D extended: getWorldToScreen2D X/Y
        # (worldX, worldY, camOffsetX, camOffsetY, camTargetX, camTargetY, camRotation, camZoom) → i32
        self._qjs_funcs["rl_getWorldToScreen2DX"] = ir.Function(
            m, ir.FunctionType(i32, [f64, f64, f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_getWorldToScreen2DX")
        self._qjs_funcs["rl_getWorldToScreen2DY"] = ir.Function(
            m, ir.FunctionType(i32, [f64, f64, f64, f64, f64, f64, f64, f64]),
            name="tsuchi_rl_getWorldToScreen2DY")

        # Gamepad extended
        self._qjs_funcs["rl_isGamepadButtonUp"] = ir.Function(
            m, ir.FunctionType(i1, [i32, i32]), name="tsuchi_rl_isGamepadButtonUp")

        # File system
        self._qjs_funcs["rl_fileExists"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_rl_fileExists")
        self._qjs_funcs["rl_directoryExists"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_rl_directoryExists")

    def _declare_clay_runtime(self):
        """Declare C wrapper functions for Clay UI bindings."""
        m = self._module
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        void = ir.VoidType()
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)

        # Lifecycle
        self._qjs_funcs["clay_init"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_clay_init")
        self._qjs_funcs["clay_loadFont"] = ir.Function(
            m, ir.FunctionType(i32, [i8p, i32]), name="tsuchi_clay_load_font")
        self._qjs_funcs["clay_setDimensions"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_clay_set_dimensions")
        self._qjs_funcs["clay_setPointer"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, i32]), name="tsuchi_clay_set_pointer")
        self._qjs_funcs["clay_updateScroll"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64]), name="tsuchi_clay_update_scroll")
        self._qjs_funcs["clay_beginLayout"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_begin_layout")
        self._qjs_funcs["clay_endLayout"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_end_layout")
        self._qjs_funcs["clay_render"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_render")

        # Elements: open(id, sizingW, sizingH, padT, padR, padB, padL, childGap, dir, bgR, bgG, bgB, bgA, cornerRadius)
        self._qjs_funcs["clay_open"] = ir.Function(
            m, ir.FunctionType(void, [i8p, f64, f64, i32, i32, i32, i32, i32, i32,
                                       i32, i32, i32, i32, f64]),
            name="tsuchi_clay_open")
        self._qjs_funcs["clay_openAligned"] = ir.Function(
            m, ir.FunctionType(void, [i8p, f64, f64, i32, i32, i32, i32, i32, i32,
                                       i32, i32, i32, i32, f64, i32, i32]),
            name="tsuchi_clay_open_aligned")
        self._qjs_funcs["clay_close"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_close")
        # text(text, fontSize, fontId, r, g, b, a)
        self._qjs_funcs["clay_text"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_text")
        # pointerOver(id) → bool
        self._qjs_funcs["clay_pointerOver"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_clay_pointer_over")

        # Clay GUI extensions
        self._qjs_funcs["clay_scroll"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_clay_scroll")
        self._qjs_funcs["clay_floating"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, i32]), name="tsuchi_clay_floating")
        self._qjs_funcs["clay_border"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_border")
        self._qjs_funcs["clay_openI"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_openI")
        self._qjs_funcs["clay_pointerOverI"] = ir.Function(
            m, ir.FunctionType(i1, [i8p, i32]), name="tsuchi_clay_pointer_over_i")
        self._qjs_funcs["clay_setMeasureTextRaylib"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_set_measure_text_raylib")
        self._qjs_funcs["clay_loadFontCjk"] = ir.Function(
            m, ir.FunctionType(i32, [i8p, i32]), name="tsuchi_clay_load_font_cjk")
        self._qjs_funcs["clay_setCustom"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_clay_set_custom")
        self._qjs_funcs["clay_destroy"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_destroy")
        self._qjs_funcs["clay_renderRaylib"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_render_raylib")
        self._qjs_funcs["clay_registerResizeCallback"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_register_resize_callback")
        self._qjs_funcs["clay_setBgColor"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32]), name="tsuchi_clay_set_bg_color")

    def _hir_uses_clay_tui(self, hir_module: HIRModule) -> bool:
        """Check if any function in the HIR uses Clay TUI calls."""
        from tsuchi.hir.nodes import HIRCall
        for func in hir_module.functions:
            for bb in func.blocks:
                for instr in bb.instructions:
                    if isinstance(instr, HIRCall) and instr.func_name.startswith("__tsuchi_clay_tui_"):
                        return True
        # Also check entry statements
        for stmt in hir_module.entry_statements:
            if "clayTui" in stmt:
                return True
        return False

    def _declare_clay_tui_runtime(self):
        """Declare C wrapper functions for Clay TUI (termbox2) bindings."""
        m = self._module
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        void = ir.VoidType()
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)

        # Lifecycle
        self._qjs_funcs["clay_tui_init"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_clay_tui_init")
        self._qjs_funcs["clay_tui_destroy"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_destroy")
        self._qjs_funcs["clay_tui_setDimensions"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_clay_tui_set_dimensions")
        self._qjs_funcs["clay_tui_beginLayout"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_begin_layout")
        self._qjs_funcs["clay_tui_endLayout"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_end_layout")
        self._qjs_funcs["clay_tui_render"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_render")

        # Elements: open(id, sizingW, sizingH, padT, padR, padB, padL, childGap, dir, bgR, bgG, bgB, bgA, cornerRadius)
        self._qjs_funcs["clay_tui_open"] = ir.Function(
            m, ir.FunctionType(void, [i8p, f64, f64, i32, i32, i32, i32, i32, i32,
                                       i32, i32, i32, i32, f64]),
            name="tsuchi_clay_tui_open")
        self._qjs_funcs["clay_tui_closeElement"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_close_element")
        # text(text, fontSize, fontId, r, g, b, a)
        self._qjs_funcs["clay_tui_text"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_tui_text")

        # Pointer
        self._qjs_funcs["clay_tui_setPointer"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, i32]), name="tsuchi_clay_tui_set_pointer")
        self._qjs_funcs["clay_tui_pointerOver"] = ir.Function(
            m, ir.FunctionType(i1, [i8p]), name="tsuchi_clay_tui_pointer_over")

        # Events
        self._qjs_funcs["clay_tui_peekEvent"] = ir.Function(
            m, ir.FunctionType(i32, [i32]), name="tsuchi_clay_tui_peek_event")
        self._qjs_funcs["clay_tui_pollEvent"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_poll_event")
        self._qjs_funcs["clay_tui_eventType"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_type")
        self._qjs_funcs["clay_tui_eventKey"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_key")
        self._qjs_funcs["clay_tui_eventCh"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_ch")
        self._qjs_funcs["clay_tui_eventW"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_w")
        self._qjs_funcs["clay_tui_eventH"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_h")

        # Terminal info
        self._qjs_funcs["clay_tui_termWidth"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_term_width")
        self._qjs_funcs["clay_tui_termHeight"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_term_height")
        # Event modifier (Phase 4)
        self._qjs_funcs["clay_tui_eventMod"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_mod")

        # Phase 4 extensions
        # border(r,g,b,a, top,right,bottom,left, cornerRadius)
        self._qjs_funcs["clay_tui_border"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32, i32, i32, f64]),
            name="tsuchi_clay_tui_border")
        # align(ax, ay)
        self._qjs_funcs["clay_tui_align"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_clay_tui_align")
        # scroll(h, v)
        self._qjs_funcs["clay_tui_scroll"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32]), name="tsuchi_clay_tui_scroll")
        # updateScroll(dx, dy, dt)
        self._qjs_funcs["clay_tui_updateScroll"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, f64]), name="tsuchi_clay_tui_update_scroll")
        # openI(id, index, sizingW, sizingH, padT, padR, padB, padL, childGap, dir, bgR, bgG, bgB, bgA, cornerRadius)
        self._qjs_funcs["clay_tui_openI"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32, f64, f64, i32, i32, i32, i32, i32, i32,
                                       i32, i32, i32, i32, f64]),
            name="tsuchi_clay_tui_openI")
        # Text buffer functions (Phase 4)
        self._qjs_funcs["clay_tui_textbufClear"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_clear")
        self._qjs_funcs["clay_tui_textbufPutchar"] = ir.Function(
            m, ir.FunctionType(void, [i32]), name="tsuchi_clay_tui_textbuf_putchar")
        self._qjs_funcs["clay_tui_textbufBackspace"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_backspace")
        self._qjs_funcs["clay_tui_textbufDelete"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_delete")
        self._qjs_funcs["clay_tui_textbufCursorLeft"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_cursor_left")
        self._qjs_funcs["clay_tui_textbufCursorRight"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_cursor_right")
        self._qjs_funcs["clay_tui_textbufHome"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_home")
        self._qjs_funcs["clay_tui_textbufEnd"] = ir.Function(
            m, ir.FunctionType(void, []), name="tsuchi_clay_tui_textbuf_end")
        self._qjs_funcs["clay_tui_textbufLen"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_textbuf_len")
        self._qjs_funcs["clay_tui_textbufCursor"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_textbuf_cursor")
        # textbufRender(fontSize, fontId, r, g, b, a)
        self._qjs_funcs["clay_tui_textbufRender"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_tui_textbuf_render")

        # Phase B extensions
        # textbufCopy() → i8* (returns string)
        self._qjs_funcs["clay_tui_textbufCopy"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_clay_tui_textbuf_copy")
        # textbufRenderRange(start, len, fontSize, fontId, r, g, b, a)
        self._qjs_funcs["clay_tui_textbufRenderRange"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_tui_textbuf_render_range")
        # textChar(ch, fontSize, fontId, r, g, b, a)
        self._qjs_funcs["clay_tui_textChar"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_tui_text_char")
        # pointerOverI(id, index) → bool
        self._qjs_funcs["clay_tui_pointerOverI"] = ir.Function(
            m, ir.FunctionType(i1, [i8p, i32]), name="tsuchi_clay_tui_pointer_over_i")
        # eventMouseX() → i32
        self._qjs_funcs["clay_tui_eventMouseX"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_mouse_x")
        # eventMouseY() → i32
        self._qjs_funcs["clay_tui_eventMouseY"] = ir.Function(
            m, ir.FunctionType(i32, []), name="tsuchi_clay_tui_event_mouse_y")
        # rgb(r, g, b) → i32 (packed terminal RGB)
        self._qjs_funcs["clay_tui_rgb"] = ir.Function(
            m, ir.FunctionType(i32, [i32, i32, i32]), name="tsuchi_clay_tui_rgb")
        # bgEx(r, g, b, a, attr)
        self._qjs_funcs["clay_tui_bgEx"] = ir.Function(
            m, ir.FunctionType(void, [i32, i32, i32, i32, i32]),
            name="tsuchi_clay_tui_bg_ex")
        # textEx(text, fontSize, fontId, r, g, b, a, bgR, bgG, bgB, bgA, attr)
        self._qjs_funcs["clay_tui_textEx"] = ir.Function(
            m, ir.FunctionType(void, [i8p, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32, i32]),
            name="tsuchi_clay_tui_text_ex")
        # floating(offsetX, offsetY, zIndex, attachElem, attachParent)
        self._qjs_funcs["clay_tui_floating"] = ir.Function(
            m, ir.FunctionType(void, [f64, f64, i32, i32, i32]),
            name="tsuchi_clay_tui_floating")

    def _declare_ui_runtime(self):
        """Declare C wrapper functions for UI widget bindings."""
        m = self._module
        void = ir.VoidType()
        i8p = ir.PointerType(ir.IntType(8))
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)
        f64 = ir.DoubleType()

        # Frame lifecycle
        self._qjs_funcs["ui_beginFrame"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_beginFrame")
        self._qjs_funcs["ui_endFrame"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_endFrame")

        # Button
        self._qjs_funcs["ui_buttonOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_buttonOpen")
        self._qjs_funcs["ui_buttonClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_buttonClose")

        # Checkbox
        self._qjs_funcs["ui_checkboxOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64]), name="tsuchi_ui_checkboxOpen")
        self._qjs_funcs["ui_checkboxClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_checkboxClose")

        # Radio
        self._qjs_funcs["ui_radioOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_radioOpen")
        self._qjs_funcs["ui_radioClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_radioClose")

        # Toggle
        self._qjs_funcs["ui_toggleOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64]), name="tsuchi_ui_toggleOpen")
        self._qjs_funcs["ui_toggleClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_toggleClose")

        # TextInput
        self._qjs_funcs["ui_textInput"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_textInput")

        # Slider
        self._qjs_funcs["ui_slider"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64, f64]), name="tsuchi_ui_slider")

        # MenuItem
        self._qjs_funcs["ui_menuItemOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_menuItemOpen")
        self._qjs_funcs["ui_menuItemClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_menuItemClose")

        # TabButton
        self._qjs_funcs["ui_tabButtonOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_tabButtonOpen")
        self._qjs_funcs["ui_tabButtonClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_tabButtonClose")

        # NumberStepper
        self._qjs_funcs["ui_numberStepper"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64, f64]), name="tsuchi_ui_numberStepper")

        # SearchBar
        self._qjs_funcs["ui_searchBar"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_searchBar")

        # ListItem
        self._qjs_funcs["ui_listItemOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_listItemOpen")
        self._qjs_funcs["ui_listItemClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_listItemClose")

        # State queries
        self._qjs_funcs["ui_clicked"] = ir.Function(m, ir.FunctionType(i1, [i8p]), name="tsuchi_ui_clicked")
        self._qjs_funcs["ui_hovered"] = ir.Function(m, ir.FunctionType(i1, [i8p]), name="tsuchi_ui_hovered")
        self._qjs_funcs["ui_toggled"] = ir.Function(m, ir.FunctionType(i1, [i8p]), name="tsuchi_ui_toggled")
        self._qjs_funcs["ui_sliderValue"] = ir.Function(m, ir.FunctionType(f64, [i8p]), name="tsuchi_ui_sliderValue")

        # Focus
        self._qjs_funcs["ui_focusNext"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_focusNext")
        self._qjs_funcs["ui_focusPrev"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_focusPrev")

        # Key/Char
        self._qjs_funcs["ui_keyPressed"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_ui_keyPressed")
        self._qjs_funcs["ui_charPressed"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_ui_charPressed")

        # Part 2B - Forms
        self._qjs_funcs["ui_textareaInput"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64, f64]), name="tsuchi_ui_textareaInput")
        self._qjs_funcs["ui_switchOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64]), name="tsuchi_ui_switchOpen")
        self._qjs_funcs["ui_switchClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_switchClose")
        self._qjs_funcs["ui_ratingOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_ratingOpen")
        self._qjs_funcs["ui_ratingClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_ratingClose")
        self._qjs_funcs["ui_segmentButtonOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_segmentButtonOpen")
        self._qjs_funcs["ui_segmentButtonClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_segmentButtonClose")

        # Part 2C - Navigation
        self._qjs_funcs["ui_navPush"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_ui_navPush")
        self._qjs_funcs["ui_navPop"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_navPop")
        self._qjs_funcs["ui_navCurrent"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_ui_navCurrent")
        self._qjs_funcs["ui_navDepth"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_ui_navDepth")

        # Part 2D - Overlay
        self._qjs_funcs["ui_accordionOpen"] = ir.Function(m, ir.FunctionType(void, [i8p, f64]), name="tsuchi_ui_accordionOpen")
        self._qjs_funcs["ui_accordionClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_accordionClose")
        self._qjs_funcs["ui_dropdownOpen"] = ir.Function(m, ir.FunctionType(void, [i8p]), name="tsuchi_ui_dropdownOpen")
        self._qjs_funcs["ui_dropdownClose"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_dropdownClose")
        self._qjs_funcs["ui_dropdownIsOpen"] = ir.Function(m, ir.FunctionType(i1, [i8p]), name="tsuchi_ui_dropdownIsOpen")
        self._qjs_funcs["ui_tooltipBegin"] = ir.Function(m, ir.FunctionType(void, [i8p]), name="tsuchi_ui_tooltipBegin")
        self._qjs_funcs["ui_tooltipEnd"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_tooltipEnd")
        self._qjs_funcs["ui_toastShow"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64]), name="tsuchi_ui_toastShow")
        self._qjs_funcs["ui_toastRender"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_ui_toastRender")

        # Part 2E - Charts
        self._qjs_funcs["ui_chartInit"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64]), name="tsuchi_ui_chartInit")
        self._qjs_funcs["ui_chartSet"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64]), name="tsuchi_ui_chartSet")
        self._qjs_funcs["ui_chartColor"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64, f64]), name="tsuchi_ui_chartColor")
        self._qjs_funcs["ui_chartRender"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64, f64, f64, f64]), name="tsuchi_ui_chartRender")

        # Part 2F - Markdown
        self._qjs_funcs["ui_markdownRender"] = ir.Function(m, ir.FunctionType(void, [i8p, f64, f64]), name="tsuchi_ui_markdownRender")

        # Part 2G - Other
        self._qjs_funcs["ui_spinnerChar"] = ir.Function(m, ir.FunctionType(i8p, []), name="tsuchi_ui_spinnerChar")
        self._qjs_funcs["ui_frameCount"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_ui_frameCount")

        # Style composition
        self._qjs_funcs["ui_style"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_ui_style")
        self._qjs_funcs["ui_styleMerge"] = ir.Function(m, ir.FunctionType(f64, [f64, f64]), name="tsuchi_ui_styleMerge")
        self._qjs_funcs["ui_styleSize"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_ui_styleSize")
        self._qjs_funcs["ui_styleKind"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_ui_styleKind")
        self._qjs_funcs["ui_styleFlex"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_ui_styleFlex")

    def _declare_game_framework(self):
        """Declare C wrapper functions for game framework bindings."""
        m = self._module
        void = ir.VoidType()
        f64 = ir.DoubleType()
        i1 = ir.IntType(1)

        # Math
        self._qjs_funcs["gf_clamp"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_clamp")
        self._qjs_funcs["gf_lerp"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_lerp")
        self._qjs_funcs["gf_rand"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_rand")
        self._qjs_funcs["gf_randRange"] = ir.Function(m, ir.FunctionType(f64, [f64, f64]), name="tsuchi_gf_randRange")
        self._qjs_funcs["gf_rgba"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64, f64]), name="tsuchi_gf_rgba")

        # Drawing
        self._qjs_funcs["gf_drawBar"] = ir.Function(m, ir.FunctionType(void, [f64]*8), name="tsuchi_gf_drawBar")
        self._qjs_funcs["gf_drawBox"] = ir.Function(m, ir.FunctionType(void, [f64]*6), name="tsuchi_gf_drawBox")
        self._qjs_funcs["gf_drawNum"] = ir.Function(m, ir.FunctionType(void, [f64]*5), name="tsuchi_gf_drawNum")
        self._qjs_funcs["gf_drawFPS"] = ir.Function(m, ir.FunctionType(void, [f64]*4), name="tsuchi_gf_drawFPS")
        self._qjs_funcs["gf_drawTile"] = ir.Function(m, ir.FunctionType(void, [f64]*7), name="tsuchi_gf_drawTile")
        self._qjs_funcs["gf_drawSprite"] = ir.Function(m, ir.FunctionType(void, [f64]*8), name="tsuchi_gf_drawSprite")
        self._qjs_funcs["gf_drawFade"] = ir.Function(m, ir.FunctionType(void, [f64]*3), name="tsuchi_gf_drawFade")

        # Input
        self._qjs_funcs["gf_getDirection"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_gf_getDirection")
        self._qjs_funcs["gf_confirmPressed"] = ir.Function(m, ir.FunctionType(i1, []), name="tsuchi_gf_confirmPressed")
        self._qjs_funcs["gf_cancelPressed"] = ir.Function(m, ir.FunctionType(i1, []), name="tsuchi_gf_cancelPressed")
        self._qjs_funcs["gf_menuCursor"] = ir.Function(m, ir.FunctionType(f64, [f64, f64]), name="tsuchi_gf_menuCursor")

        # Animation
        self._qjs_funcs["gf_animate"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_animate")

        # Timer
        self._qjs_funcs["gf_timerSet"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_timerSet")
        self._qjs_funcs["gf_timerRepeat"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_timerRepeat")
        self._qjs_funcs["gf_timerTick"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_timerTick")
        self._qjs_funcs["gf_timerActive"] = ir.Function(m, ir.FunctionType(i1, [f64]), name="tsuchi_gf_timerActive")
        self._qjs_funcs["gf_timerDone"] = ir.Function(m, ir.FunctionType(i1, [f64]), name="tsuchi_gf_timerDone")
        self._qjs_funcs["gf_timerCancel"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_timerCancel")

        # Tween
        self._qjs_funcs["gf_tweenStart"] = ir.Function(m, ir.FunctionType(void, [f64, f64, f64]), name="tsuchi_gf_tweenStart")
        self._qjs_funcs["gf_tweenTick"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_tweenTick")
        self._qjs_funcs["gf_tweenValue"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_tweenValue")
        self._qjs_funcs["gf_tweenActive"] = ir.Function(m, ir.FunctionType(i1, [f64]), name="tsuchi_gf_tweenActive")
        self._qjs_funcs["gf_tweenDone"] = ir.Function(m, ir.FunctionType(i1, [f64]), name="tsuchi_gf_tweenDone")
        self._qjs_funcs["gf_interpolate"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_interpolate")

        # Easing
        for name in ["easeLinear", "easeInQuad", "easeOutQuad", "easeInOutQuad",
                     "easeInCubic", "easeOutCubic", "easeInOutCubic",
                     "easeOutBounce", "easeOutElastic"]:
            self._qjs_funcs[f"gf_{name}"] = ir.Function(m, ir.FunctionType(f64, [f64]), name=f"tsuchi_gf_{name}")

        # Shake
        self._qjs_funcs["gf_shakeStart"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_shakeStart")
        self._qjs_funcs["gf_shakeUpdate"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_shakeUpdate")
        self._qjs_funcs["gf_shakeX"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_gf_shakeX")
        self._qjs_funcs["gf_shakeY"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_gf_shakeY")
        self._qjs_funcs["gf_shakeActive"] = ir.Function(m, ir.FunctionType(i1, []), name="tsuchi_gf_shakeActive")

        # Transition
        self._qjs_funcs["gf_transitionStart"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_transitionStart")
        self._qjs_funcs["gf_transitionUpdate"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_transitionUpdate")
        self._qjs_funcs["gf_transitionAlpha"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_gf_transitionAlpha")
        self._qjs_funcs["gf_transitionDone"] = ir.Function(m, ir.FunctionType(i1, []), name="tsuchi_gf_transitionDone")
        self._qjs_funcs["gf_transitionNextScene"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_gf_transitionNextScene")

        # Physics
        self._qjs_funcs["gf_physGravity"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_physGravity")
        self._qjs_funcs["gf_physFriction"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_physFriction")
        self._qjs_funcs["gf_physClamp"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_physClamp")

        # Particles
        self._qjs_funcs["gf_particleEmit"] = ir.Function(m, ir.FunctionType(void, [f64]*6), name="tsuchi_gf_particleEmit")
        self._qjs_funcs["gf_particleUpdate"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_particleUpdate")
        self._qjs_funcs["gf_particleDraw"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_particleDraw")
        self._qjs_funcs["gf_particleCount"] = ir.Function(m, ir.FunctionType(f64, []), name="tsuchi_gf_particleCount")
        self._qjs_funcs["gf_particleClear"] = ir.Function(m, ir.FunctionType(void, []), name="tsuchi_gf_particleClear")

        # Grid
        self._qjs_funcs["gf_gridToPx"] = ir.Function(m, ir.FunctionType(f64, [f64, f64]), name="tsuchi_gf_gridToPx")
        self._qjs_funcs["gf_pxToGrid"] = ir.Function(m, ir.FunctionType(f64, [f64, f64]), name="tsuchi_gf_pxToGrid")
        self._qjs_funcs["gf_gridIndex"] = ir.Function(m, ir.FunctionType(f64, [f64, f64, f64]), name="tsuchi_gf_gridIndex")
        self._qjs_funcs["gf_gridInBounds"] = ir.Function(m, ir.FunctionType(i1, [f64, f64, f64, f64]), name="tsuchi_gf_gridInBounds")
        self._qjs_funcs["gf_manhattan"] = ir.Function(m, ir.FunctionType(f64, [f64]*4), name="tsuchi_gf_manhattan")
        self._qjs_funcs["gf_chebyshev"] = ir.Function(m, ir.FunctionType(f64, [f64]*4), name="tsuchi_gf_chebyshev")

        # FSM
        self._qjs_funcs["gf_fsmInit"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_fsmInit")
        self._qjs_funcs["gf_fsmSet"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_fsmSet")
        self._qjs_funcs["gf_fsmTick"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_fsmTick")
        self._qjs_funcs["gf_fsmState"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_fsmState")
        self._qjs_funcs["gf_fsmPrev"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_fsmPrev")
        self._qjs_funcs["gf_fsmFrames"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_fsmFrames")
        self._qjs_funcs["gf_fsmJustEntered"] = ir.Function(m, ir.FunctionType(i1, [f64]), name="tsuchi_gf_fsmJustEntered")

        # Pool
        self._qjs_funcs["gf_poolAlloc"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_poolAlloc")
        self._qjs_funcs["gf_poolFree"] = ir.Function(m, ir.FunctionType(void, [f64, f64]), name="tsuchi_gf_poolFree")
        self._qjs_funcs["gf_poolActive"] = ir.Function(m, ir.FunctionType(i1, [f64, f64]), name="tsuchi_gf_poolActive")
        self._qjs_funcs["gf_poolCount"] = ir.Function(m, ir.FunctionType(f64, [f64]), name="tsuchi_gf_poolCount")
        self._qjs_funcs["gf_poolClear"] = ir.Function(m, ir.FunctionType(void, [f64]), name="tsuchi_gf_poolClear")

    def _ffi_mono_to_llvm(self, t):
        """Convert MonoType to LLVM type for FFI declarations."""
        from tsuchi.type_checker.types import (
            NumberType, BooleanType, StringType, VoidType,
            FFIStructType, OpaquePointerType,
        )
        if isinstance(t, NumberType):
            return ir.DoubleType()
        elif isinstance(t, BooleanType):
            return ir.IntType(32)
        elif isinstance(t, StringType):
            return ir.PointerType(ir.IntType(8))
        elif isinstance(t, VoidType):
            return ir.VoidType()
        elif isinstance(t, FFIStructType):
            field_types = [self._ffi_mono_to_llvm(ft) for ft in t.fields.values()]
            return ir.LiteralStructType(field_types)
        elif isinstance(t, OpaquePointerType):
            return ir.PointerType(ir.IntType(8))
        return ir.DoubleType()  # fallback

    def _declare_ffi_functions(self, hir_module: HIRModule):
        """Declare user FFI functions as extern C in LLVM IR."""
        if hir_module.ffi_info is None:
            return
        m = self._module
        i8p = ir.PointerType(ir.IntType(8))

        # Declare plain FFI functions (skip Class.method / Class#method keys)
        for name, ffi_fn in hir_module.ffi_info.functions.items():
            if "." in name or "#" in name:
                continue
            llvm_param_types = [self._ffi_mono_to_llvm(pt) for pt in ffi_fn.param_types]
            llvm_ret_type = self._ffi_mono_to_llvm(ffi_fn.return_type)
            key = f"ffi_{ffi_fn.c_name}"
            existing = m.globals.get(ffi_fn.c_name)
            if existing is not None:
                self._qjs_funcs[key] = existing
            else:
                self._qjs_funcs[key] = ir.Function(
                    m, ir.FunctionType(llvm_ret_type, llvm_param_types),
                    name=ffi_fn.c_name)

        # Declare opaque class methods
        for oc in hir_module.ffi_info.opaque_classes.values():
            for mfn in oc.static_methods.values():
                llvm_params = [self._ffi_mono_to_llvm(pt) for pt in mfn.param_types]
                llvm_ret = self._ffi_mono_to_llvm(mfn.return_type)
                key = f"ffi_{mfn.c_name}"
                existing = m.globals.get(mfn.c_name)
                if existing is not None:
                    self._qjs_funcs[key] = existing
                else:
                    self._qjs_funcs[key] = ir.Function(
                        m, ir.FunctionType(llvm_ret, llvm_params),
                        name=mfn.c_name)
            for mfn in oc.instance_methods.values():
                # Instance methods take opaque ptr (i8*) as first arg
                llvm_params = [i8p] + [self._ffi_mono_to_llvm(pt) for pt in mfn.param_types]
                llvm_ret = self._ffi_mono_to_llvm(mfn.return_type)
                key = f"ffi_{mfn.c_name}"
                existing = m.globals.get(mfn.c_name)
                if existing is not None:
                    self._qjs_funcs[key] = existing
                else:
                    self._qjs_funcs[key] = ir.Function(
                        m, ir.FunctionType(llvm_ret, llvm_params),
                        name=mfn.c_name)

    def _declare_array_runtime(self):
        """Declare C runtime functions for array operations."""
        m = self._module
        i8p = ir.PointerType(ir.IntType(8))  # TsuchiArray*
        f64 = ir.DoubleType()
        i32 = ir.IntType(32)

        # TsuchiArray* tsuchi_array_new(int capacity)
        self._qjs_funcs["tsuchi_array_new"] = ir.Function(
            m, ir.FunctionType(i8p, [i32]), name="tsuchi_array_new"
        )
        # void tsuchi_array_set(TsuchiArray* arr, int index, double value)
        self._qjs_funcs["tsuchi_array_set"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p, i32, f64]), name="tsuchi_array_set"
        )
        # double tsuchi_array_get(TsuchiArray* arr, int index)
        self._qjs_funcs["tsuchi_array_get"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, i32]), name="tsuchi_array_get"
        )
        # double tsuchi_array_push(TsuchiArray* arr, double value)
        self._qjs_funcs["tsuchi_array_push"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, f64]), name="tsuchi_array_push"
        )
        # int tsuchi_array_len(TsuchiArray* arr)
        self._qjs_funcs["tsuchi_array_len"] = ir.Function(
            m, ir.FunctionType(i32, [i8p]), name="tsuchi_array_len"
        )
        # double tsuchi_array_indexOf(TsuchiArray* arr, double value)
        self._qjs_funcs["tsuchi_array_indexOf"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, f64]), name="tsuchi_array_indexOf"
        )
        # double tsuchi_array_lastIndexOf(TsuchiArray* arr, double value)
        self._qjs_funcs["tsuchi_array_lastIndexOf"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, f64]), name="tsuchi_array_lastIndexOf"
        )
        # double tsuchi_array_includes(TsuchiArray* arr, double value)
        self._qjs_funcs["tsuchi_array_includes"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, f64]), name="tsuchi_array_includes"
        )
        # TsuchiArray* tsuchi_array_slice(TsuchiArray* arr, int start, int end)
        self._qjs_funcs["tsuchi_array_slice"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i32, i32]), name="tsuchi_array_slice"
        )
        # TsuchiArray* tsuchi_array_concat(TsuchiArray* a, TsuchiArray* b)
        self._qjs_funcs["tsuchi_array_concat"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_array_concat"
        )
        # void tsuchi_array_reverse(TsuchiArray* arr)
        self._qjs_funcs["tsuchi_array_reverse"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p]), name="tsuchi_array_reverse"
        )
        # void tsuchi_array_fill(TsuchiArray* arr, double val)
        self._qjs_funcs["tsuchi_array_fill"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p, f64]), name="tsuchi_array_fill"
        )
        # double tsuchi_array_pop(TsuchiArray* arr)
        self._qjs_funcs["tsuchi_array_pop"] = ir.Function(
            m, ir.FunctionType(f64, [i8p]), name="tsuchi_array_pop"
        )
        # double tsuchi_array_shift(TsuchiArray* arr)
        self._qjs_funcs["tsuchi_array_shift"] = ir.Function(
            m, ir.FunctionType(f64, [i8p]), name="tsuchi_array_shift"
        )
        # double tsuchi_array_unshift(TsuchiArray* arr, double val)
        self._qjs_funcs["tsuchi_array_unshift"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, f64]), name="tsuchi_array_unshift"
        )
        # TsuchiArray* tsuchi_array_splice(TsuchiArray* arr, int start, int deleteCount)
        self._qjs_funcs["tsuchi_array_splice"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i32, i32]), name="tsuchi_array_splice"
        )
        # double tsuchi_array_at(TsuchiArray* arr, int index)
        self._qjs_funcs["tsuchi_array_at"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, i32]), name="tsuchi_array_at"
        )
        # void tsuchi_array_print(TsuchiArray* arr)
        self._qjs_funcs["tsuchi_array_print"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p]), name="tsuchi_array_print"
        )
        # char* tsuchi_array_join(TsuchiArray* arr, const char* sep)
        self._qjs_funcs["tsuchi_array_join"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_array_join"
        )
        # String array functions — reuse TsuchiArray* (both double and char* are 8 bytes)
        # void tsuchi_sarray_set(TsuchiArray* arr, int index, const char* value)
        self._qjs_funcs["tsuchi_sarray_set"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p, i32, i8p]), name="tsuchi_sarray_set"
        )
        # const char* tsuchi_sarray_get(TsuchiArray* arr, int index)
        self._qjs_funcs["tsuchi_sarray_get"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i32]), name="tsuchi_sarray_get"
        )
        # double tsuchi_sarray_push(TsuchiArray* arr, const char* value)
        self._qjs_funcs["tsuchi_sarray_push"] = ir.Function(
            m, ir.FunctionType(f64, [i8p, i8p]), name="tsuchi_sarray_push"
        )
        # void tsuchi_sarray_print(TsuchiArray* arr)
        self._qjs_funcs["tsuchi_sarray_print"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p]), name="tsuchi_sarray_print"
        )
        # char* tsuchi_sarray_join(TsuchiArray* arr, const char* sep)
        self._qjs_funcs["tsuchi_sarray_join"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_sarray_join"
        )
        # TsuchiArray* tsuchi_str_split(const char* s, const char* sep)
        self._qjs_funcs["tsuchi_str_split"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p, i8p]), name="tsuchi_str_split"
        )
        # TsuchiArray* tsuchi_str_to_char_array(const char* s)
        self._qjs_funcs["tsuchi_str_to_char_array"] = ir.Function(
            m, ir.FunctionType(i8p, [i8p]), name="tsuchi_str_to_char_array"
        )
        # double tsuchi_parseInt(const char* str)
        self._qjs_funcs["tsuchi_parseInt"] = ir.Function(
            m, ir.FunctionType(f64, [i8p]), name="tsuchi_parseInt"
        )
        # double tsuchi_parseFloat(const char* str)
        self._qjs_funcs["tsuchi_parseFloat"] = ir.Function(
            m, ir.FunctionType(f64, [i8p]), name="tsuchi_parseFloat"
        )
        # void tsuchi_throw(const char* msg)
        self._qjs_funcs["tsuchi_throw"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p]), name="tsuchi_throw"
        )
        # void tsuchi_try_push(jmp_buf*) — push jmp_buf pointer
        self._qjs_funcs["tsuchi_try_push"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), [i8p]), name="tsuchi_try_push"
        )
        # void tsuchi_try_pop(void) — pop jmp_buf
        self._qjs_funcs["tsuchi_try_pop"] = ir.Function(
            m, ir.FunctionType(ir.VoidType(), []), name="tsuchi_try_pop"
        )
        # const char* tsuchi_get_error_msg(void) — get last error message
        self._qjs_funcs["tsuchi_get_error_msg"] = ir.Function(
            m, ir.FunctionType(i8p, []), name="tsuchi_get_error_msg"
        )
        # int setjmp(jmp_buf) — called directly from LLVM IR
        setjmp_fn = ir.Function(
            m, ir.FunctionType(i32, [i8p]), name="setjmp"
        )
        setjmp_fn.attributes.add("returns_twice")
        self._qjs_funcs["setjmp"] = setjmp_fn

    def _declare_printf(self):
        """Declare printf for console.log implementation."""
        m = self._module
        i8p = ir.PointerType(ir.IntType(8))
        i32 = ir.IntType(32)

        printf_ty = ir.FunctionType(i32, [i8p], var_arg=True)
        self._qjs_funcs["printf"] = ir.Function(m, printf_ty, name="printf")

        # Declare putchar for newline
        putchar_ty = ir.FunctionType(i32, [i32])
        self._qjs_funcs["putchar"] = ir.Function(m, putchar_ty, name="putchar")

        # Declare exit for process.exit()
        exit_ty = ir.FunctionType(ir.VoidType(), [i32])
        self._qjs_funcs["exit"] = ir.Function(m, exit_ty, name="exit")

    def _resolve_class_type(self, ct: ClassType) -> ClassType:
        """Look up the resolved ClassType with fully-inferred fields."""
        return self._resolved_classes.get(ct.name, ct)

    def _declare_native_func(self, hir_func: HIRFunction):
        """Declare _tsuchi_<name> — register in module without generating body."""
        param_types = []

        # Lifted arrows (closures and non-closures) get i8* env as first param
        has_env = hir_func.name.startswith("__anon_")
        if has_env:
            param_types.append(ir.PointerType(ir.IntType(8)))  # i8* env

        for p in hir_func.params:
            if isinstance(p.type, ClassType):
                # Class 'this' param: pass as pointer to struct (use resolved type)
                resolved = self._resolve_class_type(p.type)
                param_types.append(ir.PointerType(_get_struct_type(resolved.instance_type())))
            elif isinstance(p.type, ObjectType):
                param_types.append(_get_struct_type(p.type))
            else:
                param_types.append(_llvm_type(p.type))
        rt = hir_func.return_type
        if isinstance(rt, ClassType):
            rt = self._resolve_class_type(rt).instance_type()
        if isinstance(rt, ObjectType):
            ret_type = _get_struct_type(rt)
        else:
            ret_type = _llvm_type(hir_func.return_type)

        func_type = ir.FunctionType(ret_type, param_types)
        func_name = f"_tsuchi_{hir_func.name}"
        func = ir.Function(self._module, func_type, name=func_name)
        # Add nounwind unless function uses try/catch (setjmp/longjmp)
        has_try = any(
            isinstance(instr, HIRTryCatch)
            for bb in hir_func.blocks
            for instr in bb.instructions
        )
        if not has_try:
            func.attributes.add("nounwind")
        self._native_funcs[hir_func.name] = func

    @staticmethod
    def _compute_str_owned_candidates(hir_func: HIRFunction) -> set[str]:
        """Find SSA variables safe for tsuchi_str_concat_owned (in-place append).

        A variable is safe for owned concat if it has no aliasing risk:
        - Phi results (loop accumulators): safe because the phi always gets the
          returned pointer, so realloc is transparent to post-loop uses.
        - Variables with exactly 1 non-phi use: no aliasing possible.
        """
        phi_results: set[str] = set()
        use_counts: dict[str, int] = {}

        def _use(name: str | None):
            if name:
                use_counts[name] = use_counts.get(name, 0) + 1

        for bb in hir_func.blocks:
            for instr in bb.instructions:
                if isinstance(instr, HIRPhi):
                    phi_results.add(instr.result)
                    continue  # Phi incoming values don't count as uses
                if isinstance(instr, HIRBinaryOp):
                    _use(instr.left); _use(instr.right)
                elif isinstance(instr, HIRUnaryOp):
                    _use(instr.operand)
                elif isinstance(instr, HIRCompare):
                    _use(instr.left); _use(instr.right)
                elif isinstance(instr, HIRCall):
                    for a in instr.args: _use(a)
                elif isinstance(instr, HIRReturn):
                    _use(instr.value)
                elif isinstance(instr, HIRBranch):
                    _use(instr.condition)
                elif isinstance(instr, HIRAssign):
                    _use(instr.source)
                elif isinstance(instr, HIRFieldGet):
                    _use(instr.obj)
                elif isinstance(instr, HIRFieldSet):
                    _use(instr.obj); _use(instr.value)
                elif isinstance(instr, HIRAllocArray):
                    for e in instr.elements: _use(e)
                elif isinstance(instr, HIRArrayGet):
                    _use(instr.array); _use(instr.index)
                elif isinstance(instr, HIRArraySet):
                    _use(instr.array); _use(instr.index); _use(instr.value)
                elif isinstance(instr, HIRArrayPush):
                    _use(instr.array); _use(instr.value)
                elif isinstance(instr, HIRArrayLen):
                    _use(instr.array)
                elif isinstance(instr, HIRIndirectCall):
                    _use(instr.callee)
                    for a in instr.args: _use(a)
                elif isinstance(instr, HIRMakeClosure):
                    for c in instr.captures: _use(c)
                elif isinstance(instr, HIRStoreCapture):
                    _use(instr.value)
                elif isinstance(instr, (HIRArrayForEach, HIRArrayMap, HIRArrayFilter,
                                        HIRArrayReduce, HIRArrayReduceRight,
                                        HIRArrayFind, HIRArrayFindIndex,
                                        HIRArraySome, HIRArrayEvery, HIRArraySort)):
                    _use(instr.array); _use(instr.callback)
                    if hasattr(instr, 'initial'): _use(instr.initial)
            term = bb.terminator
            if term:
                if isinstance(term, HIRReturn):
                    _use(term.value)
                elif isinstance(term, HIRBranch):
                    _use(term.condition)

        # Safe candidates: phi results OR single-use variables
        candidates = set(phi_results)
        for var, count in use_counts.items():
            if count == 1:
                candidates.add(var)
        return candidates

    def _generate_native_func(self, hir_func: HIRFunction):
        """Generate _tsuchi_<name> — unboxed native computation."""
        func = self._native_funcs[hir_func.name]
        self._func = func
        self._ssa_values = {}
        self._blocks = {}  # HIR label → LLVM entry block (for jump targets)
        self._exit_blocks = {}  # HIR label → LLVM exit block (for phi incoming edges)
        self._deferred_phis = []
        self._ptr_obj_types = {}
        self._str_owned_ok = self._compute_str_owned_candidates(hir_func)

        # Create LLVM blocks
        for bb in hir_func.blocks:
            llvm_block = func.append_basic_block(name=bb.label)
            self._blocks[bb.label] = llvm_block
            self._exit_blocks[bb.label] = llvm_block

        # Generate each block
        for bb in hir_func.blocks:
            self._builder = ir.IRBuilder(self._blocks[bb.label])
            self._generate_block(bb, hir_func)

        # Wire deferred phi nodes (use exit blocks for incoming edges)
        for phi_instr, incoming_list in self._deferred_phis:
            for val_name, block_label in incoming_list:
                if val_name in self._ssa_values and block_label in self._exit_blocks:
                    phi_instr.add_incoming(
                        self._ssa_values[val_name],
                        self._exit_blocks[block_label]
                    )

    def _generate_block(self, bb: BasicBlock, hir_func: HIRFunction):
        """Generate LLVM IR for a single basic block."""
        # Inject catch parameter (error message) at the start of catch blocks
        if hasattr(self, '_deferred_catch_params') and bb.label in self._deferred_catch_params:
            catch_param = self._deferred_catch_params.pop(bb.label)
            fn = self._qjs_funcs["tsuchi_get_error_msg"]
            result = self._builder.call(fn, [], name=catch_param)
            self._ssa_values[catch_param] = result

        for instr in bb.instructions:
            try:
                self._generate_instruction(instr, hir_func)
            except Exception as e:
                instr_type = type(instr).__name__
                raise RuntimeError(
                    f"LLVM codegen error in function '{hir_func.name}', "
                    f"block '{bb.label}', instruction {instr_type}: {e}"
                ) from e
            # If the instruction changed LLVM blocks (e.g., array reduce/map/filter
            # created inline loops), update the exit block mapping so phi incoming
            # edges from subsequent HIR blocks resolve to the correct LLVM block.
            if self._builder.block != self._exit_blocks.get(bb.label):
                self._exit_blocks[bb.label] = self._builder.block

        if bb.terminator:
            self._generate_terminator(bb.terminator)
        elif not self._builder.block.is_terminated:
            # Implicit void return
            if isinstance(hir_func.return_type, VoidType):
                self._builder.ret_void()
            else:
                self._builder.ret(self._default_value(hir_func.return_type))

    def _generate_instruction(self, instr, hir_func: HIRFunction):
        if isinstance(instr, HIRConst):
            self._generate_const(instr)
        elif isinstance(instr, HIRParam):
            self._generate_param(instr, hir_func)
        elif isinstance(instr, HIRBinaryOp):
            self._generate_binary_op(instr)
        elif isinstance(instr, HIRUnaryOp):
            self._generate_unary_op(instr)
        elif isinstance(instr, HIRCompare):
            self._generate_compare(instr)
        elif isinstance(instr, HIRCall):
            self._generate_call(instr)
        elif isinstance(instr, HIRAssign):
            if instr.value in self._ssa_values:
                self._ssa_values[instr.target] = self._ssa_values[instr.value]
        elif isinstance(instr, HIRPhi):
            self._generate_phi(instr)
        elif isinstance(instr, HIRAllocObj):
            self._generate_alloc_obj(instr)
        elif isinstance(instr, HIRFieldGet):
            self._generate_field_get(instr)
        elif isinstance(instr, HIRFieldSet):
            self._generate_field_set(instr)
        elif isinstance(instr, HIRAllocArray):
            self._generate_alloc_array(instr)
        elif isinstance(instr, HIRArrayGet):
            self._generate_array_get(instr)
        elif isinstance(instr, HIRArraySet):
            self._generate_array_set(instr)
        elif isinstance(instr, HIRArrayPush):
            self._generate_array_push(instr)
        elif isinstance(instr, HIRArrayLen):
            self._generate_array_len(instr)
        elif isinstance(instr, HIRFuncRef):
            self._generate_func_ref(instr)
        elif isinstance(instr, HIRIndirectCall):
            self._generate_indirect_call(instr)
        elif isinstance(instr, HIRMakeClosure):
            self._generate_make_closure(instr)
        elif isinstance(instr, HIRLoadCapture):
            self._generate_load_capture(instr)
        elif isinstance(instr, HIRStoreCapture):
            self._generate_store_capture(instr)
        elif isinstance(instr, HIRArrayForEach):
            self._generate_array_foreach(instr)
        elif isinstance(instr, HIRArrayMap):
            self._generate_array_map(instr)
        elif isinstance(instr, HIRArrayFilter):
            self._generate_array_filter(instr)
        elif isinstance(instr, HIRArrayReduce):
            self._generate_array_reduce(instr)
        elif isinstance(instr, HIRArrayReduceRight):
            self._generate_array_reduce_right(instr)
        elif isinstance(instr, HIRArrayFind):
            self._generate_array_find(instr)
        elif isinstance(instr, HIRArrayFindIndex):
            self._generate_array_find_index(instr)
        elif isinstance(instr, HIRArraySome):
            self._generate_array_some(instr)
        elif isinstance(instr, HIRArrayEvery):
            self._generate_array_every(instr)
        elif isinstance(instr, HIRArraySort):
            self._generate_array_sort(instr)
        elif isinstance(instr, HIRTryCatch):
            self._generate_try_catch(instr)
        elif isinstance(instr, HIRFFIStructCreate):
            self._generate_ffi_struct_create(instr)
        elif isinstance(instr, HIRFFIStructFieldGet):
            self._generate_ffi_struct_field_get(instr)
        elif isinstance(instr, HIRLoadGlobal):
            self._generate_load_global(instr)
        elif isinstance(instr, HIRStoreGlobal):
            self._generate_store_global(instr)

    def _generate_load_global(self, instr: HIRLoadGlobal):
        gvar = self._llvm_globals.get(instr.name)
        if gvar:
            val = self._builder.load(gvar, name=instr.result)
            self._ssa_values[instr.result] = val
        else:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)

    def _generate_store_global(self, instr: HIRStoreGlobal):
        gvar = self._llvm_globals.get(instr.name)
        if gvar:
            val = self._ssa_values.get(instr.value)
            if val is not None:
                if val.type != gvar.type.pointee:
                    val = self._ensure_f64(val)
                self._builder.store(val, gvar)

    def _generate_const(self, instr: HIRConst):
        if isinstance(instr.type, NumberType):
            val = float(instr.value) if instr.value is not None else 0.0
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), val)
        elif isinstance(instr.type, BooleanType):
            val = bool(instr.value) if instr.value is not None else False
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), int(val))
        elif isinstance(instr.type, StringType):
            if isinstance(instr.value, str):
                # Create global string constant
                encoded = (instr.value + "\0").encode("utf-8")
                str_type = ir.ArrayType(ir.IntType(8), len(encoded))
                str_global = ir.GlobalVariable(self._module, str_type,
                                                name=f".str.{len(self._module.global_values)}")
                str_global.linkage = "private"
                str_global.global_constant = True
                str_global.initializer = ir.Constant(str_type, bytearray(encoded))
                ptr = self._builder.bitcast(str_global, ir.PointerType(ir.IntType(8)))
                self._ssa_values[instr.result] = ptr
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.PointerType(ir.IntType(8)),
                                                              ir.Constant(ir.IntType(64), 0))
        else:
            # Default: f64 zero
            val = float(instr.value) if instr.value is not None and isinstance(instr.value, (int, float)) else 0.0
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), val)

    def _generate_param(self, instr: HIRParam, hir_func: HIRFunction):
        # For lifted arrows, arg[0] is env — user params start at offset 1
        param_offset = 1 if hir_func.name.startswith("__anon_") else 0
        # Find param index
        for i, p in enumerate(hir_func.params):
            if p.result == instr.result:
                if isinstance(p.type, ClassType):
                    # Class 'this' param: already a pointer, use directly
                    ptr = self._func.args[i + param_offset]
                    self._ssa_values[instr.result] = ptr
                    resolved = self._resolve_class_type(p.type)
                    self._ptr_obj_types[id(ptr)] = resolved.instance_type()
                elif isinstance(p.type, ObjectType):
                    # By-value struct param; store to alloca for GEP access
                    struct_ty = _get_struct_type(p.type)
                    ptr = self._builder.alloca(struct_ty, name=f"{instr.result}.ptr")
                    self._builder.store(self._func.args[i + param_offset], ptr)
                    self._ssa_values[instr.result] = ptr
                    self._ptr_obj_types[id(ptr)] = p.type
                else:
                    val = self._func.args[i + param_offset]
                    self._ssa_values[instr.result] = val
                    if isinstance(p.type, ArrayType):
                        self._ptr_arr_types[id(val)] = p.type
                return

    def _generate_binary_op(self, instr: HIRBinaryOp):
        left = self._ssa_values.get(instr.left)
        right = self._ssa_values.get(instr.right)
        if left is None or right is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Ensure both are f64 for number operations
        if isinstance(instr.type, NumberType):
            left = self._ensure_f64(left)
            right = self._ensure_f64(right)

            if instr.op == "add":
                result = self._builder.fadd(left, right, name=instr.result)
            elif instr.op == "sub":
                result = self._builder.fsub(left, right, name=instr.result)
            elif instr.op == "mul":
                result = self._builder.fmul(left, right, name=instr.result)
            elif instr.op == "div":
                result = self._builder.fdiv(left, right, name=instr.result)
            elif instr.op == "mod":
                result = self._builder.frem(left, right, name=instr.result)
            elif instr.op == "pow":
                # Use llvm.pow.f64 intrinsic
                pow_func = self._get_or_declare_intrinsic("llvm.pow.f64",
                    ir.FunctionType(ir.DoubleType(), [ir.DoubleType(), ir.DoubleType()]))
                result = self._builder.call(pow_func, [left, right], name=instr.result)
            elif instr.op in ("bit_and", "bit_or", "bit_xor", "shl", "shr", "ushr"):
                # Bitwise: f64 → i32, op, i32 → f64
                i32 = ir.IntType(32)
                l_i32 = self._builder.fptosi(left, i32)
                r_i32 = self._builder.fptosi(right, i32)
                if instr.op == "bit_and":
                    res_i32 = self._builder.and_(l_i32, r_i32)
                elif instr.op == "bit_or":
                    res_i32 = self._builder.or_(l_i32, r_i32)
                elif instr.op == "bit_xor":
                    res_i32 = self._builder.xor(l_i32, r_i32)
                elif instr.op == "shl":
                    res_i32 = self._builder.shl(l_i32, r_i32)
                elif instr.op == "shr":
                    res_i32 = self._builder.ashr(l_i32, r_i32)
                elif instr.op == "ushr":
                    # Unsigned right shift: use lshr and convert via unsigned
                    u32 = ir.IntType(32)
                    res_i32 = self._builder.lshr(l_i32, r_i32)
                    # Convert to unsigned: zero-extend to i64, then sitofp
                    res_i64 = self._builder.zext(res_i32, ir.IntType(64))
                    result = self._builder.sitofp(res_i64, ir.DoubleType(), name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
                else:
                    res_i32 = l_i32
                result = self._builder.sitofp(res_i32, ir.DoubleType(), name=instr.result)
            else:
                result = ir.Constant(ir.DoubleType(), 0.0)

            self._ssa_values[instr.result] = result
        elif isinstance(instr.type, StringType) and instr.op == "add":
            # String concatenation — use owned (in-place) variant when left operand
            # is safe (phi result or single-use), enabling amortized O(1) string building
            if instr.left in self._str_owned_ok:
                concat_fn = self._qjs_funcs["tsuchi_str_concat_owned"]
            else:
                concat_fn = self._qjs_funcs["tsuchi_str_concat"]
            result = self._builder.call(concat_fn, [left, right], name=instr.result)
            self._ssa_values[instr.result] = result
        else:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)

    def _generate_unary_op(self, instr: HIRUnaryOp):
        operand = self._ssa_values.get(instr.operand)
        if operand is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        if instr.op == "neg" and isinstance(instr.type, NumberType):
            operand = self._ensure_f64(operand)
            result = self._builder.fsub(
                ir.Constant(ir.DoubleType(), 0.0), operand, name=instr.result
            )
        elif instr.op == "not":
            if operand.type == ir.IntType(1):
                result = self._builder.not_(operand, name=instr.result)
            elif operand.type == ir.PointerType(ir.IntType(8)):
                # string → !str means empty string check (strlen == 0)
                strlen_fn = self._qjs_funcs.get("strlen")
                if strlen_fn:
                    slen = self._builder.call(strlen_fn, [operand])
                    result = self._builder.icmp_signed("==", slen, ir.Constant(ir.IntType(64), 0), name=instr.result)
                else:
                    null = ir.Constant(operand.type, None)
                    result = self._builder.icmp_unsigned("==", operand, null, name=instr.result)
            else:
                # number → bool → not
                zero = ir.Constant(ir.DoubleType(), 0.0)
                cmp = self._builder.fcmp_ordered("==", self._ensure_f64(operand), zero)
                result = cmp
        elif instr.op == "pos" and isinstance(instr.type, NumberType):
            result = self._ensure_f64(operand)
        elif instr.op == "bit_not" and isinstance(instr.type, NumberType):
            # ~x: f64 → i32, NOT, i32 → f64
            operand = self._ensure_f64(operand)
            i32 = ir.IntType(32)
            val_i32 = self._builder.fptosi(operand, i32)
            not_i32 = self._builder.not_(val_i32)
            result = self._builder.sitofp(not_i32, ir.DoubleType(), name=instr.result)
        else:
            result = operand

        self._ssa_values[instr.result] = result

    def _generate_compare(self, instr: HIRCompare):
        left = self._ssa_values.get(instr.left)
        right = self._ssa_values.get(instr.right)
        if left is None or right is None:
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        # String comparison: use strcmp
        if isinstance(instr.operand_type, StringType):
            strcmp_fn = self._get_or_declare_strcmp()
            cmp_result = self._builder.call(strcmp_fn, [left, right], name=f"{instr.result}_cmp")
            zero = ir.Constant(ir.IntType(32), 0)
            if instr.op == "eq":
                result = self._builder.icmp_signed("==", cmp_result, zero, name=instr.result)
            elif instr.op == "ne":
                result = self._builder.icmp_signed("!=", cmp_result, zero, name=instr.result)
            elif instr.op == "lt":
                result = self._builder.icmp_signed("<", cmp_result, zero, name=instr.result)
            elif instr.op == "gt":
                result = self._builder.icmp_signed(">", cmp_result, zero, name=instr.result)
            elif instr.op == "le":
                result = self._builder.icmp_signed("<=", cmp_result, zero, name=instr.result)
            elif instr.op == "ge":
                result = self._builder.icmp_signed(">=", cmp_result, zero, name=instr.result)
            else:
                result = self._builder.icmp_signed("==", cmp_result, zero, name=instr.result)
            self._ssa_values[instr.result] = result
            return

        # Numeric comparison: use fcmp
        left = self._ensure_f64(left)
        right = self._ensure_f64(right)

        cmp_map = {
            "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
            "eq": "==", "ne": "!=",
        }
        op = cmp_map.get(instr.op, "==")
        result = self._builder.fcmp_ordered(op, left, right, name=instr.result)
        self._ssa_values[instr.result] = result

    def _generate_call(self, instr: HIRCall):
        # Handle console.log / console.error / console.warn
        if instr.func_name in ("__tsuchi_console_log", "__tsuchi_console_error", "__tsuchi_console_warn"):
            self._generate_console_log(instr, stderr=instr.func_name != "__tsuchi_console_log")
            return

        # Handle process.exit(code)
        if instr.func_name == "__tsuchi_process_exit":
            exit_fn = self._qjs_funcs.get("exit")
            if exit_fn and instr.args:
                arg = self._ssa_values.get(instr.args[0])
                if arg is not None:
                    arg = self._ensure_f64(arg)
                    code_i32 = self._builder.fptosi(arg, ir.IntType(32))
                    self._builder.call(exit_fn, [code_i32])
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Handle process.argv
        if instr.func_name == "__tsuchi_process_argv":
            c_fn = self._qjs_funcs.get("tsuchi_process_argv")
            if c_fn:
                result = self._builder.call(c_fn, [], name=instr.result)
                self._ssa_values[instr.result] = result
                if isinstance(instr.type, ArrayType):
                    self._ptr_arr_types[id(result)] = instr.type
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.PointerType(ir.IntType(8)), None)
            return

        # Handle readFile(path)
        if instr.func_name == "__tsuchi_readFile" and instr.args:
            c_fn = self._qjs_funcs.get("tsuchi_readFile")
            arg = self._ssa_values.get(instr.args[0])
            if c_fn and arg is not None:
                result = self._builder.call(c_fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # Handle writeFile(path, content)
        if instr.func_name == "__tsuchi_writeFile" and len(instr.args) >= 2:
            c_fn = self._qjs_funcs.get("tsuchi_writeFile")
            arg0 = self._ssa_values.get(instr.args[0])
            arg1 = self._ssa_values.get(instr.args[1])
            if c_fn and arg0 is not None and arg1 is not None:
                self._builder.call(c_fn, [arg0, arg1])
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Handle process.env.VARNAME → getenv
        if instr.func_name == "__tsuchi_getenv" and instr.args:
            c_fn = self._qjs_funcs.get("tsuchi_getenv")
            arg = self._ssa_values.get(instr.args[0])
            if c_fn and arg is not None:
                result = self._builder.call(c_fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # Handle exec(cmd) → string
        if instr.func_name == "__tsuchi_exec" and instr.args:
            c_fn = self._qjs_funcs.get("tsuchi_exec")
            arg = self._ssa_values.get(instr.args[0])
            if c_fn and arg is not None:
                result = self._builder.call(c_fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # Handle httpGet(url) → string
        if instr.func_name == "__tsuchi_httpGet" and instr.args:
            c_fn = self._qjs_funcs.get("tsuchi_httpGet")
            arg = self._ssa_values.get(instr.args[0])
            if c_fn and arg is not None:
                result = self._builder.call(c_fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # Handle httpPost(url, body, contentType?) → string
        if instr.func_name == "__tsuchi_httpPost" and len(instr.args) >= 2:
            c_fn = self._qjs_funcs.get("tsuchi_httpPost")
            arg0 = self._ssa_values.get(instr.args[0])
            arg1 = self._ssa_values.get(instr.args[1])
            if len(instr.args) >= 3:
                arg2 = self._ssa_values.get(instr.args[2])
            else:
                arg2 = self._make_global_string("application/json")
            if c_fn and arg0 is not None and arg1 is not None and arg2 is not None:
                result = self._builder.call(c_fn, [arg0, arg1, arg2], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # Handle FFI calls (__tsuchi_ffi_*)
        if instr.func_name.startswith("__tsuchi_ffi_"):
            c_name = instr.func_name[len("__tsuchi_ffi_"):]
            c_key = f"ffi_{c_name}"
            c_fn = self._qjs_funcs.get(c_key)
            if c_fn:
                c_args = []
                c_param_types = list(c_fn.function_type.args)
                raw_args = [self._ssa_values.get(a) for a in instr.args]
                for i, (param_ty, arg_val) in enumerate(zip(c_param_types, raw_args)):
                    if arg_val is None:
                        c_args.append(ir.Constant(param_ty, ir.Undefined))
                        continue
                    # Struct types (LiteralStructType) pass through directly
                    if isinstance(param_ty, ir.LiteralStructType):
                        c_args.append(arg_val)
                        continue
                    arg_val = self._ensure_f64(arg_val) if not isinstance(arg_val.type, ir.PointerType) else arg_val
                    if isinstance(param_ty, ir.IntType) and param_ty.width == 32:
                        i64_val = self._builder.fptosi(arg_val, ir.IntType(64))
                        c_args.append(self._builder.trunc(i64_val, ir.IntType(32)))
                    elif isinstance(param_ty, ir.DoubleType):
                        c_args.append(arg_val)
                    elif isinstance(param_ty, ir.PointerType):
                        c_args.append(arg_val)
                    else:
                        c_args.append(arg_val)

                ret_ty = c_fn.function_type.return_type
                if isinstance(ret_ty, ir.VoidType):
                    self._builder.call(c_fn, c_args)
                    self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
                elif isinstance(ret_ty, ir.IntType) and ret_ty.width == 32:
                    result = self._builder.call(c_fn, c_args, name=instr.result + "_i32")
                    result = self._builder.sitofp(result, ir.DoubleType(), name=instr.result)
                    self._ssa_values[instr.result] = result
                elif isinstance(ret_ty, ir.PointerType):
                    result = self._builder.call(c_fn, c_args, name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    # Handles DoubleType, LiteralStructType, etc.
                    result = self._builder.call(c_fn, c_args, name=instr.result)
                    self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Handle Clay calls (__tsuchi_clay_*), Raylib calls (__tsuchi_rl_*), UI calls (__tsuchi_ui_*), and Game Framework calls (__tsuchi_gf_*)
        if instr.func_name.startswith(("__tsuchi_clay_", "__tsuchi_rl_", "__tsuchi_ui_", "__tsuchi_gf_", "__tsuchi_path_", "__tsuchi_fs_", "__tsuchi_os_")):
            c_key = instr.func_name[len("__tsuchi_"):]
            c_fn = self._qjs_funcs.get(c_key)
            if c_fn:
                c_args = []
                c_param_types = list(c_fn.function_type.args)
                raw_args = [self._ssa_values.get(a) for a in instr.args]
                for i, (param_ty, arg_val) in enumerate(zip(c_param_types, raw_args)):
                    if arg_val is None:
                        c_args.append(ir.Constant(param_ty, 0))
                        continue
                    arg_val = self._ensure_f64(arg_val) if not isinstance(arg_val.type, ir.PointerType) else arg_val
                    if isinstance(param_ty, ir.IntType) and param_ty.width == 32:
                        # Use i64 intermediate to handle packed RGBA colors (> INT32_MAX)
                        i64_val = self._builder.fptosi(arg_val, ir.IntType(64))
                        c_args.append(self._builder.trunc(i64_val, ir.IntType(32)))
                    elif isinstance(param_ty, ir.DoubleType):
                        c_args.append(arg_val)
                    elif isinstance(param_ty, ir.PointerType):
                        c_args.append(arg_val)
                    else:
                        c_args.append(arg_val)

                ret_ty = c_fn.function_type.return_type
                if isinstance(ret_ty, ir.VoidType):
                    self._builder.call(c_fn, c_args)
                    self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
                elif isinstance(ret_ty, ir.IntType) and ret_ty.width == 1:
                    result = self._builder.call(c_fn, c_args, name=instr.result)
                    self._ssa_values[instr.result] = result
                elif isinstance(ret_ty, ir.IntType) and ret_ty.width == 32:
                    result = self._builder.call(c_fn, c_args, name=instr.result + "_i32")
                    result = self._builder.sitofp(result, ir.DoubleType(), name=instr.result)
                    self._ssa_values[instr.result] = result
                elif isinstance(ret_ty, ir.DoubleType):
                    result = self._builder.call(c_fn, c_args, name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    result = self._builder.call(c_fn, c_args, name=instr.result)
                    self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Handle toString conversions
        if instr.func_name == "__tsuchi_num_to_str" and len(instr.args) == 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                fn = self._qjs_funcs["tsuchi_num_to_str"]
                result = self._builder.call(fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        if instr.func_name == "__tsuchi_bool_to_str" and len(instr.args) == 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                if arg.type != ir.IntType(1):
                    arg = ir.Constant(ir.IntType(1), 0)
                fn = self._qjs_funcs["tsuchi_bool_to_str"]
                result = self._builder.call(fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # Math built-in functions: __tsuchi_Math_floor → C floor(), etc.
        _MATH_FUNC_MAP = {
            "__tsuchi_Math_floor": "floor",
            "__tsuchi_Math_ceil": "ceil",
            "__tsuchi_Math_abs": "fabs",
            "__tsuchi_Math_sqrt": "sqrt",
            "__tsuchi_Math_round": "round",
            "__tsuchi_Math_trunc": "trunc",
            "__tsuchi_Math_log": "log",
            "__tsuchi_Math_exp": "exp",
            "__tsuchi_Math_sin": "sin",
            "__tsuchi_Math_cos": "cos",
            "__tsuchi_Math_tan": "tan",
            "__tsuchi_Math_min": "fmin",
            "__tsuchi_Math_max": "fmax",
            "__tsuchi_Math_pow": "pow",
            "__tsuchi_Math_log2": "log2",
            "__tsuchi_Math_log10": "log10",
            "__tsuchi_Math_hypot": "hypot",
            "__tsuchi_Math_clz32": "tsuchi_math_clz32",
            "__tsuchi_Math_random": "tsuchi_math_random",
        }
        if instr.func_name in _MATH_FUNC_MAP:
            c_name = _MATH_FUNC_MAP[instr.func_name]
            c_fn = self._qjs_funcs.get(c_name)
            if c_fn:
                args = []
                for arg_name in instr.args:
                    arg_val = self._ssa_values.get(arg_name)
                    if arg_val is None:
                        arg_val = ir.Constant(ir.DoubleType(), 0.0)
                    args.append(self._ensure_f64(arg_val))
                result = self._builder.call(c_fn, args, name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Math.sign: (val > 0) - (val < 0) as f64
        if instr.func_name == "__tsuchi_Math_sign" and len(instr.args) == 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                zero = ir.Constant(ir.DoubleType(), 0.0)
                gt = self._builder.fcmp_ordered(">", arg, zero)
                lt = self._builder.fcmp_ordered("<", arg, zero)
                gt_f64 = self._builder.uitofp(gt, ir.DoubleType())
                lt_f64 = self._builder.uitofp(lt, ir.DoubleType())
                result = self._builder.fsub(gt_f64, lt_f64, name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Number.isInteger(x) → fmod(x, 1.0) == 0.0
        if instr.func_name == "__tsuchi_Number_isInteger" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                one = ir.Constant(ir.DoubleType(), 1.0)
                fmod_val = self._builder.frem(arg, one)
                zero = ir.Constant(ir.DoubleType(), 0.0)
                # Also check that it's not NaN or Infinity: arg == arg and fmod == 0
                is_not_nan = self._builder.fcmp_ordered("ord", arg, arg)
                is_int = self._builder.fcmp_ordered("==", fmod_val, zero)
                result = self._builder.and_(is_not_nan, is_int, name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        # Number.isFinite(x) → not NaN and not Infinity
        if instr.func_name == "__tsuchi_Number_isFinite" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                import math
                pos_inf = ir.Constant(ir.DoubleType(), math.inf)
                neg_inf = ir.Constant(ir.DoubleType(), -math.inf)
                is_not_nan = self._builder.fcmp_ordered("ord", arg, arg)
                is_not_pos_inf = self._builder.fcmp_ordered("!=", arg, pos_inf)
                is_not_neg_inf = self._builder.fcmp_ordered("!=", arg, neg_inf)
                t1 = self._builder.and_(is_not_nan, is_not_pos_inf)
                result = self._builder.and_(t1, is_not_neg_inf, name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        # Number.isNaN(x) → x != x
        if instr.func_name == "__tsuchi_Number_isNaN" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                result = self._builder.fcmp_unordered("uno", arg, arg, name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        # Number.parseInt(str) / Number.parseFloat(str) → tsuchi_parseInt/parseFloat
        if instr.func_name in ("__tsuchi_Number_parseInt", "__tsuchi_Number_parseFloat"):
            c_name = "tsuchi_parseInt" if "parseInt" in instr.func_name else "tsuchi_parseFloat"
            c_fn = self._qjs_funcs.get(c_name)
            if c_fn and len(instr.args) >= 1:
                arg = self._ssa_values.get(instr.args[0])
                if arg is not None:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Date.now() → tsuchi_date_now()
        if instr.func_name == "__tsuchi_Date_now":
            c_fn = self._qjs_funcs.get("tsuchi_date_now")
            if c_fn:
                result = self._builder.call(c_fn, [], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Built-in global functions: parseInt, parseFloat, Number, String, Boolean, isNaN
        if instr.func_name == "__tsuchi_parseInt" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                c_fn = self._qjs_funcs.get("tsuchi_parseInt")
                if c_fn:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        if instr.func_name == "__tsuchi_parseFloat" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                c_fn = self._qjs_funcs.get("tsuchi_parseFloat")
                if c_fn:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        if instr.func_name == "__tsuchi_Number" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                # If already f64, pass through; if string, convert
                if arg.type == ir.DoubleType():
                    self._ssa_values[instr.result] = arg
                elif arg.type == ir.IntType(1):
                    result = self._builder.uitofp(arg, ir.DoubleType(), name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    # String → number via C
                    c_fn = self._qjs_funcs.get("tsuchi_parseFloat")
                    if c_fn:
                        result = self._builder.call(c_fn, [arg], name=instr.result)
                        self._ssa_values[instr.result] = result
                    else:
                        self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        if instr.func_name == "__tsuchi_String" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                if arg.type == ir.DoubleType():
                    fn = self._qjs_funcs["tsuchi_num_to_str"]
                    result = self._builder.call(fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                elif arg.type == ir.IntType(1):
                    fn = self._qjs_funcs["tsuchi_bool_to_str"]
                    result = self._builder.call(fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    # Already a string
                    self._ssa_values[instr.result] = arg
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        if instr.func_name == "__tsuchi_Boolean" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                if arg.type == ir.IntType(1):
                    self._ssa_values[instr.result] = arg
                elif arg.type == ir.DoubleType():
                    # 0 and NaN → false, else → true
                    zero = ir.Constant(ir.DoubleType(), 0.0)
                    result = self._builder.fcmp_ordered("!=", arg, zero, name=instr.result)
                    self._ssa_values[instr.result] = result
                else:
                    # Non-empty string → true
                    self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 1)
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        if instr.func_name == "__tsuchi_isNaN" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                # NaN != NaN is true
                result = self._builder.fcmp_unordered("uno", arg, arg, name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        # String.fromCharCode(code) → single-char string
        if instr.func_name == "__tsuchi_String_fromCharCode" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                arg = self._ensure_f64(arg)
                c_fn = self._qjs_funcs["tsuchi_fromCharCode"]
                result = self._builder.call(c_fn, [arg], name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # String .length: __tsuchi_strlen → strlen + sitofp
        if instr.func_name == "__tsuchi_strlen" and len(instr.args) == 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                strlen_fn = self._qjs_funcs["strlen"]
                len_i64 = self._builder.call(strlen_fn, [arg], name=f"{instr.result}_i64")
                result = self._builder.sitofp(len_i64, ir.DoubleType(), name=instr.result)
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # JSON.stringify — dispatch based on argument type
        if instr.func_name == "__tsuchi_json_stringify" and len(instr.args) >= 1:
            arg_val = self._ssa_values.get(instr.args[0])
            if arg_val is not None:
                i8p = ir.PointerType(ir.IntType(8))
                if arg_val.type == ir.DoubleType():
                    c_fn = self._qjs_funcs["tsuchi_json_stringify"]
                    result = self._builder.call(c_fn, [arg_val], name=instr.result)
                elif arg_val.type == i8p:
                    c_fn = self._qjs_funcs["tsuchi_json_stringify_str"]
                    result = self._builder.call(c_fn, [arg_val], name=instr.result)
                elif arg_val.type == ir.IntType(1):
                    c_fn = self._qjs_funcs["tsuchi_json_stringify_bool"]
                    result = self._builder.call(c_fn, [arg_val], name=instr.result)
                else:
                    result = self._default_value(StringType())
                self._ssa_values[instr.result] = result
            else:
                self._ssa_values[instr.result] = self._default_value(StringType())
            return

        # JSON.parse — dispatch based on variant name
        if instr.func_name == "__tsuchi_json_parse_num":
            c_fn = self._qjs_funcs.get("tsuchi_json_parse_num")
            if c_fn and instr.args:
                arg = self._ssa_values.get(instr.args[0])
                if arg is not None:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = self._default_value(NumberType())
            return

        if instr.func_name == "__tsuchi_json_parse_str":
            c_fn = self._qjs_funcs.get("tsuchi_json_parse_str")
            if c_fn and instr.args:
                arg = self._ssa_values.get(instr.args[0])
                if arg is not None:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = self._default_value(StringType())
            return

        if instr.func_name == "__tsuchi_json_parse_bool":
            c_fn = self._qjs_funcs.get("tsuchi_json_parse_bool")
            if c_fn and instr.args:
                arg = self._ssa_values.get(instr.args[0])
                if arg is not None:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        # String methods: __tsuchi_str_* → C runtime calls
        _STR_METHOD_MAP = {
            "__tsuchi_str_indexOf": "tsuchi_str_indexOf",
            "__tsuchi_str_lastIndexOf": "tsuchi_str_lastIndexOf",
            "__tsuchi_str_includes": "tsuchi_str_includes",
            "__tsuchi_str_slice": "tsuchi_str_slice",
            "__tsuchi_str_charAt": "tsuchi_str_charAt",
            "__tsuchi_str_toUpperCase": "tsuchi_str_toUpperCase",
            "__tsuchi_str_toLowerCase": "tsuchi_str_toLowerCase",
            "__tsuchi_str_trim": "tsuchi_str_trim",
            "__tsuchi_str_trimStart": "tsuchi_str_trimStart",
            "__tsuchi_str_trimEnd": "tsuchi_str_trimEnd",
            "__tsuchi_str_startsWith": "tsuchi_str_startsWith",
            "__tsuchi_str_endsWith": "tsuchi_str_endsWith",
            "__tsuchi_str_replace": "tsuchi_str_replace",
            "__tsuchi_str_replaceAll": "tsuchi_str_replaceAll",
            "__tsuchi_str_repeat": "tsuchi_str_repeat",
            "__tsuchi_str_substring": "tsuchi_str_substring",
            "__tsuchi_str_padStart": "tsuchi_str_padStart",
            "__tsuchi_str_padEnd": "tsuchi_str_padEnd",
            "__tsuchi_str_split": "tsuchi_str_split",
            "__tsuchi_str_charCodeAt": "tsuchi_str_charCodeAt",
            "__tsuchi_str_at": "tsuchi_str_at",
            "__tsuchi_num_toString": "tsuchi_num_toString",
            "__tsuchi_num_toFixed": "tsuchi_num_toFixed",
        }
        if instr.func_name in _STR_METHOD_MAP:
            c_name = _STR_METHOD_MAP[instr.func_name]
            c_fn = self._qjs_funcs.get(c_name)
            if c_fn:
                args = []
                expected_types = list(c_fn.function_type.args)
                for i, arg_name in enumerate(instr.args):
                    arg_val = self._ssa_values.get(arg_name)
                    if arg_val is None:
                        # Provide default based on expected type
                        if i < len(expected_types) and expected_types[i] == ir.DoubleType():
                            arg_val = ir.Constant(ir.DoubleType(), 0.0)
                        else:
                            arg_val = self._default_value(StringType())
                    # Cast to expected type if needed
                    if i < len(expected_types):
                        exp = expected_types[i]
                        if exp == ir.DoubleType() and arg_val.type != ir.DoubleType():
                            arg_val = self._ensure_f64(arg_val)
                    args.append(arg_val)
                # Pad missing args with defaults (e.g., slice(start) → slice(start, Infinity))
                import math
                while len(args) < len(expected_types):
                    exp = expected_types[len(args)]
                    if exp == ir.DoubleType():
                        args.append(ir.Constant(ir.DoubleType(), math.inf))
                    elif exp == ir.PointerType(ir.IntType(8)):
                        args.append(self._default_value(StringType()))
                    else:
                        args.append(ir.Constant(exp, 0))
                result = self._builder.call(c_fn, args, name=instr.result)
                self._ssa_values[instr.result] = result
                # Track array return types (e.g., split returns string[])
                if isinstance(instr.type, ArrayType):
                    self._ptr_arr_types[id(result)] = instr.type
            else:
                self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        # Array.from(string) → string[]
        if instr.func_name == "tsuchi_str_to_char_array":
            c_fn = self._qjs_funcs.get("tsuchi_str_to_char_array")
            if c_fn and len(instr.args) == 1:
                arg = self._ssa_values.get(instr.args[0])
                if arg is not None:
                    result = self._builder.call(c_fn, [arg], name=instr.result)
                    self._ssa_values[instr.result] = result
                    if isinstance(instr.type, ArrayType):
                        self._ptr_arr_types[id(result)] = instr.type
                else:
                    self._ssa_values[instr.result] = self._default_value(instr.type)
            else:
                self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        # Array runtime methods
        if instr.func_name == "tsuchi_array_slice":
            c_fn = self._qjs_funcs.get("tsuchi_array_slice")
            if c_fn and len(instr.args) >= 2:
                arr = self._ssa_values.get(instr.args[0])
                start_f64 = self._ssa_values.get(instr.args[1])
                if arr is not None and start_f64 is not None:
                    start_f64 = self._ensure_f64(start_f64)
                    start_i32 = self._builder.fptosi(start_f64, ir.IntType(32))
                    if len(instr.args) > 2:
                        end_f64 = self._ssa_values.get(instr.args[2])
                        if end_f64 is not None:
                            end_f64 = self._ensure_f64(end_f64)
                            end_i32 = self._builder.fptosi(end_f64, ir.IntType(32))
                        else:
                            # Default end = array length
                            len_fn = self._qjs_funcs["tsuchi_array_len"]
                            end_i32 = self._builder.call(len_fn, [arr])
                    else:
                        len_fn = self._qjs_funcs["tsuchi_array_len"]
                        end_i32 = self._builder.call(len_fn, [arr])
                    result = self._builder.call(c_fn, [arr, start_i32, end_i32], name=instr.result)
                    self._ssa_values[instr.result] = result
                    if isinstance(instr.type, ArrayType):
                        self._ptr_arr_types[id(result)] = instr.type
                else:
                    self._ssa_values[instr.result] = self._default_value(instr.type)
            else:
                self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_concat":
            c_fn = self._qjs_funcs.get("tsuchi_array_concat")
            if c_fn and len(instr.args) == 2:
                a = self._ssa_values.get(instr.args[0])
                b = self._ssa_values.get(instr.args[1])
                if a is not None and b is not None:
                    result = self._builder.call(c_fn, [a, b], name=instr.result)
                    self._ssa_values[instr.result] = result
                    if isinstance(instr.type, ArrayType):
                        self._ptr_arr_types[id(result)] = instr.type
                else:
                    self._ssa_values[instr.result] = self._default_value(instr.type)
            else:
                self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_reverse":
            c_fn = self._qjs_funcs.get("tsuchi_array_reverse")
            if c_fn and len(instr.args) == 1:
                arr = self._ssa_values.get(instr.args[0])
                if arr is not None:
                    self._builder.call(c_fn, [arr])
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        if instr.func_name == "tsuchi_array_fill":
            c_fn = self._qjs_funcs.get("tsuchi_array_fill")
            if c_fn and len(instr.args) == 2:
                arr = self._ssa_values.get(instr.args[0])
                val = self._ssa_values.get(instr.args[1])
                if arr is not None and val is not None:
                    val = self._ensure_f64(val)
                    self._builder.call(c_fn, [arr, val])
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        if instr.func_name == "tsuchi_array_pop":
            c_fn = self._qjs_funcs.get("tsuchi_array_pop")
            if c_fn and len(instr.args) == 1:
                arr = self._ssa_values.get(instr.args[0])
                if arr is not None:
                    result = self._builder.call(c_fn, [arr], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_shift":
            c_fn = self._qjs_funcs.get("tsuchi_array_shift")
            if c_fn and len(instr.args) == 1:
                arr = self._ssa_values.get(instr.args[0])
                if arr is not None:
                    result = self._builder.call(c_fn, [arr], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_unshift":
            c_fn = self._qjs_funcs.get("tsuchi_array_unshift")
            if c_fn and len(instr.args) == 2:
                arr = self._ssa_values.get(instr.args[0])
                val = self._ssa_values.get(instr.args[1])
                if arr is not None and val is not None:
                    val = self._ensure_f64(val)
                    result = self._builder.call(c_fn, [arr, val], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_splice":
            c_fn = self._qjs_funcs.get("tsuchi_array_splice")
            if c_fn and len(instr.args) == 3:
                arr = self._ssa_values.get(instr.args[0])
                start = self._ssa_values.get(instr.args[1])
                del_count = self._ssa_values.get(instr.args[2])
                if arr is not None and start is not None and del_count is not None:
                    i32 = ir.IntType(32)
                    start_i32 = self._builder.fptosi(self._ensure_f64(start), i32)
                    del_i32 = self._builder.fptosi(self._ensure_f64(del_count), i32)
                    result = self._builder.call(c_fn, [arr, start_i32, del_i32], name=instr.result)
                    self._ssa_values[instr.result] = result
                    if isinstance(instr.type, ArrayType):
                        self._ptr_arr_types[id(result)] = instr.type
                    return
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_at":
            c_fn = self._qjs_funcs.get("tsuchi_array_at")
            if c_fn and len(instr.args) == 2:
                arr = self._ssa_values.get(instr.args[0])
                idx = self._ssa_values.get(instr.args[1])
                if arr is not None and idx is not None:
                    i32 = ir.IntType(32)
                    idx_i32 = self._builder.fptosi(self._ensure_f64(idx), i32)
                    result = self._builder.call(c_fn, [arr, idx_i32], name=instr.result)
                    self._ssa_values[instr.result] = result
                    return
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name == "tsuchi_array_join":
            if len(instr.args) == 2:
                arr = self._ssa_values.get(instr.args[0])
                sep = self._ssa_values.get(instr.args[1])
                if arr is not None and sep is not None:
                    # Use string array join if element type is string
                    arr_type = self._ptr_arr_types.get(id(arr))
                    is_str = arr_type and isinstance(arr_type.element_type, StringType)
                    fn_name = "tsuchi_sarray_join" if is_str else "tsuchi_array_join"
                    c_fn = self._qjs_funcs.get(fn_name)
                    if c_fn:
                        result = self._builder.call(c_fn, [arr, sep], name=instr.result)
                        self._ssa_values[instr.result] = result
                    else:
                        self._ssa_values[instr.result] = self._default_value(instr.type)
                else:
                    self._ssa_values[instr.result] = self._default_value(instr.type)
            else:
                self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        if instr.func_name in ("tsuchi_array_indexOf", "tsuchi_array_includes", "tsuchi_array_lastIndexOf"):
            c_fn = self._qjs_funcs.get(instr.func_name)
            if c_fn and len(instr.args) == 2:
                arr = self._ssa_values.get(instr.args[0])
                val = self._ssa_values.get(instr.args[1])
                if arr is not None and val is not None:
                    val = self._ensure_f64(val)
                    result = self._builder.call(c_fn, [arr, val], name=instr.result)
                    if instr.func_name == "tsuchi_array_includes":
                        # Convert f64 (1.0/0.0) → i1 for boolean
                        result = self._builder.fcmp_ordered(
                            "!=", result, ir.Constant(ir.DoubleType(), 0.0),
                            name=f"{instr.result}_bool"
                        )
                    self._ssa_values[instr.result] = result
                else:
                    self._ssa_values[instr.result] = self._default_value(instr.type)
            else:
                self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        # throw statement: __tsuchi_throw → tsuchi_throw(const char* msg)
        if instr.func_name == "__tsuchi_throw" and len(instr.args) >= 1:
            arg = self._ssa_values.get(instr.args[0])
            if arg is not None:
                fn = self._qjs_funcs["tsuchi_throw"]
                self._builder.call(fn, [arg])
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # try/catch runtime calls (emitted from HIR builder within blocks)
        if instr.func_name == "__tsuchi_try_pop":
            fn = self._qjs_funcs["tsuchi_try_pop"]
            self._builder.call(fn, [])
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return

        # Look up native function
        if instr.func_name in self._native_funcs:
            callee = self._native_funcs[instr.func_name]
            args = []
            # For __anon_ functions called directly, prepend null env pointer
            param_offset = 0
            i8p = ir.PointerType(ir.IntType(8))
            if (instr.func_name.startswith("__anon_")
                    and len(callee.function_type.args) > 0
                    and callee.function_type.args[0] == i8p):
                args.append(ir.Constant(i8p, None))
                param_offset = 1
            for i, arg_name in enumerate(instr.args):
                arg_val = self._ssa_values.get(arg_name)
                if arg_val is None:
                    arg_val = ir.Constant(ir.DoubleType(), 0.0)
                # Cast to expected param type
                expected = callee.function_type.args[i + param_offset] if (i + param_offset) < len(callee.function_type.args) else ir.DoubleType()
                # ObjectType: load struct from pointer for by-value passing
                if (isinstance(expected, ir.LiteralStructType)
                        and isinstance(arg_val.type, ir.PointerType)
                        and isinstance(arg_val.type.pointee, ir.LiteralStructType)):
                    arg_val = self._builder.load(arg_val)
                else:
                    arg_val = self._cast_to(arg_val, expected)
                args.append(arg_val)
            result = self._builder.call(callee, args, name=instr.result)
            # ObjectType/ClassType return: store by-value struct to alloca for pointer access
            ret_obj_type = self._resolve_class_type(instr.type).instance_type() if isinstance(instr.type, ClassType) else instr.type
            if isinstance(ret_obj_type, ObjectType):
                struct_ty = _get_struct_type(ret_obj_type)
                ptr = self._builder.alloca(struct_ty, name=f"{instr.result}.ptr")
                self._builder.store(result, ptr)
                self._ssa_values[instr.result] = ptr
                self._ptr_obj_types[id(ptr)] = ret_obj_type
            else:
                self._ssa_values[instr.result] = result
                # Track ArrayType returns for console.log array printing
                if isinstance(instr.type, ArrayType):
                    self._ptr_arr_types[id(result)] = instr.type
        elif instr.func_name in self._fallback_bridges:
            # Call fallback bridge function (QuickJS-backed)
            callee = self._fallback_bridges[instr.func_name]
            args = []
            for i, arg_name in enumerate(instr.args):
                arg_val = self._ssa_values.get(arg_name)
                if arg_val is None:
                    arg_val = ir.Constant(ir.DoubleType(), 0.0)
                expected = callee.function_type.args[i] if i < len(callee.function_type.args) else ir.DoubleType()
                arg_val = self._cast_to(arg_val, expected)
                args.append(arg_val)
            result = self._builder.call(callee, args, name=instr.result)
            self._ssa_values[instr.result] = result
        else:
            # Unknown function — default to 0.0
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)

    def _generate_console_log(self, instr: HIRCall, stderr: bool = False):
        """Generate code for console.log/error/warn — prints arguments to stdout."""
        printf_func = self._qjs_funcs.get("printf")
        putchar_func = self._qjs_funcs.get("putchar")

        for i, arg_name in enumerate(instr.args):
            val = self._ssa_values.get(arg_name)
            if val is None:
                continue

            if i > 0 and printf_func:
                # Print space between args
                space_fmt = self._make_global_str(" ")
                self._builder.call(printf_func, [space_fmt])

            if val.type == ir.DoubleType() and printf_func:
                # Check for NaN and Infinity first (fcmp_unordered detects NaN)
                is_nan = self._builder.fcmp_unordered("uno", val, val, name="is_nan")
                nan_block = self._func.append_basic_block("log_nan")
                not_nan_block = self._func.append_basic_block("log_not_nan")
                merge_block = self._func.append_basic_block("log_merge")

                self._builder.cbranch(is_nan, nan_block, not_nan_block)

                # NaN path
                self._builder = ir.IRBuilder(nan_block)
                nan_str = self._make_global_str("NaN")
                self._builder.call(printf_func, [nan_str])
                self._builder.branch(merge_block)

                # Not NaN: check for Infinity
                self._builder = ir.IRBuilder(not_nan_block)
                import math
                pos_inf = ir.Constant(ir.DoubleType(), math.inf)
                neg_inf = ir.Constant(ir.DoubleType(), -math.inf)
                is_pos_inf = self._builder.fcmp_ordered("==", val, pos_inf, name="is_pos_inf")
                is_neg_inf = self._builder.fcmp_ordered("==", val, neg_inf, name="is_neg_inf")

                pos_inf_block = self._func.append_basic_block("log_pos_inf")
                neg_inf_block = self._func.append_basic_block("log_neg_inf")
                normal_block = self._func.append_basic_block("log_normal")
                inf_check_block = self._func.append_basic_block("log_inf_check")

                self._builder.cbranch(is_pos_inf, pos_inf_block, inf_check_block)

                self._builder = ir.IRBuilder(pos_inf_block)
                inf_str = self._make_global_str("Infinity")
                self._builder.call(printf_func, [inf_str])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(inf_check_block)
                self._builder.cbranch(is_neg_inf, neg_inf_block, normal_block)

                self._builder = ir.IRBuilder(neg_inf_block)
                neg_inf_str = self._make_global_str("-Infinity")
                self._builder.call(printf_func, [neg_inf_str])
                self._builder.branch(merge_block)

                # Normal number: check if integer
                self._builder = ir.IRBuilder(normal_block)
                one = ir.Constant(ir.DoubleType(), 1.0)
                fmod_val = self._builder.frem(val, one)
                zero = ir.Constant(ir.DoubleType(), 0.0)
                is_int = self._builder.fcmp_ordered("==", fmod_val, zero)

                int_block = self._func.append_basic_block("log_int")
                float_block = self._func.append_basic_block("log_float")

                self._builder.cbranch(is_int, int_block, float_block)

                # Integer path: print as %d (cast to i64)
                self._builder = ir.IRBuilder(int_block)
                int_fmt = self._make_global_str("%lld")
                int_val = self._builder.fptosi(val, ir.IntType(64))
                self._builder.call(printf_func, [int_fmt, int_val])
                self._builder.branch(merge_block)

                # Float path: print as %g
                self._builder = ir.IRBuilder(float_block)
                float_fmt = self._make_global_str("%g")
                self._builder.call(printf_func, [float_fmt, val])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(merge_block)

            elif val.type == ir.IntType(1) and printf_func:
                # Boolean: print "true" or "false"
                true_block = self._func.append_basic_block("log_true")
                false_block = self._func.append_basic_block("log_false")
                merge_block = self._func.append_basic_block("log_bool_merge")

                self._builder.cbranch(val, true_block, false_block)

                self._builder = ir.IRBuilder(true_block)
                true_str = self._make_global_str("true")
                self._builder.call(printf_func, [true_str])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(false_block)
                false_str = self._make_global_str("false")
                self._builder.call(printf_func, [false_str])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(merge_block)

            elif val.type == ir.PointerType(ir.IntType(8)) and printf_func:
                # Check if this is an array (also i8*)
                arr_type = self._ptr_arr_types.get(id(val))
                if arr_type is not None:
                    self._generate_console_log_array(val)
                else:
                    # String
                    str_fmt = self._make_global_str("%s")
                    self._builder.call(printf_func, [str_fmt, val])

            elif (isinstance(val.type, ir.PointerType)
                  and isinstance(val.type.pointee, ir.LiteralStructType)
                  and printf_func):
                # Object — print as { field: value, ... }
                obj_type = self._ptr_obj_types.get(id(val))
                if obj_type is not None:
                    self._generate_console_log_object(val, obj_type)

        # Print newline
        if putchar_func:
            self._builder.call(putchar_func, [ir.Constant(ir.IntType(32), 10)])

        self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)

    def _generate_console_log_array(self, arr_ptr: ir.Value):
        """Print an array as [elem1, elem2, ...]."""
        arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_str = arr_type and isinstance(arr_type.element_type, StringType)
        fn_name = "tsuchi_sarray_print" if is_str else "tsuchi_array_print"
        print_fn = self._qjs_funcs.get(fn_name)
        if print_fn:
            self._builder.call(print_fn, [arr_ptr])

    def _generate_console_log_object(self, ptr: ir.Value, obj_type: ObjectType):
        """Print an object as { field: value, ... }."""
        printf_func = self._qjs_funcs.get("printf")
        if not printf_func:
            return

        open_fmt = self._make_global_str("{ ")
        self._builder.call(printf_func, [open_fmt])

        sorted_fields = sorted(obj_type.fields.items())
        for fi, (fname, ftype) in enumerate(sorted_fields):
            if fi > 0:
                sep_fmt = self._make_global_str(", ")
                self._builder.call(printf_func, [sep_fmt])

            name_fmt = self._make_global_str(f"{fname}: ")
            self._builder.call(printf_func, [name_fmt])

            idx = _field_index(obj_type, fname)
            i32 = ir.IntType(32)
            gep = self._builder.gep(ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)])
            val = self._builder.load(gep)

            if isinstance(ftype, NumberType):
                one = ir.Constant(ir.DoubleType(), 1.0)
                fmod_val = self._builder.frem(val, one)
                zero = ir.Constant(ir.DoubleType(), 0.0)
                is_int = self._builder.fcmp_ordered("==", fmod_val, zero)

                int_block = self._func.append_basic_block("obj_log_int")
                float_block = self._func.append_basic_block("obj_log_float")
                merge_block = self._func.append_basic_block("obj_log_merge")
                self._builder.cbranch(is_int, int_block, float_block)

                self._builder = ir.IRBuilder(int_block)
                int_fmt = self._make_global_str("%lld")
                int_val = self._builder.fptosi(val, ir.IntType(64))
                self._builder.call(printf_func, [int_fmt, int_val])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(float_block)
                float_fmt = self._make_global_str("%g")
                self._builder.call(printf_func, [float_fmt, val])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(merge_block)
            elif isinstance(ftype, BooleanType):
                true_block = self._func.append_basic_block("obj_log_true")
                false_block = self._func.append_basic_block("obj_log_false")
                merge_block = self._func.append_basic_block("obj_log_bool_merge")
                self._builder.cbranch(val, true_block, false_block)

                self._builder = ir.IRBuilder(true_block)
                self._builder.call(printf_func, [self._make_global_str("true")])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(false_block)
                self._builder.call(printf_func, [self._make_global_str("false")])
                self._builder.branch(merge_block)

                self._builder = ir.IRBuilder(merge_block)

        close_fmt = self._make_global_str(" }")
        self._builder.call(printf_func, [close_fmt])

    def _generate_alloc_obj(self, instr: HIRAllocObj):
        """Allocate an object struct on the heap (malloc)."""
        if not isinstance(instr.type, ObjectType):
            return
        struct_ty = _get_struct_type(instr.type)
        # Heap allocate so object pointers survive function returns
        i64 = ir.IntType(64)
        size = self._builder.gep(
            ir.Constant(ir.PointerType(struct_ty), None),
            [ir.Constant(ir.IntType(32), 1)],
        )
        size_int = self._builder.ptrtoint(size, i64)
        malloc_fn = self._get_or_declare_malloc()
        raw_ptr = self._builder.call(malloc_fn, [size_int], name=f"{instr.result}_raw")
        ptr = self._builder.bitcast(raw_ptr, ir.PointerType(struct_ty), name=instr.result)
        self._ssa_values[instr.result] = ptr
        self._ptr_obj_types[id(ptr)] = instr.type

    def _generate_field_get(self, instr: HIRFieldGet):
        """Read a field from an object struct via GEP + load."""
        obj_ptr = self._ssa_values.get(instr.obj)
        if obj_ptr is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        # Determine the struct type from the pointer
        obj_ptr_type = obj_ptr.type
        if not isinstance(obj_ptr_type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        struct_ty = obj_ptr_type.pointee
        # Find field index: we need the ObjectType — reconstruct from HIR
        # The field names in sorted order give us the index
        sorted_field_names = []
        if isinstance(struct_ty, ir.LiteralStructType):
            # We need to find the field index from the original ObjectType
            # Use the stored _ssa_obj_types mapping
            pass
        # We'll use the obj type from the instruction's parent context
        # For now, use field_name to find index from the struct
        # We track ObjectType → field order
        idx = self._get_field_index_from_ptr(obj_ptr, instr.field_name, instr.type)
        if idx is not None:
            i32 = ir.IntType(32)
            gep = self._builder.gep(obj_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)],
                                     name=f"{instr.result}_ptr")
            val = self._builder.load(gep, name=instr.result)
            self._ssa_values[instr.result] = val
            # Track ObjectType for nested object field access
            if isinstance(instr.type, ObjectType):
                self._ptr_obj_types[id(val)] = instr.type
        else:
            self._ssa_values[instr.result] = ir.Constant(_llvm_type(instr.type), 0)

    def _generate_field_set(self, instr: HIRFieldSet):
        """Write a field to an object struct via GEP + store."""
        obj_ptr = self._ssa_values.get(instr.obj)
        val = self._ssa_values.get(instr.value)
        if obj_ptr is None or val is None:
            return
        idx = self._get_field_index_from_ptr(obj_ptr, instr.field_name, instr.type)
        if idx is not None:
            i32 = ir.IntType(32)
            gep = self._builder.gep(obj_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)])
            target_type = _llvm_type(instr.type)
            val = self._cast_to(val, target_type)
            self._builder.store(val, gep)

    def _get_field_index_from_ptr(self, obj_ptr: ir.Value, field_name: str, field_type: MonoType) -> int | None:
        """Get field index from an object pointer by examining the struct type."""
        if not isinstance(obj_ptr.type, ir.PointerType):
            return None
        struct_ty = obj_ptr.type.pointee
        if not isinstance(struct_ty, ir.LiteralStructType):
            return None
        # Look up which ObjectType this struct corresponds to
        obj_type = self._ptr_obj_types.get(id(obj_ptr))
        if obj_type is None:
            return None
        return _field_index(obj_type, field_name) if field_name in obj_type.fields else None

    def _get_array_element(self, arr_ptr, idx_i32, name_prefix=""):
        """Get element from array with proper type conversion for object arrays."""
        arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_str = arr_type and isinstance(arr_type.element_type, StringType)
        is_obj = arr_type and isinstance(arr_type.element_type, (ObjectType, ClassType))
        get_fn = self._qjs_funcs["tsuchi_sarray_get" if is_str else "tsuchi_array_get"]
        elem = self._builder.call(get_fn, [arr_ptr, idx_i32], name=f"{name_prefix}elem")
        if is_obj:
            elem_type = arr_type.element_type
            resolved_et = elem_type
            if isinstance(elem_type, ClassType):
                resolved_et = self._resolve_class_type(elem_type).instance_type()
            struct_llvm_type = _get_struct_type(resolved_et) if isinstance(resolved_et, ObjectType) else _llvm_type(resolved_et)
            elem = self._double_to_ptr(elem, ir.PointerType(struct_llvm_type))
            if isinstance(resolved_et, ObjectType):
                self._ptr_obj_types[id(elem)] = resolved_et
        return elem

    def _is_string_array(self, arr_type: MonoType) -> bool:
        """Check if an array type holds strings."""
        return isinstance(arr_type, ArrayType) and isinstance(arr_type.element_type, StringType)

    def _is_object_array(self, arr_type: MonoType) -> bool:
        """Check if an array type holds objects/class instances (pointer-typed elements)."""
        if not isinstance(arr_type, ArrayType):
            return False
        et = arr_type.element_type
        return isinstance(et, (ObjectType, ClassType))

    def _ptr_to_double(self, ptr_val):
        """Convert a pointer to double for storage in TsuchiArray (pointer smuggling)."""
        i64 = ir.IntType(64)
        int_val = self._builder.ptrtoint(ptr_val, i64)
        return self._builder.bitcast(int_val, ir.DoubleType())

    def _double_to_ptr(self, dbl_val, ptr_type):
        """Convert a double back to a pointer retrieved from TsuchiArray."""
        i64 = ir.IntType(64)
        int_val = self._builder.bitcast(dbl_val, i64)
        return self._builder.inttoptr(int_val, ptr_type)

    def _generate_alloc_array(self, instr: HIRAllocArray):
        """Allocate array and populate with initial elements."""
        i32 = ir.IntType(32)
        n = len(instr.elements)
        cap = max(n, 4)  # minimum capacity of 4
        new_fn = self._qjs_funcs["tsuchi_array_new"]
        arr_ptr = self._builder.call(new_fn, [ir.Constant(i32, cap)], name=instr.result)
        self._ssa_values[instr.result] = arr_ptr
        if isinstance(instr.type, ArrayType):
            self._ptr_arr_types[id(arr_ptr)] = instr.type

        is_str = self._is_string_array(instr.type)
        is_obj = self._is_object_array(instr.type)
        set_fn = self._qjs_funcs["tsuchi_sarray_set" if is_str else "tsuchi_array_set"]
        for i, elem_ssa in enumerate(instr.elements):
            val = self._ssa_values.get(elem_ssa)
            if val is None:
                val = ir.Constant(ir.DoubleType(), 0.0) if not is_str else self._make_global_str("")
            if is_obj and val.type.is_pointer:
                # Object pointer → double for storage
                val = self._ptr_to_double(val)
            elif not is_str:
                val = self._ensure_f64(val)
            self._builder.call(set_fn, [arr_ptr, ir.Constant(i32, i), val])

    def _generate_array_get(self, instr: HIRArrayGet):
        """Read arr[index]."""
        arr_ptr = self._ssa_values.get(instr.array)
        index_val = self._ssa_values.get(instr.index)
        if arr_ptr is None or index_val is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        # Guard: if arr_ptr is not a pointer (e.g., double from unresolved
        # array method), return default instead of crashing.
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        index_val = self._ensure_f64(index_val)
        idx_i32 = self._builder.fptosi(index_val, ir.IntType(32))
        # Check element type from tracked array type
        arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_str = arr_type and isinstance(arr_type.element_type, StringType)
        is_obj = arr_type and isinstance(arr_type.element_type, (ObjectType, ClassType))
        get_fn = self._qjs_funcs["tsuchi_sarray_get" if is_str else "tsuchi_array_get"]
        result = self._builder.call(get_fn, [arr_ptr, idx_i32], name=instr.result)
        if is_obj:
            # Convert double back to object pointer
            elem_type = arr_type.element_type
            resolved_et = elem_type
            if isinstance(elem_type, ClassType):
                resolved_et = self._resolve_class_type(elem_type).instance_type()
            struct_llvm_type = _get_struct_type(resolved_et) if isinstance(resolved_et, ObjectType) else _llvm_type(resolved_et)
            result = self._double_to_ptr(result, ir.PointerType(struct_llvm_type))
            # Register ObjectType so field access works
            if isinstance(resolved_et, ObjectType):
                self._ptr_obj_types[id(result)] = resolved_et
        self._ssa_values[instr.result] = result

    def _generate_array_set(self, instr: HIRArraySet):
        """Write arr[index] = value."""
        arr_ptr = self._ssa_values.get(instr.array)
        index_val = self._ssa_values.get(instr.index)
        val = self._ssa_values.get(instr.value)
        if arr_ptr is None or index_val is None or val is None:
            return
        # Guard: if arr_ptr is not a pointer, skip the set.
        if not isinstance(arr_ptr.type, ir.PointerType):
            return
        index_val = self._ensure_f64(index_val)
        idx_i32 = self._builder.fptosi(index_val, ir.IntType(32))
        arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_str = arr_type and isinstance(arr_type.element_type, StringType)
        is_obj = arr_type and isinstance(arr_type.element_type, (ObjectType, ClassType))
        if is_obj and val.type.is_pointer:
            val = self._ptr_to_double(val)
        elif not is_str:
            val = self._ensure_f64(val)
        set_fn = self._qjs_funcs["tsuchi_sarray_set" if is_str else "tsuchi_array_set"]
        self._builder.call(set_fn, [arr_ptr, idx_i32, val])

    def _generate_array_push(self, instr: HIRArrayPush):
        """Push value to array, return new length as f64."""
        arr_ptr = self._ssa_values.get(instr.array)
        val = self._ssa_values.get(instr.value)
        if arr_ptr is None or val is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        # Guard: if arr_ptr is not a pointer, skip the push.
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_str = arr_type and isinstance(arr_type.element_type, StringType)
        is_obj = arr_type and isinstance(arr_type.element_type, (ObjectType, ClassType))
        if is_obj and val.type.is_pointer:
            val = self._ptr_to_double(val)
        elif not is_str:
            val = self._ensure_f64(val)
        push_fn = self._qjs_funcs["tsuchi_sarray_push" if is_str else "tsuchi_array_push"]
        result = self._builder.call(push_fn, [arr_ptr, val], name=instr.result)
        self._ssa_values[instr.result] = result

    def _generate_array_len(self, instr: HIRArrayLen):
        """Get array length as f64."""
        arr_ptr = self._ssa_values.get(instr.array)
        if arr_ptr is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        # Guard: if arr_ptr is not a pointer (e.g., double from an unresolved
        # array method like flat()), return 0 instead of crashing.
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        len_fn = self._qjs_funcs["tsuchi_array_len"]
        len_i32 = self._builder.call(len_fn, [arr_ptr], name=f"{instr.result}_i32")
        result = self._builder.sitofp(len_i32, ir.DoubleType(), name=instr.result)
        self._ssa_values[instr.result] = result

    def _generate_func_ref(self, instr: HIRFuncRef):
        """Emit a closure pair {fn_ptr, null_env} for a function reference."""
        i8p = ir.PointerType(ir.IntType(8))
        null_env = ir.Constant(i8p, None)

        if instr.func_name in self._native_funcs:
            func = self._native_funcs[instr.func_name]

            # Check if function already has env (i8*) as first param (closure with captures)
            has_env_param = (len(func.function_type.args) > 0
                            and func.function_type.args[0] == i8p)
            if has_env_param:
                # Lifted arrow already has env as first param — use directly
                fn_ptr = self._builder.bitcast(func, i8p)
            else:
                # Named function — create trampoline that accepts/ignores env
                tramp = self._get_or_create_trampoline(instr.func_name, func, instr.type)
                fn_ptr = self._builder.bitcast(tramp, i8p)

            # Create closure pair {fn_ptr, null}
            pair_type = ir.LiteralStructType([i8p, i8p])
            zero_pair = ir.Constant(pair_type, [null_env, null_env])
            pair1 = self._builder.insert_value(zero_pair, fn_ptr, 0, name=f"{instr.result}_p0")
            self._ssa_values[instr.result] = pair1
        else:
            pair_type = ir.LiteralStructType([i8p, i8p])
            self._ssa_values[instr.result] = ir.Constant(pair_type, [null_env, null_env])

    def _get_or_create_trampoline(self, func_name: str, orig_func: ir.Function, func_type) -> ir.Function:
        """Create a trampoline: ret tramp(i8* env, params...) that ignores env and calls the real function."""
        tramp_name = f"_tsuchi___tramp_{func_name}"
        if tramp_name in self._qjs_funcs:
            return self._qjs_funcs[tramp_name]

        i8p = ir.PointerType(ir.IntType(8))
        orig_param_types = list(orig_func.function_type.args)
        tramp_param_types = [i8p] + orig_param_types
        tramp_fn_type = ir.FunctionType(orig_func.function_type.return_type, tramp_param_types)

        tramp = ir.Function(self._module, tramp_fn_type, name=tramp_name)
        tramp.linkage = "internal"
        tramp.attributes.add("alwaysinline")
        tramp.attributes.add("nounwind")

        bb = tramp.append_basic_block("entry")
        builder = ir.IRBuilder(bb)

        # Forward call: skip env (arg 0), pass the rest
        args = [tramp.args[i + 1] for i in range(len(orig_param_types))]
        result = builder.call(orig_func, args)

        if isinstance(orig_func.function_type.return_type, ir.VoidType):
            builder.ret_void()
        else:
            builder.ret(result)

        self._qjs_funcs[tramp_name] = tramp
        return tramp

    def _generate_indirect_call(self, instr: HIRIndirectCall):
        """Emit an indirect call through a closure pair {fn_ptr, env_ptr}."""
        closure_pair = self._ssa_values.get(instr.callee)
        if closure_pair is None:
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        func_type = instr.func_type
        if not isinstance(func_type, FunctionType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        # Guard: if closure_pair is not a struct (e.g., double from unresolved
        # function expression), return default instead of crashing.
        if not isinstance(closure_pair.type, ir.LiteralStructType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        i8p = ir.PointerType(ir.IntType(8))

        # Extract fn_ptr and env_ptr from closure pair
        fn_ptr_raw = self._builder.extract_value(closure_pair, 0, name=f"{instr.result}_fn")
        env_ptr = self._builder.extract_value(closure_pair, 1, name=f"{instr.result}_env")

        # Build the expected function type: ret(i8* env, params...)
        param_llvm = [i8p] + [_llvm_type(pt) for pt in func_type.param_types]
        ret_llvm = _llvm_type(func_type.return_type)
        callee_fn_type = ir.FunctionType(ret_llvm, param_llvm)

        # Bitcast fn_ptr to the correct function type
        fn_ptr = self._builder.bitcast(fn_ptr_raw, ir.PointerType(callee_fn_type),
                                       name=f"{instr.result}_fptr")

        # Build args: env_ptr + user args
        args = [env_ptr]
        for i, arg_name in enumerate(instr.args):
            arg_val = self._ssa_values.get(arg_name)
            if arg_val is None:
                arg_val = ir.Constant(ir.DoubleType(), 0.0)
            if i < len(func_type.param_types):
                expected = _llvm_type(func_type.param_types[i])
                arg_val = self._cast_to(arg_val, expected)
            args.append(arg_val)

        result = self._builder.call(fn_ptr, args, name=instr.result)
        self._ssa_values[instr.result] = result

    def _generate_make_closure(self, instr: HIRMakeClosure):
        """Create a closure: allocate env struct, store captures, create pair."""
        i8p = ir.PointerType(ir.IntType(8))
        pair_type = ir.LiteralStructType([i8p, i8p])
        null = ir.Constant(i8p, None)

        func = self._native_funcs.get(instr.func_name)
        if func is None:
            self._ssa_values[instr.result] = ir.Constant(pair_type, [null, null])
            return

        fn_ptr = self._builder.bitcast(func, i8p)

        if instr.captures:
            # Build env struct type from capture types
            field_types = [_llvm_type(t) for t in instr.capture_types]
            env_struct_type = ir.LiteralStructType(field_types)

            # Allocate env on heap: malloc(sizeof(env_struct))
            i32 = ir.IntType(32)
            null_ptr = ir.Constant(ir.PointerType(env_struct_type), None)
            size_gep = self._builder.gep(null_ptr, [ir.Constant(i32, 1)],
                                         name=f"{instr.result}_sz")
            size = self._builder.ptrtoint(size_gep, ir.IntType(64))

            malloc_fn = self._get_or_declare_malloc()
            env_raw = self._builder.call(malloc_fn, [size], name=f"{instr.result}_eraw")
            env_ptr = self._builder.bitcast(env_raw, ir.PointerType(env_struct_type),
                                            name=f"{instr.result}_eptr")

            # Store captured values into env struct
            for i, (cap_ssa, cap_type) in enumerate(zip(instr.captures, instr.capture_types)):
                val = self._ssa_values.get(cap_ssa)
                if val is None:
                    val = ir.Constant(_llvm_type(cap_type), 0)
                val = self._cast_to(val, _llvm_type(cap_type))
                gep = self._builder.gep(env_ptr, [ir.Constant(i32, 0), ir.Constant(i32, i)])
                self._builder.store(val, gep)

            env_as_i8p = self._builder.bitcast(env_ptr, i8p)
        else:
            env_as_i8p = null

        # Create closure pair {fn_ptr, env_ptr}
        zero_pair = ir.Constant(pair_type, [null, null])
        pair1 = self._builder.insert_value(zero_pair, fn_ptr, 0, name=f"{instr.result}_p0")
        pair2 = self._builder.insert_value(pair1, env_as_i8p, 1, name=instr.result)
        self._ssa_values[instr.result] = pair2

    def _generate_load_capture(self, instr: HIRLoadCapture):
        """Load a captured variable from the env pointer (func.args[0])."""
        env_ptr_raw = self._func.args[0]  # i8* env is always first arg for closures

        # Build env struct type from capture types
        field_types = [_llvm_type(t) for t in instr.capture_types]
        env_struct_type = ir.LiteralStructType(field_types)

        # Bitcast env_ptr to env_struct*
        env_ptr = self._builder.bitcast(env_ptr_raw, ir.PointerType(env_struct_type),
                                        name=f"{instr.result}_env")

        # GEP to field at index
        i32 = ir.IntType(32)
        gep = self._builder.gep(env_ptr, [ir.Constant(i32, 0), ir.Constant(i32, instr.index)],
                                name=f"{instr.result}_ptr")

        # Load value
        val = self._builder.load(gep, name=instr.result)
        self._ssa_values[instr.result] = val

    def _generate_store_capture(self, instr):
        """Store a value back into the env pointer (mutable capture)."""
        env_ptr_raw = self._func.args[0]  # i8* env is always first arg for closures

        # Build env struct type from capture types
        field_types = [_llvm_type(t) for t in instr.capture_types]
        env_struct_type = ir.LiteralStructType(field_types)

        # Bitcast env_ptr to env_struct*
        env_ptr = self._builder.bitcast(env_ptr_raw, ir.PointerType(env_struct_type),
                                        name=f"{instr.value}_senv")

        # GEP to field at index
        i32 = ir.IntType(32)
        gep = self._builder.gep(env_ptr, [ir.Constant(i32, 0), ir.Constant(i32, instr.index)],
                                name=f"{instr.value}_sptr")

        # Store value
        val = self._ssa_values.get(instr.value)
        if val is not None:
            val = self._cast_to(val, _llvm_type(instr.type))
            self._builder.store(val, gep)

    def _get_or_declare_malloc(self) -> ir.Function:
        """Declare malloc(i64) -> i8*."""
        if "malloc" in self._qjs_funcs:
            return self._qjs_funcs["malloc"]
        i8p = ir.PointerType(ir.IntType(8))
        i64 = ir.IntType(64)
        malloc_type = ir.FunctionType(i8p, [i64])
        malloc_fn = ir.Function(self._module, malloc_type, name="malloc")
        self._qjs_funcs["malloc"] = malloc_fn
        return malloc_fn

    def _call_closure(self, closure_pair, cb_type: FunctionType, args: list):
        """Helper: extract fn/env from closure pair and call with env + args."""
        i8p = ir.PointerType(ir.IntType(8))

        # Guard: if closure_pair is not a struct (e.g., double from unresolved
        # function expression), return a default value instead of crashing.
        if not isinstance(closure_pair.type, ir.LiteralStructType):
            return ir.Constant(_llvm_type(cb_type.return_type), None) \
                if isinstance(_llvm_type(cb_type.return_type), ir.PointerType) \
                else ir.Constant(_llvm_type(cb_type.return_type), 0)

        fn_ptr_raw = self._builder.extract_value(closure_pair, 0, name="cb_fn")
        env_ptr = self._builder.extract_value(closure_pair, 1, name="cb_env")

        # Build param types matching function declaration convention:
        # ObjectType → struct by value (not pointer), ClassType → pointer
        param_llvm = [i8p]
        for pt in cb_type.param_types:
            if isinstance(pt, ObjectType):
                param_llvm.append(_get_struct_type(pt))
            elif isinstance(pt, ClassType):
                resolved = self._resolve_class_type(pt)
                param_llvm.append(ir.PointerType(_get_struct_type(resolved.instance_type())))
            else:
                param_llvm.append(_llvm_type(pt))
        ret_type = cb_type.return_type
        if isinstance(ret_type, ObjectType):
            ret_llvm = _get_struct_type(ret_type)
        else:
            ret_llvm = _llvm_type(ret_type)
        callee_fn_type = ir.FunctionType(ret_llvm, param_llvm)

        fn_ptr = self._builder.bitcast(fn_ptr_raw, ir.PointerType(callee_fn_type),
                                       name="cb_fptr")
        # Convert pointer args to by-value for ObjectType params
        converted_args = [env_ptr]
        for i, arg in enumerate(args):
            if i < len(cb_type.param_types) and isinstance(cb_type.param_types[i], ObjectType):
                if isinstance(arg.type, ir.PointerType):
                    arg = self._builder.load(arg, name=f"cb_arg{i}_val")
            converted_args.append(arg)
        return self._builder.call(fn_ptr, converted_args, name="cb_result")

    def _generate_array_foreach(self, instr: HIRArrayForEach):
        """Generate: for (let i = 0; i < arr.length; i++) callback(arr[i], i)."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            return
        # Guard: skip if arr_ptr or closure_pair have wrong types
        if not isinstance(arr_ptr.type, ir.PointerType):
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        # Get length
        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="fe_len")

        # Create loop blocks
        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("fe_header")
        body = func.append_basic_block("fe_body")
        exit_bb = func.append_basic_block("fe_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        # Phi for index
        idx_phi = self._builder.phi(i32, name="fe_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        # Condition: idx < len
        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="fe_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body: get element, call callback
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi)
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="fe_idx_f64")

        # Call callback(elem, idx)
        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        self._call_closure(closure_pair, cb_type, call_args)

        # Increment and loop
        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="fe_next")
        idx_phi.add_incoming(next_idx, self._builder.block)
        self._builder.branch(header)

        # Continue at exit
        self._builder = ir.IRBuilder(exit_bb)

    def _generate_array_map(self, instr: HIRArrayMap):
        """Generate: let result = []; for (...) result.push(callback(arr[i], i))."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        # Get source length
        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="map_len")

        # Allocate result array with same capacity
        new_fn = self._qjs_funcs["tsuchi_array_new"]
        result_arr = self._builder.call(new_fn, [arr_len], name="map_result")

        # Loop
        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("map_header")
        body = func.append_basic_block("map_body")
        exit_bb = func.append_basic_block("map_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="map_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="map_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="map_")
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="map_idx_f64")

        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        mapped_val = self._call_closure(closure_pair, cb_type, call_args)

        # Store in result array (detect output element type)
        is_str_dst = isinstance(instr.type, ArrayType) and isinstance(instr.type.element_type, StringType)
        is_obj_dst = isinstance(instr.type, ArrayType) and isinstance(instr.type.element_type, (ObjectType, ClassType))
        if is_str_dst:
            set_fn = self._qjs_funcs["tsuchi_sarray_set"]
        elif is_obj_dst:
            # Object result: need to alloca+store struct, then ptr→double
            if isinstance(mapped_val.type, ir.LiteralStructType):
                # mapped_val is a struct by-value, need to store in heap
                obj_type = instr.type.element_type
                struct_ty = _get_struct_type(obj_type) if isinstance(obj_type, ObjectType) else mapped_val.type
                malloc_fn = self._get_or_declare_malloc()
                i64 = ir.IntType(64)
                size = self._builder.gep(
                    ir.Constant(ir.PointerType(struct_ty), None),
                    [ir.Constant(ir.IntType(32), 1)],
                )
                size_int = self._builder.ptrtoint(size, i64)
                raw_ptr = self._builder.call(malloc_fn, [size_int], name="map_obj_raw")
                obj_ptr = self._builder.bitcast(raw_ptr, ir.PointerType(struct_ty), name="map_obj_ptr")
                self._builder.store(mapped_val, obj_ptr)
                mapped_val = self._ptr_to_double(obj_ptr)
            elif isinstance(mapped_val.type, ir.PointerType):
                mapped_val = self._ptr_to_double(mapped_val)
            set_fn = self._qjs_funcs["tsuchi_array_set"]
        else:
            mapped_val = self._ensure_f64(mapped_val)
            set_fn = self._qjs_funcs["tsuchi_array_set"]
        self._builder.call(set_fn, [result_arr, idx_phi, mapped_val])

        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="map_next")
        idx_phi.add_incoming(next_idx, self._builder.block)
        self._builder.branch(header)

        self._builder = ir.IRBuilder(exit_bb)
        self._ssa_values[instr.result] = result_arr
        if isinstance(instr.type, ArrayType):
            self._ptr_arr_types[id(result_arr)] = instr.type

    def _generate_array_filter(self, instr: HIRArrayFilter):
        """Generate: let result = []; for (...) if (callback(arr[i], i)) result.push(arr[i])."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="flt_len")

        # Allocate result array (start with same capacity)
        new_fn = self._qjs_funcs["tsuchi_array_new"]
        result_arr = self._builder.call(new_fn, [arr_len], name="flt_result")

        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("flt_header")
        body = func.append_basic_block("flt_body")
        push_bb = func.append_basic_block("flt_push")
        cont_bb = func.append_basic_block("flt_cont")
        exit_bb = func.append_basic_block("flt_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="flt_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="flt_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body: call callback
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="flt_")
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="flt_idx_f64")

        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        pred = self._call_closure(closure_pair, cb_type, call_args)

        # Branch on predicate
        pred_i1 = self._builder.trunc(pred, ir.IntType(1), name="flt_pred")
        self._builder.cbranch(pred_i1, push_bb, cont_bb)

        # Push block: push element to result
        self._builder = ir.IRBuilder(push_bb)
        src_arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_str_arr = src_arr_type and isinstance(src_arr_type.element_type, StringType)
        is_obj_arr = src_arr_type and isinstance(src_arr_type.element_type, (ObjectType, ClassType))
        if is_obj_arr:
            push_elem = self._ptr_to_double(elem)
            push_fn = self._qjs_funcs["tsuchi_array_push"]
        elif is_str_arr:
            push_elem = elem
            push_fn = self._qjs_funcs["tsuchi_sarray_push"]
        else:
            push_elem = elem
            push_fn = self._qjs_funcs["tsuchi_array_push"]
        self._builder.call(push_fn, [result_arr, push_elem])
        self._builder.branch(cont_bb)

        # Continue: increment index
        self._builder = ir.IRBuilder(cont_bb)
        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="flt_next")
        idx_phi.add_incoming(next_idx, self._builder.block)
        self._builder.branch(header)

        self._builder = ir.IRBuilder(exit_bb)
        self._ssa_values[instr.result] = result_arr
        if isinstance(instr.type, ArrayType):
            self._ptr_arr_types[id(result_arr)] = instr.type

    def _generate_array_reduce(self, instr: HIRArrayReduce):
        """Generate: let acc = initial; for (...) acc = callback(acc, arr[i]); return acc."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        initial = self._ssa_values.get(instr.initial)
        if arr_ptr is None or closure_pair is None or initial is None:
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="red_len")

        initial = self._ensure_f64(initial)

        func = self._func
        header = func.append_basic_block("red_header")
        body = func.append_basic_block("red_body")
        exit_bb = func.append_basic_block("red_exit")

        entry_bb = self._builder.block
        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="red_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        acc_phi = self._builder.phi(f64, name="red_acc")
        acc_phi.add_incoming(initial, entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="red_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="red_")

        new_acc = self._call_closure(closure_pair, cb_type, [acc_phi, elem])
        new_acc = self._ensure_f64(new_acc)

        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="red_next")
        idx_phi.add_incoming(next_idx, self._builder.block)
        acc_phi.add_incoming(new_acc, self._builder.block)
        self._builder.branch(header)

        self._builder = ir.IRBuilder(exit_bb)
        self._ssa_values[instr.result] = acc_phi

    def _generate_array_reduce_right(self, instr: HIRArrayReduceRight):
        """Generate: let acc = initial; for (i = len-1; i >= 0; i--) acc = callback(acc, arr[i]); return acc."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        initial = self._ssa_values.get(instr.initial)
        if arr_ptr is None or closure_pair is None or initial is None:
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="rr_len")
        start_idx = self._builder.sub(arr_len, ir.Constant(i32, 1), name="rr_start")

        initial = self._ensure_f64(initial)

        func = self._func
        header = func.append_basic_block("rr_header")
        body = func.append_basic_block("rr_body")
        exit_bb = func.append_basic_block("rr_exit")

        entry_bb = self._builder.block
        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="rr_idx")
        idx_phi.add_incoming(start_idx, entry_bb)

        acc_phi = self._builder.phi(f64, name="rr_acc")
        acc_phi.add_incoming(initial, entry_bb)

        cond = self._builder.icmp_signed(">=", idx_phi, ir.Constant(i32, 0), name="rr_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="rr_")

        new_acc = self._call_closure(closure_pair, cb_type, [acc_phi, elem])
        new_acc = self._ensure_f64(new_acc)

        next_idx = self._builder.sub(idx_phi, ir.Constant(i32, 1), name="rr_next")
        idx_phi.add_incoming(next_idx, self._builder.block)
        acc_phi.add_incoming(new_acc, self._builder.block)
        self._builder.branch(header)

        self._builder = ir.IRBuilder(exit_bb)
        self._ssa_values[instr.result] = acc_phi

    def _generate_array_find(self, instr: HIRArrayFind):
        """Generate: for (...) if (callback(arr[i])) return arr[i]; return NaN."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="find_len")

        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("find_header")
        body = func.append_basic_block("find_body")
        found_bb = func.append_basic_block("find_found")
        cont_bb = func.append_basic_block("find_cont")
        exit_bb = func.append_basic_block("find_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="find_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="find_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body: call callback
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="find_")
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="find_idx_f64")

        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        pred = self._call_closure(closure_pair, cb_type, call_args)
        pred_i1 = self._builder.trunc(pred, ir.IntType(1), name="find_pred")
        self._builder.cbranch(pred_i1, found_bb, cont_bb)

        # Found: break out with the element
        self._builder = ir.IRBuilder(found_bb)
        self._builder.branch(exit_bb)

        # Continue: increment
        self._builder = ir.IRBuilder(cont_bb)
        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="find_next")
        idx_phi.add_incoming(next_idx, cont_bb)
        self._builder.branch(header)

        # Exit: phi between found value and default (not found)
        self._builder = ir.IRBuilder(exit_bb)
        arr_type = self._ptr_arr_types.get(id(arr_ptr))
        is_obj_arr = arr_type and isinstance(arr_type.element_type, (ObjectType, ClassType))
        if is_obj_arr:
            # Object array: phi is a pointer type
            result_phi = self._builder.phi(elem.type, name=instr.result)
            null_ptr = ir.Constant(elem.type, None)
            result_phi.add_incoming(null_ptr, header)
            result_phi.add_incoming(elem, found_bb)
            if isinstance(arr_type.element_type, ObjectType):
                self._ptr_obj_types[id(result_phi)] = arr_type.element_type
            elif isinstance(arr_type.element_type, ClassType):
                resolved = self._resolve_class_type(arr_type.element_type)
                self._ptr_obj_types[id(result_phi)] = resolved.instance_type()
        else:
            import math
            nan_val = ir.Constant(f64, math.nan)
            result_phi = self._builder.phi(f64, name=instr.result)
            result_phi.add_incoming(nan_val, header)  # from header (loop done, not found)
            result_phi.add_incoming(elem, found_bb)
        self._ssa_values[instr.result] = result_phi

    def _generate_array_find_index(self, instr: HIRArrayFindIndex):
        """Generate: for (...) if (callback(arr[i])) return i; return -1."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), -1.0)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), -1.0)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), -1.0)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="findi_len")

        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("findi_header")
        body = func.append_basic_block("findi_body")
        found_bb = func.append_basic_block("findi_found")
        cont_bb = func.append_basic_block("findi_cont")
        exit_bb = func.append_basic_block("findi_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="findi_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="findi_cond")
        self._builder.cbranch(cond, body, exit_bb)

        # Body: call callback
        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="findi_")
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="findi_idx_f64")

        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        pred = self._call_closure(closure_pair, cb_type, call_args)
        pred_i1 = self._builder.trunc(pred, ir.IntType(1), name="findi_pred")
        self._builder.cbranch(pred_i1, found_bb, cont_bb)

        # Found: break out with the index
        self._builder = ir.IRBuilder(found_bb)
        found_idx_f64 = self._builder.sitofp(idx_phi, f64, name="findi_found_f64")
        self._builder.branch(exit_bb)

        # Continue: increment
        self._builder = ir.IRBuilder(cont_bb)
        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="findi_next")
        idx_phi.add_incoming(next_idx, cont_bb)
        self._builder.branch(header)

        # Exit: phi between found index and -1 (not found)
        self._builder = ir.IRBuilder(exit_bb)
        not_found = ir.Constant(f64, -1.0)
        result_phi = self._builder.phi(f64, name=instr.result)
        result_phi.add_incoming(not_found, header)  # from header (loop done, not found)
        result_phi.add_incoming(found_idx_f64, found_bb)
        self._ssa_values[instr.result] = result_phi

    def _generate_array_some(self, instr: HIRArraySome):
        """Generate: for (...) if (callback(arr[i])) return true; return false."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 0)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()
        i1 = ir.IntType(1)

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="some_len")

        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("some_header")
        body = func.append_basic_block("some_body")
        found_bb = func.append_basic_block("some_found")
        cont_bb = func.append_basic_block("some_cont")
        exit_bb = func.append_basic_block("some_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="some_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="some_cond")
        self._builder.cbranch(cond, body, exit_bb)

        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="some_")
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="some_idx_f64")

        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        pred = self._call_closure(closure_pair, cb_type, call_args)
        pred_i1 = self._builder.trunc(pred, ir.IntType(1), name="some_pred")
        self._builder.cbranch(pred_i1, found_bb, cont_bb)

        self._builder = ir.IRBuilder(found_bb)
        self._builder.branch(exit_bb)

        self._builder = ir.IRBuilder(cont_bb)
        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="some_next")
        idx_phi.add_incoming(next_idx, cont_bb)
        self._builder.branch(header)

        self._builder = ir.IRBuilder(exit_bb)
        result_phi = self._builder.phi(i1, name=instr.result)
        result_phi.add_incoming(ir.Constant(i1, 0), header)  # loop done: false
        result_phi.add_incoming(ir.Constant(i1, 1), found_bb)  # found: true
        self._ssa_values[instr.result] = result_phi

    def _generate_array_every(self, instr: HIRArrayEvery):
        """Generate: for (...) if (!callback(arr[i])) return false; return true."""
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 1)
            return
        # Guard: skip if arr_ptr is not a pointer
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 1)
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = ir.Constant(ir.IntType(1), 1)
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()
        i1 = ir.IntType(1)

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="every_len")

        func = self._func
        entry_bb = self._builder.block
        header = func.append_basic_block("every_header")
        body = func.append_basic_block("every_body")
        fail_bb = func.append_basic_block("every_fail")
        cont_bb = func.append_basic_block("every_cont")
        exit_bb = func.append_basic_block("every_exit")

        self._builder.branch(header)
        self._builder = ir.IRBuilder(header)

        idx_phi = self._builder.phi(i32, name="every_idx")
        idx_phi.add_incoming(ir.Constant(i32, 0), entry_bb)

        cond = self._builder.icmp_signed("<", idx_phi, arr_len, name="every_cond")
        self._builder.cbranch(cond, body, exit_bb)

        self._builder = ir.IRBuilder(body)
        elem = self._get_array_element(arr_ptr, idx_phi, name_prefix="every_")
        idx_f64 = self._builder.sitofp(idx_phi, f64, name="every_idx_f64")

        call_args = [elem]
        if len(cb_type.param_types) > 1:
            call_args.append(idx_f64)
        pred = self._call_closure(closure_pair, cb_type, call_args)
        pred_i1 = self._builder.trunc(pred, ir.IntType(1), name="every_pred")
        # If predicate is false → fail
        self._builder.cbranch(pred_i1, cont_bb, fail_bb)

        self._builder = ir.IRBuilder(fail_bb)
        self._builder.branch(exit_bb)

        self._builder = ir.IRBuilder(cont_bb)
        next_idx = self._builder.add(idx_phi, ir.Constant(i32, 1), name="every_next")
        idx_phi.add_incoming(next_idx, cont_bb)
        self._builder.branch(header)

        self._builder = ir.IRBuilder(exit_bb)
        result_phi = self._builder.phi(i1, name=instr.result)
        result_phi.add_incoming(ir.Constant(i1, 1), header)  # loop done: all passed → true
        result_phi.add_incoming(ir.Constant(i1, 0), fail_bb)  # fail: false
        self._ssa_values[instr.result] = result_phi

    def _generate_array_sort(self, instr: HIRArraySort):
        """Generate insertion sort using comparator callback.

        for i = 1 to len-1:
            key = arr[i]
            j = i - 1
            while j >= 0 and compare(arr[j], key) > 0:
                arr[j+1] = arr[j]
                j = j - 1
            arr[j+1] = key
        """
        arr_ptr = self._ssa_values.get(instr.array)
        closure_pair = self._ssa_values.get(instr.callback)
        if arr_ptr is None or closure_pair is None:
            self._ssa_values[instr.result] = arr_ptr or self._default_value(instr.type)
            return
        # Guard: skip if arr_ptr is not a pointer or closure_pair is not a struct
        if not isinstance(arr_ptr.type, ir.PointerType):
            self._ssa_values[instr.result] = self._default_value(instr.type)
            return
        if not isinstance(closure_pair.type, ir.LiteralStructType):
            # Callback not resolved — return array unsorted
            self._ssa_values[instr.result] = arr_ptr
            if isinstance(instr.type, ArrayType):
                self._ptr_arr_types[id(arr_ptr)] = instr.type
            return

        cb_type = instr.cb_type
        if not isinstance(cb_type, FunctionType):
            self._ssa_values[instr.result] = arr_ptr
            return

        i32 = ir.IntType(32)
        f64 = ir.DoubleType()

        len_fn = self._qjs_funcs["tsuchi_array_len"]
        set_fn = self._qjs_funcs["tsuchi_array_set"]
        arr_len = self._builder.call(len_fn, [arr_ptr], name="sort_len")

        func = self._func
        entry_bb = self._builder.block

        # Outer loop: for i = 1 to len-1
        outer_header = func.append_basic_block("sort_outer_hdr")
        outer_body = func.append_basic_block("sort_outer_body")
        inner_header = func.append_basic_block("sort_inner_hdr")
        inner_body = func.append_basic_block("sort_inner_body")
        inner_exit = func.append_basic_block("sort_inner_exit")
        outer_cont = func.append_basic_block("sort_outer_cont")
        exit_bb = func.append_basic_block("sort_exit")

        self._builder.branch(outer_header)

        # Outer header: i_phi, check i < len
        self._builder = ir.IRBuilder(outer_header)
        i_phi = self._builder.phi(i32, name="sort_i")
        i_phi.add_incoming(ir.Constant(i32, 1), entry_bb)
        outer_cond = self._builder.icmp_signed("<", i_phi, arr_len, name="sort_outer_cond")
        self._builder.cbranch(outer_cond, outer_body, exit_bb)

        # Outer body: key = arr[i], j = i - 1
        self._builder = ir.IRBuilder(outer_body)
        key = self._get_array_element(arr_ptr, i_phi, name_prefix="sort_")
        j_init = self._builder.sub(i_phi, ir.Constant(i32, 1), name="sort_j_init")
        self._builder.branch(inner_header)

        # Inner header: j_phi, check j >= 0 and compare(arr[j], key) > 0
        self._builder = ir.IRBuilder(inner_header)
        j_phi = self._builder.phi(i32, name="sort_j")
        j_phi.add_incoming(j_init, outer_body)

        j_ge_zero = self._builder.icmp_signed(">=", j_phi, ir.Constant(i32, 0), name="sort_j_ge0")
        # If j < 0, skip comparison
        check_bb = func.append_basic_block("sort_check")
        self._builder.cbranch(j_ge_zero, check_bb, inner_exit)

        # Check: compare(arr[j], key) > 0
        self._builder = ir.IRBuilder(check_bb)
        arr_j = self._get_array_element(arr_ptr, j_phi, name_prefix="sortj_")
        cmp_result = self._call_closure(closure_pair, cb_type, [arr_j, key])
        cmp_f64 = self._ensure_f64(cmp_result)
        cmp_gt = self._builder.fcmp_ordered(">", cmp_f64, ir.Constant(f64, 0.0), name="sort_cmp_gt")
        self._builder.cbranch(cmp_gt, inner_body, inner_exit)

        # Inner body: arr[j+1] = arr[j], j = j - 1
        self._builder = ir.IRBuilder(inner_body)
        j_plus_1 = self._builder.add(j_phi, ir.Constant(i32, 1), name="sort_jp1")
        self._builder.call(set_fn, [arr_ptr, j_plus_1, arr_j])
        j_minus_1 = self._builder.sub(j_phi, ir.Constant(i32, 1), name="sort_jm1")
        j_phi.add_incoming(j_minus_1, self._builder.block)
        self._builder.branch(inner_header)

        # Inner exit: arr[j+1] = key
        self._builder = ir.IRBuilder(inner_exit)
        j_exit_phi = self._builder.phi(i32, name="sort_j_exit")
        j_exit_phi.add_incoming(j_phi, inner_header)  # from j < 0
        j_exit_phi.add_incoming(j_phi, check_bb)  # from compare <= 0
        j_exit_plus1 = self._builder.add(j_exit_phi, ir.Constant(i32, 1), name="sort_insert_pos")
        self._builder.call(set_fn, [arr_ptr, j_exit_plus1, key])
        self._builder.branch(outer_cont)

        # Outer cont: i++
        self._builder = ir.IRBuilder(outer_cont)
        next_i = self._builder.add(i_phi, ir.Constant(i32, 1), name="sort_next_i")
        i_phi.add_incoming(next_i, outer_cont)
        self._builder.branch(outer_header)

        # Exit
        self._builder = ir.IRBuilder(exit_bb)
        self._ssa_values[instr.result] = arr_ptr
        if isinstance(instr.type, ArrayType):
            self._ptr_arr_types[id(arr_ptr)] = instr.type

    def _generate_try_catch(self, instr: HIRTryCatch):
        """Generate try/catch/finally using setjmp/longjmp.

        Allocates a jmp_buf on the stack, calls setjmp directly,
        and branches to try or catch block based on the result.
        """
        i8p = ir.PointerType(ir.IntType(8))
        i32 = ir.IntType(32)

        # Allocate jmp_buf on stack (192 bytes = 48 x i32 on arm64 macOS)
        # Use a large-enough byte array that works cross-platform
        jmpbuf_type = ir.ArrayType(ir.IntType(8), 256)
        jmpbuf = self._builder.alloca(jmpbuf_type, name="jmpbuf")
        jmpbuf_ptr = self._builder.bitcast(jmpbuf, i8p, name="jmpbuf_ptr")

        # Push jmp_buf pointer onto exception stack
        push_fn = self._qjs_funcs["tsuchi_try_push"]
        self._builder.call(push_fn, [jmpbuf_ptr])

        # Call setjmp directly — returns 0 normally, 1 from longjmp
        setjmp_fn = self._qjs_funcs["setjmp"]
        setjmp_result = self._builder.call(setjmp_fn, [jmpbuf_ptr], name="setjmp_result")

        # Branch: setjmp == 0 → try block, else → catch block
        zero = ir.Constant(i32, 0)
        is_normal = self._builder.icmp_signed("==", setjmp_result, zero, name="is_normal")

        try_bb = self._blocks.get(instr.try_block)
        catch_target = instr.catch_block or instr.finally_block or instr.merge_block
        catch_bb = self._blocks.get(catch_target)

        if try_bb and catch_bb:
            # Override the placeholder HIRJump terminator
            self._builder.cbranch(is_normal, try_bb, catch_bb)

        # If catch block needs the error message, populate the catch_param SSA var
        if instr.catch_param and instr.catch_block:
            # We need to generate the get_error_msg call at the start of the catch block
            # Store for deferred generation in the catch block
            if not hasattr(self, '_deferred_catch_params'):
                self._deferred_catch_params = {}
            self._deferred_catch_params[instr.catch_block] = instr.catch_param

    def _generate_phi(self, instr: HIRPhi):
        llvm_type = _llvm_type(instr.type)
        phi = self._builder.phi(llvm_type, name=instr.result)
        self._ssa_values[instr.result] = phi
        # Defer wiring until all blocks are generated
        self._deferred_phis.append((phi, instr.incoming))

    def _generate_terminator(self, term):
        if self._builder.block.is_terminated:
            return

        if isinstance(term, HIRReturn):
            if term.value and term.value in self._ssa_values:
                val = self._ssa_values[term.value]
                # ObjectType/ClassType return: load struct from pointer to return by value
                ret_term_type = term.type
                if isinstance(ret_term_type, ClassType):
                    ret_term_type = self._resolve_class_type(ret_term_type).instance_type()
                if isinstance(ret_term_type, ObjectType):
                    loaded = self._builder.load(val)
                    self._builder.ret(loaded)
                else:
                    ret_type = _llvm_type(term.type)
                    val = self._cast_to(val, ret_type)
                    self._builder.ret(val)
            elif isinstance(term.type, VoidType):
                self._builder.ret_void()
            else:
                self._builder.ret(self._default_value(term.type))
        elif isinstance(term, HIRBranch):
            cond = self._ssa_values.get(term.condition)
            if cond is None:
                cond = ir.Constant(ir.IntType(1), 0)
            # Ensure condition is i1
            if cond.type != ir.IntType(1):
                if cond.type == ir.DoubleType():
                    zero = ir.Constant(ir.DoubleType(), 0.0)
                    cond = self._builder.fcmp_ordered("!=", cond, zero)
                elif cond.type == ir.PointerType(ir.IntType(8)):
                    # String truthiness: non-empty string is truthy
                    strlen_fn = self._qjs_funcs.get("strlen")
                    if strlen_fn:
                        slen = self._builder.call(strlen_fn, [cond])
                        cond = self._builder.icmp_signed("!=", slen, ir.Constant(ir.IntType(64), 0))
                    else:
                        null = ir.Constant(cond.type, None)
                        cond = self._builder.icmp_unsigned("!=", cond, null)
                else:
                    cond = ir.Constant(ir.IntType(1), 0)
            true_block = self._blocks.get(term.true_block)
            false_block = self._blocks.get(term.false_block)
            if true_block and false_block:
                self._builder.cbranch(cond, true_block, false_block)
        elif isinstance(term, HIRJump):
            target = self._blocks.get(term.target_block)
            if target:
                self._builder.branch(target)

    def _generate_wrapper_func(self, hir_func: HIRFunction):
        """Generate tsuchi_wrap_<name> — JSCFunction wrapper.

        Signature: JSValue tsuchi_wrap_<name>(JSContext *ctx, JSValueConst this_val,
                                               int argc, JSValueConst *argv)

        Since JSValue is complex (struct), we generate the wrapper in C instead.
        This method is a no-op — the C wrapper is generated by quickjs_backend.py.
        """
        pass  # Wrapper generated as C code in backend

    def _default_value(self, ty: MonoType) -> ir.Value:
        """Return a default LLVM constant for a given type."""
        if isinstance(ty, NumberType):
            return ir.Constant(ir.DoubleType(), 0.0)
        elif isinstance(ty, BooleanType):
            return ir.Constant(ir.IntType(1), 0)
        elif isinstance(ty, (StringType, NullType, ArrayType)):
            return ir.Constant(ir.PointerType(ir.IntType(8)), None)
        elif isinstance(ty, FunctionType):
            i8p = ir.PointerType(ir.IntType(8))
            pair_type = ir.LiteralStructType([i8p, i8p])
            null = ir.Constant(i8p, None)
            return ir.Constant(pair_type, [null, null])
        else:
            return ir.Constant(ir.DoubleType(), 0.0)

    def _ensure_f64(self, val: ir.Value) -> ir.Value:
        if val.type == ir.DoubleType():
            return val
        if val.type == ir.IntType(1):
            return self._builder.uitofp(val, ir.DoubleType())
        if val.type == ir.IntType(32):
            return self._builder.sitofp(val, ir.DoubleType())
        if val.type == ir.IntType(64):
            return self._builder.sitofp(val, ir.DoubleType())
        return val

    def _cast_to(self, val: ir.Value, target_type: ir.Type) -> ir.Value:
        if val.type == target_type:
            return val
        if target_type == ir.DoubleType():
            return self._ensure_f64(val)
        if target_type == ir.IntType(1) and val.type == ir.DoubleType():
            zero = ir.Constant(ir.DoubleType(), 0.0)
            return self._builder.fcmp_ordered("!=", val, zero)
        # Pointer-to-struct bitcast (e.g., child class ptr → parent class ptr)
        if (isinstance(val.type, ir.PointerType) and isinstance(target_type, ir.PointerType)
                and isinstance(val.type.pointee, ir.LiteralStructType)
                and isinstance(target_type.pointee, ir.LiteralStructType)):
            return self._builder.bitcast(val, target_type)
        return val

    def _make_global_str(self, s: str) -> ir.Value:
        encoded = (s + "\0").encode("utf-8")
        str_type = ir.ArrayType(ir.IntType(8), len(encoded))
        name = f".str.{len(self._module.global_values)}"
        str_global = ir.GlobalVariable(self._module, str_type, name=name)
        str_global.linkage = "private"
        str_global.global_constant = True
        str_global.initializer = ir.Constant(str_type, bytearray(encoded))
        return self._builder.bitcast(str_global, ir.PointerType(ir.IntType(8)))

    def _get_or_declare_strcmp(self) -> ir.Function:
        """Declare strcmp(const char*, const char*) -> i32."""
        if "strcmp" in self._qjs_funcs:
            return self._qjs_funcs["strcmp"]
        i8p = ir.PointerType(ir.IntType(8))
        i32 = ir.IntType(32)
        fn_type = ir.FunctionType(i32, [i8p, i8p])
        fn = ir.Function(self._module, fn_type, name="strcmp")
        self._qjs_funcs["strcmp"] = fn
        return fn

    def _get_or_declare_intrinsic(self, name: str, func_type: ir.FunctionType) -> ir.Function:
        if name in self._qjs_funcs:
            return self._qjs_funcs[name]
        func = ir.Function(self._module, func_type, name=name)
        self._qjs_funcs[name] = func
        return func

    def _generate_ffi_struct_create(self, instr):
        """Generate FFI struct creation via insertvalue chain."""
        from tsuchi.type_checker.types import FFIStructType
        struct_type = instr.type
        if not isinstance(struct_type, FFIStructType):
            return
        llvm_struct_ty = self._ffi_mono_to_llvm(struct_type)
        # Start with undef struct
        val = ir.Constant(llvm_struct_ty, ir.Undefined)
        for i, field_ssa in enumerate(instr.field_values):
            field_val = self._ssa_values.get(field_ssa)
            if field_val is None:
                continue
            expected_ty = llvm_struct_ty.elements[i]
            # Convert f64 arg to expected field type
            if isinstance(expected_ty, ir.IntType) and expected_ty.width == 32:
                if isinstance(field_val.type, ir.DoubleType):
                    i64_val = self._builder.fptosi(field_val, ir.IntType(64))
                    field_val = self._builder.trunc(i64_val, ir.IntType(32))
            elif isinstance(expected_ty, ir.DoubleType):
                field_val = self._ensure_f64(field_val)
            val = self._builder.insert_value(val, field_val, i,
                                              name=f"{instr.result}_f{i}")
        self._ssa_values[instr.result] = val

    def _generate_ffi_struct_field_get(self, instr):
        """Generate FFI struct field extraction via extractvalue."""
        struct_val = self._ssa_values.get(instr.struct_val)
        if struct_val is None:
            self._ssa_values[instr.result] = ir.Constant(ir.DoubleType(), 0.0)
            return
        extracted = self._builder.extract_value(struct_val, instr.field_index,
                                                 name=instr.result)
        # Convert to f64 if the extracted value is i32 (boolean)
        if isinstance(extracted.type, ir.IntType) and extracted.type.width == 32:
            extracted = self._builder.sitofp(extracted, ir.DoubleType(),
                                              name=instr.result + "_f64")
        self._ssa_values[instr.result] = extracted
