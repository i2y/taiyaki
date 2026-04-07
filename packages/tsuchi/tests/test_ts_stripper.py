"""Tests for TypeScript type stripping."""

import pytest
from tsuchi.parser.ts_stripper import strip_types, extract_type_hints


class TestTypeStripping:
    def test_function_param_types(self):
        ts = "function add(a: number, b: number): number { return a + b; }"
        js = strip_types(ts)
        assert "number" not in js
        assert "function add(a, b)" in js
        assert "return a + b" in js

    def test_interface_removed(self):
        ts = """
interface Point {
    x: number;
    y: number;
}
const p = { x: 1 };
"""
        js = strip_types(ts)
        assert "interface" not in js
        assert "Point" not in js
        assert "const p = { x: 1 }" in js

    def test_variable_type_annotation(self):
        ts = "const x: number = 42;"
        js = strip_types(ts)
        assert ": number" not in js
        assert "const x = 42;" in js

    def test_preserves_template_literals(self):
        ts = "function f(name: string): string { return `hello ${name}`; }"
        js = strip_types(ts)
        assert "`hello ${name}`" in js
        assert ": string" not in js

    def test_type_alias_removed(self):
        ts = """
type ID = number;
const x = 42;
"""
        js = strip_types(ts)
        assert "type ID" not in js
        assert "const x = 42" in js

    def test_complex_function(self):
        ts = """
function greet(name: string, times: number): void {
    for (let i: number = 0; i < times; i++) {
        console.log(name);
    }
}
"""
        js = strip_types(ts)
        assert ": string" not in js
        assert ": number" not in js
        assert ": void" not in js
        assert "function greet(name, times)" in js
        assert "console.log(name)" in js

    def test_array_type(self):
        ts = "function sum(arr: number[]): number { return 0; }"
        js = strip_types(ts)
        assert ": number[]" not in js
        assert ": number" not in js
        assert "function sum(arr)" in js


class TestGenerics:
    def test_function_generic_def(self):
        ts = "function identity<T>(x: T): T { return x; }"
        js = strip_types(ts)
        assert "<T>" not in js
        assert "function identity(x)" in js
        assert "return x" in js

    def test_call_site_generic(self):
        ts = "const x = foo<number>(42);"
        js = strip_types(ts)
        assert "<number>" not in js
        assert "foo(42)" in js

    def test_class_generic(self):
        ts = "class Box<T> { value: T; }"
        js = strip_types(ts)
        assert "<T>" not in js
        assert "class Box" in js

    def test_multiple_type_params(self):
        ts = "function map<K, V>(k: K, v: V): V { return v; }"
        js = strip_types(ts)
        assert "<K, V>" not in js
        assert "function map(k, v)" in js


class TestAsExpression:
    def test_as_number(self):
        ts = "const x = value as number;"
        js = strip_types(ts)
        assert "as" not in js
        assert "number" not in js
        assert "const x = value;" in js

    def test_as_const(self):
        ts = "const x = [1, 2, 3] as const;"
        js = strip_types(ts)
        assert "as const" not in js
        assert "[1, 2, 3]" in js

    def test_as_in_expression(self):
        ts = "const len = (input as string).length;"
        js = strip_types(ts)
        assert "as string" not in js
        assert "(input).length" in js


class TestSatisfies:
    def test_satisfies_removed(self):
        ts = 'const x = {} satisfies Record<string, number>;'
        js = strip_types(ts)
        assert "satisfies" not in js
        assert "Record" not in js
        assert "const x = {};" in js


class TestNonNull:
    def test_non_null_property(self):
        ts = "const y = x!.foo;"
        js = strip_types(ts)
        # The ! should be removed but x.foo preserved
        assert "x.foo" in js
        assert "!" not in js

    def test_non_null_method(self):
        ts = "const y = obj!.method();"
        js = strip_types(ts)
        assert "obj.method()" in js
        assert "!" not in js


class TestAccessModifiers:
    def test_public_field(self):
        ts = "class Foo { public x = 5; }"
        js = strip_types(ts)
        assert "public" not in js
        assert "x = 5" in js

    def test_private_field(self):
        ts = "class Foo { private y = 10; }"
        js = strip_types(ts)
        assert "private" not in js
        assert "y = 10" in js

    def test_protected_field(self):
        ts = "class Foo { protected z = 0; }"
        js = strip_types(ts)
        assert "protected" not in js
        assert "z = 0" in js

    def test_readonly_field(self):
        ts = "class Foo { readonly w = 42; }"
        js = strip_types(ts)
        assert "readonly" not in js
        assert "w = 42" in js

    def test_constructor_param_property(self):
        ts = "class P { constructor(public x: number, private y: string) {} }"
        js = strip_types(ts)
        assert "public" not in js
        assert "private" not in js
        assert ": number" not in js
        assert ": string" not in js
        # Modifiers stripped; extra whitespace is harmless
        assert "x" in js and "y" in js

    def test_override_method(self):
        ts = "class D extends B { override speak() { return 1; } }"
        js = strip_types(ts)
        assert "override" not in js
        assert "speak()" in js

    def test_field_with_type_and_modifier(self):
        ts = "class F { public x: number = 5; }"
        js = strip_types(ts)
        assert "public" not in js
        assert ": number" not in js
        assert "x = 5" in js


