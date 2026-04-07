"""Tests for the Tsuchi JavaScript parser."""

import pytest
from tsuchi.parser.js_parser import JSParser
from tsuchi.parser.ast_nodes import (
    FunctionDecl, VarDecl, ReturnStmt, IfStmt, WhileStmt, ForStmt,
    ForOfStmt, ExpressionStmt, NumberLiteral, StringLiteral, BooleanLiteral,
    Identifier, BinaryExpr, CompareExpr, LogicalExpr, ConditionalExpr,
    CallExpr, MemberExpr, AssignExpr, UnaryExpr, UpdateExpr,
    ArrowFunction, Block, ObjectLiteralExpr, ArrayLiteral, TemplateLiteral,
    ObjectDestructure,
)


@pytest.fixture
def parser():
    return JSParser()


class TestParserBasics:
    def test_function_declaration(self, parser):
        m = parser.parse("function add(a, b) { return a + b; }")
        assert len(m.body) == 1
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        assert func.name == "add"
        assert len(func.params) == 2
        assert func.params[0].name == "a"
        assert func.params[1].name == "b"

    def test_const_declaration(self, parser):
        m = parser.parse("const x = 42;")
        assert len(m.body) == 1
        decl = m.body[0]
        assert isinstance(decl, VarDecl)
        assert decl.kind == "const"
        assert decl.name == "x"
        assert isinstance(decl.init, NumberLiteral)
        assert decl.init.value == 42.0

    def test_let_declaration(self, parser):
        m = parser.parse("let y = 10;")
        assert len(m.body) == 1
        decl = m.body[0]
        assert isinstance(decl, VarDecl)
        assert decl.kind == "let"
        assert decl.name == "y"

    def test_number_literal(self, parser):
        m = parser.parse("const x = 3.14;")
        decl = m.body[0]
        assert isinstance(decl.init, NumberLiteral)
        assert decl.init.value == 3.14

    def test_string_literal(self, parser):
        m = parser.parse('const s = "hello";')
        decl = m.body[0]
        assert isinstance(decl.init, StringLiteral)
        assert decl.init.value == "hello"

    def test_boolean_literal(self, parser):
        m = parser.parse("const t = true;")
        decl = m.body[0]
        assert isinstance(decl.init, BooleanLiteral)
        assert decl.init.value is True


class TestExpressions:
    def test_binary_expression(self, parser):
        m = parser.parse("const x = 1 + 2;")
        decl = m.body[0]
        assert isinstance(decl.init, BinaryExpr)
        assert decl.init.op == "+"

    def test_comparison(self, parser):
        m = parser.parse("const x = a > b;")
        decl = m.body[0]
        assert isinstance(decl.init, CompareExpr)
        assert decl.init.op == ">"

    def test_strict_equality(self, parser):
        m = parser.parse("const x = a === b;")
        decl = m.body[0]
        assert isinstance(decl.init, CompareExpr)
        assert decl.init.op == "==="

    def test_logical_and(self, parser):
        m = parser.parse("const x = a && b;")
        decl = m.body[0]
        assert isinstance(decl.init, LogicalExpr)
        assert decl.init.op == "&&"

    def test_logical_or(self, parser):
        m = parser.parse("const x = a || b;")
        decl = m.body[0]
        assert isinstance(decl.init, LogicalExpr)
        assert decl.init.op == "||"

    def test_ternary(self, parser):
        m = parser.parse("const x = a > 0 ? 1 : 0;")
        decl = m.body[0]
        assert isinstance(decl.init, ConditionalExpr)

    def test_unary_minus(self, parser):
        m = parser.parse("const x = -5;")
        decl = m.body[0]
        assert isinstance(decl.init, UnaryExpr)
        assert decl.init.op == "-"

    def test_not(self, parser):
        m = parser.parse("const x = !true;")
        decl = m.body[0]
        assert isinstance(decl.init, UnaryExpr)
        assert decl.init.op == "!"

    def test_call_expression(self, parser):
        m = parser.parse("add(1, 2);")
        stmt = m.body[0]
        assert isinstance(stmt, ExpressionStmt)
        call = stmt.expression
        assert isinstance(call, CallExpr)
        assert isinstance(call.callee, Identifier)
        assert call.callee.name == "add"
        assert len(call.arguments) == 2

    def test_member_expression(self, parser):
        m = parser.parse("console.log(42);")
        stmt = m.body[0]
        assert isinstance(stmt, ExpressionStmt)
        call = stmt.expression
        assert isinstance(call, CallExpr)
        assert isinstance(call.callee, MemberExpr)

    def test_update_expression(self, parser):
        m = parser.parse("i++;")
        stmt = m.body[0]
        assert isinstance(stmt, ExpressionStmt)
        assert isinstance(stmt.expression, UpdateExpr)
        assert stmt.expression.op == "++"

    def test_arrow_function(self, parser):
        m = parser.parse("const f = (x) => x * 2;")
        decl = m.body[0]
        assert isinstance(decl.init, ArrowFunction)
        assert len(decl.init.params) == 1
        assert decl.init.params[0].name == "x"


