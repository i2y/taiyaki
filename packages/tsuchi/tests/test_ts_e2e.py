"""End-to-end tests for TypeScript compilation.

Each test: TS source → compile_file → standalone binary → run → check stdout.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from tsuchi.compiler import Compiler, CompileResult


def _compile_ts_and_run(ts_source: str) -> str:
    """TS source → compile_file → binary → run → stdout."""
    compiler = Compiler()
    with tempfile.TemporaryDirectory() as tmpdir:
        ts_path = Path(tmpdir) / "test_mod.ts"
        ts_path.write_text(ts_source)
        result = compiler.compile_file(str(ts_path), output_dir=tmpdir)
        assert result.success, f"Compilation failed:\n{result.diagnostics}"
        proc = subprocess.run(
            [result.output_path], capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0, f"Runtime error:\n{proc.stderr}"
        return proc.stdout


def _compile_ts_file(ts_source: str) -> CompileResult:
    """TS source → compile_file → CompileResult (compile only, no run)."""
    compiler = Compiler()
    with tempfile.TemporaryDirectory() as tmpdir:
        ts_path = Path(tmpdir) / "test_mod.ts"
        ts_path.write_text(ts_source)
        return compiler.compile_file(str(ts_path), output_dir=tmpdir)


# ═══════════════════════════════════════════════════
#  1. Basic types
# ═══════════════════════════════════════════════════

class TestBasicTypes:
    def test_number_arithmetic(self):
        out = _compile_ts_and_run("""
function add(a: number, b: number): number {
    return a + b;
}
function mul(a: number, b: number): number {
    return a * b;
}
console.log(add(10, 32));
console.log(mul(6, 7));
""")
        lines = out.strip().splitlines()
        assert lines[0] == "42"
        assert lines[1] == "42"

    def test_string_concat(self):
        out = _compile_ts_and_run("""
function greet(name: string): string {
    return "Hello, " + name + "!";
}
console.log(greet("TypeScript"));
""")
        assert out.strip() == "Hello, TypeScript!"

    def test_boolean_branch(self):
        out = _compile_ts_and_run("""
function isPositive(n: number): boolean {
    return n > 0;
}
console.log(isPositive(5));
console.log(isPositive(-3));
""")
        lines = out.strip().splitlines()
        assert lines[0] == "true"
        assert lines[1] == "false"

    def test_void_function(self):
        out = _compile_ts_and_run("""
function sayHello(): void {
    console.log("hello");
}
sayHello();
""")
        assert out.strip() == "hello"

    def test_multiple_params(self):
        out = _compile_ts_and_run("""
function calc(a: number, b: number, c: number): number {
    return a * b + c;
}
console.log(calc(5, 8, 2));
""")
        assert out.strip() == "42"


# ═══════════════════════════════════════════════════
#  2. Type inference integration
# ═══════════════════════════════════════════════════

class TestTypeInferenceIntegration:
    def test_annotations_without_call_site(self):
        """TS annotations should make functions compilable even without direct call sites."""
        result = _compile_ts_file("""
function square(n: number): number {
    return n * n;
}
console.log(square(7));
""")
        assert result.success
        assert "square" in result.native_funcs

    def test_partial_annotations_with_call_site(self):
        """Partially annotated params + call site should work together."""
        out = _compile_ts_and_run("""
function add(a: number, b): number {
    return a + b;
}
console.log(add(20, 22));
""")
        assert out.strip() == "42"

    def test_annotations_match_call_site(self):
        """Annotations and call-site inference should agree."""
        out = _compile_ts_and_run("""
function double(x: number): number {
    return x * 2;
}
console.log(double(21));
""")
        assert out.strip() == "42"

    def test_typed_variable_with_call_init(self):
        """Top-level let with type annotation and function call initializer."""
        out = _compile_ts_and_run("""
function double(x: number): number {
    return x * 2;
}
let result: number = double(21);
console.log(result);
""")
        assert out.strip() == "42"

    def test_unannotated_inferred_from_call_site(self):
        """Functions without annotations should still compile via call-site inference."""
        out = _compile_ts_and_run("""
function add(a, b) {
    return a + b;
}
console.log(add(35, 7));
""")
        assert out.strip() == "42"


# ═══════════════════════════════════════════════════
#  3. TS syntax stripping + compilation
# ═══════════════════════════════════════════════════

class TestTSSyntaxStrip:
    def test_interface_stripped(self):
        out = _compile_ts_and_run("""
interface Point {
    x: number;
    y: number;
}

function dist(px: number, py: number): number {
    return px + py;
}
console.log(dist(30, 12));
""")
        assert out.strip() == "42"

    def test_type_alias_stripped(self):
        out = _compile_ts_and_run("""
type ID = number;
type Name = string;

