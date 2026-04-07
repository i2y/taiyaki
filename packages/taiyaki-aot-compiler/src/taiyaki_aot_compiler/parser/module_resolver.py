"""Module resolver: path resolution and dependency graph for ESM imports.

Resolves relative import paths, builds a dependency graph, and returns
modules in topological order for merge-before-infer compilation.
"""

from __future__ import annotations

from pathlib import Path
from collections import deque

from taiyaki_aot_compiler.parser.js_parser import JSParser
from taiyaki_aot_compiler.parser.ast_nodes import JSModule, ImportDeclaration


class ModuleResolver:
    """Resolve and order JavaScript modules based on import dependencies."""

    def __init__(self):
        self._parser = JSParser()

    def resolve_path(self, import_source: str, from_file: Path) -> Path:
        """Resolve a relative import path to an absolute file path.

        Handles:
        - './foo' → ./foo.js
        - './foo.js' → ./foo.js
        - '../utils' → ../utils.js
        """
        base_dir = from_file.parent
        target = base_dir / import_source

        # Try exact path first
        if target.exists() and target.is_file():
            return target.resolve()

        # Try adding .js extension
        with_js = target.with_suffix(".js")
        if with_js.exists():
            return with_js.resolve()

        # Try adding .ts extension
        with_ts = target.with_suffix(".ts")
        if with_ts.exists():
            return with_ts.resolve()

        # Try adding .jsx extension
        with_jsx = target.with_suffix(".jsx")
        if with_jsx.exists():
            return with_jsx.resolve()

        # Try adding .tsx extension
        with_tsx = target.with_suffix(".tsx")
        if with_tsx.exists():
            return with_tsx.resolve()

        # Try index.js in directory
        index_js = target / "index.js"
        if index_js.exists():
            return index_js.resolve()

        raise FileNotFoundError(
            f"Cannot resolve module '{import_source}' from '{from_file}'"
        )

    def collect_imports(self, module: JSModule) -> list[str]:
        """Extract all import source paths from a parsed module."""
        sources = []
        for stmt in module.body:
            if isinstance(stmt, ImportDeclaration):
                sources.append(stmt.source)
        return sources

    def build_dependency_graph(self, entry_file: str) -> list[Path]:
        """Build dependency graph starting from entry file.

        Returns modules in topological order (dependencies first).
        """
        entry_path = Path(entry_file).resolve()
        if not entry_path.exists():
            raise FileNotFoundError(f"Entry file not found: {entry_file}")

        # BFS to discover all modules
        visited: dict[Path, JSModule] = {}
        deps: dict[Path, list[Path]] = {}
        queue: deque[Path] = deque([entry_path])

        while queue:
            file_path = queue.popleft()
            if file_path in visited:
                continue

            source = file_path.read_text(encoding="utf-8")
            if file_path.suffix in (".ts", ".tsx"):
                from taiyaki_aot_compiler.parser.ts_stripper import strip_types
                source = strip_types(source, tsx=(file_path.suffix == ".tsx"))
            if file_path.suffix in (".jsx", ".tsx"):
                from taiyaki_aot_compiler.parser.jsx_transformer import transform_jsx
                source = transform_jsx(source)
            module = self._parser.parse(source, str(file_path))
            visited[file_path] = module

            import_sources = self.collect_imports(module)
            file_deps = []
            for imp_src in import_sources:
                try:
                    resolved = self.resolve_path(imp_src, file_path)
                    file_deps.append(resolved)
                    if resolved not in visited:
                        queue.append(resolved)
                except FileNotFoundError:
                    pass  # Skip unresolvable imports
            deps[file_path] = file_deps

        # Topological sort (Kahn's algorithm)
        return self._topological_sort(entry_path, deps)

    def _topological_sort(self, entry: Path,
                           deps: dict[Path, list[Path]]) -> list[Path]:
        """Topological sort of modules. Dependencies come before dependents."""
        all_nodes = set(deps.keys())
        # Count in-degree (how many modules depend on this module)
        in_degree: dict[Path, int] = {n: 0 for n in all_nodes}
        for node, node_deps in deps.items():
            for dep in node_deps:
                if dep in in_degree:
                    in_degree[dep] = in_degree.get(dep, 0)  # already init'd

        # Reverse: count how many times each node appears as a dependency
        in_degree = {n: 0 for n in all_nodes}
        reverse_deps: dict[Path, list[Path]] = {n: [] for n in all_nodes}
        for node, node_deps in deps.items():
            for dep in node_deps:
                if dep in all_nodes:
                    reverse_deps[dep].append(node)
                    in_degree[node] = in_degree.get(node, 0)

        # Actually: we want dependencies before dependents
        # A depends on B means B should come first
        # in_degree[A] = number of deps A has
        in_degree = {n: 0 for n in all_nodes}
        for node, node_deps in deps.items():
            for dep in node_deps:
                if dep in all_nodes:
                    in_degree[node] += 1

        queue: deque[Path] = deque()
        for node in all_nodes:
            if in_degree[node] == 0:
                queue.append(node)

        result: list[Path] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            # Find all nodes that depend on this one
            for dependent, dep_list in deps.items():
                if node in dep_list:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        # If not all nodes are in result, there's a cycle — just append remaining
        for node in all_nodes:
            if node not in result:
                result.append(node)

        return result