class TestControlFlow:
    def test_if_statement(self, parser):
        m = parser.parse("if (x > 0) { y = 1; }")
        stmt = m.body[0]
        assert isinstance(stmt, IfStmt)

    def test_if_else(self, parser):
        m = parser.parse("if (x > 0) { y = 1; } else { y = 0; }")
        stmt = m.body[0]
        assert isinstance(stmt, IfStmt)
        assert stmt.alternate is not None

    def test_while_loop(self, parser):
        m = parser.parse("while (i < 10) { i++; }")
        stmt = m.body[0]
        assert isinstance(stmt, WhileStmt)

    def test_for_loop(self, parser):
        m = parser.parse("for (let i = 0; i < 10; i++) { x += i; }")
        stmt = m.body[0]
        assert isinstance(stmt, ForStmt)
        assert isinstance(stmt.init, VarDecl)


class TestObjectTypes:
    def test_object_literal(self, parser):
        m = parser.parse("const p = { x: 1, y: 2 };")
        decl = m.body[0]
        assert isinstance(decl.init, ObjectLiteralExpr)
        assert len(decl.init.properties) == 2
        assert decl.init.properties[0][0] == "x"
        assert isinstance(decl.init.properties[0][1], NumberLiteral)
        assert decl.init.properties[1][0] == "y"


class TestObjectDestructure:
    def test_basic_destructure(self, parser):
        m = parser.parse("""
function f() {
    const obj = { x: 1, y: 2 };
    const { x, y } = obj;
    return x + y;
}
""")
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        body_stmts = func.body.body
        found = any(isinstance(s, ObjectDestructure) for s in body_stmts)
        assert found


class TestObjectSpread:
    def test_spread_in_literal(self, parser):
        m = parser.parse("""
function f() {
    const a = { x: 1 };
    const b = { ...a, y: 2 };
    return b.x + b.y;
}
""")
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        body_stmts = func.body.body
        for s in body_stmts:
            if isinstance(s, VarDecl) and s.name == "b" and isinstance(s.init, ObjectLiteralExpr):
                assert len(s.init.spreads) > 0
                break
        else:
            pytest.fail("No spread found in object literal")


class TestTemplateLiterals:
    def test_plain_template(self, parser):
        m = parser.parse("const x = `hello`;")
        decl = m.body[0]
        assert isinstance(decl.init, StringLiteral)
        assert decl.init.value == "hello"

    def test_template_with_expr(self, parser):
        m = parser.parse("const x = `hello ${name}`;")
        decl = m.body[0]
        assert isinstance(decl.init, TemplateLiteral)
        assert decl.init.quasis == ["hello ", ""]
        assert len(decl.init.expressions) == 1
        assert isinstance(decl.init.expressions[0], Identifier)

    def test_template_multi_expr(self, parser):
        m = parser.parse("const x = `${a} + ${b}`;")
        decl = m.body[0]
        assert isinstance(decl.init, TemplateLiteral)
        assert decl.init.quasis == ["", " + ", ""]
        assert len(decl.init.expressions) == 2


class TestArrayAndForOf:
    def test_array_literal(self, parser):
        m = parser.parse("const arr = [1, 2, 3];")
        decl = m.body[0]
        assert isinstance(decl, VarDecl)
        assert isinstance(decl.init, ArrayLiteral)
        assert len(decl.init.elements) == 3
        assert isinstance(decl.init.elements[0], NumberLiteral)
        assert decl.init.elements[0].value == 1.0

    def test_empty_array(self, parser):
        m = parser.parse("const arr = [];")
        decl = m.body[0]
        assert isinstance(decl.init, ArrayLiteral)
        assert len(decl.init.elements) == 0

    def test_array_subscript(self, parser):
        m = parser.parse("const x = arr[0];")
        decl = m.body[0]
        assert isinstance(decl.init, MemberExpr)
        assert decl.init.computed is True

    def test_for_of(self, parser):
        m = parser.parse("""
for (const x of arr) {
    console.log(x);
}
""")
        stmt = m.body[0]
        assert isinstance(stmt, ForOfStmt)
        assert stmt.var_name == "x"
        assert stmt.kind == "const"
        assert isinstance(stmt.iterable, Identifier)
        assert stmt.iterable.name == "arr"

    def test_for_of_let(self, parser):
        m = parser.parse("for (let item of items) { }")
        stmt = m.body[0]
        assert isinstance(stmt, ForOfStmt)
        assert stmt.var_name == "item"
        assert stmt.kind == "let"


class TestMultipleStatements:
    def test_function_and_call(self, parser):
        m = parser.parse("""
function add(a, b) {
    return a + b;
}
console.log(add(1, 2));
""")
        assert len(m.body) == 2
        assert isinstance(m.body[0], FunctionDecl)
        assert isinstance(m.body[1], ExpressionStmt)
