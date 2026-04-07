"""Tests for module merger: AST merging with name prefixing."""

import pytest
import tempfile
from pathlib import Path
from tsuchi.parser.module_merger import ModuleMerger, _module_prefix
from tsuchi.parser.ast_nodes import FunctionDecl, ExpressionStmt


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestModulePrefix:
    def test_simple_name(self):
        assert _module_prefix(Path("math.js")) == "__mod_math__"

    def test_nested_name(self):
        assert _module_prefix(Path("utils/helper.js")) == "__mod_helper__"


class TestMerger:
    def test_simple_merge(self, tmpdir):
        (tmpdir / "math.js").write_text(
            "export function add(a, b) { return a + b; }\n"
        )
        (tmpdir / "main.js").write_text(
            "import { add } from './math.js';\n"
            "console.log(add(1, 2));\n"
        )

        merger = ModuleMerger()
        merged, source, _aliases = merger.merge_modules(str(tmpdir / "main.js"))

        # Check that the merged module has the prefixed function
        func_names = [s.name for s in merged.body if isinstance(s, FunctionDecl)]
        assert "__mod_math__add" in func_names

        # Check that the entry statement references the prefixed name
        expr_stmts = [s for s in merged.body if isinstance(s, ExpressionStmt)]
        assert len(expr_stmts) > 0

    def test_merge_two_modules(self, tmpdir):
        (tmpdir / "a.js").write_text(
            "export function fa(x) { return x + 1; }\n"
        )
        (tmpdir / "b.js").write_text(
            "export function fb(x) { return x * 2; }\n"
        )
        (tmpdir / "main.js").write_text(
            "import { fa } from './a.js';\n"
            "import { fb } from './b.js';\n"
            "console.log(fa(fb(3)));\n"
        )

        merger = ModuleMerger()
        merged, _, _aliases = merger.merge_modules(str(tmpdir / "main.js"))

        func_names = [s.name for s in merged.body if isinstance(s, FunctionDecl)]
        assert "__mod_a__fa" in func_names
        assert "__mod_b__fb" in func_names

    def test_alias_import(self, tmpdir):
        (tmpdir / "math.js").write_text(
            "export function add(a, b) { return a + b; }\n"
        )
        (tmpdir / "main.js").write_text(
            "import { add as sum } from './math.js';\n"
            "console.log(sum(1, 2));\n"
        )

        merger = ModuleMerger()
        merged, _, _aliases = merger.merge_modules(str(tmpdir / "main.js"))

        # The function should be prefixed
        func_names = [s.name for s in merged.body if isinstance(s, FunctionDecl)]
        assert "__mod_math__add" in func_names

    def test_default_export(self, tmpdir):
        (tmpdir / "greet.js").write_text(
            "export default function greet() { return 42; }\n"
        )
        (tmpdir / "main.js").write_text(
            "import greet from './greet.js';\n"
            "console.log(greet());\n"
        )

        merger = ModuleMerger()
        merged, _, _aliases = merger.merge_modules(str(tmpdir / "main.js"))

        func_names = [s.name for s in merged.body if isinstance(s, FunctionDecl)]
        assert "__mod_greet__greet" in func_names