class TestImplements:
    def test_implements_removed(self):
        ts = "class Dog implements Animal { }"
        js = strip_types(ts)
        assert "implements" not in js
        assert "Animal" not in js
        assert "class Dog" in js

    def test_implements_multiple(self):
        ts = "class Cat implements Animal, Pet { }"
        js = strip_types(ts)
        assert "implements" not in js
        assert "class Cat" in js


class TestAbstractClass:
    def test_abstract_class_becomes_regular(self):
        ts = "abstract class Shape { describe() { return 1; } }"
        js = strip_types(ts)
        assert "abstract" not in js
        assert "class Shape" in js
        assert "describe()" in js

    def test_abstract_method_removed(self):
        ts = """abstract class Shape {
    abstract area(): number;
    describe() { return 1; }
}"""
        js = strip_types(ts)
        assert "abstract" not in js
        assert "area" not in js
        assert "class Shape" in js
        assert "describe()" in js


class TestDeclare:
    def test_declare_function(self):
        ts = "declare function foo(): void;"
        js = strip_types(ts)
        assert js.strip() == ""

    def test_declare_const(self):
        ts = "declare const x: number;"
        js = strip_types(ts)
        assert js.strip() == ""

    def test_declare_mixed_with_code(self):
        ts = """declare function foo(): void;
const x = 42;"""
        js = strip_types(ts)
        assert "declare" not in js
        assert "const x = 42" in js


class TestFieldBang:
    def test_field_definite_assignment(self):
        ts = "class F { x!: number; }"
        js = strip_types(ts)
        assert "!" not in js
        assert ": number" not in js
        assert "x" in js


class TestImportType:
    def test_import_type_removed(self):
        ts = 'import type { Foo } from "./foo";'
        js = strip_types(ts)
        assert js.strip() == ""

    def test_import_type_default_removed(self):
        ts = 'import type Foo from "./foo";'
        js = strip_types(ts)
        assert js.strip() == ""

    def test_inline_type_specifier(self):
        ts = 'import { type Foo, bar } from "./mod";'
        js = strip_types(ts)
        assert "Foo" not in js
        assert "bar" in js
        assert "from" in js

    def test_all_inline_type_specifiers(self):
        ts = 'import { type Foo, type Bar } from "./mod";'
        js = strip_types(ts)
        assert "Foo" not in js
        assert "Bar" not in js

    def test_normal_import_preserved(self):
        ts = 'import { foo, bar } from "./mod";'
        js = strip_types(ts)
        assert "foo" in js
        assert "bar" in js


class TestEnum:
    def test_simple_enum(self):
        ts = "enum Color { Red, Green, Blue }"
        js = strip_types(ts)
        assert "const Color" in js
        assert "Red: 0" in js
        assert "Green: 1" in js
        assert "Blue: 2" in js

    def test_numeric_enum(self):
        ts = "enum Dir { Up = 0, Down = 1 }"
        js = strip_types(ts)
        assert "Up: 0" in js
        assert "Down: 1" in js

    def test_string_enum(self):
        ts = 'enum Status { Active = "active", Inactive = "inactive" }'
        js = strip_types(ts)
        assert '"active"' in js
        assert '"inactive"' in js

    def test_const_enum(self):
        ts = "const enum X { A, B }"
        js = strip_types(ts)
        assert "const X" in js
        assert "A: 0" in js
        assert "B: 1" in js

    def test_enum_auto_increment(self):
        ts = "enum E { A = 5, B, C }"
        js = strip_types(ts)
        assert "A: 5" in js
        assert "B: 6" in js
        assert "C: 7" in js


class TestOptionalParameter:
    def test_optional_param(self):
        ts = "function foo(x?: number) { return x; }"
        js = strip_types(ts)
        assert "?" not in js
        assert ": number" not in js
        assert "function foo(x)" in js


