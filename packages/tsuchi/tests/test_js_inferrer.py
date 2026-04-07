"""Tests for the Tsuchi JS call-site type inference engine."""

import pytest
from tsuchi.parser.js_parser import JSParser
from tsuchi.type_checker.js_inferrer import JSInferrer
from tsuchi.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType, FunctionType, ObjectType, ArrayType,
    NUMBER, BOOLEAN, STRING, VOID,
)
from tsuchi.diagnostics.diagnostic import DiagnosticCollector


def infer(source: str):
    """Parse and infer types for JS source, return (TypedModule, DiagnosticCollector)."""
    parser = JSParser()
    module = parser.parse(source)
    diag = DiagnosticCollector()
    inferrer = JSInferrer(diagnostics=diag)
    typed = inferrer.check_module(module)
    return typed, diag


class TestCallSiteInference:
    def test_add_called_with_numbers(self):
        typed, diag = infer("""
function add(a, b) {
    return a + b;
}
add(1, 2);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert func.name == "add"
        assert isinstance(func.params[0][1], NumberType)
        assert isinstance(func.params[1][1], NumberType)
        assert isinstance(func.return_type, NumberType)
        assert func.is_compilable

    def test_boolean_function(self):
        typed, diag = infer("""
function isPositive(x) {
    return x > 0;
}
isPositive(5);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.params[0][1], NumberType)
        assert isinstance(func.return_type, BooleanType)
        assert func.is_compilable

    def test_no_call_site_not_compilable(self):
        typed, diag = infer("""
function mystery(x) {
    return x;
}
""")
        func = typed.functions[0]
        assert not func.is_compilable


class TestLocalInference:
    def test_let_inference(self):
        typed, diag = infer("""
function f() {
    let x = 42;
    return x;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_const_inference(self):
        typed, diag = infer("""
function f() {
    const x = 10 + 20;
    return x;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)


class TestCrossFunctionInference:
    def test_inter_function_call(self):
        typed, diag = infer("""
function double(x) {
    return x * 2;
}
function main() {
    return double(21);
}
main();
""")
        assert not diag.has_errors()
        # double should be inferred as (number) => number
        double_func = next(f for f in typed.functions if f.name == "double")
        assert isinstance(double_func.params[0][1], NumberType)
        assert isinstance(double_func.return_type, NumberType)
        assert double_func.is_compilable

    def test_recursive_fibonacci(self):
        typed, diag = infer("""
function fib(n) {
    if (n <= 1) {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}
fib(10);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.params[0][1], NumberType)
        assert isinstance(func.return_type, NumberType)
        assert func.is_compilable


class TestControlFlow:
    def test_if_else(self):
        typed, diag = infer("""
function abs(x) {
    if (x < 0) {
        return -x;
    } else {
        return x;
    }
}
abs(-5);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_while_loop(self):
        typed, diag = infer("""
function sum(n) {
    let s = 0;
    let i = 0;
    while (i < n) {
        s = s + i;
        i++;
    }
    return s;
}
sum(10);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_for_loop(self):
        typed, diag = infer("""
function sum(n) {
    let s = 0;
    for (let i = 0; i < n; i++) {
        s = s + i;
    }
    return s;
}
sum(10);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)


class TestObjectInference:
    def test_object_literal(self):
        typed, diag = infer("""
function f() {
    const p = { x: 1, y: 2 };
    return p.x;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_object_destructure(self):
        typed, diag = infer("""
function f() {
    const obj = { x: 10, y: 20 };
    const { x, y } = obj;
    return x + y;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_object_spread(self):
        typed, diag = infer("""
function f() {
    const a = { x: 1, y: 2 };
    const b = { ...a, z: 3 };
    return b.x + b.z;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)


class TestArrayInference:
    def test_array_literal(self):
        typed, diag = infer("""
function f() {
    const arr = [1, 2, 3];
    return arr;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, ArrayType)
        assert isinstance(func.return_type.element_type, NumberType)

    def test_array_subscript(self):
        typed, diag = infer("""
function f() {
    const arr = [1, 2, 3];
    return arr[0];
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_array_length(self):
        typed, diag = infer("""
function f() {
    const arr = [1, 2, 3];
    return arr.length;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_array_push(self):
        typed, diag = infer("""
function f() {
    const arr = [1, 2];
    arr.push(3);
    return arr.length;
}
f();
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.return_type, NumberType)

    def test_for_of(self):
        typed, diag = infer("""
function sum(arr) {
    let s = 0;
    for (const x of arr) {
        s = s + x;
    }
    return s;
}
sum([1, 2, 3]);
""")
        assert not diag.has_errors()
        func = typed.functions[0]
        assert isinstance(func.params[0][1], ArrayType)
        assert isinstance(func.return_type, NumberType)


class TestDiagnostics:
    def test_undefined_variable(self):
        typed, diag = infer("""
function f() {
    return x;
}
f();
""")
        assert diag.has_errors()
        assert any("Undefined variable" in d.message for d in diag.diagnostics)
