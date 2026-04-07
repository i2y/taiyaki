"""Tests for the user-facing C FFI mechanism."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from tsuchi.parser.ffi_loader import extract_ffi_declarations, FFIInfo, FFIFunction
from tsuchi.type_checker.types import NumberType, StringType, VoidType, BooleanType, FFIStructType, OpaquePointerType


# --- Phase 1: FFI Loader unit tests ---

class TestFFILoader:
    def test_basic_ffi_extraction(self):
        source = '''
// @ffi "-lm"
declare function sqrt(x: number): number;
declare function sin(x: number): number;
'''
        info = extract_ffi_declarations(source)
        assert "sqrt" in info.functions
        assert "sin" in info.functions
        assert isinstance(info.functions["sqrt"].return_type, NumberType)
        assert isinstance(info.functions["sqrt"].param_types[0], NumberType)
        assert info.functions["sqrt"].c_name == "sqrt"
        assert "-lm" in info.link_libs

    def test_c_name_override(self):
        source = '''
// @ffi "-lmylib"
// @c_name my_greet
declare function greet(name: string): void;
'''
        info = extract_ffi_declarations(source)
        assert "greet" in info.functions
        fn = info.functions["greet"]
        assert fn.c_name == "my_greet"
        assert fn.js_name == "greet"
        assert isinstance(fn.param_types[0], StringType)
        assert isinstance(fn.return_type, VoidType)

    def test_c_source_link_spec(self):
        source = '''
// @ffi "mylib.c"
declare function add(a: number, b: number): number;
'''
        info = extract_ffi_declarations(source)
        assert "mylib.c" in info.c_sources
        assert "add" in info.functions

    def test_no_ffi_pragma_ignored(self):
        source = '''
declare function regularDecl(x: number): number;
'''
        info = extract_ffi_declarations(source)
        assert len(info.functions) == 0

    def test_multiple_ffi_groups(self):
        source = '''
// @ffi "-lm"
declare function sqrt(x: number): number;

// @ffi "wrapper.c"
declare function helper(s: string): string;
'''
        info = extract_ffi_declarations(source)
        assert "sqrt" in info.functions
        assert "helper" in info.functions
        assert "-lm" in info.link_libs
        assert "wrapper.c" in info.c_sources
        assert isinstance(info.functions["helper"].return_type, StringType)

    def test_boolean_return(self):
        source = '''
// @ffi "-lcheck"
declare function isValid(x: number): boolean;
'''
        info = extract_ffi_declarations(source)
        fn = info.functions["isValid"]
        assert isinstance(fn.return_type, BooleanType)

    def test_param_names_extracted(self):
        source = '''
// @ffi "-lm"
declare function pow(base: number, exp: number): number;
'''
        info = extract_ffi_declarations(source)
        fn = info.functions["pow"]
        assert fn.param_names == ["base", "exp"]

    def test_c_name_consumed_once(self):
        source = '''
// @ffi "-lm"
// @c_name my_sqrt
declare function sqrt(x: number): number;
declare function sin(x: number): number;
'''
        info = extract_ffi_declarations(source)
        assert info.functions["sqrt"].c_name == "my_sqrt"
        assert info.functions["sin"].c_name == "sin"  # not overridden

    def test_ffi_struct_extraction(self):
        source = '''
// @ffi "vec.c"
declare interface Vector2 {
    x: number;
    y: number;
}
declare function vec2_add(a: Vector2, b: Vector2): Vector2;
'''
        info = extract_ffi_declarations(source)
        assert "Vector2" in info.structs
        st = info.structs["Vector2"]
        assert st.fields == [("x", NumberType()), ("y", NumberType())]
        fn = info.functions["vec2_add"]
        assert isinstance(fn.param_types[0], FFIStructType)
        assert fn.param_types[0].name == "Vector2"
        assert isinstance(fn.return_type, FFIStructType)
        assert fn.return_type.name == "Vector2"

    def test_ffi_opaque_class_extraction(self):
        source = '''
// @ffi "db.c"
// @opaque
declare class Database {
    // @c_name db_open
    static open(path: string): Database;
    // @c_name db_close
    close(): void;
    // @c_name db_execute
    execute(sql: string): number;
}
'''
        info = extract_ffi_declarations(source)
        assert "Database" in info.opaque_classes
        oc = info.opaque_classes["Database"]
        assert "open" in oc.static_methods
        assert oc.static_methods["open"].c_name == "db_open"
        assert isinstance(oc.static_methods["open"].return_type, OpaquePointerType)
        assert oc.static_methods["open"].return_type.name == "Database"
        assert "close" in oc.instance_methods
        assert oc.instance_methods["close"].c_name == "db_close"
        assert "execute" in oc.instance_methods
        # Check that methods are registered in info.functions
        assert "Database.open" in info.functions
        assert "Database#close" in info.functions
        assert "Database#execute" in info.functions


# --- E2E tests ---

@pytest.fixture
def compile_and_run():
    """Helper to compile a .ts file (with optional C files) and run the result."""
    def _run(ts_source: str, c_sources: dict[str, str] | None = None,
             extra_args: list[str] | None = None):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            ts_path = tmpdir / "test_ffi.ts"
            ts_path.write_text(ts_source)

            if c_sources:
                for name, content in c_sources.items():
                    (tmpdir / name).write_text(content)

            cmd = [
                "uv", "run", "tsuchi", "compile",
                str(ts_path), "-o", str(tmpdir), "-q",
            ]
            if extra_args:
                cmd.extend(extra_args)

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
            if result.returncode != 0:
                pytest.fail(f"Compile failed: {result.stderr}\n{result.stdout}")

            binary = tmpdir / "test_ffi"
            assert binary.exists(), f"Binary not found. stdout={result.stdout} stderr={result.stderr}"

            run_result = subprocess.run(
                [str(binary)], capture_output=True, text=True, timeout=10
            )
            return run_result.stdout.strip()
    return _run


def test_e2e_libm_sqrt(compile_and_run):
    """E2E: compile .ts with @ffi "-lm" and call sqrt."""
    ts_source = '''// @ffi "-lm"
declare function sqrt(x: number): number;

function main(): number {
    return sqrt(16);
}
console.log(main());
'''
    output = compile_and_run(ts_source)
    assert output == "4"


def test_e2e_custom_c_file(compile_and_run):
    """E2E: compile .ts with @ffi pointing to a .c file."""
    ts_source = '''// @ffi "myhelper.c"
declare function add_numbers(a: number, b: number): number;

function main(): number {
    return add_numbers(3, 7);
}
console.log(main());
'''
    c_source = '''
double add_numbers(double a, double b) {
    return a + b;
}
'''
    output = compile_and_run(ts_source, c_sources={"myhelper.c": c_source})
    assert output == "10"


def test_e2e_c_name_override(compile_and_run):
    """E2E: @c_name overrides the C symbol name."""
    ts_source = '''// @ffi "mywrap.c"
// @c_name my_multiply
declare function multiply(a: number, b: number): number;

function main(): number {
    return multiply(6, 7);
}
console.log(main());
'''
    c_source = '''
double my_multiply(double a, double b) {
    return a * b;
}
'''
    output = compile_and_run(ts_source, c_sources={"mywrap.c": c_source})
    assert output == "42"


def test_e2e_string_ffi(compile_and_run):
    """E2E: FFI with string parameters."""
    ts_source = '''// @ffi "strhelper.c"
declare function get_greeting(name: string): string;

console.log(get_greeting("world"));
'''
    c_source = '''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static char buf[256];

const char* get_greeting(const char* name) {
    snprintf(buf, sizeof(buf), "Hello, %s!", name);
    return buf;
}
'''
    output = compile_and_run(ts_source, c_sources={"strhelper.c": c_source})
    assert output == "Hello, world!"


def test_e2e_void_ffi(compile_and_run):
    """E2E: FFI with void return calling a side-effect function."""
    ts_source = '''// @ffi "sideeffect.c"
declare function print_hello(): void;

print_hello();
'''
    c_source = '''
#include <stdio.h>

void print_hello(void) {
    printf("hello from C\\n");
}
'''
    output = compile_and_run(ts_source, c_sources={"sideeffect.c": c_source})
    assert output == "hello from C"


def test_e2e_cli_link_flag(compile_and_run):
    """E2E: --link flag for C file from CLI."""
    ts_source = '''// @ffi "-lm"
declare function floor(x: number): number;

function main(): number {
    return floor(3.7);
}
console.log(main());
'''
    output = compile_and_run(ts_source)
    assert output == "3"


def test_e2e_dts_sidecar():
    """E2E: .js file with .d.ts sidecar containing @ffi."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        js_path = tmpdir / "app.js"
        js_path.write_text('''
function main() {
    return add_nums(3, 4);
}
console.log(main());
''')

        dts_path = tmpdir / "app.d.ts"
        dts_path.write_text('''// @ffi "helper.c"
export declare function add_nums(a: number, b: number): number;
''')

        c_path = tmpdir / "helper.c"
        c_path.write_text('''
double add_nums(double a, double b) {
    return a + b;
}
''')

        cmd = [
            "uv", "run", "tsuchi", "compile",
            str(js_path), "-o", str(tmpdir), "-q",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent)
        )
        if result.returncode != 0:
            pytest.fail(f"Compile failed: {result.stderr}\n{result.stdout}")

        binary = tmpdir / "app"
        assert binary.exists()

        run_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=10
        )
        assert run_result.stdout.strip() == "7"


