"""AST node definitions for the Tsuchi JavaScript compiler."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Location:
    line: int
    col: int
    end_line: int | None = None
    end_col: int | None = None


# --- Expression nodes ---

@dataclass
class Expression:
    """Base class for expressions."""
    loc: Location | None = None


@dataclass
class NumberLiteral(Expression):
    value: float = 0.0


@dataclass
class StringLiteral(Expression):
    value: str = ""


@dataclass
class BooleanLiteral(Expression):
    value: bool = False


@dataclass
class NullLiteral(Expression):
    pass


@dataclass
class Identifier(Expression):
    name: str = ""


@dataclass
class BinaryExpr(Expression):
    op: str = ""  # "+", "-", "*", "/", "%", "**"
    left: Expression = field(default_factory=Expression)
    right: Expression = field(default_factory=Expression)


@dataclass
class UnaryExpr(Expression):
    op: str = ""  # "-", "+", "!", "~", "typeof"
    operand: Expression = field(default_factory=Expression)
    prefix: bool = True


@dataclass
class UpdateExpr(Expression):
    """i++ / i-- / ++i / --i"""
    op: str = ""  # "++" or "--"
    operand: Expression = field(default_factory=Expression)
    prefix: bool = False


@dataclass
class CompareExpr(Expression):
    op: str = ""  # "===", "!==", "<", ">", "<=", ">="
    left: Expression = field(default_factory=Expression)
    right: Expression = field(default_factory=Expression)


@dataclass
class LogicalExpr(Expression):
    op: str = ""  # "&&", "||"
    left: Expression = field(default_factory=Expression)
    right: Expression = field(default_factory=Expression)


@dataclass
class ConditionalExpr(Expression):
    """Ternary: condition ? consequent : alternate"""
    condition: Expression = field(default_factory=Expression)
    consequent: Expression = field(default_factory=Expression)
    alternate: Expression = field(default_factory=Expression)


@dataclass
class CallExpr(Expression):
    callee: Expression = field(default_factory=Expression)
    arguments: list[Expression] = field(default_factory=list)


@dataclass
class ObjectLiteralExpr(Expression):
    """Object literal: { x: 1, y: 2, ...other }"""
    properties: list[tuple[str, Expression]] = field(default_factory=list)
    spreads: list[tuple[int, Expression]] = field(default_factory=list)  # (position_index, spread_expr)


@dataclass
class MemberExpr(Expression):
    """object.property or object[computed]"""
    object: Expression = field(default_factory=Expression)
    property: Expression = field(default_factory=Expression)
    computed: bool = False  # True for obj[expr]


@dataclass
class AssignExpr(Expression):
    """Assignment expression: a = b, a += b, etc."""
    op: str = "="  # "=", "+=", "-=", "*=", "/=", "%="
    left: Expression = field(default_factory=Expression)
    right: Expression = field(default_factory=Expression)


@dataclass
class SpreadElement(Expression):
    """Spread element: ...expr"""
    argument: Expression = field(default_factory=Expression)


@dataclass
class SequenceExpr(Expression):
    """Comma-separated expressions: (a, b, c) — evaluates all, returns last."""
    expressions: list[Expression] = field(default_factory=list)


@dataclass
class ArrayLiteral(Expression):
    """Array literal: [1, 2, 3, ...other]"""
    elements: list[Expression] = field(default_factory=list)


@dataclass
class ArrowFunction(Expression):
    """Arrow function: (a) => a * 2 or (a) => { return a * 2; }"""
    params: list[Parameter] = field(default_factory=list)
    body: Expression | Block = field(default_factory=lambda: Block())


@dataclass
class TemplateLiteral(Expression):
    """Template literal: `hello ${name}`"""
    quasis: list[str] = field(default_factory=list)
    expressions: list[Expression] = field(default_factory=list)


@dataclass
class NewExpr(Expression):
    """new ClassName(args)"""
    class_name: str = ""
    arguments: list[Expression] = field(default_factory=list)


@dataclass
class ThisExpr(Expression):
    """this keyword"""
    pass


# --- Statement nodes ---

@dataclass
class Statement:
    """Base class for statements."""
    loc: Location | None = None


@dataclass
class Parameter:
    name: str
    default: Expression | None = None
    is_rest: bool = False


@dataclass
class FunctionDecl(Statement):
    name: str = ""
    params: list[Parameter] = field(default_factory=list)
    body: Block = field(default_factory=lambda: Block())
    is_async: bool = False
    is_generator: bool = False


@dataclass
class AwaitExpr(Expression):
    """await somePromise — suspends async function until Promise resolves."""
    argument: Expression = field(default_factory=Expression)


@dataclass
class VarDecl(Statement):
    """const/let/var declaration."""
    kind: str = "const"  # "const", "let", "var"
    name: str = ""
    init: Expression | None = None


@dataclass
class ObjectDestructure(Statement):
    """const { x, y: alias = default, ...rest } = expr;"""
    kind: str = "const"  # "const", "let", "var"
    fields: list[str] = field(default_factory=list)  # destructured field names (object keys)
    init: Expression = field(default_factory=Expression)
    defaults: dict[str, Expression] = field(default_factory=dict)  # field_name → default expr
    rest_name: str | None = None  # name for ...rest element
    aliases: dict[str, str] = field(default_factory=dict)  # field_name → local_var_name


@dataclass
class ArrayDestructure(Statement):
    """const [a, b = default, ...rest] = expr;"""
    kind: str = "const"
    names: list[str] = field(default_factory=list)  # variable names in order
    init: Expression = field(default_factory=Expression)
    rest_name: str | None = None  # name for ...rest element
    defaults: dict[str, Expression] = field(default_factory=dict)  # name → default expr


@dataclass
class ReturnStmt(Statement):
    value: Expression | None = None


@dataclass
class IfStmt(Statement):
    condition: Expression = field(default_factory=Expression)
    consequent: Block = field(default_factory=lambda: Block())
    alternate: Block | IfStmt | None = None


@dataclass
class WhileStmt(Statement):
    condition: Expression = field(default_factory=Expression)
    body: Block = field(default_factory=lambda: Block())


@dataclass
class DoWhileStmt(Statement):
    condition: Expression = field(default_factory=Expression)
    body: Block = field(default_factory=lambda: Block())


@dataclass
class ForStmt(Statement):
    """C-style for: for (init; condition; update) { body }"""
    init: VarDecl | Expression | None = None
    condition: Expression | None = None
    update: Expression | None = None
    body: Block = field(default_factory=lambda: Block())


@dataclass
class ForOfStmt(Statement):
    """for (const x of iterable) { body }"""
    var_name: str = ""
    kind: str = "const"  # "const", "let", "var"
    iterable: Expression = field(default_factory=Expression)
    body: Block = field(default_factory=lambda: Block())


@dataclass
class ForInStmt(Statement):
    """for (const key in object) { body }"""
    var_name: str = ""
    kind: str = "const"  # "const", "let", "var"
    object: Expression = field(default_factory=Expression)
    body: Block = field(default_factory=lambda: Block())


@dataclass
class BreakStmt(Statement):
    label: str | None = None


@dataclass
class ContinueStmt(Statement):
    label: str | None = None


@dataclass
class LabeledStmt(Statement):
    """label: statement"""
    label_name: str = ""
    body: Statement = field(default_factory=lambda: Statement())


@dataclass
class ThrowStmt(Statement):
    """throw expression;"""
    argument: Expression = field(default_factory=Expression)


@dataclass
class TryCatchStmt(Statement):
    """try { ... } catch (e) { ... } finally { ... }"""
    try_block: Block = field(default_factory=lambda: Block())
    catch_param: str | None = None  # catch variable name, None if no catch
    catch_block: Block | None = None
    finally_block: Block | None = None


@dataclass
class SwitchCase(Statement):
    """A single case in a switch: case expr: stmts or default: stmts"""
    test: Expression | None = None  # None for default case
    body: list[Statement] = field(default_factory=list)


@dataclass
class SwitchStmt(Statement):
    """switch (discriminant) { case ...: ... }"""
    discriminant: Expression = field(default_factory=Expression)
    cases: list[SwitchCase] = field(default_factory=list)


@dataclass
class MethodDecl:
    """Method in a class body."""
    name: str = ""
    params: list[Parameter] = field(default_factory=list)
    body: Block = field(default_factory=lambda: Block())
    is_static: bool = False
    is_getter: bool = False
    is_setter: bool = False


@dataclass
class SuperCall(Expression):
    """super(args) in constructor"""
    arguments: list[Expression] = field(default_factory=list)


@dataclass
class ClassField:
    """Class field declaration: name = initializer"""
    name: str = ""
    initializer: Expression | None = None
    is_static: bool = False


@dataclass
class ClassDecl(Statement):
    """class Foo extends Bar { constructor() {} method() {} }"""
    name: str = ""
    extends: str | None = None  # parent class name
    constructor: MethodDecl | None = None
    methods: list[MethodDecl] = field(default_factory=list)
    static_methods: list[MethodDecl] = field(default_factory=list)
    field_declarations: list[ClassField] = field(default_factory=list)


@dataclass
class ExpressionStmt(Statement):
    expression: Expression = field(default_factory=Expression)


@dataclass
class Block(Statement):
    body: list[Statement] = field(default_factory=list)


# --- Module declarations ---

@dataclass
class ImportSpecifier:
    """Single import binding: { foo } or { foo as bar } or default."""
    imported: str = ""  # name in source module (or "default")
    local: str = ""  # local binding name


@dataclass
class ImportDeclaration(Statement):
    """import { foo, bar as baz } from './other.js'"""
    specifiers: list[ImportSpecifier] = field(default_factory=list)
    source: str = ""  # module path string
    namespace: str | None = None  # for import * as ns


@dataclass
class ExportDeclaration(Statement):
    """export function/class/const or export { foo, bar as baz }"""
    declaration: Statement | None = None  # FunctionDecl, VarDecl, ClassDecl
    specifiers: list[tuple[str, str]] = field(default_factory=list)  # [(local, exported)]
    is_default: bool = False


# --- Top-level ---

@dataclass
class JSModule:
    """Top-level module (a single .js file)."""
    body: list[Statement] = field(default_factory=list)
    source: str = ""  # original source text
    import_rewrite_map: dict[str, str] = field(default_factory=dict)  # original_name → prefixed_name