function identity(x: number): number {
    return x;
}
console.log(identity(42));
""")
        assert out.strip() == "42"

    def test_enum_compiles(self):
        """Enum member access should work at runtime."""
        out = _compile_ts_and_run("""
enum Color {
    Red,
    Green,
    Blue
}

function getColor(c: number): number {
    return c;
}
console.log(getColor(Color.Green));
""")
        assert out.strip() == "1"

    def test_generic_function_single_type(self):
        """Generic <T> should be stripped, function works with one concrete type."""
        out = _compile_ts_and_run("""
function identity<T>(x: number): number {
    return x;
}
console.log(identity<number>(42));
""")
        assert out.strip() == "42"

    def test_generic_function_monomorphized(self):
        """Generic function called with different types → monomorphization."""
        out = _compile_ts_and_run("""
function identity<T>(x: T): T {
    return x;
}
console.log(identity<number>(42));
console.log(identity<string>("hello"));
console.log(identity<boolean>(true));
""")
        lines = out.strip().splitlines()
        assert lines[0] == "42"
        assert lines[1] == "hello"
        assert lines[2] == "true"

    def test_generic_array_function(self):
        """Generic function with array parameter, called with different element types."""
        out = _compile_ts_and_run("""
function first<T>(arr: T[]): T {
    return arr[0];
}
console.log(first<number>([10, 20, 30]));
console.log(first<string>(["a", "b", "c"]));
""")
        lines = out.strip().splitlines()
        assert lines[0] == "10"
        assert lines[1] == "a"

    def test_as_assertion_stripped(self):
        out = _compile_ts_and_run("""
function convert(x: number): number {
    let y = x as number;
    return y * 2;
}
console.log(convert(21));
""")
        assert out.strip() == "42"

    def test_access_modifiers_stripped(self):
        """public/private modifiers should be stripped, class compiles."""
        result = _compile_ts_file("""
class Counter {
    public count: number;
    constructor() {
        this.count = 0;
    }
    public increment(): void {
        this.count = this.count + 1;
    }
}
let c = new Counter();
c.increment();
c.increment();
console.log(c.count);
""")
        # Class compilation may use QuickJS fallback — that's OK,
        # the key is that it compiles successfully
        assert result.success


# ═══════════════════════════════════════════════════
#  4. Complex programs
# ═══════════════════════════════════════════════════

class TestComplexPrograms:
    def test_multiple_functions_calling_each_other(self):
        out = _compile_ts_and_run("""
function add(a: number, b: number): number {
    return a + b;
}
function double(x: number): number {
    return add(x, x);
}
function quadruple(x: number): number {
    return double(double(x));
}
console.log(quadruple(10));
console.log(add(double(5), double(6)));
""")
        lines = out.strip().splitlines()
        assert lines[0] == "40"
        assert lines[1] == "22"

    def test_array_operations(self):
        out = _compile_ts_and_run("""
function sum(arr: number[]): number {
    let total = 0;
    let i = 0;
    while (i < arr.length) {
        total = total + arr[i];
        i = i + 1;
    }
    return total;
}
console.log(sum([10, 20, 12]));
""")
        assert out.strip() == "42"

    def test_typed_array_variable(self):
        """Top-level let with array type annotation and array literal initializer."""
        out = _compile_ts_and_run("""
function sum(arr: number[]): number {
    let total = 0;
    let i = 0;
    while (i < arr.length) {
        total = total + arr[i];
        i = i + 1;
    }
    return total;
}
let nums: number[] = [10, 20, 12];
console.log(sum(nums));
""")
        assert out.strip() == "42"

    def test_while_loop_with_branches(self):
        out = _compile_ts_and_run("""
function countEven(n: number): number {
    let count: number = 0;
    let i: number = 0;
    while (i <= n) {
        if (i - Math.floor(i / 2) * 2 == 0) {
            count = count + 1;
        }
        i = i + 1;
    }
    return count;
}
console.log(countEven(9));
""")
        assert out.strip() == "5"

    def test_recursive_function(self):
        out = _compile_ts_and_run("""
function factorial(n: number): number {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}
console.log(factorial(6));
""")
        assert out.strip() == "720"


# ═══════════════════════════════════════════════════
#  5. Compile summary with TS
# ═══════════════════════════════════════════════════

class TestCompileSummary:
    def test_native_and_fallback_lists(self):
        """compile_file on .ts should populate native_funcs/fallback_funcs."""
        result = _compile_ts_file("""
function add(a: number, b: number): number {
    return a + b;
}
function greet(name: string): string {
    return "Hi " + name;
}
console.log(add(1, 2));
console.log(greet("TS"));
""")
        assert result.success
        assert "add" in result.native_funcs
        assert "greet" in result.native_funcs
