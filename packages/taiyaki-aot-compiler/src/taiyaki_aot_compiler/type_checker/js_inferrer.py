"""HM call-site type inference engine for JavaScript.

No type annotations — all types are inferred from:
1. Literal values (42 → number, "hello" → string, true → boolean)
2. Operators (a + b with number operands → number)
3. Call sites (add(1, 2) → add: (number, number) => number)
4. Multi-pass convergence (up to 3 iterations)
"""

from __future__ import annotations

from taiyaki_aot_compiler.parser.ast_nodes import (
    JSModule, Statement, Expression, Block,
    FunctionDecl, VarDecl, ReturnStmt, IfStmt, WhileStmt, DoWhileStmt, ForStmt,
    ForOfStmt, ExpressionStmt, ObjectDestructure, ArrayDestructure, BreakStmt, ContinueStmt, LabeledStmt,
    SwitchStmt, SwitchCase,
    ClassDecl, ClassField, MethodDecl, NewExpr, ThisExpr, SuperCall, ThrowStmt, TryCatchStmt, ForInStmt,
    NumberLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    Identifier, BinaryExpr, UnaryExpr, UpdateExpr, CompareExpr,
    LogicalExpr, ConditionalExpr, CallExpr, MemberExpr, AssignExpr,
    ArrowFunction, ObjectLiteralExpr, ArrayLiteral, SpreadElement, SequenceExpr, TemplateLiteral,
    AwaitExpr,
    Location, Parameter,
    ImportDeclaration, ExportDeclaration,
)
from taiyaki_aot_compiler.type_checker.types import (
    MonoType, NumberType, BooleanType, StringType, NullType, VoidType,
    TypeVar, FunctionType, ArrayType, ObjectType, ClassType, Substitution,
    FFIStructType, OpaquePointerType, PromiseType,
    NUMBER, BOOLEAN, STRING, NULL, VOID,
)
from taiyaki_aot_compiler.type_checker.unification import unify, UnificationError
from taiyaki_aot_compiler.type_checker.builtins import binary_op_type, compare_op_type, unary_op_type
from taiyaki_aot_compiler.diagnostics.diagnostic import DiagnosticCollector, Location as DiagLocation

# Known JS/Web/runtime builtins not yet natively compiled → fallback gracefully
_JS_BUILTINS = frozenset({
    "eval", "arguments", "Symbol", "Reflect", "Proxy",
    "Set", "Map", "WeakSet", "WeakMap", "WeakRef",
    "RegExp", "Promise", "Intl", "SharedArrayBuffer",
    "Atomics", "DataView", "ArrayBuffer", "TextEncoder",
    "TextDecoder", "URL", "URLSearchParams", "Event",
    "EventTarget", "AbortController", "AbortSignal",
    "queueMicrotask", "structuredClone", "atob", "btoa",
    "globalThis", "self", "window", "document",
    "Request", "Response", "Headers",
    "ReadableStream", "WritableStream", "TransformStream",
    "Blob", "File", "FormData", "DOMException",
    "Katana", "Taiyaki",
    "fetch", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval",
    "crypto", "performance",
    "Buffer", "require",
})


class TypedFunction:
    """Result of type-checking a function."""
    def __init__(self, name: str, params: list[tuple[str, MonoType]],
                 return_type: MonoType, node: FunctionDecl,
                 node_types: dict[int, MonoType],
                 is_compilable: bool = True,
                 captures: list[tuple[str, MonoType]] | None = None,
                 defaults: list[Expression | None] | None = None):
        self.name = name
        self.params = params
        self.return_type = return_type
        self.node = node
        self.node_types = node_types
        self.is_compilable = is_compilable
        self.captures = captures or []
        self.defaults = defaults or []


class TypedModule:
    """Result of type-checking a module."""
    def __init__(self):
        self.functions: list[TypedFunction] = []
        self.global_vars: dict[str, MonoType] = {}
        self.top_level_stmts: list[Statement] = []
        self.entry_exprs: list[Expression] = []
        self.arrow_lifted_names: dict[int, str] = {}  # id(ArrowFunction) -> lifted func name
        self.arrow_captures: dict[int, list[tuple[str, MonoType]]] = {}  # id(ArrowFunction) -> captures
        self.nested_func_arrows: dict[str, ArrowFunction] = {}  # nested func name -> synthetic arrow
        self.nested_func_lifted: dict[str, str] = {}  # original name -> lifted name
        self.classes: dict[str, ClassType] = {}  # class_name -> ClassType
        self.class_decls: dict[str, ClassDecl] = {}  # class_name -> ClassDecl
        self.import_rewrite_map: dict[str, str] = {}  # import alias → prefixed name
        self.mono_call_rewrites: dict[int, str] = {}  # id(CallExpr) → mangled func name