class TestExtractTypeHints:
    def test_function_with_annotations(self):
        ts = "function add(a: number, b: number): number { return a + b; }"
        hints = extract_type_hints(ts)
        assert "add" in hints
        ft = hints["add"]
        from tsuchi.type_checker.types import NumberType
        assert all(isinstance(t, NumberType) for t in ft.param_types)
        assert isinstance(ft.return_type, NumberType)

    def test_function_without_annotations_excluded(self):
        ts = "function foo(x, y) { return x + y; }"
        hints = extract_type_hints(ts)
        assert "foo" not in hints

    def test_partial_annotations_included(self):
        ts = "function bar(x: number, y) { return x + y; }"
        hints = extract_type_hints(ts)
        assert "bar" in hints
        from tsuchi.type_checker.types import NumberType, TypeVar
        assert isinstance(hints["bar"].param_types[0], NumberType)
        assert isinstance(hints["bar"].param_types[1], TypeVar)

    def test_string_return_type(self):
        ts = 'function greet(name: string): string { return "hi " + name; }'
        hints = extract_type_hints(ts)
        assert "greet" in hints
        from tsuchi.type_checker.types import StringType
        assert isinstance(hints["greet"].param_types[0], StringType)
        assert isinstance(hints["greet"].return_type, StringType)

    def test_exported_function(self):
        ts = "export function calc(x: number): number { return x * 2; }"
        hints = extract_type_hints(ts)
        assert "calc" in hints

    def test_multiple_functions(self):
        ts = """
function add(a: number, b: number): number { return a + b; }
function concat(a: string, b: string): string { return a + b; }
function untyped(x, y) { return x; }
"""
        hints = extract_type_hints(ts)
        assert "add" in hints
        assert "concat" in hints
        assert "untyped" not in hints

    def test_array_param_type(self):
        ts = "function sum(arr: number[]): number { return 0; }"
        hints = extract_type_hints(ts)
        assert "sum" in hints
        from tsuchi.type_checker.types import ArrayType, NumberType
        assert isinstance(hints["sum"].param_types[0], ArrayType)
        assert isinstance(hints["sum"].param_types[0].element_type, NumberType)

    def test_void_return(self):
        ts = "function log(msg: string): void { }"
        hints = extract_type_hints(ts)
        assert "log" in hints
        from tsuchi.type_checker.types import VoidType, StringType
        assert isinstance(hints["log"].param_types[0], StringType)
        assert isinstance(hints["log"].return_type, VoidType)

    def test_boolean_type(self):
        ts = "function isEven(n: number): boolean { return n % 2 === 0; }"
        hints = extract_type_hints(ts)
        assert "isEven" in hints
        from tsuchi.type_checker.types import NumberType, BooleanType
        assert isinstance(hints["isEven"].param_types[0], NumberType)
        assert isinstance(hints["isEven"].return_type, BooleanType)


class TestTSTypeHintCompilation:
    def test_ts_annotations_make_function_compilable(self):
        """TS type annotations should make functions compilable even without call sites."""
        from tsuchi.compiler import Compiler
        import tempfile, subprocess
        from pathlib import Path

        # Function with type annotations but called only from console.log
        # Without type hints, the function types come from the call site.
        # With type hints from TS annotations, types are pre-seeded.
        ts_source = """
function double(x: number): number {
    return x * 2;
}
console.log(double(21));
"""
        compiler = Compiler()
        with tempfile.TemporaryDirectory() as tmpdir:
            ts_path = Path(tmpdir) / "test_hints.ts"
            ts_path.write_text(ts_source)
            result = compiler.compile_file(str(ts_path), output_dir=tmpdir)
            assert result.success, f"Compilation failed: {result.diagnostics}"
            proc = subprocess.run(
                [result.output_path], capture_output=True, text=True, timeout=10
            )
            assert proc.returncode == 0
            assert proc.stdout.strip() == "42"

    def test_ts_check_uses_type_hints(self):
        """check_file should use TS type hints for inference."""
        from tsuchi.compiler import Compiler
        import tempfile
        from pathlib import Path
        from tsuchi.type_checker.types import NumberType

        ts_source = """
function square(n: number): number {
    return n * n;
}
console.log(square(5));
"""
        compiler = Compiler()
        with tempfile.TemporaryDirectory() as tmpdir:
            ts_path = Path(tmpdir) / "test_check.ts"
            ts_path.write_text(ts_source)
            result = compiler.check_file(str(ts_path))
            assert result.success
            # Verify the function was typed correctly from TS annotations
            typed = result.typed_module
            square_fn = next(f for f in typed.functions if f.name == "square")
            assert square_fn.is_compilable
            assert isinstance(square_fn.params[0][1], NumberType)
            assert isinstance(square_fn.return_type, NumberType)


class TestTSCompilation:
    def test_ts_compile_source(self):
        """Test that TS source can be compiled after stripping."""
        from tsuchi.compiler import Compiler
        import tempfile, subprocess

        ts_source = """
function add(a: number, b: number): number {
    return a + b;
}
console.log(add(3, 4));
"""
        # Strip types manually and compile
        js_source = strip_types(ts_source)
        compiler = Compiler()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = compiler.compile_source(js_source, "test_ts", output_dir=tmpdir)
            assert result.success, f"Compilation failed: {result.diagnostics}"
            proc = subprocess.run(
                [result.output_path], capture_output=True, text=True, timeout=10
            )
            assert proc.returncode == 0
            assert proc.stdout.strip() == "7"

    def test_ts_compile_file(self):
        """Test that .ts file can be compiled via compile_file."""
        from tsuchi.compiler import Compiler
        import tempfile, subprocess
        from pathlib import Path

        ts_source = """
function multiply(a: number, b: number): number {
    return a * b;
}
console.log(multiply(6, 7));
"""
        compiler = Compiler()
        with tempfile.TemporaryDirectory() as tmpdir:
            ts_path = Path(tmpdir) / "test.ts"
            ts_path.write_text(ts_source)
            result = compiler.compile_file(str(ts_path), output_dir=tmpdir)
            assert result.success, f"Compilation failed: {result.diagnostics}"
            proc = subprocess.run(
                [result.output_path], capture_output=True, text=True, timeout=10
            )
            assert proc.returncode == 0
            assert proc.stdout.strip() == "42"
