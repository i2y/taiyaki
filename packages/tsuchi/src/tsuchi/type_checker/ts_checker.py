"""Type checker for the Tsuchi TypeScript subset compiler.

Annotation-first: reads TS type annotations, falls back to local HM inference
for unannotated let/const declarations.
"""

from __future__ import annotations

from tsuchi.parser.ast_nodes import (
    TSModule, Statement, Expression, Block,
    FunctionDecl, VarDecl, ReturnStmt, IfStmt, WhileStmt, ForStmt,
    ExpressionStmt, Parameter, InterfaceDecl, ObjectDestructure,
    NumberLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    Identifier, BinaryExpr, UnaryExpr, UpdateExpr, CompareExpr,
    LogicalExpr, ConditionalExpr, CallExpr, MemberExpr, AssignExpr,
    ArrowFunction, ObjectLiteralExpr,
    TypeAnnotation, NamedType, ArrayTypeAnnotation, FunctionTypeAnnotation,
    ObjectTypeAnnotation,
    Location,
)
from tsuchi.type_checker.types import (
    MonoType, NumberType, BooleanType, StringType, NullType, VoidType,
    TypeVar, FunctionType, ArrayType, ObjectType, Substitution,
    NUMBER, BOOLEAN, STRING, NULL, VOID,
)
from tsuchi.type_checker.unification import unify, UnificationError
from tsuchi.type_checker.builtins import binary_op_type, compare_op_type, unary_op_type
from tsuchi.diagnostics.diagnostic import DiagnosticCollector, Location as DiagLocation


class TypedFunction:
    """Result of type-checking a function."""
    def __init__(self, name: str, params: list[tuple[str, MonoType]],
                 return_type: MonoType, node: FunctionDecl,
                 node_types: dict[int, MonoType],
                 is_compilable: bool = True):
        self.name = name
        self.params = params
        self.return_type = return_type
        self.node = node
        self.node_types = node_types
        self.is_compilable = is_compilable


class TypedModule:
    """Result of type-checking a module."""
    def __init__(self):
        self.functions: list[TypedFunction] = []
        self.global_vars: dict[str, MonoType] = {}
        self.top_level_stmts: list[Statement] = []
        self.entry_exprs: list[Expression] = []  # top-level expression statements