class JSInferrer:
    """Call-site driven HM type inference for JavaScript."""

    def __init__(self, diagnostics: DiagnosticCollector | None = None,
                 type_stubs: dict[str, FunctionType] | None = None,
                 ffi_info: object = None):
        self.diag = diagnostics or DiagnosticCollector()
        self._env: dict[str, MonoType] = {}
        self._functions: dict[str, FunctionType] = {}
        self._type_stubs: dict[str, FunctionType] = type_stubs or {}
        self._ffi_info = ffi_info  # FFIInfo from ffi_loader
        self._node_types: dict[int, MonoType] = {}
        self._subst = Substitution()
        self._return_type: MonoType | None = None
        self._arrow_counter = 0
        self._arrow_lifted: dict[int, tuple[str, ArrowFunction, FunctionType, list]] = {}
        self._nested_func_arrows: dict[str, ArrowFunction] = {}  # nested func name → synthetic arrow
        self._current_func_name: str = "__top"
        # Monomorphization: original_name → list of (mangled_name, FuncDecl) clones
        self._mono_variants: dict[str, list[tuple[str, FunctionDecl]]] = {}
        self._needs_js_fallback: set[str] = set()  # Functions using JS-only builtins
        self._current_func_name: str | None = None
        self._mono_counter: int = 0
        self._mono_call_rewrites: dict[int, str] = {}  # id(CallExpr) → mangled name

    def check_module(self, module: JSModule, filename: str = "<input>") -> TypedModule:
        self.diag.register_source(filename, module.source)
        result = TypedModule()
        self._classes: dict[str, ClassType] = {}
        self._class_decls: dict[str, ClassDecl] = {}

        # Collect function and class declarations (unwrap exports)
        func_decls: list[FunctionDecl] = []
        self._func_decls: list[FunctionDecl] = []
        for stmt in module.body:
            decl = stmt
            # Unwrap ExportDeclaration to get the inner declaration
            if isinstance(decl, ExportDeclaration) and decl.declaration is not None:
                decl = decl.declaration
            if isinstance(decl, FunctionDecl):
                func_decls.append(decl)
            elif isinstance(decl, ClassDecl):
                self._register_class(decl)

        # Generate synthetic functions for class constructors and methods
        for class_name, class_decl in self._class_decls.items():
            synth_funcs = self._lower_class_to_functions(class_decl)
            func_decls.extend(synth_funcs)

        self._func_decls = func_decls

        # Register all function signatures (use stubs if available, else TypeVars)
        for func in func_decls:
            self._register_function_sig(func)

        # Register FFI functions (from @ffi pragmas)
        if self._ffi_info is not None:
            # Register plain FFI functions (skip Class.method and Class#method keys)
            for name, ffi_fn in self._ffi_info.functions.items():
                if "." not in name and "#" not in name:
                    ft = FunctionType(ffi_fn.param_types, ffi_fn.return_type)
                    self._env[name] = ft
                    self._functions[name] = ft

            # Register FFI struct types
            for sname, ffi_struct in self._ffi_info.structs.items():
                self._env[sname] = FFIStructType(
                    name=sname, fields=dict(ffi_struct.fields))

            # Register opaque class types (as namespace objects with static methods)
            for cname, oc in self._ffi_info.opaque_classes.items():
                methods: dict[str, MonoType] = {}
                for mname, mfn in oc.static_methods.items():
                    methods[mname] = FunctionType(mfn.param_types, mfn.return_type)
                self._env[cname] = ObjectType(fields=methods)

        # Register console.log/error/warn as builtin
        self._env["console"] = ObjectType(fields={
            "log": FunctionType([TypeVar()], VOID),
            "error": FunctionType([TypeVar()], VOID),
            "warn": FunctionType([TypeVar()], VOID),
        })

        # Register process as builtin
        self._env["process"] = ObjectType(fields={
            "exit": FunctionType([NUMBER], VOID),
            "argv": ArrayType(STRING),
            "env": ObjectType(fields={}),
        })

        # Register Math as builtin
        self._env["Math"] = ObjectType(fields={
            "PI": NUMBER,
            "E": NUMBER,
            "SQRT2": NUMBER,
            "LN2": NUMBER,
            "LN10": NUMBER,
            "LOG2E": NUMBER,
            "LOG10E": NUMBER,
            "floor": FunctionType([NUMBER], NUMBER),
            "ceil": FunctionType([NUMBER], NUMBER),
            "abs": FunctionType([NUMBER], NUMBER),
            "sqrt": FunctionType([NUMBER], NUMBER),
            "round": FunctionType([NUMBER], NUMBER),
            "trunc": FunctionType([NUMBER], NUMBER),
            "sign": FunctionType([NUMBER], NUMBER),
            "min": FunctionType([NUMBER, NUMBER], NUMBER),
            "max": FunctionType([NUMBER, NUMBER], NUMBER),
            "pow": FunctionType([NUMBER, NUMBER], NUMBER),
            "log": FunctionType([NUMBER], NUMBER),
            "exp": FunctionType([NUMBER], NUMBER),
            "sin": FunctionType([NUMBER], NUMBER),
            "cos": FunctionType([NUMBER], NUMBER),
            "tan": FunctionType([NUMBER], NUMBER),
            "random": FunctionType([], NUMBER),
            "log2": FunctionType([NUMBER], NUMBER),
            "log10": FunctionType([NUMBER], NUMBER),
            "hypot": FunctionType([NUMBER, NUMBER], NUMBER),
            "clz32": FunctionType([NUMBER], NUMBER),
        })

        # Register path module
        self._env["path"] = ObjectType(fields={
            "join": FunctionType([STRING, STRING], STRING),
            "resolve": FunctionType([STRING], STRING),
            "dirname": FunctionType([STRING], STRING),
            "basename": FunctionType([STRING], STRING),
            "extname": FunctionType([STRING], STRING),
            "normalize": FunctionType([STRING], STRING),
            "isAbsolute": FunctionType([STRING], BOOLEAN),
            "sep": STRING,
        })

        # Register fs module
        self._env["fs"] = ObjectType(fields={
            "readFileSync": FunctionType([STRING], STRING),
            "writeFileSync": FunctionType([STRING, STRING], VOID),
            "existsSync": FunctionType([STRING], BOOLEAN),
            "mkdirSync": FunctionType([STRING], VOID),
            "rmdirSync": FunctionType([STRING], VOID),
            "unlinkSync": FunctionType([STRING], VOID),
            "renameSync": FunctionType([STRING, STRING], VOID),
            "appendFileSync": FunctionType([STRING, STRING], VOID),
            "copyFileSync": FunctionType([STRING, STRING], VOID),
            "readdirSync": FunctionType([STRING], ArrayType(STRING)),
            # Async versions (return Promise)
            "readFile": FunctionType([STRING], PromiseType(STRING)),
            "writeFile": FunctionType([STRING, STRING], PromiseType(VOID)),
        })

        # Register os module
        self._env["os"] = ObjectType(fields={
            "platform": FunctionType([], STRING),
            "arch": FunctionType([], STRING),
            "homedir": FunctionType([], STRING),
            "tmpdir": FunctionType([], STRING),
            "hostname": FunctionType([], STRING),
            "cpus": FunctionType([], NUMBER),
            "totalmem": FunctionType([], NUMBER),
            "freemem": FunctionType([], NUMBER),
            "EOL": STRING,
        })

        # Register String as builtin (for static methods)
        self._env["String"] = ObjectType(fields={
            "fromCharCode": FunctionType([NUMBER], STRING),
        })

        # Register Date as builtin (for static methods)
        self._env["Date"] = ObjectType(fields={
            "now": FunctionType([], NUMBER),
        })

        # Register Number as builtin (for static methods)
        self._env["Number"] = ObjectType(fields={
            "isInteger": FunctionType([NUMBER], BOOLEAN),
            "isFinite": FunctionType([NUMBER], BOOLEAN),
            "isNaN": FunctionType([NUMBER], BOOLEAN),
            "parseInt": FunctionType([STRING], NUMBER),
            "parseFloat": FunctionType([STRING], NUMBER),
            "MAX_SAFE_INTEGER": NUMBER,
            "MIN_SAFE_INTEGER": NUMBER,
            "EPSILON": NUMBER,
            "MAX_VALUE": NUMBER,
            "MIN_VALUE": NUMBER,
            "POSITIVE_INFINITY": NUMBER,
            "NEGATIVE_INFINITY": NUMBER,
        })

        # Register Array as builtin (for static methods)
        self._env["Array"] = ObjectType(fields={
            "isArray": FunctionType([TypeVar()], BOOLEAN),
            "from": FunctionType([TypeVar()], ArrayType(TypeVar())),
        })

        # Register Object as builtin (for static methods)
        self._env["Object"] = ObjectType(fields={
            "keys": FunctionType([TypeVar()], ArrayType(STRING)),
            "values": FunctionType([TypeVar()], ArrayType(TypeVar())),
            "entries": FunctionType([TypeVar()], ArrayType(ArrayType(TypeVar()))),
            "assign": FunctionType([TypeVar(), TypeVar()], TypeVar()),
            "freeze": FunctionType([TypeVar()], TypeVar()),
        })

        # Register JSON as builtin
        self._env["JSON"] = ObjectType(fields={
            "stringify": FunctionType([TypeVar()], STRING),
            "parse": FunctionType([STRING], TypeVar()),
        })

        # Global constants
        self._env["Infinity"] = NUMBER
        self._env["NaN"] = NUMBER
        self._env["undefined"] = VOID
        self._env["null"] = NULL

        # Raylib color constants (packed RGBA)
        for _rl_c in ("WHITE", "BLACK", "RED", "GREEN", "BLUE", "YELLOW",
                       "ORANGE", "PURPLE", "GRAY", "DARKGRAY", "LIGHTGRAY",
                       "RAYWHITE", "BROWN", "PINK", "MAROON", "LIME",
                       "SKYBLUE", "DARKBLUE", "VIOLET", "BEIGE", "MAGENTA", "GOLD",
                       "BLANK", "DARKGREEN", "DARKPURPLE", "DARKBROWN"):
            self._env[_rl_c] = NUMBER
        # Raylib key codes
        for _rl_k in ("KEY_RIGHT", "KEY_LEFT", "KEY_DOWN", "KEY_UP",
                       "KEY_SPACE", "KEY_ENTER", "KEY_ESCAPE"):
            self._env[_rl_k] = NUMBER
        for _c in range(65, 91):  # KEY_A..KEY_Z
            self._env[f"KEY_{chr(_c)}"] = NUMBER
        # KEY_0..KEY_9
        for _d in range(48, 58):
            self._env[f"KEY_{chr(_d)}"] = NUMBER
        # Mouse buttons
        self._env["MOUSE_LEFT"] = NUMBER
        self._env["MOUSE_RIGHT"] = NUMBER
        self._env["MOUSE_MIDDLE"] = NUMBER
        # Clay sizing constants
        self._env["CLAY_FIT"] = NUMBER
        self._env["CLAY_GROW"] = NUMBER
        self._env["CLAY_LEFT_TO_RIGHT"] = NUMBER
        self._env["CLAY_TOP_TO_BOTTOM"] = NUMBER

        # termbox2 event type constants
        self._env["TB_EVENT_KEY"] = NUMBER
        self._env["TB_EVENT_RESIZE"] = NUMBER
        self._env["TB_EVENT_MOUSE"] = NUMBER
        # termbox2 key constants
        self._env["TB_KEY_ESC"] = NUMBER
        self._env["TB_KEY_ENTER"] = NUMBER
        self._env["TB_KEY_TAB"] = NUMBER
        self._env["TB_KEY_BACKSPACE"] = NUMBER
        self._env["TB_KEY_ARROW_UP"] = NUMBER
        self._env["TB_KEY_ARROW_DOWN"] = NUMBER
        self._env["TB_KEY_ARROW_LEFT"] = NUMBER
        self._env["TB_KEY_ARROW_RIGHT"] = NUMBER
        self._env["TB_KEY_SPACE"] = NUMBER
        self._env["TB_KEY_DELETE"] = NUMBER
        self._env["TB_KEY_HOME"] = NUMBER
        self._env["TB_KEY_END"] = NUMBER
        self._env["TB_KEY_PGUP"] = NUMBER
        self._env["TB_KEY_PGDN"] = NUMBER
        for _fk in range(1, 13):  # TB_KEY_F1..TB_KEY_F12
            self._env[f"TB_KEY_F{_fk}"] = NUMBER
        self._env["TB_MOD_ALT"] = NUMBER
        self._env["TB_MOD_CTRL"] = NUMBER
        self._env["TB_MOD_SHIFT"] = NUMBER
        # TUI color constants
        self._env["TB_COLOR_DEFAULT"] = NUMBER
        self._env["TB_COLOR_BLACK"] = NUMBER
        self._env["TB_COLOR_RED"] = NUMBER
        self._env["TB_COLOR_GREEN"] = NUMBER
        self._env["TB_COLOR_YELLOW"] = NUMBER
        self._env["TB_COLOR_BLUE"] = NUMBER
        self._env["TB_COLOR_MAGENTA"] = NUMBER
        self._env["TB_COLOR_CYAN"] = NUMBER
        self._env["TB_COLOR_WHITE"] = NUMBER
        # Text attributes
        self._env["TB_ATTR_BOLD"] = NUMBER
        self._env["TB_ATTR_UNDERLINE"] = NUMBER
        self._env["TB_ATTR_REVERSE"] = NUMBER
        # Gamepad button/axis constants
        for _gp in range(16):
            self._env[f"GAMEPAD_BUTTON_{_gp}"] = NUMBER
        for _ga in range(6):
            self._env[f"GAMEPAD_AXIS_{_ga}"] = NUMBER
        # Window config flag constants
        self._env["FLAG_FULLSCREEN_MODE"] = NUMBER
        self._env["FLAG_WINDOW_RESIZABLE"] = NUMBER
        self._env["FLAG_WINDOW_UNDECORATED"] = NUMBER
        self._env["FLAG_WINDOW_TRANSPARENT"] = NUMBER
        self._env["FLAG_MSAA_4X_HINT"] = NUMBER
        self._env["FLAG_VSYNC_HINT"] = NUMBER
        self._env["FLAG_WINDOW_HIGHDPI"] = NUMBER

        # Theme Colors (packed RGBA u32)
        self._env["THEME_BG"] = NUMBER           # 0x181820FF
        self._env["THEME_BG_SURFACE"] = NUMBER   # 0x242430FF
        self._env["THEME_BG_SURFACE2"] = NUMBER  # 0x2C2C3CFF
        self._env["THEME_FG"] = NUMBER            # 0xE6E6F0FF
        self._env["THEME_FG_MUTED"] = NUMBER     # 0x505064FF
        self._env["THEME_PRIMARY"] = NUMBER      # 0x3C64B4FF
        self._env["THEME_PRIMARY_HOVER"] = NUMBER # 0x5080D0FF
        self._env["THEME_SECONDARY"] = NUMBER    # 0x646478FF
        self._env["THEME_BORDER"] = NUMBER       # 0x505064FF
        self._env["THEME_FOCUS"] = NUMBER        # 0x3C5080FF
        self._env["THEME_SUCCESS"] = NUMBER      # 0x50C878FF
        self._env["THEME_WARNING"] = NUMBER      # 0xDCB450FF
        self._env["THEME_ERROR"] = NUMBER        # 0xDC5050FF
        self._env["THEME_INFO"] = NUMBER         # 0x5090DCFF
        self._env["THEME_ACCENT"] = NUMBER       # 0x6450C8FF
        # Key constants (matching raylib)
        self._env["KEY_ENTER"] = NUMBER
        self._env["KEY_ESCAPE"] = NUMBER
        self._env["KEY_TAB"] = NUMBER
        self._env["KEY_BACKSPACE"] = NUMBER
        self._env["KEY_DELETE"] = NUMBER
        self._env["KEY_LEFT"] = NUMBER
        self._env["KEY_RIGHT"] = NUMBER
        self._env["KEY_UP"] = NUMBER
        self._env["KEY_DOWN"] = NUMBER
        self._env["KEY_HOME"] = NUMBER
        self._env["KEY_END"] = NUMBER
        self._env["KEY_SPACE"] = NUMBER

        # Multi-pass inference (up to 3 passes for convergence)
        for _iteration in range(3):
            old_size = len(self._subst.mapping)

            # Process top-level variable declarations FIRST so functions can see them
            for stmt in module.body:
                if isinstance(stmt, VarDecl):
                    self._check_var_decl(stmt, filename)

            for func in func_decls:
                self._check_function_body(func, filename)

            # Also infer top-level expression statements
            for stmt in module.body:
                if isinstance(stmt, ExpressionStmt):
                    self._infer_expr(stmt.expression, filename)

            if len(self._subst.mapping) == old_size:
                break  # Converged

        # Build final result
        for func in func_decls:
            tf = self._finalize_function(func, filename)
            result.functions.append(tf)

        # Store resolved class types — apply substitution to resolve TypeVars
        # For inheritance: parent fields first in dict order, then child-only fields
        resolved_classes: dict[str, ClassType] = {}
        # Process parent classes before children
        processed = set()
        def resolve_class(name):
            if name in processed:
                return
            ct = self._classes.get(name)
            if not ct:
                return
            decl = self._class_decls.get(name)
            # Resolve parent first
            if decl and decl.extends:
                resolve_class(decl.extends)
            # Build ordered fields: parent fields first, then child-only fields
            ordered_fields: dict[str, MonoType] = {}
            if decl and decl.extends and decl.extends in resolved_classes:
                parent_ct = resolved_classes[decl.extends]
                for fn, ft in parent_ct.fields.items():
                    ordered_fields[fn] = ft
            # Add child's own fields (already have parent fields from inheritance)
            for fn, ft in ct.fields.items():
                if fn not in ordered_fields:
                    ordered_fields[fn] = self._subst.apply(ft)
                elif isinstance(ordered_fields[fn], TypeVar):
                    ordered_fields[fn] = self._subst.apply(ft)
            resolved_classes[name] = ClassType(
                name=name, fields=ordered_fields, methods=dict(ct.methods)
            )
            processed.add(name)
        for name in self._classes:
            resolve_class(name)
        result.classes = resolved_classes
        result.class_decls = dict(self._class_decls)
        result.import_rewrite_map = getattr(module, 'import_rewrite_map', {})
        result.mono_call_rewrites = self._mono_call_rewrites

        for stmt in module.body:
            if isinstance(stmt, (FunctionDecl, ClassDecl, ImportDeclaration)):
                continue
            # Unwrap ExportDeclaration
            if isinstance(stmt, ExportDeclaration):
                if stmt.declaration is not None:
                    if isinstance(stmt.declaration, (FunctionDecl, ClassDecl)):
                        continue
                    stmt = stmt.declaration
                else:
                    continue
            if isinstance(stmt, VarDecl):
                result.global_vars[stmt.name] = self._env.get(stmt.name, TypeVar())
                result.top_level_stmts.append(stmt)
            elif isinstance(stmt, ObjectDestructure):
                self._check_object_destructure(stmt, filename)
                for fname in stmt.fields:
                    local_name = stmt.aliases.get(fname, fname)
                    result.global_vars[local_name] = self._env.get(local_name, TypeVar())
                if stmt.rest_name:
                    result.global_vars[stmt.rest_name] = self._env.get(stmt.rest_name, TypeVar())
                result.top_level_stmts.append(stmt)
            elif isinstance(stmt, ArrayDestructure):
                self._check_array_destructure(stmt, filename)
                for n in stmt.names:
                    result.global_vars[n] = self._env.get(n, TypeVar())
                if stmt.rest_name:
                    result.global_vars[stmt.rest_name] = self._env.get(stmt.rest_name, TypeVar())
                result.top_level_stmts.append(stmt)
            elif isinstance(stmt, ExpressionStmt):
                result.entry_exprs.append(stmt.expression)
                result.top_level_stmts.append(stmt)

        # Finalize lifted arrow functions
        for arrow_id, (lifted_name, arrow_expr, ft, captures) in self._arrow_lifted.items():
            resolved_ft = FunctionType(
                [self._subst.apply(pt) for pt in ft.param_types],
                self._subst.apply(ft.return_type),
            )
            # Resolve capture types
            resolved_captures = [(name, self._subst.apply(typ)) for name, typ in captures]

            # Convert ArrowFunction to synthetic FunctionDecl
            if isinstance(arrow_expr.body, Block):
                body = arrow_expr.body
            else:
                body = Block(body=[ReturnStmt(value=arrow_expr.body)])
            synth_decl = FunctionDecl(
                name=lifted_name,
                params=list(arrow_expr.params),
                body=body,
            )
            resolved_params = [(p.name, resolved_ft.param_types[i])
                               for i, p in enumerate(arrow_expr.params)]
            is_compilable = all(
                not isinstance(t, TypeVar) for _, t in resolved_params
            ) and not isinstance(resolved_ft.return_type, TypeVar)

            # Re-check body for node_types
            old_env = dict(self._env)
            old_return = self._return_type
            self._node_types = {}
            # Set captured variables in env for body re-check
            for cap_name, cap_type in resolved_captures:
                self._env[cap_name] = cap_type
            for i, p in enumerate(arrow_expr.params):
                self._env[p.name] = resolved_ft.param_types[i]
            self._return_type = resolved_ft.return_type
            if isinstance(arrow_expr.body, Block):
                self._check_block(arrow_expr.body, filename)
            else:
                self._infer_expr(arrow_expr.body, filename)
            resolved_node_types = {k: self._subst.apply(v) for k, v in self._node_types.items()}
            self._env = old_env
            self._return_type = old_return

            tf = TypedFunction(
                name=lifted_name,
                params=resolved_params,
                return_type=resolved_ft.return_type,
                node=synth_decl,
                node_types=resolved_node_types,
                is_compilable=is_compilable,
                captures=resolved_captures,
            )
            result.functions.append(tf)
            result.arrow_lifted_names[arrow_id] = lifted_name
            result.arrow_captures[arrow_id] = resolved_captures

        # Pass nested function arrow mappings to TypedModule
        result.nested_func_arrows = dict(self._nested_func_arrows)

        # Build mapping: original nested func name → lifted name
        for orig_name, arrow in self._nested_func_arrows.items():
            lifted_entry = self._arrow_lifted.get(id(arrow))
            if lifted_entry:
                lifted_name_val = lifted_entry[0]
                result.nested_func_lifted[orig_name] = lifted_name_val

        return result

    def _register_class(self, class_decl: ClassDecl):
        """Register a class declaration, extracting fields from constructor."""
        class_name = class_decl.name
        self._class_decls[class_name] = class_decl

        # Inherit fields and methods from parent class
        fields: dict[str, MonoType] = {}
        methods: dict[str, FunctionType] = {}
        if class_decl.extends and class_decl.extends in self._classes:
            parent = self._classes[class_decl.extends]
            fields.update(parent.fields)
            methods.update(parent.methods)

        # Register class field declarations (class body fields with initializers)
        for cf in class_decl.field_declarations:
            if not cf.is_static:
                fields[cf.name] = TypeVar()

        # Extract fields from constructor body (this.x = ... assignments)
        if class_decl.constructor:
            for stmt in class_decl.constructor.body.body:
                if isinstance(stmt, ExpressionStmt) and isinstance(stmt.expression, AssignExpr):
                    assign = stmt.expression
                    if (isinstance(assign.left, MemberExpr)
                            and isinstance(assign.left.object, ThisExpr)
                            and isinstance(assign.left.property, Identifier)):
                        field_name = assign.left.property.name
                        fields[field_name] = TypeVar()

        # Extract method types (TypeVars initially, resolved during inference)
        for method in class_decl.methods:
            if method.is_getter:
                # Getter acts as a field — its return type is the field type
                fields[method.name] = TypeVar()
            elif method.is_setter:
                # Setter — tracked as method but invoked on assignment
                pass
            else:
                param_types = [TypeVar() for _ in method.params]
                ret_type = TypeVar()
                methods[method.name] = FunctionType(param_types, ret_type)

        ct = ClassType(name=class_name, fields=fields, methods=methods)
        self._classes[class_name] = ct

        # Register class name in env — include static methods as ObjectType fields
        static_fields: dict[str, MonoType] = {}
        for method in class_decl.static_methods:
            param_types = [TypeVar() for _ in method.params]
            ret_type = TypeVar()
            static_fields[method.name] = FunctionType(param_types, ret_type)
        if static_fields:
            self._env[class_name] = ObjectType(fields=static_fields)
        else:
            self._env[class_name] = ct

    def _lower_class_to_functions(self, class_decl: ClassDecl) -> list[FunctionDecl]:
        """Lower class constructor and methods to synthetic FunctionDecl nodes.

        Both constructor and methods get an implicit 'this' first parameter.
        """
        result: list[FunctionDecl] = []
        class_name = class_decl.name
        from taiyaki_aot_compiler.parser.ast_nodes import Parameter as ASTParam
        this_param = ASTParam(name="this")

        # Build field initialization statements: this.field = initializer
        from taiyaki_aot_compiler.parser.ast_nodes import Block as ASTBlock
        field_init_stmts = []
        for cf in class_decl.field_declarations:
            if not cf.is_static and cf.initializer is not None:
                init_assign = AssignExpr(
                    op="=",
                    left=MemberExpr(
                        object=ThisExpr(),
                        property=Identifier(name=cf.name),
                        computed=False,
                    ),
                    right=cf.initializer,
                )
                field_init_stmts.append(ExpressionStmt(expression=init_assign))

        # Constructor → __ClassName_constructor(this, param1, param2, ...)
        if class_decl.constructor:
            ctor = class_decl.constructor
            # Prepend field initializations before constructor body
            body = ASTBlock(body=field_init_stmts + list(ctor.body.body))
            synth = FunctionDecl(
                name=f"__{class_name}_constructor",
                params=[this_param] + list(ctor.params),
                body=body,
            )
            synth._is_constructor = True
            synth._class_name = class_name
            result.append(synth)
        elif field_init_stmts:
            # No explicit constructor but has field declarations — create synthetic constructor
            body = ASTBlock(body=field_init_stmts)
            synth = FunctionDecl(
                name=f"__{class_name}_constructor",
                params=[this_param],
                body=body,
            )
            synth._is_constructor = True
            synth._class_name = class_name
            result.append(synth)

        # Methods → __ClassName_methodName(this, param1, ...)
        for method in class_decl.methods:
            if method.is_getter:
                # Getter → __ClassName_get_name(this) → return type
                synth = FunctionDecl(
                    name=f"__{class_name}_get_{method.name}",
                    params=[this_param],
                    body=method.body,
                )
                synth._is_method = True
                synth._is_getter = True
                synth._class_name = class_name
                synth._method_name = method.name
                result.append(synth)
            elif method.is_setter:
                # Setter → __ClassName_set_name(this, value) → void
                synth = FunctionDecl(
                    name=f"__{class_name}_set_{method.name}",
                    params=[this_param] + list(method.params),
                    body=method.body,
                )
                synth._is_method = True
                synth._is_setter = True
                synth._class_name = class_name
                synth._method_name = method.name
                result.append(synth)
            else:
                synth = FunctionDecl(
                    name=f"__{class_name}_{method.name}",
                    params=[this_param] + list(method.params),
                    body=method.body,
                )
                synth._is_method = True
                synth._class_name = class_name
                synth._method_name = method.name
                result.append(synth)

        # Static methods → __ClassName_static_methodName(param1, ...)
        # No 'this' parameter for static methods
        for method in class_decl.static_methods:
            synth = FunctionDecl(
                name=f"__{class_name}_static_{method.name}",
                params=list(method.params),
                body=method.body,
            )
            synth._is_static_method = True
            synth._class_name = class_name
            synth._method_name = method.name
            result.append(synth)

        return result

    def _try_monomorphize(self, func_name: str, arg_types: list[MonoType],
                          filename: str,
                          call_expr: CallExpr | None = None) -> FunctionType | None:
        """Attempt to create a monomorphized clone of func_name for the given arg types.

        If an existing mono variant is compatible with the arg types, reuse it.
        Returns the FunctionType of the (new or existing) clone, or None if not possible.
        """
        import copy

        resolved_arg_types = [self._subst.apply(a) for a in arg_types]

        # Check existing mono variants for a compatible one
        if func_name in self._mono_variants:
            for mangled, _clone in self._mono_variants[func_name]:
                existing_ft = self._functions.get(mangled)
                if existing_ft is None:
                    continue
                resolved_ft = self._subst.apply(existing_ft)
                if not isinstance(resolved_ft, FunctionType):
                    continue
                # Check if all param types match
                if len(resolved_ft.param_types) != len(resolved_arg_types):
                    continue
                compatible = True
                for pt, at in zip(resolved_ft.param_types, resolved_arg_types):
                    rp = self._subst.apply(pt)
                    ra = self._subst.apply(at)
                    if type(rp) != type(ra) and not isinstance(rp, TypeVar):
                        compatible = False
                        break
                if compatible:
                    # Reuse this variant — unify and rewrite
                    if call_expr is not None:
                        self._mono_call_rewrites[id(call_expr)] = mangled
                    for i, arg_t in enumerate(arg_types):
                        if i < len(existing_ft.param_types):
                            try:
                                s = unify(self._subst.apply(existing_ft.param_types[i]),
                                          self._subst.apply(arg_t))
                                self._subst = s.compose(self._subst)
                            except UnificationError:
                                pass
                    return existing_ft

        # Find the original function declaration
        orig_decl = None
        for fd in self._func_decls:
            if fd.name == func_name:
                orig_decl = fd
                break
        if orig_decl is None:
            return None

        # Create a unique mangled name
        self._mono_counter += 1
        mangled = f"{func_name}__mono{self._mono_counter}"

        # Deep-copy the function declaration and rename it
        clone = copy.deepcopy(orig_decl)
        clone.name = mangled

        # Create fresh type signature
        param_types = [TypeVar() for _ in clone.params]
        ret_type = TypeVar()
        ft = FunctionType(param_types, ret_type)
        self._functions[mangled] = ft
        self._env[mangled] = ft

        # Register the clone
        self._func_decls.append(clone)
        if func_name not in self._mono_variants:
            self._mono_variants[func_name] = []
        self._mono_variants[func_name].append((mangled, clone))

        # Record call rewrite so HIR builder uses the mangled name
        if call_expr is not None:
            self._mono_call_rewrites[id(call_expr)] = mangled

        # Unify clone params with actual arg types
        for i, arg_t in enumerate(arg_types):
            if i < len(param_types):
                try:
                    s = unify(self._subst.apply(param_types[i]), self._subst.apply(arg_t))
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    return None

        # Check the clone's body to propagate types
        self._check_function_body(clone, filename)

        return ft

    def _register_function_sig(self, func: FunctionDecl):
        if func.name in self._type_stubs:
            # Use .d.ts stub types
            stub = self._type_stubs[func.name]
            # Match stub param count to actual param count
            param_types = list(stub.param_types[:len(func.params)])
            while len(param_types) < len(func.params):
                param_types.append(TypeVar())
            ft = FunctionType(param_types, stub.return_type)
        else:
            class_name = getattr(func, '_class_name', None)
            method_name = getattr(func, '_method_name', None)
            is_constructor = getattr(func, '_is_constructor', False)

            if class_name and class_name in self._classes:
                ct = self._classes[class_name]

                if method_name and method_name in ct.methods:
                    # Method: prepend 'this' (ClassType) to the method's FunctionType params
                    method_ft = ct.methods[method_name]
                    ft = FunctionType(
                        [ct] + list(method_ft.param_types),
                        method_ft.return_type,
                    )
                elif is_constructor:
                    # Constructor: this (ClassType) + user params, returns void
                    ctor_params = [TypeVar() for _ in func.params[1:]]  # skip 'this'
                    ft = FunctionType([ct] + ctor_params, VOID)
                else:
                    param_types = [ArrayType(TypeVar()) if p.is_rest else TypeVar() for p in func.params]
                    ret_type = TypeVar()
                    ft = FunctionType(param_types, ret_type)
            else:
                param_types = [ArrayType(TypeVar()) if p.is_rest else TypeVar() for p in func.params]
                ret_type = TypeVar()
                ft = FunctionType(param_types, ret_type)
        self._functions[func.name] = ft
        self._env[func.name] = ft

    def _check_function_body(self, func: FunctionDecl, filename: str):
        """Check a function body to gather type constraints."""
        old_env = dict(self._env)
        old_return = self._return_type
        old_func_name = self._current_func_name
        old_current_class = getattr(self, '_current_class', None)
        self._current_func_name = func.name
        # Track current class for super() calls
        self._current_class = getattr(func, '_class_name', None)

        ft = self._functions[func.name]

        for i, p in enumerate(func.params):
            self._env[p.name] = ft.param_types[i]
            # Infer type from default value if present
            if p.default is not None:
                default_t = self._infer_expr(p.default, filename)
                try:
                    s = unify(ft.param_types[i], default_t)
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    pass

        self._return_type = ft.return_type
        self._check_block(func.body, filename)

        self._env = old_env
        for name, ftype in self._functions.items():
            self._env[name] = ftype
        self._return_type = old_return
        self._current_func_name = old_func_name
        self._current_class = old_current_class

    def _finalize_function(self, func: FunctionDecl, filename: str) -> TypedFunction:
        """Finalize function: resolve types, check compilability."""
        old_env = dict(self._env)
        old_return = self._return_type
        self._node_types = {}
        self._current_func_name = func.name

        ft = self._functions[func.name]
        param_pairs: list[tuple[str, MonoType]] = []

        for i, p in enumerate(func.params):
            pt = ft.param_types[i]
            self._env[p.name] = pt
            param_pairs.append((p.name, pt))

        self._return_type = ft.return_type
        self._check_block(func.body, filename)

        resolved_ret = self._subst.apply(ft.return_type)
        # Default unresolved return type to void (no return statement)
        if isinstance(resolved_ret, TypeVar):
            resolved_ret = VOID
        # Async functions always return Promise<T>
        if func.is_async and not isinstance(resolved_ret, PromiseType):
            resolved_ret = PromiseType(resolved_ret)
        resolved_params = [(n, self._subst.apply(t)) for n, t in param_pairs]

        is_compilable = all(
            not isinstance(t, TypeVar) for _, t in resolved_params
        ) and not isinstance(resolved_ret, TypeVar)

        # If function uses JS builtins not supported natively, force fallback
        if func.name in self._needs_js_fallback:
            is_compilable = False

        # Generator functions always need JS runtime
        if getattr(func, 'is_generator', False):
            is_compilable = False

        # If this function was monomorphized, the original becomes QuickJS fallback
        # (mono variants are compiled natively instead)
        if func.name in self._mono_variants:
            is_compilable = False

        if not is_compilable:
            loc = self._make_diag_loc(func.loc, filename)
            # Build detailed list of unresolved parameters
            unresolved_parts = []
            for pname, ptype in resolved_params:
                if isinstance(ptype, TypeVar):
                    unresolved_parts.append(f"param '{pname}' (unknown type)")
            if isinstance(resolved_ret, TypeVar):
                unresolved_parts.append("return type (unknown)")
            detail = "; ".join(unresolved_parts) if unresolved_parts else "unresolved types"
            self.diag.warning(
                f"Function '{func.name}' has unresolved types, using QuickJS fallback\n"
                f"   | Unresolved: {detail}",
                location=loc,
                hint=f"Add a call site like {func.name}(...) so types can be inferred",
            )

        resolved_node_types = {k: self._subst.apply(v) for k, v in self._node_types.items()}

        self._env = old_env
        for name, ftype in self._functions.items():
            self._env[name] = ftype
        self._return_type = old_return

        # Collect default expressions
        defaults = [p.default for p in func.params]

        return TypedFunction(
            name=func.name,
            params=resolved_params,
            return_type=resolved_ret,
            node=func,
            node_types=resolved_node_types,
            is_compilable=is_compilable,
            defaults=defaults,
        )

    def _check_block(self, block: Block, filename: str):
        for stmt in block.body:
            self._check_stmt(stmt, filename)

    def _check_stmt(self, stmt: Statement, filename: str):
        if isinstance(stmt, VarDecl):
            self._check_var_decl(stmt, filename)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                val_type = self._infer_expr(stmt.value, filename)
                if self._return_type:
                    try:
                        s = unify(self._return_type, val_type)
                        self._subst = s.compose(self._subst)
                    except UnificationError as e:
                        loc = self._make_diag_loc(stmt.loc, filename)
                        self.diag.error(
                            f"Return type mismatch: {self._return_type!r} vs {val_type!r}",
                            location=loc,
                        )
        elif isinstance(stmt, IfStmt):
            self._check_if(stmt, filename)
        elif isinstance(stmt, WhileStmt):
            self._check_while(stmt, filename)
        elif isinstance(stmt, DoWhileStmt):
            self._check_block(stmt.body, filename)
            self._infer_expr(stmt.condition, filename)
        elif isinstance(stmt, ForStmt):
            self._check_for(stmt, filename)
        elif isinstance(stmt, ForOfStmt):
            self._check_for_of(stmt, filename)
        elif isinstance(stmt, ForInStmt):
            self._check_for_in(stmt, filename)
        elif isinstance(stmt, SwitchStmt):
            self._check_switch(stmt, filename)
        elif isinstance(stmt, ExpressionStmt):
            self._infer_expr(stmt.expression, filename)
        elif isinstance(stmt, ObjectDestructure):
            self._check_object_destructure(stmt, filename)
        elif isinstance(stmt, ArrayDestructure):
            self._check_array_destructure(stmt, filename)
        elif isinstance(stmt, ThrowStmt):
            # For throw new Error("msg"), just infer the args without class lookup
            if isinstance(stmt.argument, NewExpr) and stmt.argument.class_name in ("Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError", "URIError", "EvalError"):
                for arg in stmt.argument.arguments:
                    self._infer_expr(arg, filename)
            else:
                self._infer_expr(stmt.argument, filename)
        elif isinstance(stmt, TryCatchStmt):
            self._check_block(stmt.try_block, filename)
            if stmt.catch_block:
                if stmt.catch_param:
                    self._env[stmt.catch_param] = STRING  # error message as string
                self._check_block(stmt.catch_block, filename)
            if stmt.finally_block:
                self._check_block(stmt.finally_block, filename)
        elif isinstance(stmt, FunctionDecl):
            # Nested function declaration: treat as named closure
            arrow = self._nested_func_arrows.get(stmt.name)
            if not arrow:
                arrow = ArrowFunction(params=stmt.params, body=stmt.body)
                self._nested_func_arrows[stmt.name] = arrow
            # If already lifted, reuse its FunctionType for env (stable TypeVars)
            existing = self._arrow_lifted.get(id(arrow))
            if existing:
                _, _, existing_ft, _ = existing
                self._env[stmt.name] = existing_ft
                self._functions[stmt.name] = existing_ft
            elif stmt.name not in self._functions:
                # First encounter: pre-register in _functions so self-calls are direct (not captured)
                pre_params = [TypeVar() for _ in stmt.params]
                pre_ret = TypeVar()
                pre_ft = FunctionType(pre_params, pre_ret)
                self._env[stmt.name] = pre_ft
                self._functions[stmt.name] = pre_ft
            ft = self._infer_arrow(arrow, filename)
            self._env[stmt.name] = ft
            self._functions[stmt.name] = ft
        elif isinstance(stmt, LabeledStmt):
            self._check_stmt(stmt.body, filename)
        elif isinstance(stmt, Block):
            self._check_block(stmt, filename)
        elif isinstance(stmt, ImportDeclaration):
            pass  # Import declarations are resolved before inference
        elif isinstance(stmt, ExportDeclaration):
            if stmt.declaration is not None:
                self._check_stmt(stmt.declaration, filename)

    def _check_var_decl(self, decl: VarDecl, filename: str):
        init_type = self._infer_expr(decl.init, filename) if decl.init else None
        if init_type:
            self._env[decl.name] = init_type
        else:
            self._env[decl.name] = TypeVar()

    def _check_if(self, stmt: IfStmt, filename: str):
        self._infer_expr(stmt.condition, filename)
        self._check_block(stmt.consequent, filename)
        if isinstance(stmt.alternate, Block):
            self._check_block(stmt.alternate, filename)
        elif isinstance(stmt.alternate, IfStmt):
            self._check_if(stmt.alternate, filename)

    def _check_while(self, stmt: WhileStmt, filename: str):
        self._infer_expr(stmt.condition, filename)
        self._check_block(stmt.body, filename)

    def _check_for(self, stmt: ForStmt, filename: str):
        if isinstance(stmt.init, VarDecl):
            self._check_var_decl(stmt.init, filename)
        elif isinstance(stmt.init, ExpressionStmt):
            self._infer_expr(stmt.init.expression, filename)
        elif isinstance(stmt.init, Expression):
            self._infer_expr(stmt.init, filename)
        if stmt.condition:
            self._infer_expr(stmt.condition, filename)
        if stmt.update:
            self._infer_expr(stmt.update, filename)
        self._check_block(stmt.body, filename)

    def _check_for_in(self, stmt: ForInStmt, filename: str):
        self._infer_expr(stmt.object, filename)
        # for...in iterates over keys which are always strings
        self._env[stmt.var_name] = STRING
        self._check_block(stmt.body, filename)

    def _check_for_of(self, stmt: ForOfStmt, filename: str):
        iter_type = self._infer_expr(stmt.iterable, filename)
        resolved = self._subst.apply(iter_type)
        if isinstance(resolved, ArrayType):
            self._env[stmt.var_name] = resolved.element_type
        elif isinstance(resolved, StringType):
            self._env[stmt.var_name] = STRING
        else:
            self._env[stmt.var_name] = TypeVar()
        self._check_block(stmt.body, filename)

    def _check_switch(self, stmt: SwitchStmt, filename: str):
        self._infer_expr(stmt.discriminant, filename)
        for case in stmt.cases:
            if case.test is not None:
                self._infer_expr(case.test, filename)
            for body_stmt in case.body:
                self._check_stmt(body_stmt, filename)

    def _check_object_destructure(self, decl: ObjectDestructure, filename: str):
        init_type = self._infer_expr(decl.init, filename)
        resolved = self._subst.apply(init_type)
        # Infer default expression types
        for fname, default_expr in decl.defaults.items():
            self._infer_expr(default_expr, filename)
        for fname in decl.fields:
            # Use alias as local variable name if present, otherwise use field name
            local_name = decl.aliases.get(fname, fname)
            if isinstance(resolved, ObjectType) and fname in resolved.fields:
                self._env[local_name] = resolved.fields[fname]
            elif fname in decl.defaults:
                self._env[local_name] = self._infer_expr(decl.defaults[fname], filename)
            else:
                self._env[local_name] = TypeVar()
        # Rest: collect remaining fields into new ObjectType
        if decl.rest_name and isinstance(resolved, ObjectType):
            rest_fields = {k: v for k, v in resolved.fields.items() if k not in decl.fields}
            self._env[decl.rest_name] = ObjectType(fields=rest_fields)
        elif decl.rest_name:
            self._env[decl.rest_name] = TypeVar()

    def _check_array_destructure(self, decl: ArrayDestructure, filename: str):
        init_type = self._infer_expr(decl.init, filename)
        resolved = self._subst.apply(init_type)
        # Infer default expression types
        for name, default_expr in decl.defaults.items():
            self._infer_expr(default_expr, filename)
        if isinstance(resolved, ArrayType):
            for name in decl.names:
                self._env[name] = resolved.element_type
            if decl.rest_name:
                self._env[decl.rest_name] = resolved  # rest is same array type
        else:
            for name in decl.names:
                if name in decl.defaults:
                    self._env[name] = self._infer_expr(decl.defaults[name], filename)
                else:
                    self._env[name] = TypeVar()
            if decl.rest_name:
                self._env[decl.rest_name] = TypeVar()

    def _infer_expr(self, expr: Expression, filename: str) -> MonoType:
        ty = self._infer_expr_inner(expr, filename)
        self._node_types[id(expr)] = ty
        return ty

    def _infer_expr_inner(self, expr: Expression, filename: str) -> MonoType:
        if isinstance(expr, NumberLiteral):
            return NUMBER
        if isinstance(expr, StringLiteral):
            return STRING
        if isinstance(expr, BooleanLiteral):
            return BOOLEAN
        if isinstance(expr, NullLiteral):
            return NULL
        if isinstance(expr, Identifier):
            if expr.name in self._env:
                return self._subst.apply(self._env[expr.name])
            loc = self._make_diag_loc(expr.loc, filename)
            if expr.name in _JS_BUILTINS:
                self.diag.warning(f"'{expr.name}' is not natively compiled — will use JS runtime fallback", location=loc)
                if self._current_func_name:
                    self._needs_js_fallback.add(self._current_func_name)
            else:
                self.diag.error(f"Undefined variable: '{expr.name}'", location=loc)
            return TypeVar()

        if isinstance(expr, BinaryExpr):
            left_t = self._infer_expr(expr.left, filename)
            right_t = self._infer_expr(expr.right, filename)
            # Nullish coalescing: a ?? b → type of b (fallback)
            if expr.op == "??":
                return right_t
            resolved_l = self._subst.apply(left_t)
            resolved_r = self._subst.apply(right_t)
            result = binary_op_type(expr.op, resolved_l, resolved_r)
            if result:
                return result
            # For '+' with string coercion: don't unify TypeVar to string,
            # so parameters can remain as number when called with number args
            if expr.op == "+":
                if isinstance(resolved_l, StringType) and isinstance(resolved_r, TypeVar):
                    return STRING
                if isinstance(resolved_r, StringType) and isinstance(resolved_l, TypeVar):
                    return STRING
            try:
                s = unify(left_t, right_t)
                self._subst = s.compose(self._subst)
                resolved = self._subst.apply(left_t)
                result = binary_op_type(expr.op, resolved, resolved)
                if result:
                    return result
            except UnificationError:
                pass
            # Don't report errors when TypeVars are still unresolved
            resolved_l = self._subst.apply(left_t)
            resolved_r = self._subst.apply(right_t)
            if not isinstance(resolved_l, TypeVar) and not isinstance(resolved_r, TypeVar):
                loc = self._make_diag_loc(expr.loc, filename)
                self.diag.error(
                    f"Invalid binary operation: {resolved_l!r} {expr.op} {resolved_r!r}",
                    location=loc,
                )
            return TypeVar()

        if isinstance(expr, CompareExpr):
            left_t = self._infer_expr(expr.left, filename)
            right_t = self._infer_expr(expr.right, filename)
            result = compare_op_type(expr.op, self._subst.apply(left_t), self._subst.apply(right_t))
            if result:
                return result
            try:
                s = unify(left_t, right_t)
                self._subst = s.compose(self._subst)
            except UnificationError:
                pass
            return BOOLEAN

        if isinstance(expr, LogicalExpr):
            left_t = self._infer_expr(expr.left, filename)
            right_t = self._infer_expr(expr.right, filename)
            try:
                s = unify(left_t, right_t)
                self._subst = s.compose(self._subst)
            except UnificationError:
                pass
            return self._subst.apply(left_t)

        if isinstance(expr, UnaryExpr):
            operand_t = self._infer_expr(expr.operand, filename)
            result = unary_op_type(expr.op, self._subst.apply(operand_t))
            if result:
                return result
            return TypeVar()

        if isinstance(expr, UpdateExpr):
            self._infer_expr(expr.operand, filename)
            return NUMBER

        if isinstance(expr, ConditionalExpr):
            self._infer_expr(expr.condition, filename)
            then_t = self._infer_expr(expr.consequent, filename)
            else_t = self._infer_expr(expr.alternate, filename)
            try:
                s = unify(then_t, else_t)
                self._subst = s.compose(self._subst)
            except UnificationError:
                pass
            return self._subst.apply(then_t)

        if isinstance(expr, CallExpr):
            return self._infer_call(expr, filename)

        if isinstance(expr, MemberExpr):
            return self._infer_member(expr, filename)

        if isinstance(expr, AssignExpr):
            right_t = self._infer_expr(expr.right, filename)
            if expr.op == "=":
                # Simple assignment
                if isinstance(expr.left, Identifier):
                    if expr.left.name in self._env:
                        left_t = self._env[expr.left.name]
                        try:
                            s = unify(left_t, right_t)
                            self._subst = s.compose(self._subst)
                        except UnificationError:
                            pass
                    else:
                        self._env[expr.left.name] = right_t
                elif isinstance(expr.left, MemberExpr):
                    left_t = self._infer_expr(expr.left, filename)
                    try:
                        s = unify(left_t, right_t)
                        self._subst = s.compose(self._subst)
                    except UnificationError:
                        pass
                    # Setter inference: obj.prop = val → unify setter's params
                    obj_t = self._subst.apply(self._infer_expr(expr.left.object, filename))
                    if isinstance(obj_t, ClassType) and isinstance(expr.left.property, Identifier):
                        setter_name = f"__{obj_t.name}_set_{expr.left.property.name}"
                        if setter_name in self._functions:
                            st = self._functions[setter_name]
                            # Unify this param
                            if len(st.param_types) >= 1:
                                try:
                                    s = unify(self._subst.apply(st.param_types[0]), obj_t)
                                    self._subst = s.compose(self._subst)
                                except UnificationError:
                                    pass
                            # Unify value param
                            if len(st.param_types) >= 2:
                                try:
                                    s = unify(self._subst.apply(st.param_types[1]), self._subst.apply(right_t))
                                    self._subst = s.compose(self._subst)
                                except UnificationError:
                                    pass
                return right_t
            elif expr.op in ("&&=", "||=", "??="):
                # Logical assignment: x &&= y → x = x && y
                left_t = self._infer_expr(expr.left, filename)
                resolved_l = self._subst.apply(left_t)
                resolved_r = self._subst.apply(right_t)
                try:
                    s = unify(resolved_l, resolved_r)
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    pass
                return resolved_l
            else:
                # Augmented assignment: +=, -=, &=, etc.
                left_t = self._infer_expr(expr.left, filename)
                resolved_l = self._subst.apply(left_t)
                resolved_r = self._subst.apply(right_t)
                base_op = expr.op[:-1]  # "+=" → "+"
                result_t = binary_op_type(base_op, resolved_l, resolved_r)
                if result_t is None:
                    result_t = resolved_l  # fallback to left type
                if isinstance(expr.left, Identifier):
                    self._env[expr.left.name] = result_t
                return result_t

        if isinstance(expr, TemplateLiteral):
            for sub_expr in expr.expressions:
                self._infer_expr(sub_expr, filename)
            return STRING

        if isinstance(expr, SpreadElement):
            # ...arr → element type of arr
            arr_t = self._infer_expr(expr.argument, filename)
            resolved = self._subst.apply(arr_t)
            if isinstance(resolved, ArrayType):
                return resolved.element_type
            return TypeVar()

        if isinstance(expr, SequenceExpr):
            # (a, b, c) → evaluates all, returns type of last
            result_type: MonoType = VOID
            for sub in expr.expressions:
                result_type = self._infer_expr(sub, filename)
            return result_type

        if isinstance(expr, AwaitExpr):
            inner = self._infer_expr(expr.argument, filename)
            resolved = self._subst.apply(inner)
            if isinstance(resolved, PromiseType):
                return resolved.inner_type
            return inner  # await on non-Promise just returns the value

        if isinstance(expr, ArrayLiteral):
            if expr.elements:
                elem_types = []
                for e in expr.elements:
                    t = self._infer_expr(e, filename)
                    if isinstance(e, SpreadElement):
                        # Spread infers to element type, already handled
                        elem_types.append(t)
                    else:
                        elem_types.append(t)
                # Unify all element types
                base = elem_types[0]
                for et in elem_types[1:]:
                    try:
                        s = unify(base, et)
                        self._subst = s.compose(self._subst)
                    except UnificationError:
                        pass
                return ArrayType(self._subst.apply(base))
            return ArrayType(TypeVar())

        if isinstance(expr, ObjectLiteralExpr):
            fields: dict[str, MonoType] = {}
            for _, spread_expr in expr.spreads:
                spread_t = self._infer_expr(spread_expr, filename)
                spread_resolved = self._subst.apply(spread_t)
                if isinstance(spread_resolved, ObjectType):
                    fields.update(spread_resolved.fields)
            for fname, fexpr in expr.properties:
                fields[fname] = self._infer_expr(fexpr, filename)
            return ObjectType(fields=fields)

        if isinstance(expr, ArrowFunction):
            return self._infer_arrow(expr, filename)

        if isinstance(expr, NewExpr):
            return self._infer_new_expr(expr, filename)

        if isinstance(expr, ThisExpr):
            if "this" in self._env:
                return self._subst.apply(self._env["this"])
            return TypeVar()

        if isinstance(expr, SuperCall):
            # super(args) — unify with parent constructor params
            arg_types = [self._infer_expr(a, filename) for a in expr.arguments]
            # Find parent class from current function context
            if hasattr(self, '_current_class') and self._current_class:
                decl = self._class_decls.get(self._current_class)
                if decl and decl.extends:
                    parent_ctor = f"__{decl.extends}_constructor"
                    if parent_ctor in self._functions:
                        ctor_ft = self._functions[parent_ctor]
                        # param_types[0] is 'this', user args start at [1]
                        user_params = ctor_ft.param_types[1:]
                        for at, pt in zip(arg_types, user_params):
                            try:
                                s = unify(self._subst.apply(pt), self._subst.apply(at))
                                self._subst = s.compose(self._subst)
                            except UnificationError:
                                pass
            return VOID

        return TypeVar()

    def _infer_call(self, expr: CallExpr, filename: str) -> MonoType:
        # console.log/error/warn is polymorphic + variadic — infer args but skip unification
        if (isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and expr.callee.object.name == "console"
                and isinstance(expr.callee.property, Identifier)
                and expr.callee.property.name in ("log", "error", "warn")):
            for a in expr.arguments:
                self._infer_expr(a, filename)
            return VOID

        # JSON.parse — each call gets a fresh TypeVar so calls don't interfere
        if (isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and expr.callee.object.name == "JSON"
                and isinstance(expr.callee.property, Identifier)
                and expr.callee.property.name == "parse"):
            for a in expr.arguments:
                self._infer_expr(a, filename)
            return TypeVar()  # Fresh TypeVar per call site

        # FFI opaque class static method call: Database.open(...)
        if (self._ffi_info is not None
                and isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and isinstance(expr.callee.property, Identifier)):
            class_name = expr.callee.object.name
            method_name = expr.callee.property.name
            if class_name in self._ffi_info.opaque_classes:
                oc = self._ffi_info.opaque_classes[class_name]
                if method_name in oc.static_methods:
                    for a in expr.arguments:
                        self._infer_expr(a, filename)
                    return oc.static_methods[method_name].return_type

        # FFI opaque class instance method call: db.execute(...)
        if (self._ffi_info is not None
                and isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.property, Identifier)):
            obj_t = self._infer_expr(expr.callee.object, filename)
            resolved = self._subst.apply(obj_t)
            if isinstance(resolved, OpaquePointerType):
                method_name = expr.callee.property.name
                if resolved.name in self._ffi_info.opaque_classes:
                    oc = self._ffi_info.opaque_classes[resolved.name]
                    if method_name in oc.instance_methods:
                        for a in expr.arguments:
                            self._infer_expr(a, filename)
                        return oc.instance_methods[method_name].return_type

        # Object.assign(target, source) / Object.freeze(obj) — return first arg's type
        if (isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and expr.callee.object.name == "Object"
                and isinstance(expr.callee.property, Identifier)
                and expr.callee.property.name in ("assign", "freeze")):
            arg_types = [self._infer_expr(a, filename) for a in expr.arguments]
            if arg_types:
                return arg_types[0]
            return TypeVar()

        # Array.of(...args) — create array from arguments
        if (isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and expr.callee.object.name == "Array"
                and isinstance(expr.callee.property, Identifier)
                and expr.callee.property.name == "of"):
            arg_types = [self._infer_expr(a, filename) for a in expr.arguments]
            if arg_types:
                return ArrayType(self._subst.apply(arg_types[0]))
            return ArrayType(NUMBER)

        # Array.from(iterable) — convert string to char array, array to array copy
        if (isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and expr.callee.object.name == "Array"
                and isinstance(expr.callee.property, Identifier)
                and expr.callee.property.name == "from"):
            arg_types = [self._infer_expr(a, filename) for a in expr.arguments]
            if arg_types:
                resolved = self._subst.apply(arg_types[0])
                if isinstance(resolved, StringType):
                    return ArrayType(STRING)
                if isinstance(resolved, ArrayType):
                    return resolved
            return ArrayType(TypeVar())

        # Static method calls: ClassName.method(args)
        # Use the synthetic function's TypeVars directly for proper unification
        if (isinstance(expr.callee, MemberExpr)
                and isinstance(expr.callee.object, Identifier)
                and isinstance(expr.callee.property, Identifier)
                and expr.callee.object.name in self._class_decls):
            class_name = expr.callee.object.name
            method_name = expr.callee.property.name
            func_name = f"__{class_name}_static_{method_name}"
            if func_name in self._functions:
                ft = self._functions[func_name]
                arg_types = [self._infer_expr(a, filename) for a in expr.arguments]
                for arg_t, param_t in zip(arg_types, ft.param_types):
                    try:
                        s = unify(self._subst.apply(param_t), self._subst.apply(arg_t))
                        self._subst = s.compose(self._subst)
                    except UnificationError:
                        pass
                self._node_types[id(expr)] = self._subst.apply(ft.return_type)
                return self._subst.apply(ft.return_type)

        # Built-in global functions
        if isinstance(expr.callee, Identifier):
            if expr.callee.name in ("parseInt", "parseFloat", "Number"):
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return NUMBER
            if expr.callee.name == "String":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return STRING
            if expr.callee.name == "Boolean":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return BOOLEAN
            if expr.callee.name == "isNaN":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return BOOLEAN
            if expr.callee.name == "readFile":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return STRING
            if expr.callee.name == "writeFile":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return VOID
            if expr.callee.name == "exec":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return STRING
            if expr.callee.name == "httpGet":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return STRING
            if expr.callee.name == "httpPost":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return STRING
            if expr.callee.name == "setTimeout":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return PromiseType(VOID)
            if expr.callee.name == "fetch":
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return PromiseType(STRING)

            # FFI functions (from @ffi pragmas)
            if self._ffi_info is not None and expr.callee.name in self._ffi_info.functions:
                ffi_fn = self._ffi_info.functions[expr.callee.name]
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return ffi_fn.return_type

            # Raylib built-in functions
            _RAYLIB_BUILTINS = {
                # Core window
                "initWindow": VOID,       # (number, number, string) → void
                "closeWindow": VOID,      # () → void
                "windowShouldClose": BOOLEAN,  # () → boolean
                "setTargetFPS": VOID,     # (number) → void
                "getScreenWidth": NUMBER,
                "getScreenHeight": NUMBER,
                "getFrameTime": NUMBER,   # () → number (delta time)
                "getTime": NUMBER,        # () → number (elapsed time)
                "getFPS": NUMBER,         # () → number
                # Drawing
                "beginDrawing": VOID,
                "endDrawing": VOID,
                "clearBackground": VOID,  # (color) → void
                "drawRectangle": VOID,    # (x, y, w, h, color) → void
                "drawRectangleLines": VOID,
                "drawCircle": VOID,       # (x, y, radius, color) → void
                "drawCircleLines": VOID,
                "drawLine": VOID,         # (x1, y1, x2, y2, color) → void
                "drawText": VOID,         # (text, x, y, fontSize, color) → void
                "drawTriangle": VOID,     # (x1,y1,x2,y2,x3,y3,color) → void
                "measureText": NUMBER,    # (text, fontSize) → number
                # Extended shapes (Phase 3)
                "drawRectanglePro": VOID,       # (x,y,w,h,originX,originY,rotation,color)
                "drawRectangleRounded": VOID,   # (x,y,w,h,roundness,segments,color)
                "drawRectangleGradientV": VOID, # (x,y,w,h,color1,color2)
                "drawRectangleGradientH": VOID, # (x,y,w,h,color1,color2)
                "drawLineEx": VOID,             # (x1,y1,x2,y2,thick,color)
                "drawPixel": VOID,              # (x,y,color)
                "drawCircleSector": VOID,       # (cx,cy,radius,startAngle,endAngle,segments,color)
                # Textures
                "loadFont": VOID,         # (path, size) → void (sets global font)
                "loadTexture": NUMBER,    # (path) → textureId (number handle)
                "drawTexture": VOID,      # (textureId, x, y, color) → void
                "unloadTexture": VOID,    # (textureId) → void
                # Texture Pro (Phase 3)
                "drawTextureRec": VOID,         # (texId,srcX,srcY,srcW,srcH,destX,destY,color)
                "drawTexturePro": VOID,         # (texId,srcX,srcY,srcW,srcH,destX,destY,destW,destH,originX,originY,rotation,color)
                "getTextureWidth": NUMBER,      # (texId) → number
                "getTextureHeight": NUMBER,     # (texId) → number
                # Text Pro (Phase 3)
                "drawTextEx": VOID,             # (text,x,y,fontSize,spacing,color) uses loaded font
                "measureTextEx": NUMBER,        # (text,fontSize,spacing) → width using loaded font
                # Input: keyboard
                "isKeyDown": BOOLEAN,     # (key) → boolean
                "isKeyPressed": BOOLEAN,  # (key) → boolean
                "isKeyReleased": BOOLEAN,
                "getKeyPressed": NUMBER,  # () → number (key code)
                "getCharPressed": NUMBER, # () → number (char code) (Phase 3)
                "isKeyUp": BOOLEAN,       # (key) → boolean (Phase 3)
                # Input: mouse
                "getMouseX": NUMBER,
                "getMouseY": NUMBER,
                "isMouseButtonDown": BOOLEAN,
                "isMouseButtonPressed": BOOLEAN,
                "isMouseButtonReleased": BOOLEAN,
                "getMouseWheelMove": NUMBER,    # () → number (Phase 3)
                # Color helper
                "color": NUMBER,          # (r, g, b, a) → packed color
                "colorAlpha": NUMBER,     # (color, alpha) → packed color (Phase 3)
                # Window extended (Phase 3)
                "toggleFullscreen": VOID,       # () → void
                "setWindowSize": VOID,          # (w, h) → void
                "setWindowTitle": VOID,         # (title) → void
                "setConfigFlags": VOID,         # (flags) → void
                "isWindowFocused": BOOLEAN,     # () → boolean
                "isWindowResized": BOOLEAN,     # () → boolean
                # Audio device (Phase 1)
                "initAudioDevice": VOID,        # () → void
                "closeAudioDevice": VOID,       # () → void
                "setMasterVolume": VOID,        # (vol) → void
                "getMasterVolume": NUMBER,      # () → number
                # Sound (Phase 1) — handle-based
                "loadSound": NUMBER,            # (path) → soundId
                "playSound": VOID,              # (id) → void
                "stopSound": VOID,              # (id) → void
                "pauseSound": VOID,             # (id) → void
                "resumeSound": VOID,            # (id) → void
                "setSoundVolume": VOID,         # (id, vol) → void
                "setSoundPitch": VOID,          # (id, pitch) → void
                "isSoundPlaying": BOOLEAN,      # (id) → boolean
                "unloadSound": VOID,            # (id) → void
                # Music (Phase 1) — handle-based
                "loadMusic": NUMBER,            # (path) → musicId
                "playMusic": VOID,              # (id) → void
                "stopMusic": VOID,              # (id) → void
                "pauseMusic": VOID,             # (id) → void
                "resumeMusic": VOID,            # (id) → void
                "updateMusic": VOID,            # (id) → void
                "setMusicVolume": VOID,         # (id, vol) → void
                "isMusicPlaying": BOOLEAN,      # (id) → boolean
                "getMusicTimeLength": NUMBER,   # (id) → number
                "getMusicTimePlayed": NUMBER,   # (id) → number
                "unloadMusic": VOID,            # (id) → void
                # Camera2D (Phase 2)
                "beginMode2D": VOID,            # (offsetX,offsetY,targetX,targetY,rotation,zoom)
                "endMode2D": VOID,              # () → void
                # Collision (Phase 2)
                "checkCollisionRecs": BOOLEAN,        # (x1,y1,w1,h1,x2,y2,w2,h2)
                "checkCollisionCircles": BOOLEAN,     # (cx1,cy1,r1,cx2,cy2,r2)
                "checkCollisionCircleRec": BOOLEAN,   # (cx,cy,r,rx,ry,rw,rh)
                "checkCollisionPointRec": BOOLEAN,    # (px,py,rx,ry,rw,rh)
                "checkCollisionPointCircle": BOOLEAN, # (px,py,cx,cy,r)
                # Random (Phase 2)
                "getRandomValue": NUMBER,       # (min, max) → number
                # Gamepad (Phase 5)
                "isGamepadAvailable": BOOLEAN,        # (gamepad) → boolean
                "isGamepadButtonDown": BOOLEAN,       # (gamepad, button) → boolean
                "isGamepadButtonPressed": BOOLEAN,    # (gamepad, button) → boolean
                "isGamepadButtonReleased": BOOLEAN,   # (gamepad, button) → boolean
                "getGamepadAxisMovement": NUMBER,     # (gamepad, axis) → number
                "getGamepadAxisCount": NUMBER,        # (gamepad) → number
                "getGamepadButtonPressed": NUMBER,    # () → number
                "getGamepadName": BOOLEAN,            # (gamepad) → boolean (exists check)
                # Music extended
                "seekMusic": VOID,             # (id, position) → void
                "setMusicPitch": VOID,         # (id, pitch) → void
                # Audio device extended
                "isAudioDeviceReady": BOOLEAN,  # () → boolean
                # Font extended
                "unloadFont": VOID,            # () → void
                # Text measurement extended
                "measureTextExY": NUMBER,      # (text, fontSize, spacing) → height
                # Texture extended
                "drawTextureScaled": VOID,     # (texId, x, y, scale, color) → void
                "isTextureValid": BOOLEAN,     # (texId) → boolean
                # Camera2D extended
                "getWorldToScreen2DX": NUMBER, # (worldX,worldY,camOX,camOY,camTX,camTY,camRot,camZoom) → number
                "getWorldToScreen2DY": NUMBER, # same → number
                # Gamepad extended
                "isGamepadButtonUp": BOOLEAN,  # (gamepad, button) → boolean
                # File system
                "fileExists": BOOLEAN,         # (path) → boolean
                "directoryExists": BOOLEAN,    # (path) → boolean
            }
            if expr.callee.name in _RAYLIB_BUILTINS:
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return _RAYLIB_BUILTINS[expr.callee.name]

            # Clay UI built-in functions
            _CLAY_BUILTINS = {
                "clayInit": VOID,          # (width, height) → void
                "clayLoadFont": NUMBER,    # (path, size) → fontId
                "claySetDimensions": VOID, # (width, height) → void
                "claySetPointer": VOID,    # (x, y, down) → void
                "clayUpdateScroll": VOID,  # (dx, dy, dt) → void
                "clayBeginLayout": VOID,   # () → void
                "clayEndLayout": VOID,     # () → void
                "clayRender": VOID,        # () → void
                "clayOpen": VOID,          # (id, sizingW, sizingH, ...) → void
                "clayOpenAligned": VOID,   # (id, sizingW, sizingH, ..., alignX, alignY) → void
                "clayClose": VOID,         # () → void
                "clayText": VOID,          # (text, fontSize, fontId, r, g, b, a) → void
                "clayPointerOver": BOOLEAN, # (id) → boolean
            }
            if expr.callee.name in _CLAY_BUILTINS:
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return _CLAY_BUILTINS[expr.callee.name]

            # Clay TUI built-in functions (termbox2 backend)
            _CLAY_TUI_BUILTINS = {
                "clayTuiInit": VOID,              # (colorMode) → void
                "clayTuiDestroy": VOID,           # () → void
                "clayTuiSetDimensions": VOID,     # (w, h) → void
                "clayTuiBeginLayout": VOID,       # () → void
                "clayTuiEndLayout": VOID,         # () → void
                "clayTuiRender": VOID,            # () → void
                "clayTuiOpen": VOID,              # (id, sizingW, sizingH, ...) → void
                "clayTuiCloseElement": VOID,      # () → void
                "clayTuiText": VOID,              # (text, fontSize, fontId, r, g, b, a) → void
                "clayTuiSetPointer": VOID,        # (x, y, down) → void
                "clayTuiPointerOver": BOOLEAN,    # (id) → boolean
                "clayTuiPeekEvent": NUMBER,       # (timeoutMs) → eventType
                "clayTuiPollEvent": NUMBER,       # () → eventType
                "clayTuiEventType": NUMBER,       # () → eventType
                "clayTuiEventKey": NUMBER,        # () → keyCode
                "clayTuiEventCh": NUMBER,         # () → charCode
                "clayTuiEventW": NUMBER,          # () → resize width
                "clayTuiEventH": NUMBER,          # () → resize height
                "clayTuiTermWidth": NUMBER,       # () → terminal width
                "clayTuiTermHeight": NUMBER,      # () → terminal height
                "clayTuiEventMod": NUMBER,        # () → modifier keys (Phase 4)
                # Border (Phase 4)
                "clayTuiBorder": VOID,            # (r,g,b,a, top,right,bottom,left, cornerRadius)
                # Alignment (Phase 4)
                "clayTuiAlign": VOID,             # (ax, ay)
                # Scroll (Phase 4)
                "clayTuiScroll": VOID,            # (h, v) — enable scroll axes
                "clayTuiUpdateScroll": VOID,      # (dx, dy, dt)
                # Open indexed (Phase 4)
                "clayTuiOpenI": VOID,             # (id, index, sizingW, sizingH, ...) — for lists
                # Text buffer (Phase 4)
                "clayTuiTextbufClear": VOID,      # () → void
                "clayTuiTextbufPutchar": VOID,    # (ch) → void
                "clayTuiTextbufBackspace": VOID,  # () → void
                "clayTuiTextbufDelete": VOID,     # () → void
                "clayTuiTextbufCursorLeft": VOID, # () → void
                "clayTuiTextbufCursorRight": VOID,# () → void
                "clayTuiTextbufHome": VOID,       # () → void
                "clayTuiTextbufEnd": VOID,        # () → void
                "clayTuiTextbufLen": NUMBER,      # () → number
                "clayTuiTextbufCursor": NUMBER,   # () → number
                "clayTuiTextbufRender": VOID,     # (fontSize, fontId, r, g, b, a) → void
                # Phase B extensions
                "clayTuiTextbufCopy": STRING,           # () → string (buffer content)
                "clayTuiTextbufRenderRange": VOID,      # (start, len, fontSize, fontId, r, g, b, a) → void
                "clayTuiTextChar": VOID,                # (ch, fontSize, fontId, r, g, b, a) → void
                "clayTuiPointerOverI": BOOLEAN,         # (id, index) → boolean
                "clayTuiEventMouseX": NUMBER,           # () → number
                "clayTuiEventMouseY": NUMBER,           # () → number
                "clayTuiRgb": NUMBER,                   # (r, g, b) → number (pack terminal RGB)
                "clayTuiBgEx": VOID,                    # (r, g, b, a, attr) → void
                "clayTuiTextEx": VOID,                  # (text, fontSize, fontId, r, g, b, a, bgR, bgG, bgB, bgA, attr) → void
                "clayTuiFloating": VOID,                # (offsetX, offsetY, zIndex, attachElem, attachParent) → void
            }
            if expr.callee.name in _CLAY_TUI_BUILTINS:
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return _CLAY_TUI_BUILTINS[expr.callee.name]

            # Clay GUI extension builtins (scroll/floating/border for raylib path)
            _CLAY_GUI_EXT_BUILTINS = {
                "clayScroll": VOID,          # (h: number, v: number)
                "clayFloating": VOID,        # (offsetX: number, offsetY: number, z: number)
                "clayBorder": VOID,          # (r, g, b, a, top, right, bottom, left, radius)
                "clayOpenI": VOID,           # same as clayOpen but with numeric index
                "clayPointerOverI": BOOLEAN, # (id: string, index: number)
                "claySetMeasureTextRaylib": VOID,
                "clayLoadFontCjk": NUMBER,   # (path: string, size: number)
                "claySetCustom": VOID,       # (chartId: number)
                "clayDestroy": VOID,
                "clayRenderRaylib": VOID,
                "clayRegisterResizeCallback": VOID,
                "claySetBgColor": VOID,      # (r, g, b)
            }
            if expr.callee.name in _CLAY_GUI_EXT_BUILTINS:
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return _CLAY_GUI_EXT_BUILTINS[expr.callee.name]

            # Interactive Widget builtins
            _UI_BUILTINS = {
                "beginFrame": VOID,
                "endFrame": VOID,
                "buttonOpen": VOID,       # (id: string, kind: number, size: number)
                "buttonClose": VOID,
                "checkboxOpen": VOID,     # (id: string, checked: number, size: number)
                "checkboxClose": VOID,
                "radioOpen": VOID,        # (id: string, index: number, selected: number, size: number)
                "radioClose": VOID,
                "toggleOpen": VOID,       # (id: string, on: number, size: number)
                "toggleClose": VOID,
                "textInput": VOID,        # (id: string, buf: number, w: number, size: number)
                "slider": VOID,           # (id: string, value: number, min: number, max: number, w: number)
                "menuItemOpen": VOID,     # (id: string, index: number, cursor: number, size: number)
                "menuItemClose": VOID,
                "tabButtonOpen": VOID,    # (id: string, index: number, active: number, size: number)
                "tabButtonClose": VOID,
                "numberStepper": VOID,    # (id: string, value: number, min: number, max: number, size: number)
                "searchBar": VOID,        # (id: string, buf: number, w: number, size: number)
                "listItemOpen": VOID,     # (id: string, index: number, selected: number, size: number)
                "listItemClose": VOID,
                "clicked": BOOLEAN,       # (id: string) → was clicked this frame
                "hovered": BOOLEAN,       # (id: string) → is hovered
                "toggled": BOOLEAN,       # (id: string) → was toggled this frame
                "sliderValue": NUMBER,    # (id: string) → current slider value
                "focusNext": VOID,
                "focusPrev": VOID,
                "uiKeyPressed": NUMBER,     # () → unified key code
                "uiCharPressed": NUMBER,    # () → character code
                # Part 2B - Forms
                "textareaInput": VOID,
                "switchOpen": VOID,
                "switchClose": VOID,
                "ratingOpen": VOID,
                "ratingClose": VOID,
                "ratingValue": NUMBER,
                "segmentButtonOpen": VOID,
                "segmentButtonClose": VOID,
                # Part 2C - Navigation
                "navPush": VOID,
                "navPop": VOID,
                "navCurrent": NUMBER,
                "navDepth": NUMBER,
                # Part 2D - Overlay
                "accordionOpen": VOID,
                "accordionClose": VOID,
                "accordionToggled": BOOLEAN,
                "dropdownOpen": VOID,
                "dropdownClose": VOID,
                "dropdownIsOpen": BOOLEAN,
                "tooltipBegin": VOID,
                "tooltipEnd": VOID,
                "toastShow": VOID,
                "toastRender": VOID,
                # Part 2E - Charts
                "chartInit": VOID,
                "chartSet": VOID,
                "chartColor": VOID,
                "chartRender": VOID,
                # Part 2F - Markdown
                "markdownRender": VOID,
                # Part 2G - Other
                "uiSpinnerChar": STRING,
                "uiFrameCount": NUMBER,
                "uiStyle": NUMBER,
                "uiStyleMerge": NUMBER,
                "uiStyleSize": NUMBER,
                "uiStyleKind": NUMBER,
                "uiStyleFlex": NUMBER,
            }
            if expr.callee.name in _UI_BUILTINS:
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return _UI_BUILTINS[expr.callee.name]

            # Game Framework builtins
            _GF_BUILTINS = {
                "gfClamp": NUMBER,           # (v, lo, hi)
                "gfLerp": NUMBER,            # (a, b, t)
                "gfRand": NUMBER,            # (max)
                "gfRandRange": NUMBER,       # (min, max)
                "gfRgba": NUMBER,            # (r, g, b, a)
                "gfDrawBar": VOID,           # (x, y, w, h, val, max, fg, bg)
                "gfDrawBox": VOID,           # (x, y, w, h, bg, border)
                "gfDrawNum": VOID,           # (x, y, n, sz, col)
                "gfDrawFPS": VOID,           # (x, y, sz, col)
                "gfDrawTile": VOID,          # (texId, tileId, cols, srcSz, dstSz, dx, dy)
                "gfDrawSprite": VOID,        # (texId, frame, srcW, srcH, dx, dy, dstW, dstH)
                "gfDrawFade": VOID,          # (alpha, w, h)
                "gfGetDirection": NUMBER,    # ()
                "gfConfirmPressed": BOOLEAN, # ()
                "gfCancelPressed": BOOLEAN,  # ()
                "gfMenuCursor": NUMBER,      # (cursor, count)
                "gfAnimate": NUMBER,         # (counter, maxFrames, speed)
                "gfTimerSet": VOID,          # (slot, duration)
                "gfTimerRepeat": VOID,       # (slot, interval)
                "gfTimerTick": VOID,         # (dt)
                "gfTimerActive": BOOLEAN,    # (slot)
                "gfTimerDone": BOOLEAN,      # (slot)
                "gfTimerCancel": VOID,       # (slot)
                "gfTweenStart": VOID,        # (slot, duration, easing)
                "gfTweenTick": VOID,         # (dt)
                "gfTweenValue": NUMBER,      # (slot)
                "gfTweenActive": BOOLEAN,    # (slot)
                "gfTweenDone": BOOLEAN,      # (slot)
                "gfInterpolate": NUMBER,     # (start, end, t)
                "gfEaseLinear": NUMBER,      # (t)
                "gfEaseInQuad": NUMBER,
                "gfEaseOutQuad": NUMBER,
                "gfEaseInOutQuad": NUMBER,
                "gfEaseInCubic": NUMBER,
                "gfEaseOutCubic": NUMBER,
                "gfEaseInOutCubic": NUMBER,
                "gfEaseOutBounce": NUMBER,
                "gfEaseOutElastic": NUMBER,
                "gfShakeStart": VOID,        # (intensity, duration)
                "gfShakeUpdate": VOID,       # (dt)
                "gfShakeX": NUMBER,          # ()
                "gfShakeY": NUMBER,          # ()
                "gfShakeActive": BOOLEAN,    # ()
                "gfTransitionStart": VOID,   # (duration, nextScene)
                "gfTransitionUpdate": VOID,  # (dt)
                "gfTransitionAlpha": NUMBER, # ()
                "gfTransitionDone": BOOLEAN, # ()
                "gfTransitionNextScene": NUMBER, # ()
                "gfPhysGravity": NUMBER,     # (vy, g, dt)
                "gfPhysFriction": NUMBER,    # (v, friction, dt)
                "gfPhysClamp": NUMBER,       # (val, min, max)
                "gfParticleEmit": VOID,      # (x, y, vx, vy, life, color)
                "gfParticleUpdate": VOID,    # (dt, gravity)
                "gfParticleDraw": VOID,      # (size)
                "gfParticleCount": NUMBER,   # ()
                "gfParticleClear": VOID,     # ()
                "gfGridToPx": NUMBER,        # (grid, tileSize)
                "gfPxToGrid": NUMBER,        # (px, tileSize)
                "gfGridIndex": NUMBER,       # (x, y, cols)
                "gfGridInBounds": BOOLEAN,   # (x, y, cols, rows)
                "gfManhattan": NUMBER,       # (x1, y1, x2, y2)
                "gfChebyshev": NUMBER,       # (x1, y1, x2, y2)
                "gfFsmInit": VOID,           # (id, state)
                "gfFsmSet": VOID,            # (id, state)
                "gfFsmTick": VOID,           # (id)
                "gfFsmState": NUMBER,        # (id)
                "gfFsmPrev": NUMBER,         # (id)
                "gfFsmFrames": NUMBER,       # (id)
                "gfFsmJustEntered": BOOLEAN, # (id)
                "gfPoolAlloc": NUMBER,       # (poolId)
                "gfPoolFree": VOID,          # (poolId, index)
                "gfPoolActive": BOOLEAN,     # (poolId, index)
                "gfPoolCount": NUMBER,       # (poolId)
                "gfPoolClear": VOID,         # (poolId)
            }
            if expr.callee.name in _GF_BUILTINS:
                for a in expr.arguments:
                    self._infer_expr(a, filename)
                return _GF_BUILTINS[expr.callee.name]

        callee_t = self._infer_expr(expr.callee, filename)
        arg_types = [self._infer_expr(a, filename) for a in expr.arguments]

        resolved = self._subst.apply(callee_t)
        if isinstance(resolved, FunctionType):
            # For missing args with defaults, infer default type and unify
            if (len(arg_types) < len(resolved.param_types)
                    and isinstance(expr.callee, Identifier)):
                func_name = expr.callee.name
                for func_decl in self._func_decls:
                    if func_decl.name == func_name:
                        for i in range(len(arg_types), len(resolved.param_types)):
                            if i < len(func_decl.params) and func_decl.params[i].default is not None:
                                default_t = self._infer_expr(func_decl.params[i].default, filename)
                                try:
                                    s = unify(resolved.param_types[i], default_t)
                                    self._subst = s.compose(self._subst)
                                except UnificationError:
                                    pass
                        break

            # Check if last param is a rest parameter (must be declared with ...rest in source)
            has_rest = False
            if isinstance(expr.callee, Identifier):
                _fd = None
                for _fd_candidate in self._func_decls:
                    if _fd_candidate.name == expr.callee.name:
                        _fd = _fd_candidate
                        break
                if _fd and _fd.params and _fd.params[-1].is_rest:
                    has_rest = True
            normal_param_count = len(resolved.param_types) - 1 if has_rest else len(resolved.param_types)

            # Try unifying each argument with the corresponding parameter.
            # On type mismatch for a known function, attempt monomorphization.
            mono_needed = False
            for i, (arg_t, param_t) in enumerate(zip(arg_types[:normal_param_count], resolved.param_types[:normal_param_count])):
                # JS allows passing callbacks with fewer params than expected.
                a_resolved = self._subst.apply(arg_t)
                p_resolved = self._subst.apply(param_t)
                if (isinstance(a_resolved, FunctionType)
                        and isinstance(p_resolved, FunctionType)
                        and len(a_resolved.param_types) < len(p_resolved.param_types)):
                    padded_params = list(a_resolved.param_types)
                    while len(padded_params) < len(p_resolved.param_types):
                        padded_params.append(TypeVar())
                    arg_t = FunctionType(padded_params, a_resolved.return_type)
                try:
                    s = unify(self._subst.apply(param_t), self._subst.apply(arg_t))
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    mono_needed = True
                    break

            if mono_needed and isinstance(expr.callee, Identifier):
                func_name = expr.callee.name
                clone_ft = self._try_monomorphize(func_name, arg_types, filename, call_expr=expr)
                if clone_ft is not None:
                    return self._subst.apply(clone_ft.return_type)
                # Monomorphization failed — emit original error
                loc = self._make_diag_loc(expr.loc, filename)
                self.diag.error(
                    f"Argument type mismatch for '{func_name}': "
                    f"cannot unify parameter types with argument types",
                    location=loc,
                )
            elif mono_needed:
                loc = self._make_diag_loc(expr.loc, filename)
                self.diag.error(
                    f"Argument type mismatch in call",
                    location=loc,
                )

            # Rest parameter: unify excess args with the array element type
            if has_rest and len(arg_types) > normal_param_count:
                rest_param_t = self._subst.apply(resolved.param_types[-1])
                if isinstance(rest_param_t, ArrayType):
                    for arg_t in arg_types[normal_param_count:]:
                        try:
                            s = unify(self._subst.apply(rest_param_t.element_type), self._subst.apply(arg_t))
                            self._subst = s.compose(self._subst)
                        except UnificationError:
                            pass

            return self._subst.apply(resolved.return_type)

        return TypeVar()

    def _infer_member(self, expr: MemberExpr, filename: str) -> MonoType:
        obj_t = self._infer_expr(expr.object, filename)
        resolved = self._subst.apply(obj_t)

        # Array subscript: arr[i]
        if expr.computed and isinstance(resolved, ArrayType):
            self._infer_expr(expr.property, filename)
            return resolved.element_type

        # FFI struct field access: v.x, v.y
        if isinstance(resolved, FFIStructType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name
            if field_name in resolved.fields:
                return resolved.fields[field_name]
            return TypeVar()

        # Opaque pointer instance method access: db.execute, db.close
        if isinstance(resolved, OpaquePointerType) and isinstance(expr.property, Identifier):
            method_name = expr.property.name
            if self._ffi_info is not None and resolved.name in self._ffi_info.opaque_classes:
                oc = self._ffi_info.opaque_classes[resolved.name]
                if method_name in oc.instance_methods:
                    mfn = oc.instance_methods[method_name]
                    return FunctionType(mfn.param_types, mfn.return_type)
            return TypeVar()

        if isinstance(resolved, ClassType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name
            # Check for getter — unify this param and return getter's return type
            getter_name = f"__{resolved.name}_get_{field_name}"
            if getter_name in self._functions:
                gt = self._functions[getter_name]
                # Unify this param with the class type
                if gt.param_types:
                    try:
                        s = unify(self._subst.apply(gt.param_types[0]), resolved)
                        self._subst = s.compose(self._subst)
                    except UnificationError:
                        pass
                return self._subst.apply(gt.return_type)
            if field_name in resolved.fields:
                return self._subst.apply(resolved.fields[field_name])
            if field_name in resolved.methods:
                return resolved.methods[field_name]
            loc = self._make_diag_loc(expr.loc, filename)
            self.diag.error(f"Property '{field_name}' does not exist on class {resolved.name}", location=loc)
            return TypeVar()

        if isinstance(resolved, ObjectType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name
            if field_name in resolved.fields:
                return resolved.fields[field_name]
            # process.env.VARNAME → STRING (dynamic field access)
            if (isinstance(expr.object, MemberExpr)
                    and isinstance(expr.object.object, Identifier)
                    and expr.object.object.name == "process"
                    and isinstance(expr.object.property, Identifier)
                    and expr.object.property.name == "env"):
                return STRING
            # Check if this is a class instance and the field is a method
            class_name = getattr(resolved, '_class_name', None)
            if class_name and class_name in self._classes:
                ct = self._classes[class_name]
                if field_name in ct.methods:
                    return ct.methods[field_name]
            loc = self._make_diag_loc(expr.loc, filename)
            self.diag.error(f"Property '{field_name}' does not exist on type {resolved!r}", location=loc)
            return TypeVar()

        if isinstance(resolved, ArrayType) and isinstance(expr.property, Identifier):
            if expr.property.name == "length":
                return NUMBER
            if expr.property.name == "push":
                return FunctionType([resolved.element_type], NUMBER)
            if expr.property.name == "forEach":
                # forEach(callback: (elem, index) => void): void
                cb_type = FunctionType([resolved.element_type, NUMBER], VOID)
                return FunctionType([cb_type], VOID)
            if expr.property.name == "map":
                # map(callback: (elem, index) => T): T[]
                ret_tv = TypeVar()
                cb_type = FunctionType([resolved.element_type, NUMBER], ret_tv)
                return FunctionType([cb_type], ArrayType(ret_tv))
            if expr.property.name == "filter":
                # filter(callback: (elem, index) => boolean): same_element[]
                cb_type = FunctionType([resolved.element_type, NUMBER], BOOLEAN)
                return FunctionType([cb_type], ArrayType(resolved.element_type))
            if expr.property.name == "reduce":
                # reduce(callback: (acc, elem) => T, initial: T): T
                acc_tv = TypeVar()
                cb_type = FunctionType([acc_tv, resolved.element_type], acc_tv)
                return FunctionType([cb_type, acc_tv], acc_tv)
            if expr.property.name in ("indexOf", "lastIndexOf"):
                return FunctionType([resolved.element_type], NUMBER)
            if expr.property.name == "includes":
                return FunctionType([resolved.element_type], BOOLEAN)
            if expr.property.name == "reduceRight":
                acc_tv = TypeVar()
                cb_type = FunctionType([acc_tv, resolved.element_type], acc_tv)
                return FunctionType([cb_type, acc_tv], acc_tv)
            if expr.property.name == "slice":
                return FunctionType([NUMBER, NUMBER], ArrayType(resolved.element_type))
            if expr.property.name == "concat":
                return FunctionType([ArrayType(resolved.element_type)], ArrayType(resolved.element_type))
            if expr.property.name == "reverse":
                return FunctionType([], ArrayType(resolved.element_type))
            if expr.property.name == "join":
                # join(separator?: string): string
                return FunctionType([STRING], STRING)
            if expr.property.name == "find":
                # find(callback: (elem, index) => boolean): element_type
                cb_type = FunctionType([resolved.element_type, NUMBER], BOOLEAN)
                return FunctionType([cb_type], resolved.element_type)
            if expr.property.name == "some":
                # some(callback: (elem, index) => boolean): boolean
                cb_type = FunctionType([resolved.element_type, NUMBER], BOOLEAN)
                return FunctionType([cb_type], BOOLEAN)
            if expr.property.name == "every":
                # every(callback: (elem, index) => boolean): boolean
                cb_type = FunctionType([resolved.element_type, NUMBER], BOOLEAN)
                return FunctionType([cb_type], BOOLEAN)
            if expr.property.name == "sort":
                # sort(compareFn?: (a, b) => number): array (mutates)
                cb_type = FunctionType([resolved.element_type, resolved.element_type], NUMBER)
                return FunctionType([cb_type], ArrayType(resolved.element_type))
            if expr.property.name == "flat":
                return FunctionType([], ArrayType(resolved.element_type))
            if expr.property.name == "fill":
                return FunctionType([resolved.element_type], ArrayType(resolved.element_type))
            if expr.property.name == "findIndex":
                cb_type = FunctionType([resolved.element_type, NUMBER], BOOLEAN)
                return FunctionType([cb_type], NUMBER)
            if expr.property.name == "pop":
                return FunctionType([], resolved.element_type)
            if expr.property.name == "shift":
                return FunctionType([], resolved.element_type)
            if expr.property.name == "unshift":
                return FunctionType([resolved.element_type], NUMBER)
            if expr.property.name == "splice":
                return FunctionType([NUMBER, NUMBER], ArrayType(resolved.element_type))
            if expr.property.name == "at":
                return FunctionType([NUMBER], resolved.element_type)

        # String .length and string methods
        if isinstance(resolved, StringType) and isinstance(expr.property, Identifier):
            if expr.property.name == "length":
                return NUMBER
            # String.at(index) - supports negative index
            if expr.property.name == "at":
                return FunctionType([NUMBER], STRING)
            # String methods that return number
            if expr.property.name in ("indexOf", "lastIndexOf"):
                return FunctionType([STRING], NUMBER)
            # String methods that return boolean
            if expr.property.name in ("includes", "startsWith", "endsWith"):
                return FunctionType([STRING], BOOLEAN)
            # String methods that return string (with args)
            if expr.property.name == "slice":
                return FunctionType([NUMBER, NUMBER], STRING)
            if expr.property.name == "charAt":
                return FunctionType([NUMBER], STRING)
            # charCodeAt returns number (char code)
            if expr.property.name == "charCodeAt":
                return FunctionType([NUMBER], NUMBER)
            # String methods that return string (no args)
            if expr.property.name in ("toUpperCase", "toLowerCase", "trim", "trimStart", "trimEnd"):
                return FunctionType([], STRING)
            # replace(search, replacement) → string
            if expr.property.name in ("replace", "replaceAll"):
                return FunctionType([STRING, STRING], STRING)
            # repeat(count) → string
            if expr.property.name == "repeat":
                return FunctionType([NUMBER], STRING)
            # substring(start, end) → string
            if expr.property.name == "substring":
                return FunctionType([NUMBER, NUMBER], STRING)
            # padStart(targetLength, padString) → string
            if expr.property.name == "padStart":
                return FunctionType([NUMBER, STRING], STRING)
            # padEnd(targetLength, padString) → string
            if expr.property.name == "padEnd":
                return FunctionType([NUMBER, STRING], STRING)
            # split(separator) → string[]
            if expr.property.name == "split":
                return FunctionType([STRING], ArrayType(STRING))

        # Number methods
        if isinstance(resolved, NumberType) and isinstance(expr.property, Identifier):
            if expr.property.name == "toString":
                return FunctionType([], STRING)
            if expr.property.name == "toFixed":
                return FunctionType([NUMBER], STRING)

        return TypeVar()

    def _infer_new_expr(self, expr: NewExpr, filename: str) -> MonoType:
        """Infer type of `new ClassName(args)` — returns instance ObjectType."""
        class_name = expr.class_name
        if class_name not in self._classes:
            loc = self._make_diag_loc(expr.loc, filename)
            self.diag.warning(f"Unknown class: '{class_name}' — will use JS runtime fallback", location=loc)
            return TypeVar()

        ct = self._classes[class_name]

        # Infer argument types and unify with constructor params (skip 'this' at index 0)
        arg_types = [self._infer_expr(a, filename) for a in expr.arguments]
        ctor_name = f"__{class_name}_constructor"
        # If no constructor for this class, try parent class constructor (implicit super)
        if ctor_name not in self._functions:
            decl = self._class_decls.get(class_name)
            if decl and decl.extends and f"__{decl.extends}_constructor" in self._functions:
                ctor_name = f"__{decl.extends}_constructor"
        if ctor_name in self._functions:
            ctor_ft = self._functions[ctor_name]
            # param_types[0] is 'this', user args start at param_types[1]
            user_param_types = ctor_ft.param_types[1:]
            for i, (arg_t, param_t) in enumerate(zip(arg_types, user_param_types)):
                try:
                    s = unify(self._subst.apply(param_t), self._subst.apply(arg_t))
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    pass

        # Return the ClassType directly — it carries both fields and methods
        return ct

    def _infer_arrow(self, expr: ArrowFunction, filename: str) -> MonoType:
        old_env = dict(self._env)

        if id(expr) in self._arrow_lifted:
            # Reuse existing FunctionType (stable TypeVars across passes)
            _, _, ft, _ = self._arrow_lifted[id(expr)]
            for i, p in enumerate(expr.params):
                self._env[p.name] = ft.param_types[i]
            if isinstance(expr.body, Block):
                old_ret = self._return_type
                self._return_type = ft.return_type
                self._check_block(expr.body, filename)
                self._return_type = old_ret
            else:
                body_type = self._infer_expr(expr.body, filename)
                # Unify body type with arrow return type (may resolve on later passes)
                try:
                    s = unify(ft.return_type, body_type)
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    pass
            self._env = old_env
            return ft

        # First encounter: create new TypeVars
        param_types: list[MonoType] = [TypeVar() for _ in expr.params]
        for i, p in enumerate(expr.params):
            self._env[p.name] = param_types[i]

        if isinstance(expr.body, Block):
            old_ret = self._return_type
            self._return_type = TypeVar()
            self._check_block(expr.body, filename)
            ret = self._return_type  # Keep the TypeVar, don't apply subst yet
            self._return_type = old_ret
        else:
            ret = self._infer_expr(expr.body, filename)

        self._env = old_env
        ft = FunctionType(param_types, ret)

        # Detect free variables (captures)
        param_names = {p.name for p in expr.params}
        body_ids = self._collect_identifiers(expr.body)
        captures: list[tuple[str, MonoType]] = []
        for name in sorted(body_ids):  # sorted for deterministic order
            if (name not in param_names
                    and name in old_env
                    and name not in self._functions
                    and name not in ("console", "Math")):
                captures.append((name, old_env[name]))

        # Register for lambda lifting
        lifted_name = f"__anon_{self._current_func_name}_{self._arrow_counter}"
        self._arrow_counter += 1
        self._arrow_lifted[id(expr)] = (lifted_name, expr, ft, captures)

        return ft

    def _collect_identifiers(self, node) -> set[str]:
        """Collect all Identifier names referenced in an AST subtree."""
        if node is None:
            return set()
        if isinstance(node, Identifier):
            return {node.name}
        if isinstance(node, (str, int, float, bool)):
            return set()
        if isinstance(node, ArrowFunction):
            return set()  # Don't descend into nested arrows
        result: set[str] = set()
        if isinstance(node, (list, tuple)):
            for item in node:
                result |= self._collect_identifiers(item)
        elif hasattr(node, '__dataclass_fields__'):
            for key in node.__dataclass_fields__:
                val = getattr(node, key)
                if isinstance(val, (str, int, float, bool, type(None))):
                    continue
                result |= self._collect_identifiers(val)
        return result

    def _make_diag_loc(self, loc: Location | None, filename: str) -> DiagLocation | None:
        if loc is None:
            return None
        return DiagLocation(
            file=filename,
            line=loc.line,
            col=loc.col,
            end_line=loc.end_line,
            end_col=loc.end_col,
        )
