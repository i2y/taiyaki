"""Tests for the Tsuchi type checker."""

import pytest
from taiyaki_aot_compiler.parser.ts_parser import TSParser
from taiyaki_aot_compiler.type_checker.ts_checker import TSTypeChecker
from taiyaki_aot_compiler.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType, FunctionType, ObjectType,
    NUMBER, BOOLEAN, STRING, VOID,
)
from taiyaki_aot_compiler.diagnostics.diagnostic import DiagnosticCollector


def check(source: str):
    """Parse and type-check source, return (TypedModule, DiagnosticCollector)."""
    parser = TSParser()
    module = parser.parse(source)
    diag = DiagnosticCollector()
    checker = TSTypeChecker(diagnostics=diag)
    typed = checker.check_module(module)
    return typed, diag


class TestBasicTypes:
    def test_number_annotation(self):
        typed, diag = check("function f(x: number): number { return x; }")
        assert not diag.has_errors()
        assert len(typed.functions) == 1
        func = typed.functions[0]
        assert func.name == "f"
        assert isinstance(func.return_type, NumberType)
        assert func.is_compilable

    def test_boolean_annotation(self):
        typed, diag = check("function f(x: boolean): boolean { return x; }")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, BooleanType)

    def test_void_return(self):
        typed, diag = check("function f(): void { }")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, VoidType)

    def test_number_arithmetic(self):
        typed, diag = check("""
function add(a: number, b: number): number {
    return a + b;
}
""")
        assert not diag.has_errors()
        assert typed.functions[0].is_compilable

    def test_string_concat(self):
        typed, diag = check("""
function greet(name: string): string {
    return "hello " + name;
}
""")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, StringType)


class TestTypeInference:
    def test_let_inference(self):
        typed, diag = check("""
function f(): number {
    let x = 42;
    return x;
}
""")
        assert not diag.has_errors()

    def test_const_inference(self):
        typed, diag = check("""
function f(): number {
    const x = 10 + 20;
    return x;
}
""")
        assert not diag.has_errors()


class TestFunctionCalls:
    def test_inter_function_call(self):
        typed, diag = check("""
function double(x: number): number {
    return x * 2;
}
function main(): number {
    return double(21);
}
""")
        assert not diag.has_errors()
        assert len(typed.functions) == 2

    def test_recursive_function(self):
        typed, diag = check("""
function fib(n: number): number {
    if (n <= 1) { return n; }
    return fib(n - 1) + fib(n - 2);
}
""")
        assert not diag.has_errors()


class TestControlFlow:
    def test_if_else(self):
        typed, diag = check("""
function abs(x: number): number {
    if (x < 0) {
        return -x;
    } else {
        return x;
    }
}
""")
        assert not diag.has_errors()

    def test_while_loop(self):
        typed, diag = check("""
function sum(n: number): number {
    let s = 0;
    let i = 0;
    while (i < n) {
        s = s + i;
        i++;
    }
    return s;
}
""")
        assert not diag.has_errors()

    def test_for_loop(self):
        typed, diag = check("""
function sum(n: number): number {
    let s = 0;
    for (let i = 0; i < n; i++) {
        s = s + i;
    }
    return s;
}
""")
        assert not diag.has_errors()


class TestObjectTypes:
    def test_interface_definition(self):
        typed, diag = check("""
interface Point {
    x: number;
    y: number;
}
function getX(p: Point): number {
    return p.x;
}
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.params[0][1], ObjectType)
        assert isinstance(func.return_type, NumberType)

    def test_object_literal_inference(self):
        typed, diag = check("""
function f(): number {
    const p = { x: 1, y: 2 };
    return p.x;
}
""")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, NumberType)

    def test_property_access_type(self):
        typed, diag = check("""
interface Vec2 {
    x: number;
    y: number;
}
function length(v: Vec2): number {
    return (v.x * v.x + v.y * v.y) ** 0.5;
}
""")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, NumberType)

    def test_object_type_annotation(self):
        typed, diag = check("""
function getX(p: { x: number; y: number }): number {
    return p.x;
}
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.params[0][1], ObjectType)


class TestInterfaceExtends:
    def test_extends_inherits_fields(self):
        typed, diag = check("""
interface Base {
    x: number;
}
interface Derived extends Base {
    y: number;
}
function getX(d: Derived): number {
    return d.x;
}
""")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, NumberType)

    def test_extends_with_own_field(self):
        typed, diag = check("""
interface Base {
    x: number;
}
interface Derived extends Base {
    y: number;
}
function sum(d: Derived): number {
    return d.x + d.y;
}
""")
        assert not diag.has_errors()


class TestObjectDestructure:
    def test_destructure_types(self):
        typed, diag = check("""
function f(): number {
    const obj = { x: 1, y: 2 };
    const { x, y } = obj;
    return x + y;
}
""")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, NumberType)


class TestSpread:
    def test_spread_object(self):
        typed, diag = check("""
function f(): number {
    const a = { x: 1, y: 2 };
    const b = { ...a, z: 3 };
    return b.x + b.z;
}
""")
        assert not diag.has_errors()
        assert isinstance(typed.functions[0].return_type, NumberType)


class TestStructuralSubtyping:
    def test_missing_property_error(self):
        typed, diag = check("""
interface Point {
    x: number;
    y: number;
}
function f(p: Point): number {
    return p.z;
}
""")
        assert diag.has_errors()
        assert any("does not exist" in d.message for d in diag.diagnostics)


class TestDiagnostics:
    def test_undefined_variable(self):
        typed, diag = check("""
function f(): number {
    return x;
}
""")
        assert diag.has_errors()
        assert any("Undefined variable" in d.message for d in diag.diagnostics)

    def test_type_mismatch_in_var(self):
        typed, diag = check("""
function f(): number {
    const x: number = "hello";
    return x;
}
""")
        assert diag.has_errors()