class TSTypeChecker:
    """Type-check a Tsuchi AST module."""

    def __init__(self, diagnostics: DiagnosticCollector | None = None):
        self.diag = diagnostics or DiagnosticCollector()
        self._env: dict[str, MonoType] = {}  # variable name → type
        self._functions: dict[str, FunctionType] = {}  # function name → FunctionType
        self._interfaces: dict[str, ObjectType] = {}  # interface name → ObjectType
        self._node_types: dict[int, MonoType] = {}  # ast node id → type
        self._subst = Substitution()
        self._return_type: MonoType | None = None

    def check_module(self, module: TSModule, filename: str = "<input>") -> TypedModule:
        self.diag.register_source(filename, module.source)
        result = TypedModule()

        # First pass: register interfaces and function signatures
        for stmt in module.body:
            if isinstance(stmt, InterfaceDecl):
                self._register_interface(stmt)
        for stmt in module.body:
            if isinstance(stmt, FunctionDecl):
                self._register_function_sig(stmt, filename)

        # Register console.log as builtin
        self._env["console"] = ObjectType(fields={
            "log": FunctionType([TypeVar()], VOID),
        })

        # Second pass: type-check function bodies + top-level statements
        for stmt in module.body:
            if isinstance(stmt, InterfaceDecl):
                continue
            if isinstance(stmt, FunctionDecl):
                tf = self._check_function(stmt, filename)
                result.functions.append(tf)
            elif isinstance(stmt, VarDecl):
                self._check_var_decl(stmt, filename)
                result.global_vars[stmt.name] = self._env.get(stmt.name, TypeVar())
                result.top_level_stmts.append(stmt)
            elif isinstance(stmt, ObjectDestructure):
                self._check_object_destructure(stmt, filename)
                for fname in stmt.fields:
                    result.global_vars[fname] = self._env.get(fname, TypeVar())
                result.top_level_stmts.append(stmt)
            elif isinstance(stmt, ExpressionStmt):
                self._infer_expr(stmt.expression, filename)
                result.entry_exprs.append(stmt.expression)
                result.top_level_stmts.append(stmt)

        return result

    def _register_interface(self, decl: InterfaceDecl):
        fields: dict[str, MonoType] = {}
        # First, copy fields from parent interfaces
        for parent_name in decl.extends:
            if parent_name in self._interfaces:
                fields.update(self._interfaces[parent_name].fields)
        # Then add own fields (can override parent)
        for fname, ftype_ann in decl.fields:
            fields[fname] = self._resolve_type_annotation(ftype_ann)
        self._interfaces[decl.name] = ObjectType(fields=fields)

    def _register_function_sig(self, func: FunctionDecl, filename: str):
        param_types: list[MonoType] = []
        for p in func.params:
            pt = self._resolve_type_annotation(p.type_annotation)
            param_types.append(pt)

        ret_type = self._resolve_type_annotation(func.return_type) if func.return_type else TypeVar()
        ft = FunctionType(param_types, ret_type)
        self._functions[func.name] = ft
        self._env[func.name] = ft

    def _check_function(self, func: FunctionDecl, filename: str) -> TypedFunction:
        old_env = dict(self._env)
        old_return = self._return_type
        self._node_types = {}

        param_pairs: list[tuple[str, MonoType]] = []
        ft = self._functions[func.name]

        for i, p in enumerate(func.params):
            pt = ft.param_types[i]
            self._env[p.name] = pt
            param_pairs.append((p.name, pt))

        self._return_type = ft.return_type

        # Check body
        self._check_block(func.body, filename)

        # Apply substitution to resolve TypeVars
        resolved_ret = self._subst.apply(ft.return_type)
        resolved_params = [(n, self._subst.apply(t)) for n, t in param_pairs]

        # Check compilability: all param types and return type must be concrete
        is_compilable = all(
            not isinstance(t, TypeVar) for _, t in resolved_params
        ) and not isinstance(resolved_ret, TypeVar)

        if not is_compilable:
            loc = self._make_diag_loc(func.loc, filename)
            self.diag.warning(
                f"Function '{func.name}' has unresolved types, skipping compilation",
                location=loc,
            )

        # Apply subst to all node_types
        resolved_node_types = {k: self._subst.apply(v) for k, v in self._node_types.items()}

        self._env = old_env
        # Restore function bindings
        for name, ft in self._functions.items():
            self._env[name] = ft
        self._return_type = old_return

        return TypedFunction(
            name=func.name,
            params=resolved_params,
            return_type=resolved_ret,
            node=func,
            node_types=resolved_node_types,
            is_compilable=is_compilable,
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
                            f"Return type mismatch: expected {self._return_type!r}, got {val_type!r}",
                            location=loc,
                        )
        elif isinstance(stmt, IfStmt):
            self._check_if(stmt, filename)
        elif isinstance(stmt, WhileStmt):
            self._check_while(stmt, filename)
        elif isinstance(stmt, ForStmt):
            self._check_for(stmt, filename)
        elif isinstance(stmt, ExpressionStmt):
            self._infer_expr(stmt.expression, filename)
        elif isinstance(stmt, ObjectDestructure):
            self._check_object_destructure(stmt, filename)
        elif isinstance(stmt, Block):
            self._check_block(stmt, filename)

    def _check_var_decl(self, decl: VarDecl, filename: str):
        ann_type = self._resolve_type_annotation(decl.type_annotation) if decl.type_annotation else None
        init_type = self._infer_expr(decl.init, filename) if decl.init else None

        if ann_type and init_type:
            try:
                s = unify(ann_type, init_type)
                self._subst = s.compose(self._subst)
            except UnificationError:
                loc = self._make_diag_loc(decl.loc, filename)
                self.diag.error(
                    f"Type mismatch in variable '{decl.name}': "
                    f"declared as {ann_type!r}, initialized with {init_type!r}",
                    location=loc,
                )
            self._env[decl.name] = ann_type
        elif ann_type:
            self._env[decl.name] = ann_type
        elif init_type:
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

    def _check_object_destructure(self, decl: ObjectDestructure, filename: str):
        init_type = self._infer_expr(decl.init, filename)
        resolved = self._subst.apply(init_type)
        for fname in decl.fields:
            if isinstance(resolved, ObjectType) and fname in resolved.fields:
                self._env[fname] = resolved.fields[fname]
            else:
                self._env[fname] = TypeVar()

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
            self.diag.error(f"Undefined variable: '{expr.name}'", location=loc)
            return TypeVar()

        if isinstance(expr, BinaryExpr):
            left_t = self._infer_expr(expr.left, filename)
            right_t = self._infer_expr(expr.right, filename)
            result = binary_op_type(expr.op, self._subst.apply(left_t), self._subst.apply(right_t))
            if result:
                return result
            # Try unification for TypeVar resolution
            try:
                s = unify(left_t, right_t)
                self._subst = s.compose(self._subst)
                resolved = self._subst.apply(left_t)
                result = binary_op_type(expr.op, resolved, resolved)
                if result:
                    return result
            except UnificationError:
                pass
            loc = self._make_diag_loc(expr.loc, filename)
            self.diag.error(
                f"Invalid binary operation: {self._subst.apply(left_t)!r} {expr.op} {self._subst.apply(right_t)!r}",
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
            # && and || return one of their operands in JS
            # For type checking, we return the common type
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
                # obj.field = value
                self._infer_expr(expr.left, filename)
            return right_t

        if isinstance(expr, ObjectLiteralExpr):
            fields: dict[str, MonoType] = {}
            # Handle spreads first (they can be overridden by explicit properties)
            for _, spread_expr in expr.spreads:
                spread_t = self._infer_expr(spread_expr, filename)
                spread_resolved = self._subst.apply(spread_t)
                if isinstance(spread_resolved, ObjectType):
                    fields.update(spread_resolved.fields)
            # Then explicit properties
            for fname, fexpr in expr.properties:
                fields[fname] = self._infer_expr(fexpr, filename)
            return ObjectType(fields=fields)

        if isinstance(expr, ArrowFunction):
            return self._infer_arrow(expr, filename)

        return TypeVar()

    def _infer_call(self, expr: CallExpr, filename: str) -> MonoType:
        callee_t = self._infer_expr(expr.callee, filename)
        arg_types = [self._infer_expr(a, filename) for a in expr.arguments]

        resolved = self._subst.apply(callee_t)
        if isinstance(resolved, FunctionType):
            # Unify arguments with params
            for i, (arg_t, param_t) in enumerate(zip(arg_types, resolved.param_types)):
                try:
                    s = unify(param_t, arg_t)
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    loc = self._make_diag_loc(expr.loc, filename)
                    self.diag.error(
                        f"Argument type mismatch at position {i}: "
                        f"expected {param_t!r}, got {arg_t!r}",
                        location=loc,
                    )
            return self._subst.apply(resolved.return_type)

        # console.log etc. handled via member expr resolution
        return TypeVar()

    def _infer_member(self, expr: MemberExpr, filename: str) -> MonoType:
        obj_t = self._infer_expr(expr.object, filename)
        resolved = self._subst.apply(obj_t)

        if isinstance(resolved, ObjectType) and isinstance(expr.property, Identifier):
            field_name = expr.property.name
            if field_name in resolved.fields:
                return resolved.fields[field_name]
            else:
                loc = self._make_diag_loc(expr.loc, filename)
                self.diag.error(f"Property '{field_name}' does not exist on type {resolved!r}", location=loc)
                return TypeVar()

        # Array.length etc.
        if isinstance(resolved, ArrayType) and isinstance(expr.property, Identifier):
            if expr.property.name == "length":
                return NUMBER
            if expr.property.name == "push":
                return FunctionType([resolved.element_type], NUMBER)

        return TypeVar()

    def _infer_arrow(self, expr: ArrowFunction, filename: str) -> MonoType:
        param_types: list[MonoType] = []
        old_env = dict(self._env)

        for p in expr.params:
            pt = self._resolve_type_annotation(p.type_annotation) if p.type_annotation else TypeVar()
            param_types.append(pt)
            self._env[p.name] = pt

        ret_type_ann = self._resolve_type_annotation(expr.return_type) if expr.return_type else None

        if isinstance(expr.body, Block):
            old_ret = self._return_type
            self._return_type = ret_type_ann or TypeVar()
            self._check_block(expr.body, filename)
            ret = self._subst.apply(self._return_type)
            self._return_type = old_ret
        else:
            ret = self._infer_expr(expr.body, filename)
            if ret_type_ann:
                try:
                    s = unify(ret_type_ann, ret)
                    self._subst = s.compose(self._subst)
                except UnificationError:
                    pass
                ret = ret_type_ann

        self._env = old_env
        return FunctionType(param_types, ret)

    def _resolve_type_annotation(self, ann: TypeAnnotation | None) -> MonoType:
        if ann is None:
            return TypeVar()
        if isinstance(ann, NamedType):
            name = ann.name
            if name == "number":
                return NUMBER
            elif name == "boolean":
                return BOOLEAN
            elif name == "string":
                return STRING
            elif name == "void":
                return VOID
            elif name == "null":
                return NULL
            elif name in self._interfaces:
                return self._interfaces[name]
            return TypeVar()
        if isinstance(ann, ArrayTypeAnnotation):
            elem = self._resolve_type_annotation(ann.element_type)
            return ArrayType(elem)
        if isinstance(ann, FunctionTypeAnnotation):
            params = [self._resolve_type_annotation(p) for p in ann.param_types]
            ret = self._resolve_type_annotation(ann.return_type)
            return FunctionType(params, ret)
        if isinstance(ann, ObjectTypeAnnotation):
            fields: dict[str, MonoType] = {}
            for fname, ftype_ann in ann.fields:
                fields[fname] = self._resolve_type_annotation(ftype_ann)
            return ObjectType(fields=fields)
        return TypeVar()

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
