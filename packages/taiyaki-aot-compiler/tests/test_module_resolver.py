"""Tests for module resolver: path resolution and dependency ordering."""

import pytest
import tempfile
from pathlib import Path
from taiyaki_aot_compiler.parser.module_resolver import ModuleResolver


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestPathResolution:
    def test_resolve_relative_js(self, tmpdir):
        (tmpdir / "main.js").write_text("import { add } from './math.js';\n")
        (tmpdir / "math.js").write_text("export function add(a, b) { return a + b; }\n")

        resolver = ModuleResolver()
        result = resolver.resolve_path("./math.js", tmpdir / "main.js")
        assert result == (tmpdir / "math.js").resolve()

    def test_resolve_without_extension(self, tmpdir):
        (tmpdir / "main.js").write_text("import { add } from './math';\n")
        (tmpdir / "math.js").write_text("export function add(a, b) { return a + b; }\n")

        resolver = ModuleResolver()
        result = resolver.resolve_path("./math", tmpdir / "main.js")
        assert result == (tmpdir / "math.js").resolve()

    def test_resolve_not_found(self, tmpdir):
        (tmpdir / "main.js").write_text("")

        resolver = ModuleResolver()
        with pytest.raises(FileNotFoundError):
            resolver.resolve_path("./nonexistent", tmpdir / "main.js")


class TestDependencyGraph:
    def test_single_import(self, tmpdir):
        (tmpdir / "main.js").write_text(
            "import { add } from './math.js';\nconsole.log(add(1, 2));\n"
        )
        (tmpdir / "math.js").write_text(
            "export function add(a, b) { return a + b; }\n"
        )

        resolver = ModuleResolver()
        order = resolver.build_dependency_graph(str(tmpdir / "main.js"))

        # math.js should come before main.js
        paths = [p.name for p in order]
        assert "math.js" in paths
        assert "main.js" in paths
        assert paths.index("math.js") < paths.index("main.js")

    def test_chain_dependency(self, tmpdir):
        (tmpdir / "main.js").write_text(
            "import { greet } from './greet.js';\nconsole.log(greet());\n"
        )
        (tmpdir / "greet.js").write_text(
            "import { name } from './config.js';\n"
            "export function greet() { return 'Hello ' + name; }\n"
        )
        (tmpdir / "config.js").write_text(
            "export const name = 'World';\n"
        )

        resolver = ModuleResolver()
        order = resolver.build_dependency_graph(str(tmpdir / "main.js"))

        paths = [p.name for p in order]
        assert paths.index("config.js") < paths.index("greet.js")
        assert paths.index("greet.js") < paths.index("main.js")

    def test_no_imports(self, tmpdir):
        (tmpdir / "main.js").write_text("console.log(42);\n")

        resolver = ModuleResolver()
        order = resolver.build_dependency_graph(str(tmpdir / "main.js"))
        assert len(order) == 1
        assert order[0].name == "main.js"


class TestCollectImports:
    def test_named_imports(self, tmpdir):
        from taiyaki_aot_compiler.parser.js_parser import JSParser
        source = "import { foo, bar } from './utils.js';\n"
        parser = JSParser()
        module = parser.parse(source)

        resolver = ModuleResolver()
        imports = resolver.collect_imports(module)
        assert imports == ["./utils.js"]