def test_e2e_ffi_struct(compile_and_run):
    """E2E: FFI struct passed by value."""
    ts_source = '''// @ffi "vec.c"
declare interface Vector2 {
    x: number;
    y: number;
}
declare function vec2_add(a: Vector2, b: Vector2): Vector2;
declare function vec2_length(v: Vector2): number;

function main(): number {
    const a: Vector2 = { x: 3, y: 0 };
    const b: Vector2 = { x: 0, y: 4 };
    const c = vec2_add(a, b);
    return vec2_length(c);
}
console.log(main());
'''
    c_source = '''
#include <math.h>

typedef struct { double x; double y; } Vector2;

Vector2 vec2_add(Vector2 a, Vector2 b) {
    Vector2 r;
    r.x = a.x + b.x;
    r.y = a.y + b.y;
    return r;
}

double vec2_length(Vector2 v) {
    return sqrt(v.x * v.x + v.y * v.y);
}
'''
    output = compile_and_run(ts_source, c_sources={"vec.c": c_source})
    assert output == "5"


def test_e2e_ffi_struct_field_access(compile_and_run):
    """E2E: Access fields of a returned FFI struct."""
    ts_source = '''// @ffi "point.c"
declare interface Point {
    x: number;
    y: number;
}
declare function make_point(x: number, y: number): Point;

function main(): number {
    const p = make_point(10, 20);
    return p.x + p.y;
}
console.log(main());
'''
    c_source = '''
typedef struct { double x; double y; } Point;

Point make_point(double x, double y) {
    Point p;
    p.x = x;
    p.y = y;
    return p;
}
'''
    output = compile_and_run(ts_source, c_sources={"point.c": c_source})
    assert output == "30"


def test_e2e_ffi_opaque_class(compile_and_run):
    """E2E: Opaque pointer class with static and instance methods."""
    ts_source = '''// @ffi "counter.c"
// @opaque
declare class Counter {
    // @c_name counter_new
    static create(initial: number): Counter;
    // @c_name counter_increment
    increment(): void;
    // @c_name counter_get
    get(): number;
    // @c_name counter_free
    destroy(): void;
}

function main(): number {
    const c = Counter.create(10);
    c.increment();
    c.increment();
    c.increment();
    const val = c.get();
    c.destroy();
    return val;
}
console.log(main());
'''
    c_source = '''
#include <stdlib.h>

typedef struct { double value; } Counter;

Counter* counter_new(double initial) {
    Counter *c = (Counter*)malloc(sizeof(Counter));
    c->value = initial;
    return c;
}

void counter_increment(Counter *c) {
    c->value += 1.0;
}

double counter_get(Counter *c) {
    return c->value;
}

void counter_free(Counter *c) {
    free(c);
}
'''
    output = compile_and_run(ts_source, c_sources={"counter.c": c_source})
    assert output == "13"
