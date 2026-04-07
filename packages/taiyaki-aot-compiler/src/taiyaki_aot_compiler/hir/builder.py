"""HIR Builder: Typed AST → SSA-form HIR."""

from __future__ import annotations

from taiyaki_aot_compiler.parser.ast_nodes import (
    JSModule, Statement, Expression, Block,
    FunctionDecl, VarDecl, ReturnStmt, IfStmt, WhileStmt, ForStmt,
    ForOfStmt, DoWhileStmt, ExpressionStmt, ObjectDestructure, ArrayDestructure, BreakStmt, ContinueStmt, LabeledStmt,
    SwitchStmt, SwitchCase,
    ClassDecl, NewExpr, ThisExpr, SuperCall, ThrowStmt, TryCatchStmt, ForInStmt,
    NumberLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    Identifier, BinaryExpr, UnaryExpr, UpdateExpr, CompareExpr,
    LogicalExpr, ConditionalExpr, CallExpr, MemberExpr, AssignExpr,
    ArrowFunction, ObjectLiteralExpr, ArrayLiteral, SpreadElement, SequenceExpr, TemplateLiteral,
    AwaitExpr,
)
from taiyaki_aot_compiler.type_checker.types import (
    MonoType, NumberType, BooleanType, StringType, VoidType, NullType, TypeVar,
    FunctionType, ObjectType, ArrayType, ClassType,
    FFIStructType, OpaquePointerType, PromiseType,
    NUMBER, BOOLEAN, STRING, VOID, NULL,
)
from taiyaki_aot_compiler.type_checker.js_inferrer import TypedFunction, TypedModule
from taiyaki_aot_compiler.hir.nodes import (
    HIRModule, HIRFunction, BasicBlock, FallbackFuncInfo,
    HIRConst, HIRParam, HIRBinaryOp, HIRUnaryOp, HIRCompare,
    HIRCall, HIRAssign, HIRReturn, HIRBranch, HIRJump, HIRPhi,
    HIRAllocObj, HIRFieldGet, HIRFieldSet,
    HIRAllocArray, HIRArrayGet, HIRArraySet, HIRArrayPush, HIRArrayLen,
    HIRFuncRef, HIRIndirectCall,
    HIRMakeClosure, HIRLoadCapture, HIRStoreCapture,
    HIRArrayForEach, HIRArrayMap, HIRArrayFilter, HIRArrayReduce, HIRArrayReduceRight,
    HIRArrayFind, HIRArrayFindIndex, HIRArraySome, HIRArrayEvery, HIRArraySort,
    HIRAwait,
    HIRTryCatch,
    HIRFFIStructCreate, HIRFFIStructFieldGet,
)

# Map TS binary ops to HIR op names
_BINOP_MAP = {
    "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "**": "pow",
    "&": "bit_and", "|": "bit_or", "^": "bit_xor",
    "<<": "shl", ">>": "shr", ">>>": "ushr",
}

_CMPOP_MAP = {
    "===": "eq", "!==": "ne", "<": "lt", ">": "gt", "<=": "le", ">=": "ge",
}


