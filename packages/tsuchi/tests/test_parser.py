"""Tests for the Tsuchi TypeScript parser."""

import pytest
from tsuchi.parser.ts_parser import TSParser
from tsuchi.parser.ast_nodes import (
    FunctionDecl, VarDecl, ReturnStmt, IfStmt, WhileStmt, ForStmt,
    ExpressionStmt, NumberLiteral, StringLiteral, BooleanLiteral,
    Identifier, BinaryExpr, CompareExpr, LogicalExpr, ConditionalExpr,
    CallExpr, MemberExpr, AssignExpr, UnaryExpr, UpdateExpr,
    ArrowFunction, Block, InterfaceDecl, ObjectLiteralExpr,
    ObjectDestructure,
    NamedType, ArrayTypeAnnotation, ObjectTypeAnnotation,
)


@pytest.fixture
def parser():
    return TSParser()


class TestParserBasics:
    def test_function_declaration(self, parser):
        m = parser.parse("function add(a: number, b: number): number { return a + b; }")
        assert len(m.body) == 1
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        assert func.name == "add"
        assert len(func.params) == 2
        assert func.params[0].name == "a"
        assert isinstance(func.params[0].type_annotation, NamedType)
        assert func.params[0].type_annotation.name == "number"
        assert isinstance(func.return_type, NamedType)
        assert func.return_type.name == "number"

    def test_const_declaration(self, parser):
        m = parser.parse("const x: number = 42;")
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
        m = parser.parse("const f = (x: number): number => x * 2;")
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


class TestTypeAnnotations:
    def test_number_type(self, parser):
        m = parser.parse("const x: number = 42;")
        decl = m.body[0]
        assert isinstance(decl.type_annotation, NamedType)
        assert decl.type_annotation.name == "number"

    def test_boolean_type(self, parser):
        m = parser.parse("const x: boolean = true;")
        decl = m.body[0]
        assert decl.type_annotation.name == "boolean"

    def test_string_type(self, parser):
        m = parser.parse('const x: string = "hello";')
        decl = m.body[0]
        assert decl.type_annotation.name == "string"

    def test_void_return(self, parser):
        m = parser.parse("function f(): void { }")
        func = m.body[0]
        assert isinstance(func.return_type, NamedType)
        assert func.return_type.name == "void"

    def test_array_type(self, parser):
        m = parser.parse("const x: number[] = [1, 2, 3];")
        decl = m.body[0]
        assert isinstance(decl.type_annotation, ArrayTypeAnnotation)
        assert isinstance(decl.type_annotation.element_type, NamedType)
        assert decl.type_annotation.element_type.name == "number"


class TestObjectTypes:
    def test_interface_declaration(self, parser):
        m = parser.parse("""
interface Point {
    x: number;
    y: number;
}
""")
        assert len(m.body) == 1
        decl = m.body[0]
        assert isinstance(decl, InterfaceDecl)
        assert decl.name == "Point"
        assert len(decl.fields) == 2
        assert decl.fields[0][0] == "x"
        assert isinstance(decl.fields[0][1], NamedType)
        assert decl.fields[0][1].name == "number"
        assert decl.fields[1][0] == "y"

    def test_object_type_annotation(self, parser):
        m = parser.parse("function f(p: { x: number; y: number }): number { return p.x; }")
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        ann = func.params[0].type_annotation
        assert isinstance(ann, ObjectTypeAnnotation)
        assert len(ann.fields) == 2
        assert ann.fields[0][0] == "x"
        assert ann.fields[1][0] == "y"

    def test_object_literal(self, parser):
        m = parser.parse("const p = { x: 1, y: 2 };")
        decl = m.body[0]
        assert isinstance(decl.init, ObjectLiteralExpr)
        assert len(decl.init.properties) == 2
        assert decl.init.properties[0][0] == "x"
        assert isinstance(decl.init.properties[0][1], NumberLiteral)
        assert decl.init.properties[1][0] == "y"

    def test_interface_with_function(self, parser):
        m = parser.parse("""
interface Point {
    x: number;
    y: number;
}
function getX(p: Point): number {
    return p.x;
}
""")
        assert len(m.body) == 2
        assert isinstance(m.body[0], InterfaceDecl)
        assert isinstance(m.body[1], FunctionDecl)
        # Parameter type should be NamedType("Point")
        param_ann = m.body[1].params[0].type_annotation
        assert isinstance(param_ann, NamedType)
        assert param_ann.name == "Point"


class TestInterfaceExtends:
    def test_interface_extends_single(self, parser):
        m = parser.parse("""
interface Base {
    x: number;
}
interface Derived extends Base {
    y: number;
}
""")
        assert len(m.body) == 2
        derived = m.body[1]
        assert isinstance(derived, InterfaceDecl)
        assert derived.name == "Derived"
        assert "Base" in derived.extends
        field_names = [f[0] for f in derived.fields]
        assert "y" in field_names

    def test_interface_optional_field(self, parser):
        m = parser.parse("""
interface Config {
    name: string;
    debug?: boolean;
}
""")
        assert len(m.body) == 1
        iface = m.body[0]
        assert isinstance(iface, InterfaceDecl)
        field_names = [f[0] for f in iface.fields]
        assert "name" in field_names
        assert "debug" in field_names
        assert "debug" in iface.optional_fields


class TestObjectDestructure:
    def test_basic_destructure(self, parser):
        m = parser.parse("""
function f(): number {
    const obj = { x: 1, y: 2 };
    const { x, y } = obj;
    return x + y;
}
""")
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        # Find the destructure statement
        body_stmts = func.body.body
        found = any(isinstance(s, ObjectDestructure) for s in body_stmts)
        assert found


class TestObjectSpread:
    def test_spread_in_literal(self, parser):
        m = parser.parse("""
function f(): number {
    const a = { x: 1 };
    const b = { ...a, y: 2 };
    return b.x + b.y;
}
""")
        func = m.body[0]
        assert isinstance(func, FunctionDecl)
        # Find the spread object literal
        body_stmts = func.body.body
        for s in body_stmts:
            if isinstance(s, VarDecl) and s.name == "b" and isinstance(s.init, ObjectLiteralExpr):
                assert len(s.init.spreads) > 0
                break
        else:
            pytest.fail("No spread found in object literal")


class TestMultipleStatements:
    def test_function_and_call(self, parser):
        m = parser.parse("""
function add(a: number, b: number): number {
    return a + b;
}
console.log(add(1, 2));
""")
        assert len(m.body) == 2
        assert isinstance(m.body[0], FunctionDecl)
        assert isinstance(m.body[1], ExpressionStmt)
