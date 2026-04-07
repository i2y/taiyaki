"""Module merger: merge multiple parsed modules into a single compilation unit.

Strategy: prefix all module-local names with a module-unique prefix to avoid
name collisions, then rewrite import references to use the source module's
prefixed names.
"""

from __future__ import annotations

import re
from pathlib import Path
from copy import deepcopy

from taiyaki_aot_compiler.parser.ast_nodes import (
    JSModule, Statement, Expression, Block,
    FunctionDecl, VarDecl, ClassDecl, ExpressionStmt,
    ImportDeclaration, ExportDeclaration, ImportSpecifier,
    Identifier, CallExpr, MemberExpr,
)
from taiyaki_aot_compiler.parser.js_parser import JSParser
from taiyaki_aot_compiler.parser.module_resolver import ModuleResolver


def _module_prefix(file_path: Path) -> str:
    """Generate a unique prefix for a module from its file path.

    ./math.js → __mod_math__
    ./utils/helper.js → __mod_utils_helper__
    """
    stem = file_path.stem
    # Clean up the name to be a valid identifier part
    clean = re.sub(r'[^a-zA-Z0-9]', '_', stem)
    return f"__mod_{clean}__"


class ModuleMerger:
    """Merge multiple JS modules into a single compilation unit."""

    def __init__(self):
        self._parser = JSParser()
        self._resolver = ModuleResolver()

    def merge_modules(self, entry_file: str) -> tuple[JSModule, str, dict]:
        """Parse and merge all modules starting from entry_file.

        Returns (merged_module, merged_source, ts_type_hints).
        ts_type_hints maps prefixed function names to FunctionType for TS-annotated functions.
        """
        entry_path = Path(entry_file).resolve()
        ordered_files = self._resolver.build_dependency_graph(entry_file)

        # Parse all modules, extracting TS type hints before stripping
        parsed: dict[Path, JSModule] = {}
        sources: dict[Path, str] = {}
        ts_type_hints: dict = {}
        for file_path in ordered_files:
            source = file_path.read_text(encoding="utf-8")
            if file_path.suffix in (".ts", ".tsx"):
                from taiyaki_aot_compiler.parser.ts_stripper import strip_types, extract_type_hints
                hints = extract_type_hints(source)
                prefix = _module_prefix(file_path) if file_path != entry_path else ""
                for name, ft in hints.items():
                    ts_type_hints[prefix + name] = ft
                source = strip_types(source, tsx=(file_path.suffix == ".tsx"))
            if file_path.suffix in (".jsx", ".tsx"):
                from taiyaki_aot_compiler.parser.jsx_transformer import transform_jsx
                source = transform_jsx(source)
            parsed[file_path] = self._parser.parse(source, str(file_path))
            sources[file_path] = source

        # Collect exports from each module
        exports: dict[Path, dict[str, str]] = {}  # file → {exported_name → local_name}
        for file_path in ordered_files:
            exports[file_path] = self._collect_exports(parsed[file_path])

        # Build import resolution map for each module
        # Maps (file_path, local_import_name) → (source_file, source_local_name)
        import_map: dict[Path, dict[str, tuple[Path, str]]] = {}
        for file_path in ordered_files:
            import_map[file_path] = {}
            module = parsed[file_path]
            for stmt in module.body:
                if isinstance(stmt, ImportDeclaration):
                    try:
                        source_path = self._resolver.resolve_path(
                            stmt.source, file_path)
                    except FileNotFoundError:
                        continue
                    source_exports = exports.get(source_path, {})
                    for spec in stmt.specifiers:
                        # spec.imported is the exported name, spec.local is the local binding
                        source_local = source_exports.get(spec.imported, spec.imported)
                        import_map[file_path][spec.local] = (source_path, source_local)
                    if stmt.namespace:
                        # import * as ns → store namespace mapping
                        import_map[file_path][f"__ns__{stmt.namespace}"] = (source_path, "__namespace__")

        # Merge: rewrite names and combine
        merged_stmts: list[Statement] = []
        merged_source_lines: list[str] = []

        for file_path in ordered_files:
            module = parsed[file_path]
            prefix = _module_prefix(file_path) if file_path != entry_path else ""

            for stmt in module.body:
                # Skip import declarations (already resolved)
                if isinstance(stmt, ImportDeclaration):
                    continue

                # Unwrap export declarations
                if isinstance(stmt, ExportDeclaration):
                    if stmt.declaration is not None:
                        stmt = stmt.declaration
                    else:
                        continue  # export { ... } — names already tracked

                # Prefix function/class/var names for non-entry modules
                if prefix:
                    stmt = self._prefix_declaration(stmt, prefix)

                merged_stmts.append(stmt)

            # Add source lines for fallback
            merged_source_lines.append(f"// --- {file_path.name} ---")
            merged_source_lines.append(sources[file_path])

        # Build rewrite map and rewrite identifier references
        rewrite_map = self._build_rewrite_map(import_map, entry_path)
        if rewrite_map:
            for stmt in merged_stmts:
                self._rewrite_stmt(stmt, rewrite_map)

        merged_source = "\n".join(merged_source_lines)
        return JSModule(body=merged_stmts, source=merged_source,
                        import_rewrite_map=rewrite_map), merged_source, ts_type_hints

    def _collect_exports(self, module: JSModule) -> dict[str, str]:
        """Collect exported names from a module.

        Returns dict mapping exported_name → local_name.
        """
        result: dict[str, str] = {}
        for stmt in module.body:
            if isinstance(stmt, ExportDeclaration):
                if stmt.declaration is not None:
                    if isinstance(stmt.declaration, FunctionDecl):
                        name = stmt.declaration.name
                        if stmt.is_default:
                            result["default"] = name
                        else:
                            result[name] = name
                    elif isinstance(stmt.declaration, ClassDecl):
                        name = stmt.declaration.name
                        if stmt.is_default:
                            result["default"] = name
                        else:
                            result[name] = name
                    elif isinstance(stmt.declaration, VarDecl):
                        name = stmt.declaration.name
                        if stmt.is_default:
                            result["default"] = name
                        else:
                            result[name] = name
                for local, exported in stmt.specifiers:
                    result[exported] = local
        return result

    def _prefix_declaration(self, stmt: Statement, prefix: str) -> Statement:
        """Add module prefix to top-level declaration names."""
        if isinstance(stmt, FunctionDecl):
            new_stmt = deepcopy(stmt)
            new_stmt.name = prefix + stmt.name
            return new_stmt
        elif isinstance(stmt, ClassDecl):
            new_stmt = deepcopy(stmt)
            new_stmt.name = prefix + stmt.name
            return new_stmt
        elif isinstance(stmt, VarDecl):
            new_stmt = deepcopy(stmt)
            new_stmt.name = prefix + stmt.name
            return new_stmt
        return stmt

    def _build_rewrite_map(self, import_map: dict[Path, dict[str, tuple[Path, str]]],
                            entry_path: Path) -> dict[str, str]:
        """Build the entry module's identifier rewrite map."""
        entry_imports = import_map.get(entry_path, {})
        rewrite_map: dict[str, str] = {}
        for local_name, (source_path, source_local) in entry_imports.items():
            if local_name.startswith("__ns__"):
                continue
            prefix = _module_prefix(source_path)
            rewrite_map[local_name] = prefix + source_local
        return rewrite_map

    def _rewrite_stmt(self, stmt: Statement, rewrite_map: dict[str, str]):
        """Recursively rewrite identifiers in a statement."""
        if isinstance(stmt, ExpressionStmt):
            self._rewrite_expr(stmt.expression, rewrite_map)
        elif isinstance(stmt, FunctionDecl):
            self._rewrite_block(stmt.body, rewrite_map)
        elif isinstance(stmt, VarDecl):
            if stmt.init:
                self._rewrite_expr(stmt.init, rewrite_map)
        elif isinstance(stmt, Block):
            self._rewrite_block(stmt, rewrite_map)

    def _rewrite_block(self, block: Block, rewrite_map: dict[str, str]):
        """Rewrite identifiers in all statements of a block."""
        for stmt in block.body:
            self._rewrite_stmt(stmt, rewrite_map)

    def _rewrite_expr(self, expr: Expression, rewrite_map: dict[str, str]):
        """Recursively rewrite identifiers in an expression."""
        if isinstance(expr, Identifier):
            if expr.name in rewrite_map:
                expr.name = rewrite_map[expr.name]
        elif isinstance(expr, CallExpr):
            self._rewrite_expr(expr.callee, rewrite_map)
            for arg in expr.arguments:
                self._rewrite_expr(arg, rewrite_map)
        elif isinstance(expr, MemberExpr):
            self._rewrite_expr(expr.object, rewrite_map)
            if expr.computed:
                self._rewrite_expr(expr.property, rewrite_map)
