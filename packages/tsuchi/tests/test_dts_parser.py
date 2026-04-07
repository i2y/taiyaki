"""Tests for .d.ts type stub parsing and integration with JSInferrer."""

import pytest
from tsuchi.type_checker.dts_parser import DTSParser
from tsuchi.type_checker.types import (
    NumberType, BooleanType, StringType, VoidType, ObjectType,
    FunctionType, ArrayType,
    NUMBER, BOOLEAN, STRING, VOID,
)
from tsuchi.parser.js_parser import JSParser
from tsuchi.type_checker.js_inferrer import JSInferrer
from tsuchi.diagnostics.diagnostic import DiagnosticCollector


@pytest.fixture
def dts_parser():
    return DTSParser()


class TestDTSParsing:
    def test_simple_function(self, dts_parser):
        stubs = dts_parser.parse("export function add(a: number, b: number): number;")
        assert "add" in stubs
        ft = stubs["add"]
        assert len(ft.param_types) == 2
        assert isinstance(ft.param_types[0], NumberType)
        assert isinstance(ft.param_types[1], NumberType)
        assert isinstance(ft.return_type, NumberType)

    def test_string_function(self, dts_parser):
        stubs = dts_parser.parse("export function greet(name: string): string;")
        assert "greet" in stubs
        ft = stubs["greet"]
        assert isinstance(ft.param_types[0], StringType)
        assert isinstance(ft.return_type, StringType)

    def test_boolean_return(self, dts_parser):
        stubs = dts_parser.parse("export function isEven(n: number): boolean;")
        ft = stubs["isEven"]
        assert isinstance(ft.param_types[0], NumberType)
        assert isinstance(ft.return_type, BooleanType)

    def test_void_return(self, dts_parser):
        stubs = dts_parser.parse("export function log(msg: string): void;")
        ft = stubs["log"]
        assert isinstance(ft.return_type, VoidType)

    def test_object_param(self, dts_parser):
        stubs = dts_parser.parse(
            "export function getX(p: { x: number; y: number }): number;"
        )
        ft = stubs["getX"]
        assert isinstance(ft.param_types[0], ObjectType)
        assert "x" in ft.param_types[0].fields
        assert "y" in ft.param_types[0].fields
        assert isinstance(ft.param_types[0].fields["x"], NumberType)
        assert isinstance(ft.return_type, NumberType)

    def test_multiple_functions(self, dts_parser):
        stubs = dts_parser.parse("""
export function add(a: number, b: number): number;
export function sub(a: number, b: number): number;
export function greet(name: string): string;
""")
        assert len(stubs) == 3
        assert "add" in stubs
        assert "sub" in stubs
        assert "greet" in stubs

    def test_no_export(self, dts_parser):
        stubs = dts_parser.parse("function helper(x: number): number;")
        assert "helper" in stubs

    def test_array_type(self, dts_parser):
        stubs = dts_parser.parse("export function sum(arr: number[]): number;")
        ft = stubs["sum"]
        assert isinstance(ft.param_types[0], ArrayType)
        assert isinstance(ft.param_types[0].element_type, NumberType)


class TestDTSIntegration:
    def test_stub_makes_function_compilable(self):
        """A function with no call site should be compilable if .d.ts provides types."""
        stubs = DTSParser().parse("export function add(a: number, b: number): number;")

        js_source = """
function add(a, b) {
    return a + b;
}
"""
        parser = JSParser()
        module = parser.parse(js_source)
        diag = DiagnosticCollector()
        inferrer = JSInferrer(diagnostics=diag, type_stubs=stubs)
        typed = inferrer.check_module(module)

        assert not diag.has_errors()
        func = typed.functions[0]
        assert func.name == "add"
        assert func.is_compilable
        assert isinstance(func.params[0][1], NumberType)
        assert isinstance(func.params[1][1], NumberType)
        assert isinstance(func.return_type, NumberType)

    def test_without_stub_not_compilable(self):
        """Without stub and without call site, function should NOT be compilable."""
        js_source = """
function add(a, b) {
    return a + b;
}
"""
        parser = JSParser()
        module = parser.parse(js_source)
        diag = DiagnosticCollector()
        inferrer = JSInferrer(diagnostics=diag)
        typed = inferrer.check_module(module)

        func = typed.functions[0]
        assert not func.is_compilable

    def test_stub_overrides_inference(self):
        """Stub types should be used even when call site exists."""
        stubs = DTSParser().parse("export function double(x: number): number;")

        js_source = """
function double(x) {
    return x * 2;
}
double(5);
"""
        parser = JSParser()
        module = parser.parse(js_source)
        diag = DiagnosticCollector()
        inferrer = JSInferrer(diagnostics=diag, type_stubs=stubs)
        typed = inferrer.check_module(module)

        assert not diag.has_errors()
        func = typed.functions[0]
        assert func.is_compilable
        assert isinstance(func.params[0][1], NumberType)

    def test_stub_with_object_param(self):
        """Stub with object type param should work."""
        stubs = DTSParser().parse(
            "export function getX(p: { x: number; y: number }): number;"
        )

        js_source = """
function getX(p) {
    return p.x;
}
"""
        parser = JSParser()
        module = parser.parse(js_source)
        diag = DiagnosticCollector()
        inferrer = JSInferrer(diagnostics=diag, type_stubs=stubs)
        typed = inferrer.check_module(module)

        assert not diag.has_errors()
        func = typed.functions[0]
        assert func.is_compilable
        assert isinstance(func.params[0][1], ObjectType)
        assert isinstance(func.return_type, NumberType)