class HIRBuilder:
    """Build HIR from a TypedModule."""

    def __init__(self):
        self._ssa_counter = 0
        self._block_counter = 0
        self._blocks: list[BasicBlock] = []
        self._current_block: BasicBlock | None = None
        self._vars: dict[str, str] = {}  # variable name → current SSA var
        self._var_types: dict[str, MonoType] = {}  # variable name → type
        self._node_types: dict[int, MonoType] = {}
        self._functions: dict[str, FunctionType] = {}  # all function signatures
        self._loop_exit: str | None = None  # label for break target
        self._loop_continue: str | None = None  # label for continue target
        self._continue_snapshots: list[tuple[str, dict[str, str]]] = []  # (block_label, vars_snapshot)
        self._break_snapshots: list[tuple[str, dict[str, str]]] = []  # (block_label, vars_snapshot)
        self._label_exits: dict[str, str] = {}  # JS label → exit block label
        self._label_continues: dict[str, str] = {}  # JS label → continue block label
        self._pending_label: str | None = None  # label name for next loop
        self._arrow_lifted_names: dict[int, str] = {}  # id(ArrowFunction) → lifted func name
        self._arrow_captures: dict[int, list[tuple[str, MonoType]]] = {}  # id(ArrowFunction) → captures
        # Mutable closure support: maps capture var name → (index, capture_types_list)
        self._capture_info: dict[str, tuple[int, list[MonoType]]] = {}
        # Block scoping: tracks variable names re-declared via let in current inner block
        self._block_redeclared: set[str] = set()
        self._redeclared_saved: dict[str, tuple[str, MonoType]] = {}  # name → (old_ssa, old_type)

    def _type_hint_str(self, ty: MonoType) -> str:
        """Convert a MonoType to a simple string hint for fallback bridge."""
        if isinstance(ty, NumberType):
            return "number"
        elif isinstance(ty, BooleanType):
            return "boolean"
        elif isinstance(ty, StringType):
            return "string"
        elif isinstance(ty, VoidType):
            return "void"
        return "number"  # default fallback

    def build(self, typed_module: TypedModule, source: str = "", ffi_info: object = None) -> HIRModule:
        hir_funcs: list[HIRFunction] = []
        entry_stmts: list[str] = []
        fallback_sources: dict[str, str] = {}
        fallback_signatures: dict[str, FallbackFuncInfo] = {}

        # Store arrow lifted name mappings
        self._arrow_lifted_names = typed_module.arrow_lifted_names
        self._arrow_captures = typed_module.arrow_captures
        self._nested_func_arrows = typed_module.nested_func_arrows
        self._nested_func_lifted = typed_module.nested_func_lifted  # original name → lifted name
        self._classes = typed_module.classes
        self._class_decls = typed_module.class_decls
        self._ffi_info = ffi_info
        self._global_vars = typed_module.global_vars  # top-level var/let names → types
        self._typed_module = typed_module  # for mono_call_rewrites

        # Track which functions are fallbacks for call resolution
        self._fallback_funcs: set[str] = set()

        # Collect function signatures, defaults, and AST nodes
        source_lines = source.splitlines() if source else []
        self._func_defaults: dict[str, list[Expression | None]] = {}
        self._func_nodes: dict[str, FunctionDecl] = {}
        for tf in typed_module.functions:
            self._functions[tf.name] = FunctionType(
                [t for _, t in tf.params], tf.return_type
            )
            if tf.defaults:
                self._func_defaults[tf.name] = tf.defaults
            self._func_nodes[tf.name] = tf.node

        # Collect fallback sources for non-compilable functions
        for tf in typed_module.functions:
            if not tf.is_compilable and tf.node.loc:
                start = tf.node.loc.line - 1
                end = (tf.node.loc.end_line or tf.node.loc.line) - 1
                if start < len(source_lines):
                    fb_src = "\n".join(source_lines[start:end + 1])
                    fallback_sources[tf.name] = fb_src
                    fallback_signatures[tf.name] = FallbackFuncInfo(
                        name=tf.name,
                        param_count=len(tf.params),
                        return_type_hint=self._type_hint_str(tf.return_type),
                    )
                    self._fallback_funcs.add(tf.name)

        for tf in typed_module.functions:
            if tf.is_compilable:
                hir_func = self._build_function(tf)
                hir_funcs.append(hir_func)

        # Collect top-level statements as entry JS source.
        # Constant numeric VarDecls are handled via LLVM globals (fast init).
        # Non-constant VarDecls (function calls, arrays, objects) must be
        # evaluated by QuickJS so the variable is defined at runtime.
        global_var_inits: dict[str, float] = {}
        for stmt in typed_module.top_level_stmts:
            if isinstance(stmt, VarDecl) and stmt.name in typed_module.global_vars:
                from taiyaki_aot_compiler.parser.ast_nodes import NumberLiteral, UnaryExpr
                is_const_num = False
                if stmt.init is not None:
                    if isinstance(stmt.init, NumberLiteral):
                        global_var_inits[stmt.name] = stmt.init.value
                        is_const_num = True
                    elif (isinstance(stmt.init, UnaryExpr) and stmt.init.op == "-"
                          and isinstance(stmt.init.operand, NumberLiteral)):
                        global_var_inits[stmt.name] = -stmt.init.operand.value
                        is_const_num = True
                # Non-constant initializers → let QuickJS evaluate
                if not is_const_num and stmt.loc and stmt.loc.line - 1 < len(source_lines):
                    start = stmt.loc.line - 1
                    end = (stmt.loc.end_line or stmt.loc.line) - 1
                    lines = source_lines[start:end + 1]
                    entry_stmts.append("\n".join(lines))
            elif stmt.loc and stmt.loc.line - 1 < len(source_lines):
                start = stmt.loc.line - 1
                end = (stmt.loc.end_line or stmt.loc.line) - 1
                lines = source_lines[start:end + 1]
                entry_stmts.append("\n".join(lines))

        # Build func_aliases: import_name → prefixed_name (for QuickJS registration)
        func_aliases: dict[str, str] = {}
        for alias, canonical in typed_module.import_rewrite_map.items():
            func_aliases[alias] = canonical

        return HIRModule(
            functions=hir_funcs,
            fallback_sources=fallback_sources,
            fallback_signatures=fallback_signatures,
            entry_statements=entry_stmts,
            classes=typed_module.classes,
            func_aliases=func_aliases,
            ffi_info=self._ffi_info,
            global_vars=typed_module.global_vars,
            global_var_inits=global_var_inits,
        )

    def _build_function(self, tf: TypedFunction) -> HIRFunction:
        self._ssa_counter = 0
        self._block_counter = 0
        self._current_func_name = tf.name
        self._blocks = []
        self._vars = {}
        self._var_types = {}
        self._node_types = tf.node_types

        entry = self._fresh_block("entry")
        self._current_block = entry

        params: list[HIRParam] = []

        # Load captures from env if this is a closure function
        old_capture_info = self._capture_info
        self._capture_info = {}
        if tf.captures:
            capture_types = [t for _, t in tf.captures]
            for i, (cap_name, cap_type) in enumerate(tf.captures):
                cap_ssa = self._fresh_ssa()
                self._emit(HIRLoadCapture(
                    env="__env__",
                    index=i,
                    capture_types=capture_types,
                    result=cap_ssa,
                    type=cap_type,
                ))
                self._vars[cap_name] = cap_ssa
                self._var_types[cap_name] = cap_type
                # Register for mutable capture write-back
                self._capture_info[cap_name] = (i, capture_types)

        for pname, ptype in tf.params:
            ssa = self._fresh_ssa()
            p = HIRParam(name=pname, type=ptype, result=ssa)
            params.append(p)
            entry.instructions.append(p)
            self._vars[pname] = ssa
            self._var_types[pname] = ptype

        self._build_block(tf.node.body)

        # Ensure last block has a terminator
        if self._current_block and self._current_block.terminator is None:
            ret_val = None
            if not isinstance(tf.return_type, VoidType):
                # Implicit return with type-appropriate default value
                ret_val = self._emit_default_value(tf.return_type)
            self._current_block.terminator = HIRReturn(value=ret_val, type=tf.return_type)

        self._capture_info = old_capture_info

        return HIRFunction(
            name=tf.name,
            params=params,
            blocks=self._blocks,
            return_type=tf.return_type,
            captures=tf.captures,
            is_async=getattr(tf.node, 'is_async', False),
        )

    def _build_block(self, block: Block):
        for stmt in block.body:
            self._build_stmt(stmt)

    def _build_stmt(self, stmt: Statement):
        if self._current_block is None or self._current_block.terminator is not None:
            return  # Dead code after return/branch

        if isinstance(stmt, VarDecl):
            self._build_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            self._build_return(stmt)
        elif isinstance(stmt, IfStmt):
            self._build_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._build_while(stmt)
        elif isinstance(stmt, DoWhileStmt):
            self._build_do_while(stmt)
        elif isinstance(stmt, ForStmt):
            self._build_for(stmt)
        elif isinstance(stmt, ForOfStmt):
            self._build_for_of(stmt)
        elif isinstance(stmt, ForInStmt):
            self._build_for_in(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._build_switch(stmt)
        elif isinstance(stmt, BreakStmt):
            if stmt.label and stmt.label in self._label_exits:
                self._break_snapshots.append((self._current_block.label, dict(self._vars)))
                self._current_block.terminator = HIRJump(target_block=self._label_exits[stmt.label])
            elif self._loop_exit:
                self._break_snapshots.append((self._current_block.label, dict(self._vars)))
                self._current_block.terminator = HIRJump(target_block=self._loop_exit)
        elif isinstance(stmt, ContinueStmt):
            if stmt.label and stmt.label in self._label_continues:
                self._continue_snapshots.append((self._current_block.label, dict(self._vars)))
                self._current_block.terminator = HIRJump(target_block=self._label_continues[stmt.label])
            elif self._loop_continue:
                self._continue_snapshots.append((self._current_block.label, dict(self._vars)))
                self._current_block.terminator = HIRJump(target_block=self._loop_continue)
        elif isinstance(stmt, LabeledStmt):
            self._build_labeled(stmt)
        elif isinstance(stmt, ExpressionStmt):
            self._build_expr(stmt.expression)
        elif isinstance(stmt, ObjectDestructure):
            self._build_object_destructure(stmt)
        elif isinstance(stmt, ArrayDestructure):
            self._build_array_destructure(stmt)
        elif isinstance(stmt, ThrowStmt):
            self._build_throw(stmt)
        elif isinstance(stmt, TryCatchStmt):
            self._build_try_catch(stmt)
        elif isinstance(stmt, FunctionDecl):
            # Nested function declaration: bind as closure reference
            arrow = self._nested_func_arrows.get(stmt.name)
            if arrow:
                ref = self._build_arrow_ref(arrow)
                self._vars[stmt.name] = ref
                # Get the FunctionType from the lifted function entry
                # (_get_type defaults to NUMBER which causes phi nodes to
                # incorrectly convert closure pairs to doubles in loops)
                lifted_name = self._nested_func_lifted.get(stmt.name)
                if lifted_name and lifted_name in self._functions:
                    self._var_types[stmt.name] = self._functions[lifted_name]
                else:
                    func_type = self._get_type(arrow)
                    if func_type:
                        self._var_types[stmt.name] = func_type
        elif isinstance(stmt, Block):
            self._build_block(stmt)

    def _build_var_decl(self, decl: VarDecl):
        # Track shadowed variables for block scoping
        if decl.name in self._vars and decl.name not in self._block_redeclared:
            self._block_redeclared.add(decl.name)
            self._redeclared_saved[decl.name] = (
                self._vars[decl.name],
                self._var_types.get(decl.name, NUMBER),
            )
        if decl.init:
            val = self._build_expr(decl.init)
            self._vars[decl.name] = val
            self._var_types[decl.name] = self._get_type(decl.init)
        else:
            # Uninitialized → default value
            val = self._emit_const(0.0, NUMBER)
            self._vars[decl.name] = val
            self._var_types[decl.name] = NUMBER

    def _build_return(self, stmt: ReturnStmt):
        if stmt.value:
            val = self._build_expr(stmt.value)
            ret_type = self._get_type(stmt.value)
        else:
            val = None
            ret_type = VOID
        self._current_block.terminator = HIRReturn(value=val, type=ret_type)

    def _build_labeled(self, stmt: LabeledStmt):
        """Build labeled statement: register label exit/continue targets.

        For labeled loops, `break label` jumps to the loop's own exit block.
        We use a sentinel value and let the loop builder set the actual target.
        """
        label = stmt.label_name
        old_label_exit = self._label_exits.get(label)

        # Mark that we're in a labeled context — the loop builder will
        # set the actual exit target via _pending_label
        self._pending_label = label

        # Build the inner statement (the loop builder will register the exit target)
        self._build_stmt(stmt.body)

        self._pending_label = None

        # Restore old label mappings
        if old_label_exit is not None:
            self._label_exits[label] = old_label_exit
        else:
            self._label_exits.pop(label, None)

    def _build_throw(self, stmt: ThrowStmt):
        """Build throw statement: extract message and call __tsuchi_throw."""
        # Handle throw new Error("message") → extract the string arg
        # For other throw expressions, convert to string
        _ERROR_CLASSES = ("Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError", "URIError", "EvalError")
        if isinstance(stmt.argument, NewExpr) and stmt.argument.class_name in _ERROR_CLASSES:
            if stmt.argument.arguments:
                # Prepend error class name: "TypeError: msg"
                msg = self._build_expr(stmt.argument.arguments[0])
                if stmt.argument.class_name != "Error":
                    prefix = self._emit_const(f"{stmt.argument.class_name}: ", STRING)
                    concat_result = self._fresh_ssa()
                    self._emit(HIRBinaryOp(
                        op="add", left=prefix, right=msg,
                        result=concat_result, type=STRING,
                    ))
                    msg = concat_result
            else:
                msg = self._emit_const(stmt.argument.class_name, STRING)
        else:
            msg = self._build_expr(stmt.argument)
            msg_type = self._get_type(stmt.argument)
            if not isinstance(msg_type, StringType):
                msg = self._emit_const("Error", STRING)
        result = self._fresh_ssa()
        self._emit(HIRCall(
            func_name="__tsuchi_throw", args=[msg],
            result=result, type=VOID,
        ))

    def _build_try_catch(self, stmt: TryCatchStmt):
        """Build try/catch/finally — emits blocks and HIRTryCatch for LLVM setjmp."""
        try_block = self._fresh_block("try_body")
        catch_block = self._fresh_block("catch_body") if stmt.catch_block else None
        finally_block = self._fresh_block("finally_body") if stmt.finally_block else None
        merge_block = self._fresh_block("try_merge")

        catch_param_ssa = None
        if stmt.catch_param:
            catch_param_ssa = self._fresh_ssa()

        # Emit HIRTryCatch in current block — LLVM generator handles setjmp/branch
        self._emit(HIRTryCatch(
            try_block=try_block.label,
            catch_block=catch_block.label if catch_block else None,
            catch_param=catch_param_ssa,
            finally_block=finally_block.label if finally_block else None,
            merge_block=merge_block.label,
        ))
        # The HIRTryCatch sets the terminator (done by LLVM generator)
        # Mark block as terminated so we move to try_block
        self._current_block.terminator = HIRJump(target_block=try_block.label)  # placeholder

        # Try block
        pre_vars = dict(self._vars)
        self._current_block = try_block
        self._build_block(stmt.try_block)
        # Pop jmp_buf after try completes normally
        pop_result = self._fresh_ssa()
        self._emit(HIRCall(
            func_name="__tsuchi_try_pop", args=[],
            result=pop_result, type=VOID,
        ))
        try_exit = self._current_block
        try_vars = dict(self._vars)
        after_try_target = finally_block.label if finally_block else merge_block.label
        if try_exit.terminator is None:
            try_exit.terminator = HIRJump(target_block=after_try_target)

        # Catch block
        catch_vars = dict(pre_vars)
        catch_exit = None
        if catch_block and stmt.catch_block:
            self._vars = dict(pre_vars)
            self._current_block = catch_block
            if stmt.catch_param and catch_param_ssa:
                # LLVM generator will populate this SSA var with error msg
                self._vars[stmt.catch_param] = catch_param_ssa
            self._build_block(stmt.catch_block)
            catch_exit = self._current_block
            catch_vars = dict(self._vars)
            after_catch_target = finally_block.label if finally_block else merge_block.label
            if catch_exit.terminator is None:
                catch_exit.terminator = HIRJump(target_block=after_catch_target)

        # Finally block
        if finally_block and stmt.finally_block:
            # Finally receives vars from whichever path ran — use try_vars as base
            self._vars = dict(try_vars)
            self._current_block = finally_block
            self._build_block(stmt.finally_block)
            finally_exit = self._current_block
            try_vars = dict(self._vars)  # update try_vars with finally modifications
            if finally_exit.terminator is None:
                finally_exit.terminator = HIRJump(target_block=merge_block.label)
            # Also build finally for catch path — but in SSA we can't easily split,
            # so we'll use the finally-modified try_vars as the merge vars

        # Merge block — add phi nodes for variables modified in try vs catch
        self._blocks.remove(merge_block)
        self._blocks.append(merge_block)
        self._current_block = merge_block

        # Determine which paths reach merge
        def _reaches_merge(exit_blk):
            if exit_blk is None:
                return False
            t = exit_blk.terminator
            if t is None:
                return True
            if isinstance(t, HIRReturn):
                return False
            if isinstance(t, HIRJump):
                target = t.target_block
                # Reaches merge if it jumps to merge or finally (which jumps to merge)
                if target == merge_block.label:
                    return True
                if finally_block and target == finally_block.label:
                    return True
            return False

        if finally_block:
            # With finally, both paths go through finally to merge
            # Use try_vars (which includes finally modifications) as the merge state
            self._vars = dict(try_vars)
        else:
            try_reached = _reaches_merge(try_exit)
            catch_reached = _reaches_merge(catch_exit) if catch_block else False

            if try_reached and catch_reached:
                # Add phi nodes for variables that differ between try and catch paths
                all_names = set(try_vars.keys()) | set(catch_vars.keys())
                self._vars = dict(pre_vars)
                for name in all_names:
                    if name in try_vars and name in catch_vars:
                        tv = try_vars[name]
                        cv = catch_vars[name]
                        if tv != cv:
                            phi_ssa = self._fresh_ssa()
                            phi_type = self._var_types.get(name, NUMBER)
                            phi = HIRPhi(
                                incoming=[(tv, try_exit.label), (cv, catch_exit.label)],
                                result=phi_ssa,
                                type=phi_type,
                            )
                            merge_block.instructions.append(phi)
                            self._vars[name] = phi_ssa
                        else:
                            self._vars[name] = tv
                    elif name in try_vars:
                        self._vars[name] = try_vars[name]
                    elif name in catch_vars:
                        self._vars[name] = catch_vars[name]
            elif try_reached:
                self._vars = try_vars
            elif catch_reached:
                self._vars = catch_vars
            else:
                self._vars = dict(pre_vars)

    def _build_if(self, stmt: IfStmt):
        cond = self._build_expr(stmt.condition)

        then_block = self._fresh_block("if_then")
        else_block = self._fresh_block("if_else") if stmt.alternate else None
        merge_block = self._fresh_block("if_merge")

        false_target = else_block.label if else_block else merge_block.label
        branch_block = self._current_block  # block containing the branch
        self._current_block.terminator = HIRBranch(
            condition=cond,
            true_block=then_block.label,
            false_block=false_target,
        )

        # Then branch
        pre_vars = dict(self._vars)
        pre_var_types = dict(self._var_types)
        self._current_block = then_block
        # Save block-scope shadow state
        saved_redecl = self._block_redeclared
        saved_redecl_saved = self._redeclared_saved
        self._block_redeclared = set()
        self._redeclared_saved = {}
        self._build_block(stmt.consequent)
        # Restore shadowed variables (let x inside block doesn't leak)
        for name in self._block_redeclared:
            if name in self._redeclared_saved:
                old_ssa, old_type = self._redeclared_saved[name]
                self._vars[name] = old_ssa
                self._var_types[name] = old_type
        self._block_redeclared = saved_redecl
        self._redeclared_saved = saved_redecl_saved
        then_vars = dict(self._vars)
        then_exit = self._current_block
        if then_exit.terminator is None:
            then_exit.terminator = HIRJump(target_block=merge_block.label)

        # Else branch
        else_vars = pre_vars
        else_exit = None
        if stmt.alternate:
            self._vars = dict(pre_vars)
            self._var_types = dict(pre_var_types)
            self._current_block = else_block
            saved_redecl = self._block_redeclared
            saved_redecl_saved = self._redeclared_saved
            self._block_redeclared = set()
            self._redeclared_saved = {}
            if isinstance(stmt.alternate, Block):
                self._build_block(stmt.alternate)
            elif isinstance(stmt.alternate, IfStmt):
                self._build_if(stmt.alternate)
            else:
                self._build_block(stmt.alternate)
            # Restore shadowed variables
            for name in self._block_redeclared:
                if name in self._redeclared_saved:
                    old_ssa, old_type = self._redeclared_saved[name]
                    self._vars[name] = old_ssa
                    self._var_types[name] = old_type
            self._block_redeclared = saved_redecl
            self._redeclared_saved = saved_redecl_saved
            else_vars = dict(self._vars)
            else_exit = self._current_block
            if else_exit.terminator is None:
                else_exit.terminator = HIRJump(target_block=merge_block.label)

        # Merge: add phi nodes for variables that differ
        # Reorder: move merge_block after any blocks created during then/else
        self._blocks.remove(merge_block)
        self._blocks.append(merge_block)

        self._current_block = merge_block

        def _reaches_merge(exit_blk):
            """Check if a branch actually reaches the merge block."""
            if exit_blk is None:
                return False
            t = exit_blk.terminator
            if t is None:
                return True  # will get an implicit jump added
            if isinstance(t, HIRReturn):
                return False
            if isinstance(t, HIRJump) and t.target_block == merge_block.label:
                return True
            return False  # break/continue jump elsewhere

        then_reached = _reaches_merge(then_exit)
        else_reached = _reaches_merge(else_exit) if stmt.alternate else True
        else_exit_label = else_exit.label if else_exit else branch_block.label

        if then_reached and else_reached:
            all_names = set(then_vars.keys()) | set(else_vars.keys())
            for name in all_names:
                if name in then_vars and name in else_vars:
                    tv = then_vars[name]
                    ev = else_vars[name]
                    if tv != ev:
                        phi_ssa = self._fresh_ssa()
                        phi_type = self._var_types.get(name, NUMBER)
                        phi = HIRPhi(
                            incoming=[(tv, then_exit.label), (ev, else_exit_label)],
                            result=phi_ssa,
                            type=phi_type,
                        )
                        merge_block.instructions.append(phi)
                        self._vars[name] = phi_ssa
                    else:
                        self._vars[name] = tv
                elif name in then_vars:
                    self._vars[name] = then_vars[name]
                elif name in else_vars:
                    self._vars[name] = else_vars[name]
        elif then_reached:
            self._vars = then_vars
        elif else_reached:
            self._vars = else_vars

        # Remove variables introduced inside if branches from outer scope
        # (variables declared with let inside if/else should not leak out)
        for name in list(self._vars.keys()):
            if name not in pre_vars:
                del self._vars[name]

    def _build_while(self, stmt: WhileStmt):
        header = self._fresh_block("while_header")
        body_block = self._fresh_block("while_body")
        latch_block = self._fresh_block("while_latch")
        exit_block = self._fresh_block("while_exit")

        # If this while loop is inside a labeled statement, register the exit target
        if self._pending_label:
            self._label_exits[self._pending_label] = exit_block.label
            self._pending_label = None

        entry_block = self._current_block
        pre_vars = dict(self._vars)
        self._current_block.terminator = HIRJump(target_block=header.label)

        # Header: phi nodes + condition
        self._current_block = header

        # Create phi nodes for scalar vars (skip array/object/function — loop-invariant)
        phi_map: dict[str, str] = {}
        for name, ssa in pre_vars.items():
            vt = self._var_types.get(name, NUMBER)
            if isinstance(vt, (ArrayType, ObjectType, FunctionType)):
                continue
            phi_ssa = self._fresh_ssa()
            phi = HIRPhi(
                incoming=[(ssa, entry_block.label)],
                result=phi_ssa,
                type=vt,
            )
            header.instructions.append(phi)
            phi_map[name] = phi_ssa
            self._vars[name] = phi_ssa

        cond = self._build_expr(stmt.condition)
        self._current_block.terminator = HIRBranch(
            condition=cond,
            true_block=body_block.label,
            false_block=exit_block.label,
        )

        # Body — set loop labels for break/continue
        # continue jumps to latch_block, break jumps to exit_block
        old_loop_exit = self._loop_exit
        old_loop_continue = self._loop_continue
        old_continue_snapshots = self._continue_snapshots
        old_break_snapshots = self._break_snapshots
        self._loop_exit = exit_block.label
        self._loop_continue = latch_block.label
        self._continue_snapshots = []
        self._break_snapshots = []
        self._current_block = body_block
        saved_redecl_w = self._block_redeclared
        saved_redecl_saved_w = self._redeclared_saved
        self._block_redeclared = set()
        self._redeclared_saved = {}
        self._build_block(stmt.body)
        # Restore shadowed variables at loop body exit
        for name in self._block_redeclared:
            if name in self._redeclared_saved:
                old_ssa, old_type = self._redeclared_saved[name]
                self._vars[name] = old_ssa
                self._var_types[name] = old_type
        self._block_redeclared = saved_redecl_w
        self._redeclared_saved = saved_redecl_saved_w
        continue_snapshots = self._continue_snapshots
        break_snapshots = self._break_snapshots
        self._loop_exit = old_loop_exit
        self._loop_continue = old_loop_continue
        self._continue_snapshots = old_continue_snapshots
        self._break_snapshots = old_break_snapshots

        body_end_vars = dict(self._vars)
        body_end_block = self._current_block
        body_falls_through = body_end_block.terminator is None
        if body_falls_through:
            body_end_block.terminator = HIRJump(target_block=latch_block.label)

        # Reorder: move latch and exit blocks after any blocks created during body
        self._blocks.remove(latch_block)
        self._blocks.remove(exit_block)
        self._blocks.append(latch_block)
        self._blocks.append(exit_block)

        # Latch block: merge values from body end + continue paths, then jump to header
        self._current_block = latch_block

        # Collect all incoming edges to latch
        latch_incoming: list[tuple[str, dict[str, str]]] = []
        if body_falls_through:
            latch_incoming.append((body_end_block.label, body_end_vars))
        for cont_label, cont_vars in continue_snapshots:
            latch_incoming.append((cont_label, cont_vars))

        if len(latch_incoming) > 1:
            # Need phi nodes in the latch to merge values
            latch_merged_vars: dict[str, str] = {}
            all_var_names = set()
            for _, vars_snap in latch_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, phi_map.get(name, "")), label)
                        for label, vars_snap in latch_incoming
                        if vars_snap.get(name, phi_map.get(name, ""))]
                if len(set(v for v, _ in vals)) == 1:
                    latch_merged_vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    phi_type = self._var_types.get(name, NUMBER)
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=phi_type)
                    latch_block.instructions.append(phi)
                    latch_merged_vars[name] = phi_ssa
            self._vars = latch_merged_vars
        elif len(latch_incoming) == 1:
            self._vars = latch_incoming[0][1]
        # else: no incoming edges (all paths break), vars stay as is

        self._current_block.terminator = HIRJump(target_block=header.label)

        # Patch header phi incoming from latch back-edge
        for instr in header.instructions:
            if isinstance(instr, HIRPhi):
                for name, phi_ssa in phi_map.items():
                    if instr.result == phi_ssa:
                        body_val = self._vars.get(name, phi_ssa)
                        instr.incoming.append((body_val, latch_block.label))
                        break

        # At exit, merge header phi values (condition-false path) with break snapshots
        self._current_block = exit_block
        header_vars = {name: phi_ssa for name, phi_ssa in phi_map.items()}

        # Collect all incoming edges to exit block
        exit_incoming: list[tuple[str, dict[str, str]]] = []
        exit_incoming.append((header.label, header_vars))
        for brk_label, brk_vars in break_snapshots:
            exit_incoming.append((brk_label, brk_vars))

        if len(exit_incoming) > 1:
            all_var_names = set()
            for _, vars_snap in exit_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, header_vars.get(name, "")), label)
                        for label, vars_snap in exit_incoming
                        if vars_snap.get(name, header_vars.get(name, ""))]
                if not vals:
                    continue
                unique_vals = set(v for v, _ in vals)
                if len(unique_vals) == 1:
                    self._vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    var_type = self._var_types.get(name, NUMBER)
                    if isinstance(var_type, (ArrayType, ObjectType, FunctionType)):
                        self._vars[name] = vals[0][0]
                        continue
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=var_type)
                    exit_block.instructions.append(phi)
                    self._vars[name] = phi_ssa
        else:
            for name, phi_ssa in phi_map.items():
                self._vars[name] = phi_ssa

        # Remove variables introduced inside the loop body from outer scope
        for name in list(self._vars.keys()):
            if name not in pre_vars:
                del self._vars[name]

    def _build_do_while(self, stmt: DoWhileStmt):
        """Build do-while loop: body executes before condition check."""
        body_block = self._fresh_block("dowhile_body")
        latch_block = self._fresh_block("dowhile_latch")
        exit_block = self._fresh_block("dowhile_exit")

        # If this do-while loop is inside a labeled statement, register the exit target
        if self._pending_label:
            self._label_exits[self._pending_label] = exit_block.label
            self._pending_label = None

        entry_block = self._current_block
        pre_vars = dict(self._vars)
        self._current_block.terminator = HIRJump(target_block=body_block.label)

        # Body block: phi nodes at body entry (for back-edge from latch)
        self._current_block = body_block
        phi_map: dict[str, str] = {}
        for name, ssa in pre_vars.items():
            vt = self._var_types.get(name, NUMBER)
            if isinstance(vt, (ArrayType, ObjectType, FunctionType)):
                continue  # loop-invariant, skip phi
            phi_ssa = self._fresh_ssa()
            phi = HIRPhi(
                incoming=[(ssa, entry_block.label)],
                result=phi_ssa,
                type=vt,
            )
            body_block.instructions.append(phi)
            phi_map[name] = phi_ssa
            self._vars[name] = phi_ssa

        # Body — set loop labels for break/continue
        old_loop_exit = self._loop_exit
        old_loop_continue = self._loop_continue
        old_continue_snapshots = self._continue_snapshots
        old_break_snapshots = self._break_snapshots
        self._loop_exit = exit_block.label
        self._loop_continue = latch_block.label
        self._continue_snapshots = []
        self._break_snapshots = []
        saved_redecl_dw = self._block_redeclared
        saved_redecl_saved_dw = self._redeclared_saved
        self._block_redeclared = set()
        self._redeclared_saved = {}
        self._build_block(stmt.body)
        for name in self._block_redeclared:
            if name in self._redeclared_saved:
                old_ssa, old_type = self._redeclared_saved[name]
                self._vars[name] = old_ssa
                self._var_types[name] = old_type
        self._block_redeclared = saved_redecl_dw
        self._redeclared_saved = saved_redecl_saved_dw
        continue_snapshots = self._continue_snapshots
        break_snapshots = self._break_snapshots
        self._loop_exit = old_loop_exit
        self._loop_continue = old_loop_continue
        self._continue_snapshots = old_continue_snapshots
        self._break_snapshots = old_break_snapshots

        body_end_vars = dict(self._vars)
        body_end_block = self._current_block
        body_falls_through = body_end_block.terminator is None
        if body_falls_through:
            body_end_block.terminator = HIRJump(target_block=latch_block.label)

        # Reorder: move latch and exit blocks after any blocks created during body
        self._blocks.remove(latch_block)
        self._blocks.remove(exit_block)
        self._blocks.append(latch_block)
        self._blocks.append(exit_block)

        # Latch block: merge, check condition
        self._current_block = latch_block

        latch_incoming: list[tuple[str, dict[str, str]]] = []
        if body_falls_through:
            latch_incoming.append((body_end_block.label, body_end_vars))
        for cont_label, cont_vars in continue_snapshots:
            latch_incoming.append((cont_label, cont_vars))

        if len(latch_incoming) > 1:
            latch_merged_vars: dict[str, str] = {}
            all_var_names = set()
            for _, vars_snap in latch_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, phi_map.get(name, "")), label)
                        for label, vars_snap in latch_incoming
                        if vars_snap.get(name, phi_map.get(name, ""))]
                if len(set(v for v, _ in vals)) == 1:
                    latch_merged_vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    phi_type = self._var_types.get(name, NUMBER)
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=phi_type)
                    latch_block.instructions.append(phi)
                    latch_merged_vars[name] = phi_ssa
            self._vars = latch_merged_vars
        elif len(latch_incoming) == 1:
            self._vars = latch_incoming[0][1]

        cond = self._build_expr(stmt.condition)
        latch_vars = dict(self._vars)  # Save before branching
        self._current_block.terminator = HIRBranch(
            condition=cond,
            true_block=body_block.label,
            false_block=exit_block.label,
        )

        # Patch body phi incoming from latch back-edge
        for instr in body_block.instructions:
            if isinstance(instr, HIRPhi):
                for name, phi_ssa in phi_map.items():
                    if instr.result == phi_ssa:
                        body_val = self._vars.get(name, phi_ssa)
                        instr.incoming.append((body_val, latch_block.label))
                        break

        # At exit, merge latch vars (condition-false path) with break snapshots
        self._current_block = exit_block
        if break_snapshots:
            exit_incoming: list[tuple[str, dict[str, str]]] = []
            exit_incoming.append((latch_block.label, latch_vars))
            for brk_label, brk_vars in break_snapshots:
                exit_incoming.append((brk_label, brk_vars))
            all_var_names = set()
            for _, vars_snap in exit_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, latch_vars.get(name, "")), label)
                        for label, vars_snap in exit_incoming
                        if vars_snap.get(name, latch_vars.get(name, ""))]
                if not vals:
                    continue
                unique_vals = set(v for v, _ in vals)
                if len(unique_vals) == 1:
                    self._vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    var_type = self._var_types.get(name, NUMBER)
                    if isinstance(var_type, (ArrayType, ObjectType, FunctionType)):
                        self._vars[name] = vals[0][0]
                        continue
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=var_type)
                    exit_block.instructions.append(phi)
                    self._vars[name] = phi_ssa
        else:
            self._vars = latch_vars

        # Remove variables introduced inside the loop body from outer scope
        for name in list(self._vars.keys()):
            if name not in pre_vars:
                del self._vars[name]

    def _build_for(self, stmt: ForStmt):
        # Save scope for for-init variable declarations (let i = ... should be scoped to the for)
        saved_redecl_for_init = self._block_redeclared
        saved_redecl_saved_for_init = self._redeclared_saved
        self._block_redeclared = set()
        self._redeclared_saved = {}

        # Init
        if isinstance(stmt.init, VarDecl):
            self._build_var_decl(stmt.init)
        elif isinstance(stmt.init, Expression):
            self._build_expr(stmt.init)
        elif isinstance(stmt.init, ExpressionStmt):
            self._build_expr(stmt.init.expression)

        # Capture for-init redeclarations so we can restore after the entire for loop
        for_init_redeclared = self._block_redeclared.copy()
        for_init_saved = self._redeclared_saved.copy()
        self._block_redeclared = saved_redecl_for_init
        self._redeclared_saved = saved_redecl_saved_for_init

        header = self._fresh_block("for_header")
        body_block = self._fresh_block("for_body")
        update_block = self._fresh_block("for_update")
        exit_block = self._fresh_block("for_exit")

        # If this for loop is inside a labeled statement, register the exit target
        if self._pending_label:
            self._label_exits[self._pending_label] = exit_block.label
            self._pending_label = None

        entry_block = self._current_block
        pre_vars = dict(self._vars)
        self._current_block.terminator = HIRJump(target_block=header.label)

        # Header: phi nodes + condition
        self._current_block = header
        phi_map: dict[str, str] = {}
        for name, ssa in pre_vars.items():
            var_type = self._var_types.get(name, NUMBER)
            # Skip array/object/function vars — they are loop-invariant
            if isinstance(var_type, (ArrayType, ObjectType, FunctionType)):
                continue
            phi_ssa = self._fresh_ssa()
            phi = HIRPhi(
                incoming=[(ssa, entry_block.label)],
                result=phi_ssa,
                type=var_type,
            )
            header.instructions.append(phi)
            phi_map[name] = phi_ssa
            self._vars[name] = phi_ssa

        if stmt.condition:
            cond = self._build_expr(stmt.condition)
        else:
            cond = self._emit_const(True, BOOLEAN)

        self._current_block.terminator = HIRBranch(
            condition=cond,
            true_block=body_block.label,
            false_block=exit_block.label,
        )

        # Body — set loop labels for break/continue
        # continue jumps to update_block (not header), break jumps to exit_block
        old_loop_exit = self._loop_exit
        old_loop_continue = self._loop_continue
        old_continue_snapshots = self._continue_snapshots
        old_break_snapshots = self._break_snapshots
        self._loop_exit = exit_block.label
        self._loop_continue = update_block.label
        self._continue_snapshots = []
        self._break_snapshots = []
        self._current_block = body_block
        saved_redecl_f = self._block_redeclared
        saved_redecl_saved_f = self._redeclared_saved
        self._block_redeclared = set()
        self._redeclared_saved = {}
        self._build_block(stmt.body)
        for name in self._block_redeclared:
            if name in self._redeclared_saved:
                old_ssa, old_type = self._redeclared_saved[name]
                self._vars[name] = old_ssa
                self._var_types[name] = old_type
        self._block_redeclared = saved_redecl_f
        self._redeclared_saved = saved_redecl_saved_f
        continue_snapshots = self._continue_snapshots
        break_snapshots = self._break_snapshots
        self._loop_exit = old_loop_exit
        self._loop_continue = old_loop_continue
        self._continue_snapshots = old_continue_snapshots
        self._break_snapshots = old_break_snapshots

        body_end_vars = dict(self._vars)
        body_end_block = self._current_block
        body_falls_through = body_end_block.terminator is None
        if body_falls_through:
            body_end_block.terminator = HIRJump(target_block=update_block.label)

        # Reorder: move update and exit blocks after any blocks created during body
        # (e.g. inner loops). This ensures SSA values from inner loops are defined
        # before the outer update block references them.
        self._blocks.remove(update_block)
        self._blocks.remove(exit_block)
        self._blocks.append(update_block)
        self._blocks.append(exit_block)

        # Update block: merge values from body end + continue paths, run update, jump to header
        self._current_block = update_block

        # Collect all incoming edges to update block
        update_incoming: list[tuple[str, dict[str, str]]] = []
        if body_falls_through:
            update_incoming.append((body_end_block.label, body_end_vars))
        for cont_label, cont_vars in continue_snapshots:
            update_incoming.append((cont_label, cont_vars))

        if len(update_incoming) > 1:
            merged_vars: dict[str, str] = {}
            all_var_names = set()
            for _, vars_snap in update_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, phi_map.get(name, "")), label)
                        for label, vars_snap in update_incoming
                        if vars_snap.get(name, phi_map.get(name, ""))]
                if len(set(v for v, _ in vals)) == 1:
                    merged_vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    var_type = self._var_types.get(name, NUMBER)
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=var_type)
                    update_block.instructions.append(phi)
                    merged_vars[name] = phi_ssa
            self._vars = merged_vars
        elif len(update_incoming) == 1:
            self._vars = update_incoming[0][1]

        if stmt.update:
            self._build_expr(stmt.update)
        self._current_block.terminator = HIRJump(target_block=header.label)

        # Patch phi — the back-edge now comes from update_block
        body_exit = self._current_block  # update_block
        for instr in header.instructions:
            if isinstance(instr, HIRPhi):
                for name, phi_ssa in phi_map.items():
                    if instr.result == phi_ssa:
                        body_val = self._vars.get(name, phi_ssa)
                        instr.incoming.append((body_val, body_exit.label))
                        break

        # At exit, merge header phi values (condition-false path) with break snapshots
        self._current_block = exit_block
        header_vars = {name: phi_ssa for name, phi_ssa in phi_map.items()}

        exit_incoming: list[tuple[str, dict[str, str]]] = []
        exit_incoming.append((header.label, header_vars))
        for brk_label, brk_vars in break_snapshots:
            exit_incoming.append((brk_label, brk_vars))

        if len(exit_incoming) > 1:
            all_var_names = set()
            for _, vars_snap in exit_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, header_vars.get(name, "")), label)
                        for label, vars_snap in exit_incoming
                        if vars_snap.get(name, header_vars.get(name, ""))]
                if not vals:
                    continue
                unique_vals = set(v for v, _ in vals)
                if len(unique_vals) == 1:
                    self._vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    var_type = self._var_types.get(name, NUMBER)
                    if isinstance(var_type, (ArrayType, ObjectType, FunctionType)):
                        self._vars[name] = vals[0][0]
                        continue
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=var_type)
                    exit_block.instructions.append(phi)
                    self._vars[name] = phi_ssa
        else:
            for name, phi_ssa in phi_map.items():
                self._vars[name] = phi_ssa

        # Remove variables introduced inside the loop body from outer scope
        # (basic block scoping for let: temp vars from inner blocks shouldn't leak out)
        for name in list(self._vars.keys()):
            if name not in pre_vars and name not in phi_map:
                del self._vars[name]

        # Restore for-init shadowed variables (let i in for-init shouldn't leak)
        for name in for_init_redeclared:
            if name in for_init_saved:
                old_ssa, old_type = for_init_saved[name]
                self._vars[name] = old_ssa
                self._var_types[name] = old_type

    def _build_switch(self, stmt: SwitchStmt):
        """Build switch statement as chained comparisons + branches.

        Supports:
        - break: jumps to exit block
        - fall-through: if a case has no break/return, execution continues to next case body
        - default: unconditional jump if no case matches

        Strategy:
        1. Evaluate discriminant once
        2. Build chained test blocks: each tests discriminant === case.test
           On match → jump to case body; on mismatch → next test (or default/exit)
        3. Build case body blocks sequentially. Fall-through means the end of
           case i jumps into case i+1's body, carrying variable state forward.
           Since a case body can be entered from its test block (fresh vars) OR
           from the previous case's fall-through (modified vars), we use phi nodes
           at body entry when there are multiple predecessors.
        """
        exit_block = self._fresh_block("switch_exit")
        # Remove exit block temporarily so case blocks come first in block order
        self._blocks.remove(exit_block)

        # Evaluate discriminant once
        disc_val = self._build_expr(stmt.discriminant)
        disc_type = self._get_type(stmt.discriminant)

        cmp_op = "eq"

        # Set _loop_exit so that BreakStmt jumps to the switch exit block
        old_loop_exit = self._loop_exit
        self._loop_exit = exit_block.label

        pre_switch_vars = dict(self._vars)
        num_cases = len(stmt.cases)

        # Pre-create case body blocks and test blocks
        case_body_blocks: list[BasicBlock] = []
        case_test_blocks: list[BasicBlock | None] = []

        for i, case in enumerate(stmt.cases):
            case_body_blocks.append(self._fresh_block(f"switch_case_{i}"))
            if case.test is not None:
                case_test_blocks.append(self._fresh_block(f"switch_test_{i}"))
            else:
                case_test_blocks.append(None)  # default case has no test

        # Find the default case index
        default_idx = None
        for i, case in enumerate(stmt.cases):
            if case.test is None:
                default_idx = i
                break

        # Compute "no match" target: where to go if all tests fail
        if default_idx is not None:
            no_match_target = case_body_blocks[default_idx].label
        else:
            no_match_target = exit_block.label

        # Jump to the first test block (or default/exit if no test cases)
        first_test_idx = None
        for i in range(num_cases):
            if case_test_blocks[i] is not None:
                first_test_idx = i
                break

        if first_test_idx is not None:
            self._current_block.terminator = HIRJump(target_block=case_test_blocks[first_test_idx].label)
        else:
            self._current_block.terminator = HIRJump(target_block=no_match_target)

        # Build test blocks
        for i, case in enumerate(stmt.cases):
            if case.test is None:
                continue

            self._current_block = case_test_blocks[i]
            self._vars = dict(pre_switch_vars)

            test_val = self._build_expr(case.test)
            cmp_result = self._fresh_ssa()
            self._emit(HIRCompare(
                op=cmp_op, left=disc_val, right=test_val,
                result=cmp_result, operand_type=disc_type,
            ))

            # Find next test block on mismatch
            next_target = None
            for j in range(i + 1, num_cases):
                if case_test_blocks[j] is not None:
                    next_target = case_test_blocks[j].label
                    break
            if next_target is None:
                next_target = no_match_target

            self._current_block.terminator = HIRBranch(
                condition=cmp_result,
                true_block=case_body_blocks[i].label,
                false_block=next_target,
            )

        # Build case body blocks with fall-through support
        # Track: (exit_block, exit_vars) for each case that reaches exit_block
        case_exit_info: list[tuple[BasicBlock, dict[str, str]]] = []

        # fall_through_info: if previous case falls through, this holds
        # (source_block, vars_at_exit) so we can merge with the test entry.
        fall_through_info: tuple[BasicBlock, dict[str, str]] | None = None

        for i, case in enumerate(stmt.cases):
            self._current_block = case_body_blocks[i]

            # Determine incoming edges to this body block:
            # 1. From test block (or direct jump for default) - uses pre_switch_vars
            # 2. From previous case's fall-through - uses fall_through vars
            if fall_through_info is not None:
                ft_block, ft_vars = fall_through_info
                # We have two predecessors: merge with phi nodes
                # The "test entry" uses pre_switch_vars
                # The "fall-through" uses ft_vars
                # We need to figure out which blocks are predecessors.
                # Predecessor from test: the test block for this case, or
                #   for default, the last test block's false branch, or entry jump
                # We'll find the test predecessor(s) by examining who jumps here

                # Collect test predecessors
                test_pred_labels: list[str] = []
                for j in range(num_cases):
                    tb = case_test_blocks[j]
                    if tb is not None and tb.terminator is not None:
                        if isinstance(tb.terminator, HIRBranch):
                            if tb.terminator.true_block == case_body_blocks[i].label:
                                test_pred_labels.append(tb.label)
                            if tb.terminator.false_block == case_body_blocks[i].label:
                                test_pred_labels.append(tb.label)
                        elif isinstance(tb.terminator, HIRJump):
                            if tb.terminator.target_block == case_body_blocks[i].label:
                                test_pred_labels.append(tb.label)
                # Also check entry block jump (for first case or default-only)
                # This is already covered by test blocks

                merged_vars: dict[str, str] = {}
                all_names = set(pre_switch_vars.keys()) | set(ft_vars.keys())
                for name in all_names:
                    test_val = pre_switch_vars.get(name)
                    ft_val = ft_vars.get(name)
                    if test_val == ft_val and test_val is not None:
                        merged_vars[name] = test_val
                    elif test_pred_labels and test_val is not None and ft_val is not None:
                        phi_ssa = self._fresh_ssa()
                        incoming = [(ft_val, ft_block.label)]
                        for tpl in test_pred_labels:
                            incoming.append((test_val, tpl))
                        phi_type = self._var_types.get(name, NUMBER)
                        phi = HIRPhi(incoming=incoming, result=phi_ssa, type=phi_type)
                        case_body_blocks[i].instructions.append(phi)
                        merged_vars[name] = phi_ssa
                    elif ft_val is not None:
                        merged_vars[name] = ft_val
                    elif test_val is not None:
                        merged_vars[name] = test_val
                self._vars = merged_vars
                fall_through_info = None
            else:
                self._vars = dict(pre_switch_vars)

            # Build body statements
            for body_stmt in case.body:
                self._build_stmt(body_stmt)
                if self._current_block is None or self._current_block.terminator is not None:
                    break

            # Check what happened at end of case body
            case_exit_block = self._current_block
            if case_exit_block is not None and case_exit_block.terminator is None:
                # No break/return: fall through
                if i + 1 < num_cases:
                    case_exit_block.terminator = HIRJump(target_block=case_body_blocks[i + 1].label)
                    fall_through_info = (case_exit_block, dict(self._vars))
                else:
                    # Last case, no break: just jump to exit
                    case_exit_block.terminator = HIRJump(target_block=exit_block.label)
                    case_exit_info.append((case_exit_block, dict(self._vars)))
            elif case_exit_block is not None and isinstance(case_exit_block.terminator, HIRJump):
                if case_exit_block.terminator.target_block == exit_block.label:
                    case_exit_info.append((case_exit_block, dict(self._vars)))
                # else: some other jump (e.g. continue in a loop), don't add to exit info

        # Restore loop exit
        self._loop_exit = old_loop_exit

        # Also, the "no match" path may go directly to exit_block (when no default)
        # We need to account for that as a predecessor with pre_switch_vars
        no_match_reaches_exit = (default_idx is None)

        # Merge at exit block
        self._current_block = exit_block

        all_exit_paths: list[tuple[str, dict[str, str]]] = []
        for exit_blk, vars_snap in case_exit_info:
            all_exit_paths.append((exit_blk.label, vars_snap))

        if no_match_reaches_exit:
            # Find the block label that jumps to exit when no case matches
            # This is the last test block's false branch (or the entry block if no tests)
            # We need to find which block(s) have exit_block.label as target
            no_match_labels: list[str] = []
            for j in range(num_cases):
                tb = case_test_blocks[j]
                if tb is not None and tb.terminator is not None:
                    if isinstance(tb.terminator, HIRBranch):
                        if tb.terminator.false_block == exit_block.label:
                            no_match_labels.append(tb.label)
                    elif isinstance(tb.terminator, HIRJump):
                        if tb.terminator.target_block == exit_block.label:
                            no_match_labels.append(tb.label)
            for lbl in no_match_labels:
                all_exit_paths.append((lbl, pre_switch_vars))

        if all_exit_paths:
            all_var_names = set(pre_switch_vars.keys())
            for _, vars_snap in all_exit_paths:
                all_var_names.update(vars_snap.keys())

            for name in all_var_names:
                vals = []
                for exit_label, vars_snap in all_exit_paths:
                    v = vars_snap.get(name, pre_switch_vars.get(name))
                    if v is not None:
                        vals.append((v, exit_label))

                if not vals:
                    continue

                unique_vals = set(v for v, _ in vals)
                if len(unique_vals) == 1:
                    self._vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    phi_type = self._var_types.get(name, NUMBER)
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=phi_type)
                    exit_block.instructions.append(phi)
                    self._vars[name] = phi_ssa
        else:
            self._vars = dict(pre_switch_vars)

        # Re-append exit block at end so it comes after all case blocks in block order
        self._blocks.append(exit_block)

    def _build_expr(self, expr: Expression) -> str:
        if isinstance(expr, NumberLiteral):
            return self._emit_const(expr.value, NUMBER)

        if isinstance(expr, StringLiteral):
            return self._emit_const(expr.value, STRING)

        if isinstance(expr, BooleanLiteral):
            return self._emit_const(expr.value, BOOLEAN)

        if isinstance(expr, NullLiteral):
            return self._emit_const(None, VOID)

        if isinstance(expr, Identifier):
            if expr.name in self._vars:
                return self._vars[expr.name]
            # Global variable reference
            if expr.name in self._global_vars:
                from taiyaki_aot_compiler.hir.nodes import HIRLoadGlobal
                result = self._fresh_ssa()
                gtype = self._global_vars[expr.name]
                self._emit(HIRLoadGlobal(name=expr.name, result=result, type=gtype))
                return result
            # Function reference: emit function pointer
            if expr.name in self._functions:
                result = self._fresh_ssa()
                ft = self._functions[expr.name]
                self._emit(HIRFuncRef(func_name=expr.name, result=result, type=ft))
                return result
            # Global constants
            import math
            if expr.name == "Infinity":
                return self._emit_const(math.inf, NUMBER)
            if expr.name == "NaN":
                return self._emit_const(math.nan, NUMBER)
            if expr.name == "undefined":
                return self._emit_const(0.0, NUMBER)
            if expr.name == "null":
                return self._emit_const(0.0, NUMBER)

            # Raylib color constants (packed RGBA as f64)
            _RL_COLORS = {
                "WHITE": 0xFFFFFFFF, "BLACK": 0x000000FF,
                "RED": 0xFF0000FF, "GREEN": 0x00FF00FF,
                "BLUE": 0x0000FFFF, "YELLOW": 0xFFFF00FF,
                "ORANGE": 0xFF8000FF, "PURPLE": 0x8000FFFF,
                "GRAY": 0x808080FF, "DARKGRAY": 0x505050FF,
                "LIGHTGRAY": 0xC8C8C8FF, "RAYWHITE": 0xF5F5F5FF,
                "BROWN": 0x7F6347FF, "PINK": 0xFF6B9DFF,
                "MAROON": 0xBE2137FF, "LIME": 0x00E430FF,
                "SKYBLUE": 0x66BFFFFF, "DARKBLUE": 0x0082C8FF,
                "VIOLET": 0x7B69E0FF, "BEIGE": 0xD3B694FF,
                "MAGENTA": 0xFF00FFFF, "GOLD": 0xFFCB00FF,
                "BLANK": 0x00000000,
                "DARKGREEN": 0x006400FF,
                "DARKPURPLE": 0x702090FF,
                "DARKBROWN": 0x4C3224FF,
            }
            if expr.name in _RL_COLORS:
                return self._emit_const(float(_RL_COLORS[expr.name]), NUMBER)

            # Clay sizing constants
            _CLAY_CONSTS = {
                "CLAY_FIT": 0.0,
                "CLAY_GROW": -1.0,
                "CLAY_LEFT_TO_RIGHT": 0.0,
                "CLAY_TOP_TO_BOTTOM": 1.0,
            }
            if expr.name in _CLAY_CONSTS:
                return self._emit_const(_CLAY_CONSTS[expr.name], NUMBER)

            # Theme constants (packed RGBA u32 as f64)
            _THEME_COLORS = {
                "THEME_BG": 0x181820FF,
                "THEME_BG_SURFACE": 0x242430FF,
                "THEME_BG_SURFACE2": 0x2C2C3CFF,
                "THEME_FG": 0xE6E6F0FF,
                "THEME_FG_MUTED": 0x505064FF,
                "THEME_PRIMARY": 0x3C64B4FF,
                "THEME_PRIMARY_HOVER": 0x5080D0FF,
                "THEME_SECONDARY": 0x646478FF,
                "THEME_BORDER": 0x505064FF,
                "THEME_FOCUS": 0x3C5080FF,
                "THEME_SUCCESS": 0x50C878FF,
                "THEME_WARNING": 0xDCB450FF,
                "THEME_ERROR": 0xDC5050FF,
                "THEME_INFO": 0x5090DCFF,
                "THEME_ACCENT": 0x6450C8FF,
            }
            if expr.name in _THEME_COLORS:
                return self._emit_const(float(_THEME_COLORS[expr.name]), NUMBER)

            # Key constants (matching raylib)
            _KEY_CONSTS = {
                "KEY_ENTER": 257.0,
                "KEY_ESCAPE": 256.0,
                "KEY_TAB": 258.0,
                "KEY_BACKSPACE": 259.0,
                "KEY_DELETE": 261.0,
                "KEY_LEFT": 263.0,
                "KEY_RIGHT": 262.0,
                "KEY_UP": 265.0,
                "KEY_DOWN": 264.0,
                "KEY_HOME": 268.0,
                "KEY_END": 269.0,
                "KEY_SPACE": 32.0,
            }
            if expr.name in _KEY_CONSTS:
                return self._emit_const(_KEY_CONSTS[expr.name], NUMBER)

            # termbox2 event type constants
            _TB_CONSTS = {
                "TB_EVENT_KEY": 1.0,
                "TB_EVENT_RESIZE": 2.0,
                "TB_EVENT_MOUSE": 3.0,
                "TB_KEY_ESC": 27.0,
                "TB_KEY_ENTER": 13.0,
                "TB_KEY_TAB": 9.0,
                "TB_KEY_BACKSPACE": 127.0,
                "TB_KEY_ARROW_UP": 65517.0,
                "TB_KEY_ARROW_DOWN": 65516.0,
                "TB_KEY_ARROW_LEFT": 65515.0,
                "TB_KEY_ARROW_RIGHT": 65514.0,
                "TB_KEY_SPACE": 32.0,
                # Phase 4 additions
                "TB_KEY_DELETE": 65522.0,
                "TB_KEY_HOME": 65521.0,
                "TB_KEY_END": 65520.0,
                "TB_KEY_PGUP": 65519.0,
                "TB_KEY_PGDN": 65518.0,
                "TB_KEY_F1": 65535.0,
                "TB_KEY_F2": 65534.0,
                "TB_KEY_F3": 65533.0,
                "TB_KEY_F4": 65532.0,
                "TB_KEY_F5": 65531.0,
                "TB_KEY_F6": 65530.0,
                "TB_KEY_F7": 65529.0,
                "TB_KEY_F8": 65528.0,
                "TB_KEY_F9": 65527.0,
                "TB_KEY_F10": 65526.0,
                "TB_KEY_F11": 65525.0,
                "TB_KEY_F12": 65524.0,
                "TB_MOD_ALT": 1.0,
                "TB_MOD_CTRL": 2.0,
                "TB_MOD_SHIFT": 4.0,
                # TUI color constants
                "TB_COLOR_DEFAULT": 0.0,
                "TB_COLOR_BLACK": 1.0,
                "TB_COLOR_RED": 2.0,
                "TB_COLOR_GREEN": 3.0,
                "TB_COLOR_YELLOW": 4.0,
                "TB_COLOR_BLUE": 5.0,
                "TB_COLOR_MAGENTA": 6.0,
                "TB_COLOR_CYAN": 7.0,
                "TB_COLOR_WHITE": 8.0,
                # Text attributes
                "TB_ATTR_BOLD": 256.0,
                "TB_ATTR_UNDERLINE": 512.0,
                "TB_ATTR_REVERSE": 1024.0,
            }
            if expr.name in _TB_CONSTS:
                return self._emit_const(_TB_CONSTS[expr.name], NUMBER)

            # Raylib key codes
            _RL_KEYS = {
                "KEY_RIGHT": 262, "KEY_LEFT": 263, "KEY_DOWN": 264,
                "KEY_UP": 265, "KEY_SPACE": 32, "KEY_ENTER": 257,
                "KEY_ESCAPE": 256,
                "MOUSE_LEFT": 0, "MOUSE_RIGHT": 1, "MOUSE_MIDDLE": 2,
            }
            # KEY_A..KEY_Z
            for _c in range(65, 91):
                _RL_KEYS[f"KEY_{chr(_c)}"] = _c
            # KEY_0..KEY_9
            for _d in range(48, 58):
                _RL_KEYS[f"KEY_{chr(_d)}"] = _d
            if expr.name in _RL_KEYS:
                return self._emit_const(float(_RL_KEYS[expr.name]), NUMBER)

            # Gamepad button constants (Phase 5)
            _GP_CONSTS = {}
            for _gp in range(16):
                _GP_CONSTS[f"GAMEPAD_BUTTON_{_gp}"] = float(_gp)
            for _ga in range(6):
                _GP_CONSTS[f"GAMEPAD_AXIS_{_ga}"] = float(_ga)
            if expr.name in _GP_CONSTS:
                return self._emit_const(_GP_CONSTS[expr.name], NUMBER)

            # Window config flag constants (Phase 3)
            _FLAG_CONSTS = {
                "FLAG_FULLSCREEN_MODE": 2.0,
                "FLAG_WINDOW_RESIZABLE": 4.0,
                "FLAG_WINDOW_UNDECORATED": 8.0,
                "FLAG_WINDOW_TRANSPARENT": 16.0,
                "FLAG_MSAA_4X_HINT": 32.0,
                "FLAG_VSYNC_HINT": 64.0,
                "FLAG_WINDOW_HIGHDPI": 8192.0,
            }
            if expr.name in _FLAG_CONSTS:
                return self._emit_const(_FLAG_CONSTS[expr.name], NUMBER)

            return self._emit_const(expr.name, STRING)

        if isinstance(expr, BinaryExpr):
            if expr.op == "instanceof":
                # Compile-time instanceof: check if left's type matches right class name
                left_type = self._get_type(expr.left)
                self._build_expr(expr.left)  # evaluate for side effects
                if isinstance(expr.right, Identifier):
                    class_name = expr.right.name
                    # Check if left is an instance of the class (or subclass)
                    is_instance = False
                    if isinstance(left_type, ClassType):
                        # Walk up the inheritance chain
                        check_name = left_type.name
                        while check_name:
                            if check_name == class_name:
                                is_instance = True
                                break
                            decl = self._class_decls.get(check_name)
                            check_name = decl.extends if decl else None
                    return self._emit_const(is_instance, BOOLEAN)
                return self._emit_const(False, BOOLEAN)

            if expr.op == "in":
                # Compile-time 'in' operator: "key" in obj → check if field exists
                right_type = self._get_type(expr.right)
                if isinstance(expr.left, StringLiteral):
                    key = expr.left.value
                    has_key = False
                    if isinstance(right_type, ObjectType):
                        has_key = key in right_type.fields
                    elif isinstance(right_type, ClassType):
                        resolved = self._classes.get(right_type.name, right_type)
                        has_key = key in resolved.fields or key in resolved.methods
                    self._build_expr(expr.right)  # evaluate for side effects
                    return self._emit_const(has_key, BOOLEAN)
                self._build_expr(expr.left)
                self._build_expr(expr.right)
                return self._emit_const(False, BOOLEAN)

            if expr.op == "??":
                # Nullish coalescing: use right if left is null/void
                # At compile time, if left is a NullLiteral, just use right
                if isinstance(expr.left, NullLiteral):
                    return self._build_expr(expr.right)
                # Otherwise, treat like ||: use left if truthy, right otherwise
                return self._build_logical(LogicalExpr(
                    op="||", left=expr.left, right=expr.right, loc=expr.loc
                ))
            left = self._build_expr(expr.left)
            right = self._build_expr(expr.right)
            result_type = self._get_type(expr)
            op_name = _BINOP_MAP.get(expr.op, expr.op)

            # Auto-coerce number/boolean to string for string concatenation
            if op_name == "add" and isinstance(result_type, StringType):
                left_type = self._get_type(expr.left)
                right_type = self._get_type(expr.right)
                if isinstance(left_type, NumberType):
                    coerced = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="__tsuchi_num_to_str", args=[left],
                        result=coerced, type=STRING, is_js_fallback=True
                    ))
                    left = coerced
                elif isinstance(left_type, BooleanType):
                    coerced = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="__tsuchi_bool_to_str", args=[left],
                        result=coerced, type=STRING, is_js_fallback=True
                    ))
                    left = coerced
                if isinstance(right_type, NumberType):
                    coerced = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="__tsuchi_num_to_str", args=[right],
                        result=coerced, type=STRING, is_js_fallback=True
                    ))
                    right = coerced
                elif isinstance(right_type, BooleanType):
                    coerced = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="__tsuchi_bool_to_str", args=[right],
                        result=coerced, type=STRING, is_js_fallback=True
                    ))
                    right = coerced

            result = self._fresh_ssa()
            self._emit(HIRBinaryOp(op=op_name, left=left, right=right, result=result, type=result_type))
            return result

        if isinstance(expr, CompareExpr):
            left = self._build_expr(expr.left)
            right = self._build_expr(expr.right)
            result = self._fresh_ssa()
            op_name = _CMPOP_MAP.get(expr.op, expr.op)
            operand_type = self._get_type(expr.left)
            self._emit(HIRCompare(op=op_name, left=left, right=right, result=result, operand_type=operand_type))
            return result

        if isinstance(expr, LogicalExpr):
            return self._build_logical(expr)

        if isinstance(expr, UnaryExpr):
            if expr.op == "typeof":
                # Compile-time typeof: resolve operand type → string constant
                operand_type = self._get_type(expr.operand)
                if isinstance(operand_type, NumberType):
                    typeof_str = "number"
                elif isinstance(operand_type, BooleanType):
                    typeof_str = "boolean"
                elif isinstance(operand_type, StringType):
                    typeof_str = "string"
                elif isinstance(operand_type, FunctionType):
                    typeof_str = "function"
                elif isinstance(operand_type, ObjectType):
                    typeof_str = "object"
                elif isinstance(operand_type, ArrayType):
                    typeof_str = "object"
                else:
                    typeof_str = "undefined"
                return self._emit_const(typeof_str, STRING)
            if expr.op == "void":
                # void evaluates operand for side effects, returns undefined (0)
                self._build_expr(expr.operand)
                return self._emit_const(0.0, NUMBER)
            operand = self._build_expr(expr.operand)
            result = self._fresh_ssa()
            op_name = {"-": "neg", "+": "pos", "!": "not", "~": "bit_not"}.get(expr.op, expr.op)
            result_type = self._get_type(expr)
            self._emit(HIRUnaryOp(op=op_name, operand=operand, result=result, type=result_type))
            return result

        if isinstance(expr, UpdateExpr):
            return self._build_update(expr)

        if isinstance(expr, ConditionalExpr):
            return self._build_ternary(expr)

        if isinstance(expr, CallExpr):
            return self._build_call(expr)

        if isinstance(expr, TemplateLiteral):
            return self._build_template_literal(expr)

        if isinstance(expr, ArrayLiteral):
            return self._build_array_literal(expr)

        if isinstance(expr, ObjectLiteralExpr):
            return self._build_object_literal(expr)

        if isinstance(expr, MemberExpr):
            return self._build_member_access(expr)

        if isinstance(expr, AssignExpr):
            return self._build_assign(expr)

        if isinstance(expr, ArrowFunction):
            return self._build_arrow_ref(expr)

        if isinstance(expr, NewExpr):
            return self._build_new_expr(expr)

        if isinstance(expr, ThisExpr):
            if "this" in self._vars:
                return self._vars["this"]
            return self._emit_const(0.0, NUMBER)

        if isinstance(expr, SuperCall):
            return self._build_super_call(expr)

        if isinstance(expr, SpreadElement):
            # SpreadElement used as an expression (e.g., in array literal — handled separately)
            return self._build_expr(expr.argument)

        if isinstance(expr, SequenceExpr):
            # (a, b, c) → evaluate all, return last
            result = self._emit_const(0.0, NUMBER)
            for sub in expr.expressions:
                result = self._build_expr(sub)
            return result

        if isinstance(expr, AwaitExpr):
            promise_var = self._build_expr(expr.argument)
            result = self._fresh_ssa()
            # Determine the result type
            promise_type = self._get_type(expr.argument)
            if isinstance(promise_type, PromiseType):
                result_type = promise_type.inner_type
            else:
                result_type = self._get_type(expr)
            self._emit(HIRAwait(promise=promise_var, result=result, result_type=result_type))
            return result

        # Fallback
        return self._emit_const(0.0, NUMBER)

    def _build_super_call(self, expr: SuperCall) -> str:
        """Build super(args) → call parent class constructor with this."""
        # Find the current class from the function name (__ClassName_constructor)
        func_name = self._current_func_name if hasattr(self, '_current_func_name') else ""
        parent_class = None
        if func_name.startswith("__") and "_constructor" in func_name:
            class_name = func_name[2:].rsplit("_constructor", 1)[0]
            if class_name in self._class_decls:
                decl = self._class_decls[class_name]
                parent_class = decl.extends

        if parent_class and f"__{parent_class}_constructor" in self._functions:
            ctor_name = f"__{parent_class}_constructor"
            this_var = self._vars.get("this")
            if this_var:
                args = [this_var]
                for arg_expr in expr.arguments:
                    args.append(self._build_expr(arg_expr))
                result = self._fresh_ssa()
                self._emit(HIRCall(
                    func_name=ctor_name, args=args,
                    result=result, type=VOID,
                ))
                return result

        return self._emit_const(0.0, NUMBER)

    def _build_logical(self, expr: LogicalExpr) -> str:
        left = self._build_expr(expr.left)
        result_type = self._get_type(expr)

        right_block = self._fresh_block("logical_right")
        merge_block = self._fresh_block("logical_merge")

        if expr.op == "&&":
            self._current_block.terminator = HIRBranch(
                condition=left, true_block=right_block.label, false_block=merge_block.label
            )
        else:  # ||
            self._current_block.terminator = HIRBranch(
                condition=left, true_block=merge_block.label, false_block=right_block.label
            )

        left_exit = self._current_block

        self._current_block = right_block
        right = self._build_expr(expr.right)
        right_exit = self._current_block
        if right_exit.terminator is None:
            right_exit.terminator = HIRJump(target_block=merge_block.label)

        self._current_block = merge_block
        phi_result = self._fresh_ssa()
        phi = HIRPhi(
            incoming=[(left, left_exit.label), (right, right_exit.label)],
            result=phi_result,
            type=result_type,
        )
        merge_block.instructions.append(phi)
        return phi_result

    def _build_ternary(self, expr: ConditionalExpr) -> str:
        cond = self._build_expr(expr.condition)
        result_type = self._get_type(expr)

        then_block = self._fresh_block("tern_then")
        else_block = self._fresh_block("tern_else")
        merge_block = self._fresh_block("tern_merge")

        self._current_block.terminator = HIRBranch(
            condition=cond, true_block=then_block.label, false_block=else_block.label
        )

        self._current_block = then_block
        then_val = self._build_expr(expr.consequent)
        then_exit = self._current_block
        if then_exit.terminator is None:
            then_exit.terminator = HIRJump(target_block=merge_block.label)

        self._current_block = else_block
        else_val = self._build_expr(expr.alternate)
        else_exit = self._current_block
        if else_exit.terminator is None:
            else_exit.terminator = HIRJump(target_block=merge_block.label)

        self._current_block = merge_block
        phi_result = self._fresh_ssa()
        phi = HIRPhi(
            incoming=[(then_val, then_exit.label), (else_val, else_exit.label)],
            result=phi_result,
            type=result_type,
        )
        merge_block.instructions.append(phi)
        return phi_result

    def _build_call(self, expr: CallExpr) -> str:
        # Handle console.log specially
        if isinstance(expr.callee, MemberExpr):
            return self._build_member_call_expr(expr)

        if isinstance(expr.callee, Identifier):
            func_name = expr.callee.name

            # FFI functions (from @ffi pragmas)
            if self._ffi_info is not None and func_name in self._ffi_info.functions:
                ffi_fn = self._ffi_info.functions[func_name]
                hir_name = f"__tsuchi_ffi_{ffi_fn.c_name}"
                args = self._build_ffi_args(expr.arguments, ffi_fn.param_types)
                result = self._fresh_ssa()
                self._emit(HIRCall(func_name=hir_name, args=args, result=result, type=ffi_fn.return_type))
                return result

            # Built-in global functions
            _BUILTIN_GLOBALS = {
                "parseInt": ("__tsuchi_parseInt", NUMBER),
                "parseFloat": ("__tsuchi_parseFloat", NUMBER),
                "Number": ("__tsuchi_Number", NUMBER),
                "String": ("__tsuchi_String", STRING),
                "Boolean": ("__tsuchi_Boolean", BOOLEAN),
                "isNaN": ("__tsuchi_isNaN", BOOLEAN),
                "readFile": ("__tsuchi_readFile", STRING),
                "writeFile": ("__tsuchi_writeFile", VOID),
                "exec": ("__tsuchi_exec", STRING),
                "httpGet": ("__tsuchi_httpGet", STRING),
                "httpPost": ("__tsuchi_httpPost", STRING),
                "setTimeout": ("__tsuchi_setTimeout_async", PromiseType(VOID)),
                "fetch": ("__tsuchi_fetch_async", PromiseType(STRING)),
                # Raylib: core window
                "initWindow": ("__tsuchi_rl_initWindow", VOID),
                "closeWindow": ("__tsuchi_rl_closeWindow", VOID),
                "windowShouldClose": ("__tsuchi_rl_windowShouldClose", BOOLEAN),
                "setTargetFPS": ("__tsuchi_rl_setTargetFPS", VOID),
                "getScreenWidth": ("__tsuchi_rl_getScreenWidth", NUMBER),
                "getScreenHeight": ("__tsuchi_rl_getScreenHeight", NUMBER),
                "getFrameTime": ("__tsuchi_rl_getFrameTime", NUMBER),
                "getTime": ("__tsuchi_rl_getTime", NUMBER),
                "getFPS": ("__tsuchi_rl_getFPS", NUMBER),
                # Raylib: window extended (Phase 3)
                "toggleFullscreen": ("__tsuchi_rl_toggleFullscreen", VOID),
                "setWindowSize": ("__tsuchi_rl_setWindowSize", VOID),
                "setWindowTitle": ("__tsuchi_rl_setWindowTitle", VOID),
                "setConfigFlags": ("__tsuchi_rl_setConfigFlags", VOID),
                "isWindowFocused": ("__tsuchi_rl_isWindowFocused", BOOLEAN),
                "isWindowResized": ("__tsuchi_rl_isWindowResized", BOOLEAN),
                # Raylib: drawing
                "beginDrawing": ("__tsuchi_rl_beginDrawing", VOID),
                "endDrawing": ("__tsuchi_rl_endDrawing", VOID),
                "clearBackground": ("__tsuchi_rl_clearBackground", VOID),
                "drawRectangle": ("__tsuchi_rl_drawRectangle", VOID),
                "drawRectangleLines": ("__tsuchi_rl_drawRectangleLines", VOID),
                "drawCircle": ("__tsuchi_rl_drawCircle", VOID),
                "drawCircleLines": ("__tsuchi_rl_drawCircleLines", VOID),
                "drawLine": ("__tsuchi_rl_drawLine", VOID),
                "drawText": ("__tsuchi_rl_drawText", VOID),
                "drawTriangle": ("__tsuchi_rl_drawTriangle", VOID),
                "measureText": ("__tsuchi_rl_measureText", NUMBER),
                # Raylib: extended shapes (Phase 3)
                "drawRectanglePro": ("__tsuchi_rl_drawRectanglePro", VOID),
                "drawRectangleRounded": ("__tsuchi_rl_drawRectangleRounded", VOID),
                "drawRectangleGradientV": ("__tsuchi_rl_drawRectangleGradientV", VOID),
                "drawRectangleGradientH": ("__tsuchi_rl_drawRectangleGradientH", VOID),
                "drawLineEx": ("__tsuchi_rl_drawLineEx", VOID),
                "drawPixel": ("__tsuchi_rl_drawPixel", VOID),
                "drawCircleSector": ("__tsuchi_rl_drawCircleSector", VOID),
                # Raylib: textures
                "loadFont": ("__tsuchi_rl_loadFont", VOID),
                "loadTexture": ("__tsuchi_rl_loadTexture", NUMBER),
                "drawTexture": ("__tsuchi_rl_drawTexture", VOID),
                "unloadTexture": ("__tsuchi_rl_unloadTexture", VOID),
                # Raylib: texture pro (Phase 3)
                "drawTextureRec": ("__tsuchi_rl_drawTextureRec", VOID),
                "drawTexturePro": ("__tsuchi_rl_drawTexturePro", VOID),
                "getTextureWidth": ("__tsuchi_rl_getTextureWidth", NUMBER),
                "getTextureHeight": ("__tsuchi_rl_getTextureHeight", NUMBER),
                # Raylib: text pro (Phase 3)
                "drawTextEx": ("__tsuchi_rl_drawTextEx", VOID),
                "measureTextEx": ("__tsuchi_rl_measureTextEx", NUMBER),
                # Raylib: input keyboard
                "isKeyDown": ("__tsuchi_rl_isKeyDown", BOOLEAN),
                "isKeyPressed": ("__tsuchi_rl_isKeyPressed", BOOLEAN),
                "isKeyReleased": ("__tsuchi_rl_isKeyReleased", BOOLEAN),
                "getKeyPressed": ("__tsuchi_rl_getKeyPressed", NUMBER),
                "getCharPressed": ("__tsuchi_rl_getCharPressed", NUMBER),
                "isKeyUp": ("__tsuchi_rl_isKeyUp", BOOLEAN),
                # Raylib: input mouse
                "getMouseX": ("__tsuchi_rl_getMouseX", NUMBER),
                "getMouseY": ("__tsuchi_rl_getMouseY", NUMBER),
                "isMouseButtonDown": ("__tsuchi_rl_isMouseButtonDown", BOOLEAN),
                "isMouseButtonPressed": ("__tsuchi_rl_isMouseButtonPressed", BOOLEAN),
                "isMouseButtonReleased": ("__tsuchi_rl_isMouseButtonReleased", BOOLEAN),
                "getMouseWheelMove": ("__tsuchi_rl_getMouseWheelMove", NUMBER),
                # Raylib: color helper
                "color": ("__tsuchi_rl_color", NUMBER),
                "colorAlpha": ("__tsuchi_rl_colorAlpha", NUMBER),
                # Raylib: audio device (Phase 1)
                "initAudioDevice": ("__tsuchi_rl_initAudioDevice", VOID),
                "closeAudioDevice": ("__tsuchi_rl_closeAudioDevice", VOID),
                "setMasterVolume": ("__tsuchi_rl_setMasterVolume", VOID),
                "getMasterVolume": ("__tsuchi_rl_getMasterVolume", NUMBER),
                # Raylib: sound (Phase 1)
                "loadSound": ("__tsuchi_rl_loadSound", NUMBER),
                "playSound": ("__tsuchi_rl_playSound", VOID),
                "stopSound": ("__tsuchi_rl_stopSound", VOID),
                "pauseSound": ("__tsuchi_rl_pauseSound", VOID),
                "resumeSound": ("__tsuchi_rl_resumeSound", VOID),
                "setSoundVolume": ("__tsuchi_rl_setSoundVolume", VOID),
                "setSoundPitch": ("__tsuchi_rl_setSoundPitch", VOID),
                "isSoundPlaying": ("__tsuchi_rl_isSoundPlaying", BOOLEAN),
                "unloadSound": ("__tsuchi_rl_unloadSound", VOID),
                # Raylib: music (Phase 1)
                "loadMusic": ("__tsuchi_rl_loadMusic", NUMBER),
                "playMusic": ("__tsuchi_rl_playMusic", VOID),
                "stopMusic": ("__tsuchi_rl_stopMusic", VOID),
                "pauseMusic": ("__tsuchi_rl_pauseMusic", VOID),
                "resumeMusic": ("__tsuchi_rl_resumeMusic", VOID),
                "updateMusic": ("__tsuchi_rl_updateMusic", VOID),
                "setMusicVolume": ("__tsuchi_rl_setMusicVolume", VOID),
                "isMusicPlaying": ("__tsuchi_rl_isMusicPlaying", BOOLEAN),
                "getMusicTimeLength": ("__tsuchi_rl_getMusicTimeLength", NUMBER),
                "getMusicTimePlayed": ("__tsuchi_rl_getMusicTimePlayed", NUMBER),
                "unloadMusic": ("__tsuchi_rl_unloadMusic", VOID),
                # Raylib: camera2D (Phase 2)
                "beginMode2D": ("__tsuchi_rl_beginMode2D", VOID),
                "endMode2D": ("__tsuchi_rl_endMode2D", VOID),
                # Raylib: collision (Phase 2)
                "checkCollisionRecs": ("__tsuchi_rl_checkCollisionRecs", BOOLEAN),
                "checkCollisionCircles": ("__tsuchi_rl_checkCollisionCircles", BOOLEAN),
                "checkCollisionCircleRec": ("__tsuchi_rl_checkCollisionCircleRec", BOOLEAN),
                "checkCollisionPointRec": ("__tsuchi_rl_checkCollisionPointRec", BOOLEAN),
                "checkCollisionPointCircle": ("__tsuchi_rl_checkCollisionPointCircle", BOOLEAN),
                # Raylib: random (Phase 2)
                "getRandomValue": ("__tsuchi_rl_getRandomValue", NUMBER),
                # Raylib: gamepad (Phase 5)
                "isGamepadAvailable": ("__tsuchi_rl_isGamepadAvailable", BOOLEAN),
                "isGamepadButtonDown": ("__tsuchi_rl_isGamepadButtonDown", BOOLEAN),
                "isGamepadButtonPressed": ("__tsuchi_rl_isGamepadButtonPressed", BOOLEAN),
                "isGamepadButtonReleased": ("__tsuchi_rl_isGamepadButtonReleased", BOOLEAN),
                "getGamepadAxisMovement": ("__tsuchi_rl_getGamepadAxisMovement", NUMBER),
                "getGamepadAxisCount": ("__tsuchi_rl_getGamepadAxisCount", NUMBER),
                "getGamepadButtonPressed": ("__tsuchi_rl_getGamepadButtonPressed", NUMBER),
                "getGamepadName": ("__tsuchi_rl_getGamepadName", BOOLEAN),
                # Raylib: music extended
                "seekMusic": ("__tsuchi_rl_seekMusic", VOID),
                "setMusicPitch": ("__tsuchi_rl_setMusicPitch", VOID),
                # Raylib: audio device extended
                "isAudioDeviceReady": ("__tsuchi_rl_isAudioDeviceReady", BOOLEAN),
                # Raylib: font extended
                "unloadFont": ("__tsuchi_rl_unloadFont", VOID),
                # Raylib: text measurement extended
                "measureTextExY": ("__tsuchi_rl_measureTextExY", NUMBER),
                # Raylib: texture extended
                "drawTextureScaled": ("__tsuchi_rl_drawTextureScaled", VOID),
                "isTextureValid": ("__tsuchi_rl_isTextureValid", BOOLEAN),
                # Raylib: camera2D extended
                "getWorldToScreen2DX": ("__tsuchi_rl_getWorldToScreen2DX", NUMBER),
                "getWorldToScreen2DY": ("__tsuchi_rl_getWorldToScreen2DY", NUMBER),
                # Raylib: gamepad extended
                "isGamepadButtonUp": ("__tsuchi_rl_isGamepadButtonUp", BOOLEAN),
                # File system
                "fileExists": ("__tsuchi_rl_fileExists", BOOLEAN),
                "directoryExists": ("__tsuchi_rl_directoryExists", BOOLEAN),
                # Clay UI
                "clayInit": ("__tsuchi_clay_init", VOID),
                "clayLoadFont": ("__tsuchi_clay_loadFont", NUMBER),
                "claySetDimensions": ("__tsuchi_clay_setDimensions", VOID),
                "claySetPointer": ("__tsuchi_clay_setPointer", VOID),
                "clayUpdateScroll": ("__tsuchi_clay_updateScroll", VOID),
                "clayBeginLayout": ("__tsuchi_clay_beginLayout", VOID),
                "clayEndLayout": ("__tsuchi_clay_endLayout", VOID),
                "clayRender": ("__tsuchi_clay_render", VOID),
                "clayOpen": ("__tsuchi_clay_open", VOID),
                "clayOpenAligned": ("__tsuchi_clay_openAligned", VOID),
                "clayClose": ("__tsuchi_clay_close", VOID),
                "clayText": ("__tsuchi_clay_text", VOID),
                "clayPointerOver": ("__tsuchi_clay_pointerOver", BOOLEAN),
                # Clay GUI extensions (scroll, floating, border, openI, etc.)
                "clayScroll": ("__tsuchi_clay_scroll", VOID),
                "clayFloating": ("__tsuchi_clay_floating", VOID),
                "clayBorder": ("__tsuchi_clay_border", VOID),
                "clayOpenI": ("__tsuchi_clay_openI", VOID),
                "clayPointerOverI": ("__tsuchi_clay_pointerOverI", BOOLEAN),
                "claySetMeasureTextRaylib": ("__tsuchi_clay_setMeasureTextRaylib", VOID),
                "clayLoadFontCjk": ("__tsuchi_clay_loadFontCjk", NUMBER),
                "claySetCustom": ("__tsuchi_clay_setCustom", VOID),
                "clayDestroy": ("__tsuchi_clay_destroy", VOID),
                "clayRenderRaylib": ("__tsuchi_clay_renderRaylib", VOID),
                "clayRegisterResizeCallback": ("__tsuchi_clay_registerResizeCallback", VOID),
                "claySetBgColor": ("__tsuchi_clay_setBgColor", VOID),
                # Clay TUI (termbox2 backend)
                "clayTuiInit": ("__tsuchi_clay_tui_init", VOID),
                "clayTuiDestroy": ("__tsuchi_clay_tui_destroy", VOID),
                "clayTuiSetDimensions": ("__tsuchi_clay_tui_setDimensions", VOID),
                "clayTuiBeginLayout": ("__tsuchi_clay_tui_beginLayout", VOID),
                "clayTuiEndLayout": ("__tsuchi_clay_tui_endLayout", VOID),
                "clayTuiRender": ("__tsuchi_clay_tui_render", VOID),
                "clayTuiOpen": ("__tsuchi_clay_tui_open", VOID),
                "clayTuiCloseElement": ("__tsuchi_clay_tui_closeElement", VOID),
                "clayTuiText": ("__tsuchi_clay_tui_text", VOID),
                "clayTuiSetPointer": ("__tsuchi_clay_tui_setPointer", VOID),
                "clayTuiPointerOver": ("__tsuchi_clay_tui_pointerOver", BOOLEAN),
                "clayTuiPeekEvent": ("__tsuchi_clay_tui_peekEvent", NUMBER),
                "clayTuiPollEvent": ("__tsuchi_clay_tui_pollEvent", NUMBER),
                "clayTuiEventType": ("__tsuchi_clay_tui_eventType", NUMBER),
                "clayTuiEventKey": ("__tsuchi_clay_tui_eventKey", NUMBER),
                "clayTuiEventCh": ("__tsuchi_clay_tui_eventCh", NUMBER),
                "clayTuiEventW": ("__tsuchi_clay_tui_eventW", NUMBER),
                "clayTuiEventH": ("__tsuchi_clay_tui_eventH", NUMBER),
                "clayTuiTermWidth": ("__tsuchi_clay_tui_termWidth", NUMBER),
                "clayTuiTermHeight": ("__tsuchi_clay_tui_termHeight", NUMBER),
                "clayTuiEventMod": ("__tsuchi_clay_tui_eventMod", NUMBER),
                # Clay TUI extensions (Phase 4)
                "clayTuiBorder": ("__tsuchi_clay_tui_border", VOID),
                "clayTuiAlign": ("__tsuchi_clay_tui_align", VOID),
                "clayTuiScroll": ("__tsuchi_clay_tui_scroll", VOID),
                "clayTuiUpdateScroll": ("__tsuchi_clay_tui_updateScroll", VOID),
                "clayTuiOpenI": ("__tsuchi_clay_tui_openI", VOID),
                "clayTuiTextbufClear": ("__tsuchi_clay_tui_textbufClear", VOID),
                "clayTuiTextbufPutchar": ("__tsuchi_clay_tui_textbufPutchar", VOID),
                "clayTuiTextbufBackspace": ("__tsuchi_clay_tui_textbufBackspace", VOID),
                "clayTuiTextbufDelete": ("__tsuchi_clay_tui_textbufDelete", VOID),
                "clayTuiTextbufCursorLeft": ("__tsuchi_clay_tui_textbufCursorLeft", VOID),
                "clayTuiTextbufCursorRight": ("__tsuchi_clay_tui_textbufCursorRight", VOID),
                "clayTuiTextbufHome": ("__tsuchi_clay_tui_textbufHome", VOID),
                "clayTuiTextbufEnd": ("__tsuchi_clay_tui_textbufEnd", VOID),
                "clayTuiTextbufLen": ("__tsuchi_clay_tui_textbufLen", NUMBER),
                "clayTuiTextbufCursor": ("__tsuchi_clay_tui_textbufCursor", NUMBER),
                "clayTuiTextbufRender": ("__tsuchi_clay_tui_textbufRender", VOID),
                # Clay TUI Phase B extensions
                "clayTuiTextbufCopy": ("__tsuchi_clay_tui_textbufCopy", STRING),
                "clayTuiTextbufRenderRange": ("__tsuchi_clay_tui_textbufRenderRange", VOID),
                "clayTuiTextChar": ("__tsuchi_clay_tui_textChar", VOID),
                "clayTuiPointerOverI": ("__tsuchi_clay_tui_pointerOverI", BOOLEAN),
                "clayTuiEventMouseX": ("__tsuchi_clay_tui_eventMouseX", NUMBER),
                "clayTuiEventMouseY": ("__tsuchi_clay_tui_eventMouseY", NUMBER),
                "clayTuiRgb": ("__tsuchi_clay_tui_rgb", NUMBER),
                "clayTuiBgEx": ("__tsuchi_clay_tui_bgEx", VOID),
                "clayTuiTextEx": ("__tsuchi_clay_tui_textEx", VOID),
                "clayTuiFloating": ("__tsuchi_clay_tui_floating", VOID),
                # Interactive Widgets
                "beginFrame": ("__tsuchi_ui_beginFrame", VOID),
                "endFrame": ("__tsuchi_ui_endFrame", VOID),
                "buttonOpen": ("__tsuchi_ui_buttonOpen", VOID),
                "buttonClose": ("__tsuchi_ui_buttonClose", VOID),
                "checkboxOpen": ("__tsuchi_ui_checkboxOpen", VOID),
                "checkboxClose": ("__tsuchi_ui_checkboxClose", VOID),
                "radioOpen": ("__tsuchi_ui_radioOpen", VOID),
                "radioClose": ("__tsuchi_ui_radioClose", VOID),
                "toggleOpen": ("__tsuchi_ui_toggleOpen", VOID),
                "toggleClose": ("__tsuchi_ui_toggleClose", VOID),
                "textInput": ("__tsuchi_ui_textInput", VOID),
                "slider": ("__tsuchi_ui_slider", VOID),
                "menuItemOpen": ("__tsuchi_ui_menuItemOpen", VOID),
                "menuItemClose": ("__tsuchi_ui_menuItemClose", VOID),
                "tabButtonOpen": ("__tsuchi_ui_tabButtonOpen", VOID),
                "tabButtonClose": ("__tsuchi_ui_tabButtonClose", VOID),
                "numberStepper": ("__tsuchi_ui_numberStepper", VOID),
                "searchBar": ("__tsuchi_ui_searchBar", VOID),
                "listItemOpen": ("__tsuchi_ui_listItemOpen", VOID),
                "listItemClose": ("__tsuchi_ui_listItemClose", VOID),
                "clicked": ("__tsuchi_ui_clicked", BOOLEAN),
                "hovered": ("__tsuchi_ui_hovered", BOOLEAN),
                "toggled": ("__tsuchi_ui_toggled", BOOLEAN),
                "sliderValue": ("__tsuchi_ui_sliderValue", NUMBER),
                "focusNext": ("__tsuchi_ui_focusNext", VOID),
                "focusPrev": ("__tsuchi_ui_focusPrev", VOID),
                "uiKeyPressed": ("__tsuchi_ui_keyPressed", NUMBER),
                "uiCharPressed": ("__tsuchi_ui_charPressed", NUMBER),
                # Part 2B - Forms
                "textareaInput": ("__tsuchi_ui_textareaInput", VOID),
                "switchOpen": ("__tsuchi_ui_switchOpen", VOID),
                "switchClose": ("__tsuchi_ui_switchClose", VOID),
                "ratingOpen": ("__tsuchi_ui_ratingOpen", VOID),
                "ratingClose": ("__tsuchi_ui_ratingClose", VOID),
                "ratingValue": ("__tsuchi_ui_sliderValue", NUMBER),
                "segmentButtonOpen": ("__tsuchi_ui_segmentButtonOpen", VOID),
                "segmentButtonClose": ("__tsuchi_ui_segmentButtonClose", VOID),
                # Part 2C - Navigation
                "navPush": ("__tsuchi_ui_navPush", VOID),
                "navPop": ("__tsuchi_ui_navPop", VOID),
                "navCurrent": ("__tsuchi_ui_navCurrent", NUMBER),
                "navDepth": ("__tsuchi_ui_navDepth", NUMBER),
                # Part 2D - Overlay
                "accordionOpen": ("__tsuchi_ui_accordionOpen", VOID),
                "accordionClose": ("__tsuchi_ui_accordionClose", VOID),
                "accordionToggled": ("__tsuchi_ui_toggled", BOOLEAN),
                "dropdownOpen": ("__tsuchi_ui_dropdownOpen", VOID),
                "dropdownClose": ("__tsuchi_ui_dropdownClose", VOID),
                "dropdownIsOpen": ("__tsuchi_ui_dropdownIsOpen", BOOLEAN),
                "tooltipBegin": ("__tsuchi_ui_tooltipBegin", VOID),
                "tooltipEnd": ("__tsuchi_ui_tooltipEnd", VOID),
                "toastShow": ("__tsuchi_ui_toastShow", VOID),
                "toastRender": ("__tsuchi_ui_toastRender", VOID),
                # Part 2E - Charts
                "chartInit": ("__tsuchi_ui_chartInit", VOID),
                "chartSet": ("__tsuchi_ui_chartSet", VOID),
                "chartColor": ("__tsuchi_ui_chartColor", VOID),
                "chartRender": ("__tsuchi_ui_chartRender", VOID),
                # Part 2F - Markdown
                "markdownRender": ("__tsuchi_ui_markdownRender", VOID),
                # Part 2G - Other
                "uiSpinnerChar": ("__tsuchi_ui_spinnerChar", STRING),
                "uiFrameCount": ("__tsuchi_ui_frameCount", NUMBER),
                "uiStyle": ("__tsuchi_ui_style", NUMBER),
                "uiStyleMerge": ("__tsuchi_ui_styleMerge", NUMBER),
                "uiStyleSize": ("__tsuchi_ui_styleSize", NUMBER),
                "uiStyleKind": ("__tsuchi_ui_styleKind", NUMBER),
                "uiStyleFlex": ("__tsuchi_ui_styleFlex", NUMBER),
                # Game Framework
                "gfClamp": ("__tsuchi_gf_clamp", NUMBER),
                "gfLerp": ("__tsuchi_gf_lerp", NUMBER),
                "gfRand": ("__tsuchi_gf_rand", NUMBER),
                "gfRandRange": ("__tsuchi_gf_randRange", NUMBER),
                "gfRgba": ("__tsuchi_gf_rgba", NUMBER),
                "gfDrawBar": ("__tsuchi_gf_drawBar", VOID),
                "gfDrawBox": ("__tsuchi_gf_drawBox", VOID),
                "gfDrawNum": ("__tsuchi_gf_drawNum", VOID),
                "gfDrawFPS": ("__tsuchi_gf_drawFPS", VOID),
                "gfDrawTile": ("__tsuchi_gf_drawTile", VOID),
                "gfDrawSprite": ("__tsuchi_gf_drawSprite", VOID),
                "gfDrawFade": ("__tsuchi_gf_drawFade", VOID),
                "gfGetDirection": ("__tsuchi_gf_getDirection", NUMBER),
                "gfConfirmPressed": ("__tsuchi_gf_confirmPressed", BOOLEAN),
                "gfCancelPressed": ("__tsuchi_gf_cancelPressed", BOOLEAN),
                "gfMenuCursor": ("__tsuchi_gf_menuCursor", NUMBER),
                "gfAnimate": ("__tsuchi_gf_animate", NUMBER),
                "gfTimerSet": ("__tsuchi_gf_timerSet", VOID),
                "gfTimerRepeat": ("__tsuchi_gf_timerRepeat", VOID),
                "gfTimerTick": ("__tsuchi_gf_timerTick", VOID),
                "gfTimerActive": ("__tsuchi_gf_timerActive", BOOLEAN),
                "gfTimerDone": ("__tsuchi_gf_timerDone", BOOLEAN),
                "gfTimerCancel": ("__tsuchi_gf_timerCancel", VOID),
                "gfTweenStart": ("__tsuchi_gf_tweenStart", VOID),
                "gfTweenTick": ("__tsuchi_gf_tweenTick", VOID),
                "gfTweenValue": ("__tsuchi_gf_tweenValue", NUMBER),
                "gfTweenActive": ("__tsuchi_gf_tweenActive", BOOLEAN),
                "gfTweenDone": ("__tsuchi_gf_tweenDone", BOOLEAN),
                "gfInterpolate": ("__tsuchi_gf_interpolate", NUMBER),
                "gfEaseLinear": ("__tsuchi_gf_easeLinear", NUMBER),
                "gfEaseInQuad": ("__tsuchi_gf_easeInQuad", NUMBER),
                "gfEaseOutQuad": ("__tsuchi_gf_easeOutQuad", NUMBER),
                "gfEaseInOutQuad": ("__tsuchi_gf_easeInOutQuad", NUMBER),
                "gfEaseInCubic": ("__tsuchi_gf_easeInCubic", NUMBER),
                "gfEaseOutCubic": ("__tsuchi_gf_easeOutCubic", NUMBER),
                "gfEaseInOutCubic": ("__tsuchi_gf_easeInOutCubic", NUMBER),
                "gfEaseOutBounce": ("__tsuchi_gf_easeOutBounce", NUMBER),
                "gfEaseOutElastic": ("__tsuchi_gf_easeOutElastic", NUMBER),
                "gfShakeStart": ("__tsuchi_gf_shakeStart", VOID),
                "gfShakeUpdate": ("__tsuchi_gf_shakeUpdate", VOID),
                "gfShakeX": ("__tsuchi_gf_shakeX", NUMBER),
                "gfShakeY": ("__tsuchi_gf_shakeY", NUMBER),
                "gfShakeActive": ("__tsuchi_gf_shakeActive", BOOLEAN),
                "gfTransitionStart": ("__tsuchi_gf_transitionStart", VOID),
                "gfTransitionUpdate": ("__tsuchi_gf_transitionUpdate", VOID),
                "gfTransitionAlpha": ("__tsuchi_gf_transitionAlpha", NUMBER),
                "gfTransitionDone": ("__tsuchi_gf_transitionDone", BOOLEAN),
                "gfTransitionNextScene": ("__tsuchi_gf_transitionNextScene", NUMBER),
                "gfPhysGravity": ("__tsuchi_gf_physGravity", NUMBER),
                "gfPhysFriction": ("__tsuchi_gf_physFriction", NUMBER),
                "gfPhysClamp": ("__tsuchi_gf_physClamp", NUMBER),
                "gfParticleEmit": ("__tsuchi_gf_particleEmit", VOID),
                "gfParticleUpdate": ("__tsuchi_gf_particleUpdate", VOID),
                "gfParticleDraw": ("__tsuchi_gf_particleDraw", VOID),
                "gfParticleCount": ("__tsuchi_gf_particleCount", NUMBER),
                "gfParticleClear": ("__tsuchi_gf_particleClear", VOID),
                "gfGridToPx": ("__tsuchi_gf_gridToPx", NUMBER),
                "gfPxToGrid": ("__tsuchi_gf_pxToGrid", NUMBER),
                "gfGridIndex": ("__tsuchi_gf_gridIndex", NUMBER),
                "gfGridInBounds": ("__tsuchi_gf_gridInBounds", BOOLEAN),
                "gfManhattan": ("__tsuchi_gf_manhattan", NUMBER),
                "gfChebyshev": ("__tsuchi_gf_chebyshev", NUMBER),
                "gfFsmInit": ("__tsuchi_gf_fsmInit", VOID),
                "gfFsmSet": ("__tsuchi_gf_fsmSet", VOID),
                "gfFsmTick": ("__tsuchi_gf_fsmTick", VOID),
                "gfFsmState": ("__tsuchi_gf_fsmState", NUMBER),
                "gfFsmPrev": ("__tsuchi_gf_fsmPrev", NUMBER),
                "gfFsmFrames": ("__tsuchi_gf_fsmFrames", NUMBER),
                "gfFsmJustEntered": ("__tsuchi_gf_fsmJustEntered", BOOLEAN),
                "gfPoolAlloc": ("__tsuchi_gf_poolAlloc", NUMBER),
                "gfPoolFree": ("__tsuchi_gf_poolFree", VOID),
                "gfPoolActive": ("__tsuchi_gf_poolActive", BOOLEAN),
                "gfPoolCount": ("__tsuchi_gf_poolCount", NUMBER),
                "gfPoolClear": ("__tsuchi_gf_poolClear", VOID),
            }
            if func_name in _BUILTIN_GLOBALS:
                hir_name, ret_type = _BUILTIN_GLOBALS[func_name]
                args = [self._build_expr(a) for a in expr.arguments]
                result = self._fresh_ssa()
                self._emit(HIRCall(func_name=hir_name, args=args, result=result, type=ret_type))
                return result

            # Check if this is a variable holding a function pointer
            callee_type = self._get_type(expr.callee)
            if (isinstance(callee_type, FunctionType)
                    and func_name in self._vars
                    and func_name not in self._functions):
                # Indirect call through function variable
                callee_ssa = self._vars[func_name]
                args = [self._build_expr(a) for a in expr.arguments]
                result = self._fresh_ssa()
                result_type = self._get_type(expr)
                self._emit(HIRIndirectCall(
                    callee=callee_ssa, args=args, result=result,
                    type=result_type, func_type=callee_type,
                ))
                return result

            # Check if function has a rest parameter
            func_type = self._functions.get(func_name)
            func_decl = self._get_func_decl(func_name)
            has_rest = func_decl and func_decl.params and func_decl.params[-1].is_rest
            if has_rest:
                normal_count = len(func_decl.params) - 1
                # Build normal args
                args = [self._build_expr(a) for a in expr.arguments[:normal_count]]
                # Collect excess args into an array
                rest_args = [self._build_expr(a) for a in expr.arguments[normal_count:]]
                rest_arr = self._fresh_ssa()
                rest_elem_type = NUMBER
                if func_type and len(func_type.param_types) > 0:
                    rest_pt = func_type.param_types[-1]
                    if isinstance(rest_pt, ArrayType):
                        rest_elem_type = rest_pt.element_type
                self._emit(HIRAllocArray(
                    elements=rest_args, result=rest_arr,
                    type=ArrayType(rest_elem_type),
                ))
                args.append(rest_arr)
            else:
                # Check for spread elements in arguments
                has_spread = any(isinstance(a, SpreadElement) for a in expr.arguments)
                if has_spread and func_type:
                    args = self._build_spread_call_args(expr.arguments, func_type)
                else:
                    args = [self._build_expr(a) for a in expr.arguments]

            # Pad missing args with default values
            defaults = self._func_defaults.get(func_name, [])
            if func_type and len(args) < len(func_type.param_types):
                for i in range(len(args), len(func_type.param_types)):
                    if i < len(defaults) and defaults[i] is not None:
                        args.append(self._build_expr(defaults[i]))
                    else:
                        args.append(self._emit_const(0.0, NUMBER))

            # Rewrite nested function names to their lifted names
            call_name = self._nested_func_lifted.get(func_name, func_name)

            # Monomorphization: rewrite call to mangled variant if applicable
            mono_rewrites = getattr(self._typed_module, 'mono_call_rewrites', {})
            if id(expr) in mono_rewrites:
                call_name = mono_rewrites[id(expr)]

            result = self._fresh_ssa()
            result_type = self._get_type(expr)
            # If calling an async function, ensure return type is PromiseType
            called_tf = None
            for tf in self._typed_module.functions:
                if tf.name == func_name or tf.name == call_name:
                    called_tf = tf
                    break
            if called_tf and getattr(called_tf.node, 'is_async', False):
                if isinstance(called_tf.return_type, PromiseType):
                    result_type = called_tf.return_type
                elif not isinstance(result_type, PromiseType):
                    result_type = PromiseType(called_tf.return_type)
            self._emit(HIRCall(
                func_name=call_name, args=args, result=result, type=result_type
            ))
            return result

        # Handle inline arrow call: ((x) => x + 1)(5)
        if isinstance(expr.callee, ArrowFunction):
            callee_ssa = self._build_arrow_ref(expr.callee)
            callee_type = self._get_type(expr.callee)
            args = [self._build_expr(a) for a in expr.arguments]
            result = self._fresh_ssa()
            result_type = self._get_type(expr)
            if isinstance(callee_type, FunctionType):
                self._emit(HIRIndirectCall(
                    callee=callee_ssa, args=args, result=result,
                    type=result_type, func_type=callee_type,
                ))
            else:
                self._emit(HIRCall(func_name="<unknown>", args=args, result=result, type=result_type))
            return result

        # Fallback
        args = [self._build_expr(a) for a in expr.arguments]
        result = self._fresh_ssa()
        self._emit(HIRCall(func_name="<unknown>", args=args, result=result, type=NUMBER))
        return result

    def _build_spread_call_args(self, arguments: list[Expression], func_type: FunctionType) -> list[str]:
        """Build call arguments when spread elements are present.

        For `foo(...arr)`, extract individual elements from the array
        to fill the function's parameter slots.
        """
        args: list[str] = []
        param_idx = 0
        for arg in arguments:
            if isinstance(arg, SpreadElement):
                # ...arr → extract elements by index to fill remaining params
                arr_val = self._build_expr(arg.argument)
                arr_type = self._get_type(arg.argument)
                elem_type = arr_type.element_type if isinstance(arr_type, ArrayType) else NUMBER
                remaining = len(func_type.param_types) - param_idx
                for i in range(remaining):
                    idx = self._emit_const(float(i), NUMBER)
                    result = self._fresh_ssa()
                    self._emit(HIRArrayGet(
                        array=arr_val, index=idx, result=result, type=elem_type,
                    ))
                    args.append(result)
                    param_idx += 1
                break  # spread consumes remaining params
            else:
                args.append(self._build_expr(arg))
                param_idx += 1
        return args

    def _build_ffi_args(self, arguments: list, param_types: list[MonoType]) -> list[str]:
        """Build FFI call arguments, converting object literals to FFI struct creates."""
        args = []
        for i, a in enumerate(arguments):
            pt = param_types[i] if i < len(param_types) else None
            if isinstance(pt, FFIStructType) and isinstance(a, ObjectLiteralExpr):
                # Build struct from object literal fields
                field_order = list(pt.fields.keys())
                lit_fields: dict[str, Expression] = {}
                for prop in a.properties:
                    if hasattr(prop, 'key') and hasattr(prop, 'value'):
                        key = prop.key
                        if isinstance(key, Identifier):
                            lit_fields[key.name] = prop.value
                        elif isinstance(key, StringLiteral):
                            lit_fields[key.value] = prop.value
                field_vals = []
                for fname in field_order:
                    if fname in lit_fields:
                        field_vals.append(self._build_expr(lit_fields[fname]))
                    else:
                        field_vals.append(self._emit_const(0.0, NUMBER))
                result = self._fresh_ssa()
                self._emit(HIRFFIStructCreate(
                    field_values=field_vals, result=result, type=pt,
                ))
                args.append(result)
            elif isinstance(pt, FFIStructType):
                # Variable holding an object → extract fields into struct by value
                obj_ssa = self._build_expr(a)
                # Check if the source expression already has FFI struct type
                src_type = self._get_type(a)
                if isinstance(src_type, FFIStructType):
                    # Already a by-value struct — pass directly
                    args.append(obj_ssa)
                else:
                    # Object pointer → load fields via HIRFieldGet, pack into struct
                    field_order = list(pt.fields.keys())
                    field_vals = []
                    for fi, fname in enumerate(field_order):
                        ftype = pt.fields[fname]
                        fget_result = self._fresh_ssa()
                        self._emit(HIRFieldGet(
                            obj=obj_ssa, field_name=fname,
                            result=fget_result, type=ftype,
                        ))
                        field_vals.append(fget_result)
                    result = self._fresh_ssa()
                    self._emit(HIRFFIStructCreate(
                        field_values=field_vals, result=result, type=pt,
                    ))
                    args.append(result)
            else:
                args.append(self._build_expr(a))
        return args

    def _build_member_call_expr(self, expr: CallExpr) -> str:
        """Handle method calls like console.log(...), arr.push(...), str.indexOf(...)."""
        member = expr.callee
        if isinstance(member, MemberExpr):
            # FFI opaque class static method: Database.open(...)
            if (self._ffi_info is not None
                    and isinstance(member.object, Identifier)
                    and isinstance(member.property, Identifier)
                    and member.object.name in self._ffi_info.opaque_classes):
                oc = self._ffi_info.opaque_classes[member.object.name]
                method_name = member.property.name
                if method_name in oc.static_methods:
                    mfn = oc.static_methods[method_name]
                    hir_name = f"__tsuchi_ffi_{mfn.c_name}"
                    args = self._build_ffi_args(expr.arguments, mfn.param_types)
                    result = self._fresh_ssa()
                    self._emit(HIRCall(func_name=hir_name, args=args, result=result, type=mfn.return_type))
                    return result

            # FFI opaque class instance method: db.execute(...), db.close()
            if (self._ffi_info is not None
                    and isinstance(member.property, Identifier)):
                obj_type = self._get_type(member.object)
                if isinstance(obj_type, OpaquePointerType):
                    class_name = obj_type.name
                    method_name = member.property.name
                    if class_name in self._ffi_info.opaque_classes:
                        oc = self._ffi_info.opaque_classes[class_name]
                        if method_name in oc.instance_methods:
                            mfn = oc.instance_methods[method_name]
                            hir_name = f"__tsuchi_ffi_{mfn.c_name}"
                            obj_ssa = self._build_expr(member.object)
                            args = [obj_ssa] + self._build_ffi_args(expr.arguments, mfn.param_types)
                            result = self._fresh_ssa()
                            self._emit(HIRCall(func_name=hir_name, args=args, result=result, type=mfn.return_type))
                            return result

            # Array.isArray(x) — compile-time check
            if (isinstance(member.object, Identifier) and member.object.name == "Array"
                    and isinstance(member.property, Identifier) and member.property.name == "isArray"):
                if expr.arguments:
                    arg_type = self._get_type(expr.arguments[0])
                    self._build_expr(expr.arguments[0])  # evaluate for side effects
                    is_arr = isinstance(arg_type, ArrayType)
                    return self._emit_const(is_arr, BOOLEAN)
                return self._emit_const(False, BOOLEAN)

            # Array.of(...args) — create array from arguments (same as array literal)
            if (isinstance(member.object, Identifier) and member.object.name == "Array"
                    and isinstance(member.property, Identifier) and member.property.name == "of"):
                args = [self._build_expr(a) for a in expr.arguments]
                arr_type = self._get_type(expr)
                elem_type = arr_type.element_type if isinstance(arr_type, ArrayType) else NUMBER
                result = self._fresh_ssa()
                self._emit(HIRAllocArray(
                    elements=args, result=result, type=ArrayType(elem_type),
                ))
                return result

            # Array.from(str) — convert string to char array
            if (isinstance(member.object, Identifier) and member.object.name == "Array"
                    and isinstance(member.property, Identifier) and member.property.name == "from"):
                if expr.arguments:
                    arg = self._build_expr(expr.arguments[0])
                    arg_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    if isinstance(arg_type, StringType):
                        self._emit(HIRCall(
                            func_name="tsuchi_str_to_char_array", args=[arg],
                            result=result, type=ArrayType(STRING),
                        ))
                    else:
                        # Fallback: just return the arg as-is if it's already an array
                        return arg
                    return result

            # JSON.stringify(x) — runtime call
            if (isinstance(member.object, Identifier) and member.object.name == "JSON"
                    and isinstance(member.property, Identifier) and member.property.name == "stringify"):
                if expr.arguments:
                    arg = self._build_expr(expr.arguments[0])
                    arg_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="__tsuchi_json_stringify", args=[arg],
                        result=result, type=STRING,
                    ))
                    return result
                return self._emit_const("undefined", STRING)

            # JSON.parse(x) — always returns string; caller converts if needed
            if (isinstance(member.object, Identifier) and member.object.name == "JSON"
                    and isinstance(member.property, Identifier) and member.property.name == "parse"):
                if expr.arguments:
                    arg = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="__tsuchi_json_parse_str", args=[arg],
                        result=result, type=STRING,
                    ))
                    return result
                return self._emit_const("", STRING)

            # Object.assign(target, source) — compile-time field merge
            if (isinstance(member.object, Identifier) and member.object.name == "Object"
                    and isinstance(member.property, Identifier)
                    and member.property.name == "assign"
                    and len(expr.arguments) >= 2):
                target_type = self._get_type(expr.arguments[0])
                source_type = self._get_type(expr.arguments[1])
                target = self._build_expr(expr.arguments[0])
                source = self._build_expr(expr.arguments[1])
                # Copy source fields into target
                if isinstance(target_type, ObjectType) and isinstance(source_type, ObjectType):
                    for fname in source_type.fields:
                        val = self._fresh_ssa()
                        self._emit(HIRFieldGet(
                            obj=source, field_name=fname,
                            result=val, type=source_type.fields[fname],
                        ))
                        self._emit(HIRFieldSet(
                            obj=target, field_name=fname,
                            value=val, type=source_type.fields[fname],
                        ))
                return target

            # Object.freeze(obj) — no-op at compile time, just return obj
            if (isinstance(member.object, Identifier) and member.object.name == "Object"
                    and isinstance(member.property, Identifier)
                    and member.property.name == "freeze"
                    and expr.arguments):
                return self._build_expr(expr.arguments[0])

            # Object.keys(obj) / Object.values(obj) — compile-time expansion
            if (isinstance(member.object, Identifier) and member.object.name == "Object"
                    and isinstance(member.property, Identifier)
                    and member.property.name in ("keys", "values")
                    and expr.arguments):
                arg_type = self._get_type(expr.arguments[0])
                if isinstance(arg_type, ObjectType):
                    obj = self._build_expr(expr.arguments[0])
                    sorted_fields = sorted(arg_type.fields.keys())
                    if member.property.name == "keys":
                        # Create string array from field names
                        # Use AllocArray with string elements
                        elements = [self._emit_const(fname, STRING) for fname in sorted_fields]
                        arr_result = self._fresh_ssa()
                        self._emit(HIRAllocArray(
                            elements=elements, result=arr_result,
                            type=ArrayType(STRING),
                        ))
                        return arr_result
                    else:  # values
                        field_types = [arg_type.fields[f] for f in sorted_fields]
                        # Get values from object fields
                        elements = []
                        for fname in sorted_fields:
                            val = self._fresh_ssa()
                            self._emit(HIRFieldGet(
                                obj=obj, field_name=fname,
                                result=val, type=arg_type.fields[fname],
                            ))
                            elements.append(val)
                        arr_result = self._fresh_ssa()
                        first_type = field_types[0] if field_types else NUMBER
                        self._emit(HIRAllocArray(
                            elements=elements, result=arr_result,
                            type=ArrayType(first_type),
                        ))
                        return arr_result

            obj_type = self._get_type(member.object)

            # Static method calls: ClassName.method(args) → __ClassName_static_method(args)
            if (isinstance(member.object, Identifier)
                    and isinstance(member.property, Identifier)
                    and member.object.name in self._class_decls):
                class_name = member.object.name
                method_name = member.property.name
                func_name = f"__{class_name}_static_{method_name}"
                if func_name in self._functions:
                    args = []
                    for arg_expr in expr.arguments:
                        args.append(self._build_expr(arg_expr))
                    result = self._fresh_ssa()
                    result_type = self._get_type(expr)
                    self._emit(HIRCall(
                        func_name=func_name, args=args,
                        result=result, type=result_type,
                    ))
                    return result

            # Class method calls: obj.method(args) → __ClassName_method(obj, args)
            # Walk up inheritance chain if method not found on direct class
            if (isinstance(obj_type, ClassType)
                    and isinstance(member.property, Identifier)):
                method_name = member.property.name
                class_name = obj_type.name
                func_name = f"__{class_name}_{method_name}"
                # Walk up inheritance to find the method
                search_class = class_name
                while func_name not in self._functions and search_class in self._class_decls:
                    parent = self._class_decls[search_class].extends
                    if not parent:
                        break
                    func_name = f"__{parent}_{method_name}"
                    search_class = parent
                if func_name in self._functions:
                    obj = self._build_expr(member.object)
                    args = [obj]  # this
                    for arg_expr in expr.arguments:
                        args.append(self._build_expr(arg_expr))
                    result = self._fresh_ssa()
                    result_type = self._get_type(expr)
                    self._emit(HIRCall(
                        func_name=func_name, args=args,
                        result=result, type=result_type,
                    ))
                    return result

            # Array methods
            if (isinstance(obj_type, ArrayType)
                    and isinstance(member.property, Identifier)):
                method = member.property.name

                if method == "push":
                    arr = self._build_expr(member.object)
                    if expr.arguments:
                        val = self._build_expr(expr.arguments[0])
                    else:
                        val = self._emit_const(0.0, NUMBER)
                    result = self._fresh_ssa()
                    self._emit(HIRArrayPush(
                        array=arr, value=val, result=result,
                        type=obj_type.element_type,
                    ))
                    return result

                if method == "forEach" and expr.arguments:
                    from taiyaki_aot_compiler.parser.ast_nodes import (
                        ArrowFunction as _AF, Block as _Block, ForStmt,
                        VarDecl, CompareExpr, MemberExpr as _ME, Identifier as _Id,
                        UpdateExpr, NumberLiteral, ExpressionStmt,
                    )
                    cb_expr = expr.arguments[0]
                    # Desugar forEach(fn) → for loop to support mutable captures
                    if isinstance(cb_expr, _AF) and cb_expr.params:
                        idx_name = f"__fe_i_{id(expr)}"
                        arr_node = member.object
                        param_name = cb_expr.params[0].name

                        # Synthesize: for (let __i = 0; __i < arr.length; __i++) { let p = arr[__i]; ...body }
                        init = VarDecl(name=idx_name, init=NumberLiteral(value=0))
                        condition = CompareExpr(
                            op="<",
                            left=_Id(name=idx_name),
                            right=_ME(object=arr_node, property=_Id(name="length")),
                        )
                        update = UpdateExpr(op="++", operand=_Id(name=idx_name), prefix=False)
                        elem_decl = VarDecl(
                            name=param_name,
                            init=_ME(object=arr_node, property=_Id(name=idx_name), computed=True),
                        )
                        body_stmts = [elem_decl]
                        if isinstance(cb_expr.body, _Block):
                            body_stmts.extend(cb_expr.body.body)
                        else:
                            body_stmts.append(ExpressionStmt(expression=cb_expr.body))

                        for_stmt = ForStmt(
                            init=init,
                            condition=condition,
                            update=update,
                            body=_Block(body=body_stmts),
                        )
                        self._build_for(for_stmt)
                        return self._emit_const(0.0, NUMBER)
                    else:
                        arr = self._build_expr(member.object)
                        cb = self._build_expr(expr.arguments[0])
                        cb_type = self._get_type(expr.arguments[0])
                        self._emit(HIRArrayForEach(
                            array=arr, callback=cb, cb_type=cb_type,
                        ))
                        return self._emit_const(0.0, NUMBER)

                if method == "map" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result_type = self._get_type(expr)
                    result = self._fresh_ssa()
                    self._emit(HIRArrayMap(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=result_type,
                    ))
                    return result

                if method == "filter" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result_type = self._get_type(expr)
                    result = self._fresh_ssa()
                    self._emit(HIRArrayFilter(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=result_type,
                    ))
                    return result

                if method in ("reduce", "reduceRight") and len(expr.arguments) >= 2:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    initial = self._build_expr(expr.arguments[1])
                    cb_type = self._get_type(expr.arguments[0])
                    result_type = self._get_type(expr)
                    result = self._fresh_ssa()
                    if method == "reduceRight":
                        self._emit(HIRArrayReduceRight(
                            array=arr, callback=cb, cb_type=cb_type,
                            initial=initial,
                            result=result, type=result_type,
                        ))
                    else:
                        self._emit(HIRArrayReduce(
                            array=arr, callback=cb, cb_type=cb_type,
                            initial=initial,
                            result=result, type=result_type,
                        ))
                    return result

                if method == "at" and expr.arguments:
                    arr = self._build_expr(member.object)
                    idx = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_at",
                        args=[arr, idx], result=result,
                        type=obj_type.element_type,
                    ))
                    return result

                if method in ("indexOf", "includes", "lastIndexOf") and expr.arguments:
                    arr = self._build_expr(member.object)
                    val = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    result_type = NUMBER if method in ("indexOf", "lastIndexOf") else BOOLEAN
                    self._emit(HIRCall(
                        func_name=f"tsuchi_array_{method}",
                        args=[arr, val], result=result,
                        type=result_type,
                    ))
                    return result

                if method == "slice":
                    arr = self._build_expr(member.object)
                    start = self._build_expr(expr.arguments[0]) if len(expr.arguments) > 0 else self._emit_const(0.0, NUMBER)
                    end_arg = self._build_expr(expr.arguments[1]) if len(expr.arguments) > 1 else None
                    result = self._fresh_ssa()
                    result_type = self._get_type(expr)
                    # Pass start and end as args, codegen will convert to i32
                    args = [arr, start]
                    if end_arg:
                        args.append(end_arg)
                    self._emit(HIRCall(
                        func_name="tsuchi_array_slice",
                        args=args, result=result,
                        type=result_type,
                    ))
                    return result

                if method == "concat" and expr.arguments:
                    arr = self._build_expr(member.object)
                    other = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    result_type = self._get_type(expr)
                    self._emit(HIRCall(
                        func_name="tsuchi_array_concat",
                        args=[arr, other], result=result,
                        type=result_type,
                    ))
                    return result

                if method == "reverse":
                    arr = self._build_expr(member.object)
                    self._emit(HIRCall(
                        func_name="tsuchi_array_reverse",
                        args=[arr], result=self._fresh_ssa(),
                        type=VOID,
                    ))
                    return arr  # reverse mutates and returns the same array

                if method == "join" and expr.arguments:
                    arr = self._build_expr(member.object)
                    sep = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_join",
                        args=[arr, sep], result=result,
                        type=STRING,
                    ))
                    return result

                if method == "find" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRArrayFind(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=obj_type.element_type,
                    ))
                    return result

                if method == "findIndex" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRArrayFindIndex(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=NUMBER,
                    ))
                    return result

                if method == "fill" and expr.arguments:
                    arr = self._build_expr(member.object)
                    val = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_fill",
                        args=[arr, val], result=result,
                        type=ArrayType(obj_type.element_type),
                    ))
                    return arr  # fill mutates and returns same array

                if method == "pop":
                    arr = self._build_expr(member.object)
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_pop",
                        args=[arr], result=result,
                        type=obj_type.element_type,
                    ))
                    return result

                if method == "shift":
                    arr = self._build_expr(member.object)
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_shift",
                        args=[arr], result=result,
                        type=obj_type.element_type,
                    ))
                    return result

                if method == "unshift" and expr.arguments:
                    arr = self._build_expr(member.object)
                    val = self._build_expr(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_unshift",
                        args=[arr, val], result=result,
                        type=NUMBER,
                    ))
                    return result

                if method == "splice" and len(expr.arguments) >= 2:
                    arr = self._build_expr(member.object)
                    start = self._build_expr(expr.arguments[0])
                    del_count = self._build_expr(expr.arguments[1])
                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name="tsuchi_array_splice",
                        args=[arr, start, del_count], result=result,
                        type=ArrayType(obj_type.element_type),
                    ))
                    return result

                if method == "some" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRArraySome(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=BOOLEAN,
                    ))
                    return result

                if method == "every" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRArrayEvery(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=BOOLEAN,
                    ))
                    return result

                if method == "sort" and expr.arguments:
                    arr = self._build_expr(member.object)
                    cb = self._build_expr(expr.arguments[0])
                    cb_type = self._get_type(expr.arguments[0])
                    result = self._fresh_ssa()
                    self._emit(HIRArraySort(
                        array=arr, callback=cb, cb_type=cb_type,
                        result=result, type=ArrayType(obj_type.element_type),
                    ))
                    return result

            # String methods: str.indexOf, str.includes, str.slice, etc.
            _STR_METHODS = {
                "indexOf", "lastIndexOf", "includes", "slice", "charAt", "charCodeAt", "at",
                "toUpperCase", "toLowerCase", "trim", "trimStart", "trimEnd",
                "startsWith", "endsWith",
                "replace", "replaceAll", "repeat", "substring",
                "padStart", "padEnd", "split",
            }
            if (isinstance(obj_type, StringType)
                    and isinstance(member.property, Identifier)
                    and member.property.name in _STR_METHODS):
                method_name = member.property.name
                obj_val = self._build_expr(member.object)
                args = [obj_val] + [self._build_expr(a) for a in expr.arguments]
                result = self._fresh_ssa()
                result_type = self._get_type(expr)
                self._emit(HIRCall(
                    func_name=f"__tsuchi_str_{method_name}",
                    args=args, result=result,
                    type=result_type, is_js_fallback=True,
                ))
                return result

            # Number methods: n.toString(), n.toFixed(digits)
            _NUM_METHODS = {"toString", "toFixed"}
            if (isinstance(obj_type, NumberType)
                    and isinstance(member.property, Identifier)
                    and member.property.name in _NUM_METHODS):
                method_name = member.property.name
                obj_val = self._build_expr(member.object)
                args = [obj_val] + [self._build_expr(a) for a in expr.arguments]
                result = self._fresh_ssa()
                result_type = self._get_type(expr)
                self._emit(HIRCall(
                    func_name=f"__tsuchi_num_{method_name}",
                    args=args, result=result,
                    type=result_type, is_js_fallback=True,
                ))
                return result

            if isinstance(member.object, Identifier):
                obj_name = member.object.name
                if isinstance(member.property, Identifier):
                    method_name = member.property.name
                    func_name = f"__tsuchi_{obj_name}_{method_name}"

                    args = [self._build_expr(a) for a in expr.arguments]
                    result_type = self._get_type(expr)

                    # Math.min/max with 3+ args: chain pairwise calls
                    if obj_name == "Math" and method_name in ("min", "max") and len(args) > 2:
                        acc = args[0]
                        for i in range(1, len(args)):
                            result = self._fresh_ssa()
                            self._emit(HIRCall(
                                func_name=func_name, args=[acc, args[i]], result=result,
                                type=result_type, is_js_fallback=True
                            ))
                            acc = result
                        return acc

                    result = self._fresh_ssa()
                    self._emit(HIRCall(
                        func_name=func_name, args=args, result=result,
                        type=result_type, is_js_fallback=True
                    ))
                    return result

        args = [self._build_expr(a) for a in expr.arguments]
        result = self._fresh_ssa()
        self._emit(HIRCall(func_name="<member_call>", args=args, result=result, type=NUMBER))
        return result

    def _build_member_access(self, expr: MemberExpr) -> str:
        # process.argv → call C runtime to build string array
        if (isinstance(expr.object, Identifier) and expr.object.name == "process"
                and isinstance(expr.property, Identifier) and expr.property.name == "argv"):
            result = self._fresh_ssa()
            self._emit(HIRCall(
                func_name="__tsuchi_process_argv", args=[],
                result=result, type=ArrayType(STRING),
            ))
            return result

        # process.env.VARNAME → call getenv("VARNAME")
        if (isinstance(expr.object, MemberExpr)
                and isinstance(expr.object.object, Identifier)
                and expr.object.object.name == "process"
                and isinstance(expr.object.property, Identifier)
                and expr.object.property.name == "env"
                and isinstance(expr.property, Identifier)):
            var_name = expr.property.name
            name_const = self._emit_const(var_name, STRING)
            result = self._fresh_ssa()
            self._emit(HIRCall(
                func_name="__tsuchi_getenv", args=[name_const],
                result=result, type=STRING,
            ))
            return result

        # Math constants: Math.PI, Math.E, etc.
        if (isinstance(expr.object, Identifier) and expr.object.name == "Math"
                and isinstance(expr.property, Identifier)):
            import math
            math_constants = {
                "PI": math.pi, "E": math.e, "SQRT2": math.sqrt(2),
                "LN2": math.log(2), "LN10": math.log(10),
                "LOG2E": math.log2(math.e), "LOG10E": math.log10(math.e),
            }
            if expr.property.name in math_constants:
                return self._emit_const(math_constants[expr.property.name], NUMBER)

        # Number constants: Number.MAX_SAFE_INTEGER, etc.
        if (isinstance(expr.object, Identifier) and expr.object.name == "Number"
                and isinstance(expr.property, Identifier)):
            import math
            num_constants = {
                "MAX_SAFE_INTEGER": 2**53 - 1,
                "MIN_SAFE_INTEGER": -(2**53 - 1),
                "EPSILON": 2**-52,
                "MAX_VALUE": 1.7976931348623157e+308,
                "MIN_VALUE": 5e-324,
                "POSITIVE_INFINITY": math.inf,
                "NEGATIVE_INFINITY": -math.inf,
            }
            if expr.property.name in num_constants:
                return self._emit_const(num_constants[expr.property.name], NUMBER)

        obj = self._build_expr(expr.object)
        obj_type = self._get_type(expr.object)

        # Array subscript: arr[i]
        if expr.computed and isinstance(obj_type, ArrayType):
            index = self._build_expr(expr.property)
            result = self._fresh_ssa()
            self._emit(HIRArrayGet(
                array=obj, index=index,
                result=result, type=obj_type.element_type,
            ))
            return result

        # Array .length
        if isinstance(obj_type, ArrayType) and isinstance(expr.property, Identifier):
            if expr.property.name == "length":
                result = self._fresh_ssa()
                self._emit(HIRArrayLen(array=obj, result=result))
                return result

        # String .length
        if isinstance(obj_type, StringType) and isinstance(expr.property, Identifier):
            if expr.property.name == "length":
                result = self._fresh_ssa()
                self._emit(HIRCall(
                    func_name="__tsuchi_strlen", args=[obj],
                    result=result, type=NUMBER, is_js_fallback=True,
                ))
                return result

        # FFI struct field access (extractvalue)
        if isinstance(obj_type, FFIStructType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name
            field_list = list(obj_type.fields.keys())
            if field_name in field_list:
                idx = field_list.index(field_name)
                field_type = obj_type.fields[field_name]
                result = self._fresh_ssa()
                self._emit(HIRFFIStructFieldGet(
                    struct_val=obj, field_index=idx,
                    result=result, type=field_type,
                ))
                return result

        # ClassType field access (class instances)
        if isinstance(obj_type, ClassType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name

            # Check if this is a getter property
            class_decl = self._class_decls.get(obj_type.name)
            if class_decl:
                for method in class_decl.methods:
                    if method.is_getter and method.name == field_name:
                        func_name = f"__{obj_type.name}_get_{field_name}"
                        if func_name in self._functions:
                            result = self._fresh_ssa()
                            result_type = self._get_type(expr)
                            self._emit(HIRCall(
                                func_name=func_name, args=[obj],
                                result=result, type=result_type,
                            ))
                            return result

            # Use resolved class fields (with substitution applied)
            resolved_ct = self._classes.get(obj_type.name, obj_type)
            if field_name in resolved_ct.fields:
                result = self._fresh_ssa()
                field_type = resolved_ct.fields[field_name]
                self._emit(HIRFieldGet(
                    obj=obj, field_name=field_name,
                    result=result, type=field_type,
                ))
                return result

        # ObjectType field access
        if isinstance(obj_type, ObjectType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name
            if field_name in obj_type.fields:
                result = self._fresh_ssa()
                field_type = obj_type.fields[field_name]
                self._emit(HIRFieldGet(
                    obj=obj, field_name=field_name,
                    result=result, type=field_type,
                ))
                return result
        return obj

    def _build_update(self, expr: UpdateExpr) -> str:
        if isinstance(expr.operand, Identifier):
            name = expr.operand.name
            old_val = self._vars.get(name)
            if old_val is None:
                old_val = self._emit_const(0.0, NUMBER)

            one = self._emit_const(1.0, NUMBER)
            result = self._fresh_ssa()
            op = "add" if expr.op == "++" else "sub"
            self._emit(HIRBinaryOp(op=op, left=old_val, right=one, result=result, type=NUMBER))
            self._vars[name] = result
            self._emit_store_capture_if_needed(name, result)

            if expr.prefix:
                return result
            else:
                return old_val

        return self._emit_const(0.0, NUMBER)

    def _build_object_literal(self, expr: ObjectLiteralExpr) -> str:
        obj_type = self._get_type(expr)
        if not isinstance(obj_type, ObjectType):
            obj_type = ObjectType(fields={})
        # Use ALL fields from the inferred type (includes spread fields)
        field_list = [(fname, ftype) for fname, ftype in sorted(obj_type.fields.items())]
        result = self._fresh_ssa()
        self._emit(HIRAllocObj(fields=field_list, result=result, type=obj_type))
        # Handle spreads first — copy fields from spread source
        for _, spread_expr in expr.spreads:
            spread_val = self._build_expr(spread_expr)
            spread_type = self._get_type(spread_expr)
            if isinstance(spread_type, ObjectType):
                for fname in spread_type.fields:
                    if fname in obj_type.fields:
                        fget_result = self._fresh_ssa()
                        ftype = spread_type.fields[fname]
                        self._emit(HIRFieldGet(
                            obj=spread_val, field_name=fname,
                            result=fget_result, type=ftype,
                        ))
                        self._emit(HIRFieldSet(
                            obj=result, field_name=fname,
                            value=fget_result, type=ftype,
                        ))
        # Set explicit properties (override spread values)
        for fname, fexpr in expr.properties:
            val = self._build_expr(fexpr)
            ftype = obj_type.fields.get(fname, NUMBER)
            self._emit(HIRFieldSet(obj=result, field_name=fname, value=val, type=ftype))
        return result

    def _build_new_expr(self, expr: NewExpr) -> str:
        """Build `new ClassName(args)`: alloc struct, call constructor, return struct."""
        class_name = expr.class_name
        if class_name not in self._classes:
            return self._emit_const(0.0, NUMBER)

        ct = self._classes[class_name]
        # Create an ObjectType from class fields for allocation
        obj_type = ct.instance_type()
        # Use insertion order if _ordered (inheritance), else alphabetical
        if getattr(obj_type, '_ordered', False):
            field_list = list(obj_type.fields.items())
        else:
            field_list = sorted(obj_type.fields.items())
        result = self._fresh_ssa()
        self._emit(HIRAllocObj(fields=field_list, result=result, type=obj_type))

        # Call constructor: __ClassName_constructor(this, args...)
        ctor_name = f"__{class_name}_constructor"
        if ctor_name in self._functions:
            args = [result]  # this
            for arg_expr in expr.arguments:
                args.append(self._build_expr(arg_expr))
            ctor_result = self._fresh_ssa()
            self._emit(HIRCall(
                func_name=ctor_name, args=args,
                result=ctor_result, type=VOID,
            ))

        return result

    def _build_template_literal(self, expr: TemplateLiteral) -> str:
        """Build template literal by concatenating quasis and expressions."""
        # Build: quasis[0] + str(expr[0]) + quasis[1] + str(expr[1]) + ...
        result = self._emit_const(expr.quasis[0], STRING) if expr.quasis else self._emit_const("", STRING)
        for i, sub_expr in enumerate(expr.expressions):
            # Convert expression to string via HIR call
            expr_val = self._build_expr(sub_expr)
            expr_type = self._get_type(sub_expr)
            # Convert to string if needed
            if isinstance(expr_type, NumberType):
                str_val = self._fresh_ssa()
                self._emit(HIRCall(
                    func_name="__tsuchi_num_to_str", args=[expr_val],
                    result=str_val, type=STRING, is_js_fallback=True
                ))
                expr_val = str_val
            elif isinstance(expr_type, BooleanType):
                str_val = self._fresh_ssa()
                self._emit(HIRCall(
                    func_name="__tsuchi_bool_to_str", args=[expr_val],
                    result=str_val, type=STRING, is_js_fallback=True
                ))
                expr_val = str_val
            # Concat with current result
            concat_result = self._fresh_ssa()
            self._emit(HIRBinaryOp(op="add", left=result, right=expr_val, result=concat_result, type=STRING))
            result = concat_result
            # Concat next quasi
            if i + 1 < len(expr.quasis) and expr.quasis[i + 1]:
                quasi_val = self._emit_const(expr.quasis[i + 1], STRING)
                concat_result2 = self._fresh_ssa()
                self._emit(HIRBinaryOp(op="add", left=result, right=quasi_val, result=concat_result2, type=STRING))
                result = concat_result2
        return result

    def _build_array_literal(self, expr: ArrayLiteral) -> str:
        arr_type = self._get_type(expr)
        has_spread = any(isinstance(e, SpreadElement) for e in expr.elements)
        if not has_spread:
            elem_ssas = [self._build_expr(e) for e in expr.elements]
            result = self._fresh_ssa()
            self._emit(HIRAllocArray(elements=elem_ssas, result=result, type=arr_type))
            return result

        # Has spread: allocate empty, then push/concat
        result = self._fresh_ssa()
        self._emit(HIRAllocArray(elements=[], result=result, type=arr_type))
        for elem in expr.elements:
            if isinstance(elem, SpreadElement):
                # ...arr → concat arr into result
                src = self._build_expr(elem.argument)
                concat_result = self._fresh_ssa()
                self._emit(HIRCall(
                    func_name="tsuchi_array_concat",
                    args=[result, src],
                    result=concat_result,
                    type=arr_type,
                    is_js_fallback=False,
                ))
                result = concat_result
            else:
                val = self._build_expr(elem)
                push_result = self._fresh_ssa()
                self._emit(HIRArrayPush(array=result, value=val, result=push_result, type=NUMBER))
        return result

    def _build_for_in(self, stmt: ForInStmt):
        """Build for...in by unrolling over known object keys.

        for (const key in obj) { body } → execute body once per field name.
        """
        obj_type = self._get_type(stmt.object)
        if isinstance(obj_type, ClassType):
            obj_type = obj_type.instance_type()
        if not isinstance(obj_type, ObjectType):
            return  # Can't iterate non-objects

        field_names = sorted(obj_type.fields.keys())
        if not field_names:
            return

        # Unroll: for each field name, set var = "fieldname" and execute body
        for fname in field_names:
            key_ssa = self._emit_const(fname, STRING)
            self._vars[stmt.var_name] = key_ssa
            saved_redecl_fi = self._block_redeclared
            saved_redecl_saved_fi = self._redeclared_saved
            self._block_redeclared = set()
            self._redeclared_saved = {}
            self._build_block(stmt.body)
            for name in self._block_redeclared:
                if name in self._redeclared_saved:
                    old_ssa, old_type = self._redeclared_saved[name]
                    self._vars[name] = old_ssa
                    self._var_types[name] = old_type
            self._block_redeclared = saved_redecl_fi
            self._redeclared_saved = saved_redecl_saved_fi

    def _build_for_of(self, stmt: ForOfStmt):
        """Build for-of loop: for (const x of arr) { body } — supports arrays and strings."""
        arr_val = self._build_expr(stmt.iterable)
        iterable_type = self._get_type(stmt.iterable)
        is_string_iter = isinstance(iterable_type, StringType)

        # Get length (array length or string length)
        len_ssa = self._fresh_ssa()
        if is_string_iter:
            self._emit(HIRCall(func_name="__tsuchi_strlen", args=[arr_val], result=len_ssa, type=NUMBER))
        else:
            self._emit(HIRArrayLen(array=arr_val, result=len_ssa))

        # Index variable (starts at 0)
        idx_ssa = self._emit_const(0.0, NUMBER)

        header = self._fresh_block("forof_header")
        body_block = self._fresh_block("forof_body")
        latch_block = self._fresh_block("forof_latch")
        exit_block = self._fresh_block("forof_exit")

        # If this for-of loop is inside a labeled statement, register the exit target
        if self._pending_label:
            self._label_exits[self._pending_label] = exit_block.label
            self._pending_label = None

        entry_block = self._current_block
        # Track all outer vars for cleanup (including arrays/objects/functions)
        outer_scope_vars = set(self._vars.keys())
        # Only put number/boolean variables + index in the phi map.
        # Skip array/object/function variables — they're loop-invariant
        # or would break phi type expectations (phi only supports f64/i1).
        pre_vars: dict[str, str] = {}
        for name, ssa in self._vars.items():
            vt = self._var_types.get(name, NUMBER)
            if isinstance(vt, (ArrayType, ObjectType, FunctionType)):
                continue  # loop-invariant, skip phi
            pre_vars[name] = ssa
        pre_vars["__forof_idx"] = idx_ssa
        self._current_block.terminator = HIRJump(target_block=header.label)

        # Header: phi nodes + condition (idx < len)
        self._current_block = header
        phi_map: dict[str, str] = {}
        for name, ssa in pre_vars.items():
            vt = self._var_types.get(name, NUMBER)
            if isinstance(vt, (ArrayType, ObjectType, FunctionType)):
                continue  # loop-invariant, skip phi
            phi_ssa = self._fresh_ssa()
            phi = HIRPhi(
                incoming=[(ssa, entry_block.label)],
                result=phi_ssa,
                type=vt,
            )
            header.instructions.append(phi)
            phi_map[name] = phi_ssa
            self._vars[name] = phi_ssa

        # Condition: idx < len (use loop-invariant len_ssa directly)
        cond = self._fresh_ssa()
        self._emit(HIRCompare(
            op="lt",
            left=self._vars["__forof_idx"],
            right=len_ssa,
            result=cond,
        ))
        self._current_block.terminator = HIRBranch(
            condition=cond,
            true_block=body_block.label,
            false_block=exit_block.label,
        )

        # Body: get element, bind variable (use loop-invariant arr_val directly)
        self._current_block = body_block
        if is_string_iter:
            elem_type = STRING
            elem_ssa = self._fresh_ssa()
            self._emit(HIRCall(
                func_name="__tsuchi_str_charAt",
                args=[arr_val, self._vars["__forof_idx"]],
                result=elem_ssa,
                type=STRING,
            ))
        else:
            arr_type = self._get_type(stmt.iterable)
            elem_type = arr_type.element_type if isinstance(arr_type, ArrayType) else NUMBER
            elem_ssa = self._fresh_ssa()
            self._emit(HIRArrayGet(
                array=arr_val,
                index=self._vars["__forof_idx"],
                result=elem_ssa,
                type=elem_type,
            ))
        self._vars[stmt.var_name] = elem_ssa
        self._var_types[stmt.var_name] = elem_type

        # Set loop labels for break/continue
        old_loop_exit = self._loop_exit
        old_loop_continue = self._loop_continue
        old_continue_snapshots = self._continue_snapshots
        old_break_snapshots = self._break_snapshots
        self._loop_exit = exit_block.label
        self._loop_continue = latch_block.label
        self._continue_snapshots = []
        self._break_snapshots = []
        saved_redecl_fo = self._block_redeclared
        saved_redecl_saved_fo = self._redeclared_saved
        self._block_redeclared = set()
        self._redeclared_saved = {}
        self._build_block(stmt.body)
        for name in self._block_redeclared:
            if name in self._redeclared_saved:
                old_ssa, old_type = self._redeclared_saved[name]
                self._vars[name] = old_ssa
                self._var_types[name] = old_type
        self._block_redeclared = saved_redecl_fo
        self._redeclared_saved = saved_redecl_saved_fo
        continue_snapshots = self._continue_snapshots
        break_snapshots = self._break_snapshots
        self._loop_exit = old_loop_exit
        self._loop_continue = old_loop_continue
        self._continue_snapshots = old_continue_snapshots
        self._break_snapshots = old_break_snapshots

        body_end_vars = dict(self._vars)
        body_end_block = self._current_block
        body_falls_through = body_end_block.terminator is None
        if body_falls_through:
            body_end_block.terminator = HIRJump(target_block=latch_block.label)

        # Latch block: merge values from body end + continue paths, increment index, jump to header
        self._current_block = latch_block

        # Collect all incoming edges to latch
        latch_incoming: list[tuple[str, dict[str, str]]] = []
        if body_falls_through:
            latch_incoming.append((body_end_block.label, body_end_vars))
        for cont_label, cont_vars in continue_snapshots:
            latch_incoming.append((cont_label, cont_vars))

        if len(latch_incoming) > 1:
            latch_merged_vars: dict[str, str] = {}
            all_var_names = set()
            for _, vars_snap in latch_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                vals = [(vars_snap.get(name, phi_map.get(name, "")), label)
                        for label, vars_snap in latch_incoming
                        if vars_snap.get(name, phi_map.get(name, ""))]
                if len(set(v for v, _ in vals)) == 1:
                    latch_merged_vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    phi_type = self._var_types.get(name, NUMBER)
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=phi_type)
                    latch_block.instructions.append(phi)
                    latch_merged_vars[name] = phi_ssa
            self._vars = latch_merged_vars
        elif len(latch_incoming) == 1:
            self._vars = latch_incoming[0][1]

        # Increment index
        one = self._emit_const(1.0, NUMBER)
        new_idx = self._fresh_ssa()
        self._emit(HIRBinaryOp(
            op="add",
            left=self._vars["__forof_idx"],
            right=one,
            result=new_idx,
            type=NUMBER,
        ))
        self._vars["__forof_idx"] = new_idx

        self._current_block.terminator = HIRJump(target_block=header.label)

        # Patch phi — back-edge from latch
        for instr in header.instructions:
            if isinstance(instr, HIRPhi):
                for name, phi_ssa in phi_map.items():
                    if instr.result == phi_ssa:
                        body_val = self._vars.get(name, phi_ssa)
                        instr.incoming.append((body_val, latch_block.label))
                        break

        # At exit, merge header phi values with break snapshots
        self._current_block = exit_block
        header_vars = {name: phi_ssa for name, phi_ssa in phi_map.items()
                       if not name.startswith("__forof_")}

        if break_snapshots:
            exit_incoming: list[tuple[str, dict[str, str]]] = []
            exit_incoming.append((header.label, header_vars))
            for brk_label, brk_vars in break_snapshots:
                exit_incoming.append((brk_label, brk_vars))
            all_var_names = set()
            for _, vars_snap in exit_incoming:
                all_var_names.update(vars_snap.keys())
            for name in all_var_names:
                if name.startswith("__forof_"):
                    continue
                vals = [(vars_snap.get(name, header_vars.get(name, "")), label)
                        for label, vars_snap in exit_incoming
                        if vars_snap.get(name, header_vars.get(name, ""))]
                if not vals:
                    continue
                unique_vals = set(v for v, _ in vals)
                if len(unique_vals) == 1:
                    self._vars[name] = vals[0][0]
                else:
                    phi_ssa = self._fresh_ssa()
                    var_type = self._var_types.get(name, NUMBER)
                    if isinstance(var_type, (ArrayType, ObjectType, FunctionType)):
                        self._vars[name] = vals[0][0]
                        continue
                    phi = HIRPhi(incoming=list(vals), result=phi_ssa, type=var_type)
                    exit_block.instructions.append(phi)
                    self._vars[name] = phi_ssa
        else:
            for name, phi_ssa in phi_map.items():
                if not name.startswith("__forof_"):
                    self._vars[name] = phi_ssa

        # Remove variables introduced inside the loop body from outer scope
        for name in list(self._vars.keys()):
            if name not in outer_scope_vars and name != stmt.var_name:
                del self._vars[name]

    def _build_arrow_ref(self, expr: ArrowFunction) -> str:
        """Emit a function reference or closure for a lifted arrow function."""
        lifted_name = self._arrow_lifted_names.get(id(expr))
        if lifted_name:
            captures = self._arrow_captures.get(id(expr), [])
            func_type = self._get_type(expr)
            if captures:
                # Create closure with captured values
                capture_ssas = []
                capture_types = []
                for cap_name, cap_type in captures:
                    cap_ssa = self._vars.get(cap_name)
                    if cap_ssa is None:
                        cap_ssa = self._emit_const(0.0, NUMBER)
                    capture_ssas.append(cap_ssa)
                    capture_types.append(cap_type)
                result = self._fresh_ssa()
                self._emit(HIRMakeClosure(
                    func_name=lifted_name,
                    captures=capture_ssas,
                    capture_types=capture_types,
                    result=result,
                    type=func_type,
                ))
                return result
            else:
                # No captures — simple function ref
                result = self._fresh_ssa()
                self._emit(HIRFuncRef(func_name=lifted_name, result=result, type=func_type))
                return result
        return self._emit_const(0.0, NUMBER)

    def _build_object_destructure(self, decl: ObjectDestructure):
        init_val = self._build_expr(decl.init)
        init_type = self._get_type(decl.init)
        if isinstance(init_type, ObjectType):
            for fname in decl.fields:
                local_name = decl.aliases.get(fname, fname)
                if fname in init_type.fields:
                    result = self._fresh_ssa()
                    ftype = init_type.fields[fname]
                    self._emit(HIRFieldGet(
                        obj=init_val, field_name=fname,
                        result=result, type=ftype,
                    ))
                    self._vars[local_name] = result
                    self._var_types[local_name] = ftype
                elif fname in decl.defaults:
                    val = self._build_expr(decl.defaults[fname])
                    self._vars[local_name] = val
                    self._var_types[local_name] = self._get_type(decl.defaults[fname])
                else:
                    val = self._emit_const(0.0, NUMBER)
                    self._vars[local_name] = val
                    self._var_types[local_name] = NUMBER
            # Rest: allocate new object with remaining fields
            if decl.rest_name:
                rest_fields = {k: v for k, v in init_type.fields.items() if k not in decl.fields}
                if rest_fields:
                    rest_type = ObjectType(fields=rest_fields)
                    # Allocate struct with correct types
                    alloc_fields = [(rf_name, rest_fields[rf_name]) for rf_name in sorted(rest_fields.keys())]
                    rest_result = self._fresh_ssa()
                    self._emit(HIRAllocObj(
                        fields=alloc_fields, result=rest_result, type=rest_type,
                    ))
                    # Copy field values from source object
                    for rf_name in sorted(rest_fields.keys()):
                        rf_val = self._fresh_ssa()
                        self._emit(HIRFieldGet(
                            obj=init_val, field_name=rf_name,
                            result=rf_val, type=rest_fields[rf_name],
                        ))
                        self._emit(HIRFieldSet(
                            obj=rest_result, field_name=rf_name,
                            value=rf_val, type=rest_fields[rf_name],
                        ))
                    self._vars[decl.rest_name] = rest_result
                    self._var_types[decl.rest_name] = rest_type
                else:
                    rest_type = ObjectType(fields={})
                    rest_result = self._fresh_ssa()
                    self._emit(HIRAllocObj(
                        fields=[], result=rest_result, type=rest_type,
                    ))
                    self._vars[decl.rest_name] = rest_result
                    self._var_types[decl.rest_name] = rest_type
        else:
            for fname in decl.fields:
                local_name = decl.aliases.get(fname, fname)
                if fname in decl.defaults:
                    val = self._build_expr(decl.defaults[fname])
                    self._vars[local_name] = val
                    self._var_types[local_name] = self._get_type(decl.defaults[fname])
                else:
                    val = self._emit_const(0.0, NUMBER)
                    self._vars[local_name] = val
                    self._var_types[local_name] = NUMBER

    def _build_array_destructure(self, decl: ArrayDestructure):
        arr_val = self._build_expr(decl.init)
        arr_type = self._get_type(decl.init)
        elem_type = arr_type.element_type if isinstance(arr_type, ArrayType) else NUMBER
        for i, name in enumerate(decl.names):
            idx_val = self._emit_const(float(i), NUMBER)
            result = self._fresh_ssa()
            self._emit(HIRArrayGet(
                array=arr_val, index=idx_val,
                result=result, type=elem_type,
            ))
            self._vars[name] = result
            self._var_types[name] = elem_type
        if decl.rest_name:
            start_val = self._emit_const(float(len(decl.names)), NUMBER)
            rest_result = self._fresh_ssa()
            self._emit(HIRCall(
                func_name="tsuchi_array_slice",
                args=[arr_val, start_val],
                result=rest_result,
                type=arr_type if isinstance(arr_type, ArrayType) else ArrayType(NUMBER),
            ))
            self._vars[decl.rest_name] = rest_result
            self._var_types[decl.rest_name] = arr_type if isinstance(arr_type, ArrayType) else ArrayType(NUMBER)

    def _build_assign(self, expr: AssignExpr) -> str:
        if expr.op == "=":
            if isinstance(expr.left, MemberExpr):
                obj = self._build_expr(expr.left.object)
                val = self._build_expr(expr.right)
                obj_type = self._get_type(expr.left.object)
                # Array element assignment: arr[i] = value
                if expr.left.computed and isinstance(obj_type, ArrayType):
                    index = self._build_expr(expr.left.property)
                    elem_type = obj_type.element_type
                    self._emit(HIRArraySet(
                        array=obj, index=index, value=val, type=elem_type,
                    ))
                    return val
                # Class instance field assignment: this.field = value
                if isinstance(obj_type, ClassType) and isinstance(expr.left.property, Identifier):
                    field_name = expr.left.property.name
                    # Check if this is a setter property
                    class_decl = self._class_decls.get(obj_type.name)
                    if class_decl:
                        for method in class_decl.methods:
                            if method.is_setter and method.name == field_name:
                                func_name = f"__{obj_type.name}_set_{field_name}"
                                if func_name in self._functions:
                                    result = self._fresh_ssa()
                                    self._emit(HIRCall(
                                        func_name=func_name, args=[obj, val],
                                        result=result, type=VOID,
                                    ))
                                    return val
                    # Use resolved class fields (with substitution applied)
                    resolved_ct = self._classes.get(obj_type.name, obj_type)
                    ftype = resolved_ct.fields.get(field_name, NUMBER)
                    self._emit(HIRFieldSet(obj=obj, field_name=field_name, value=val, type=ftype))
                    return val
                # Object field assignment: obj.field = value
                if isinstance(obj_type, ObjectType) and isinstance(expr.left.property, Identifier):
                    field_name = expr.left.property.name
                    ftype = obj_type.fields.get(field_name, NUMBER)
                    self._emit(HIRFieldSet(obj=obj, field_name=field_name, value=val, type=ftype))
                return val
            val = self._build_expr(expr.right)
            if isinstance(expr.left, Identifier):
                # Global variable: store to LLVM global, don't cache in local _vars
                if expr.left.name in self._global_vars:
                    from taiyaki_aot_compiler.hir.nodes import HIRStoreGlobal
                    gtype = self._global_vars[expr.left.name]
                    self._emit(HIRStoreGlobal(name=expr.left.name, value=val, type=gtype))
                else:
                    self._vars[expr.left.name] = val
                    self._emit_store_capture_if_needed(expr.left.name, val)
            return val
        elif expr.op in ("&&=", "||=", "??="):
            # Logical assignment: desugar to x = x && y / x = x || y / x = x ?? y
            logical_op = expr.op[:-1]  # "&&=" → "&&", "||=" → "||", "??=" → "??"
            synthetic = LogicalExpr(op=logical_op, left=expr.left, right=expr.right)
            # Propagate inferred type to the synthetic expression
            node_id = id(expr)
            if node_id in self._node_types:
                self._node_types[id(synthetic)] = self._node_types[node_id]
            result = self._build_logical(synthetic)
            if isinstance(expr.left, Identifier):
                self._vars[expr.left.name] = result
                self._emit_store_capture_if_needed(expr.left.name, result)
            return result
        else:
            # Augmented assignment: +=, -=, etc.
            left_val = self._build_expr(expr.left)
            right_val = self._build_expr(expr.right)
            result = self._fresh_ssa()
            base_op = expr.op[:-1]  # "+=" → "+"
            op_name = _BINOP_MAP.get(base_op, base_op)
            # Determine result type from the expression's inferred type
            result_type = self._get_type(expr)
            self._emit(HIRBinaryOp(op=op_name, left=left_val, right=right_val, result=result, type=result_type))
            if isinstance(expr.left, Identifier):
                if expr.left.name in self._global_vars:
                    from taiyaki_aot_compiler.hir.nodes import HIRStoreGlobal
                    gtype = self._global_vars[expr.left.name]
                    self._emit(HIRStoreGlobal(name=expr.left.name, value=result, type=gtype))
                else:
                    self._vars[expr.left.name] = result
                    self._var_types[expr.left.name] = result_type
                    self._emit_store_capture_if_needed(expr.left.name, result)
            return result

    def _get_type(self, expr: Expression) -> MonoType:
        node_id = id(expr)
        if node_id in self._node_types:
            t = self._node_types[node_id]
            if not isinstance(t, TypeVar):
                return t
        return NUMBER  # default to number

    def _emit_store_capture_if_needed(self, var_name: str, val_ssa: str):
        """If var_name is a captured variable, emit HIRStoreCapture to write back to env."""
        if var_name in self._capture_info:
            index, capture_types = self._capture_info[var_name]
            cap_type = capture_types[index]
            self._emit(HIRStoreCapture(
                env="__env__",
                index=index,
                capture_types=capture_types,
                value=val_ssa,
                type=cap_type,
            ))

    def _emit_default_value(self, ty: MonoType) -> str:
        """Emit a type-appropriate default value constant."""
        if isinstance(ty, NumberType):
            return self._emit_const(0.0, NUMBER)
        elif isinstance(ty, BooleanType):
            return self._emit_const(False, BOOLEAN)
        elif isinstance(ty, StringType):
            return self._emit_const("", STRING)
        elif isinstance(ty, NullType):
            return self._emit_const(None, NULL)
        else:
            return self._emit_const(0.0, NUMBER)

    def _emit_const(self, value: float | bool | str | None, ty: MonoType) -> str:
        result = self._fresh_ssa()
        self._emit(HIRConst(value=value, type=ty, result=result))
        return result

    def _emit(self, instr):
        if self._current_block:
            self._current_block.instructions.append(instr)

    def _get_func_decl(self, name: str) -> FunctionDecl | None:
        """Look up the AST FunctionDecl node by function name."""
        return self._func_nodes.get(name)

    def _fresh_ssa(self) -> str:
        self._ssa_counter += 1
        return f"%{self._ssa_counter}"

    def _fresh_block(self, prefix: str = "bb") -> BasicBlock:
        self._block_counter += 1
        label = f"{prefix}_{self._block_counter}"
        block = BasicBlock(label=label)
        self._blocks.append(block)
        return block
