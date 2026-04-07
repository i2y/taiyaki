"""TypeScript type stripper: .ts → .js via tree-sitter-typescript.

Strips type annotations, interface declarations, and type-only constructs
while preserving all runtime code. This is a lightweight alternative to SWC
for the subset of TypeScript that Tsuchi supports.
"""

from __future__ import annotations

import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Parser, Node

TS_LANGUAGE = Language(ts_ts.language_typescript())
TSX_LANGUAGE = Language(ts_ts.language_tsx())

# Node types to remove entirely (wherever they appear as children)
_REMOVE_NODES = frozenset({
    "type_annotation",           # : number, : string, etc.
    "interface_declaration",     # interface Foo { ... }
    "type_alias_declaration",    # type Foo = ...
    "type_parameters",           # <T> on function/class definitions
    "type_arguments",            # <number> on call sites
    "implements_clause",         # implements Foo, Bar
    "accessibility_modifier",    # public, private, protected
    "override_modifier",         # override
    "readonly",                  # readonly modifier
    "ambient_declaration",       # declare function foo(): void; etc.
    "abstract_method_signature", # abstract area(): number;
})


def extract_type_hints(source: str) -> dict:
    """Extract function type annotations from TypeScript source.

    Parses the .ts source with tree-sitter-typescript and returns
    dict[str, FunctionType] for functions with at least one concrete
    type annotation. This is passed as type_stubs to the inferrer so
    that TS annotations seed type inference (faster convergence, fewer
    QuickJS fallbacks).
    """
    from tsuchi.type_checker.dts_parser import DTSParser
    from tsuchi.type_checker.types import TypeVar, VoidType

    parser = DTSParser()
    all_hints = parser.parse(source)

    # Keep functions where at least one type was concretely annotated.
    # Exclude fully generic signatures (all params AND return are TypeVar)
    # since shared TypeVar semantics conflict with multi-pass inference;
    # those rely on call-site inference + monomorphization instead.
    from tsuchi.type_checker.types import ArrayType as _AT
    def _is_all_typevar(ft):
        """Check if a function signature is fully generic (no concrete types)."""
        for t in ft.param_types:
            if isinstance(t, _AT) and isinstance(t.element_type, TypeVar):
                continue  # T[] — generic array param
            if isinstance(t, TypeVar):
                continue
            return False  # Has at least one concrete type
        if isinstance(ft.return_type, TypeVar):
            return True
        return False

    return {
        name: ft for name, ft in all_hints.items()
        if (any(not isinstance(t, TypeVar) for t in ft.param_types)
            or not isinstance(ft.return_type, (TypeVar, VoidType)))
        and not _is_all_typevar(ft)
    }


def strip_types(source: str, tsx: bool = False) -> str:
    """Strip TypeScript type annotations from source, returning plain JavaScript.

    If tsx=True, uses the TSX grammar which supports JSX syntax in .tsx files.
    """
    lang = TSX_LANGUAGE if tsx else TS_LANGUAGE
    parser = Parser(lang)
    tree = parser.parse(source.encode("utf-8"))
    src_bytes = source.encode("utf-8")
    result: list[str] = []
    _emit_node(tree.root_node, src_bytes, result)
    return "".join(result)


def _emit_node(node: Node, src: bytes, out: list[str]):
    """Recursively emit node text, skipping type-annotation nodes."""
    # Skip entire node if it's a type-only construct
    if node.type in _REMOVE_NODES:
        return

    if not node.children:
        # Leaf node — emit its text
        out.append(node.text.decode())
        return

    # --- Special handlers ---

    # Parameters: strip type annotation, ?, accessibility_modifier, readonly, !
    if node.type in ("required_parameter", "optional_parameter"):
        _emit_parameter(node, src, out)
        return

    # Type assertions: emit only the expression (first child)
    if node.type in ("as_expression", "satisfies_expression"):
        _emit_node(node.children[0], src, out)
        return

    # Non-null assertion: emit only the expression, drop trailing !
    if node.type == "non_null_expression":
        _emit_node(node.children[0], src, out)
        return

    # Abstract class: emit as regular class, skip 'abstract' keyword
    if node.type == "abstract_class_declaration":
        _emit_children_skip(node, src, out, {"abstract"})
        return

    # Class field: strip accessibility_modifier, readonly, !, type_annotation
    if node.type == "public_field_definition":
        _emit_children_skip(node, src, out,
                            {"accessibility_modifier", "readonly", "!", "type_annotation"})
        return

    # import statement: handle `import type` and inline type specifiers
    if node.type == "import_statement":
        if _is_type_only_import(node):
            return  # Remove entire type-only import
        _emit_import_statement(node, src, out)
        return

    # Enum: transform to const object
    if node.type == "enum_declaration":
        _emit_enum(node, src, out)
        return

    # --- Default: emit children preserving whitespace ---
    prev_end = node.start_byte
    for child in node.children:
        if child.type in _REMOVE_NODES:
            prev_end = child.end_byte
            continue

        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out)
        prev_end = child.end_byte

    # Trailing text after last child
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _emit_parameter(node: Node, src: bytes, out: list[str]):
    """Emit a TS parameter, stripping type annotation, ?, modifiers, and !."""
    _PARAM_SKIP = {"type_annotation", "?", "accessibility_modifier", "readonly", "!"}
    prev_end = node.start_byte
    for child in node.children:
        if child.type in _PARAM_SKIP:
            prev_end = child.end_byte
            continue
        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out)
        prev_end = child.end_byte
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _emit_children_skip(node: Node, src: bytes, out: list[str],
                         skip_types: set[str]):
    """Emit children of node, skipping those whose type is in skip_types."""
    prev_end = node.start_byte
    for child in node.children:
        if child.type in skip_types or child.type in _REMOVE_NODES:
            prev_end = child.end_byte
            continue
        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out)
        prev_end = child.end_byte
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _is_type_only_import(node: Node) -> bool:
    """Check if this is `import type { ... } from '...'`."""
    children = node.children
    # Structure: import type import_clause from string ;
    for i, child in enumerate(children):
        if child.type == "import" and i == 0:
            continue
        if child.type == "type" and i == 1:
            return True
        break
    return False


def _emit_import_statement(node: Node, src: bytes, out: list[str]):
    """Emit import statement, filtering out inline type specifiers."""
    prev_end = node.start_byte
    for child in node.children:
        if child.type == "import_clause":
            gap = src[prev_end:child.start_byte].decode()
            out.append(gap)
            _emit_import_clause(child, src, out)
            prev_end = child.end_byte
            continue
        if child.type in _REMOVE_NODES:
            prev_end = child.end_byte
            continue
        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out)
        prev_end = child.end_byte
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _emit_import_clause(node: Node, src: bytes, out: list[str]):
    """Emit import clause, delegating to named_imports handler."""
    prev_end = node.start_byte
    for child in node.children:
        if child.type == "named_imports":
            gap = src[prev_end:child.start_byte].decode()
            out.append(gap)
            _emit_named_imports(child, src, out)
            prev_end = child.end_byte
            continue
        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out)
        prev_end = child.end_byte
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _has_type_keyword(specifier: Node) -> bool:
    """Check if an import_specifier has a `type` child (inline type specifier)."""
    return any(c.type == "type" for c in specifier.children)


def _emit_named_imports(node: Node, src: bytes, out: list[str]):
    """Emit { foo, bar } but filter out type-only specifiers like { type Foo, bar }."""
    # Collect non-type specifiers
    specifiers = []
    for child in node.children:
        if child.type == "import_specifier" and not _has_type_keyword(child):
            specifiers.append(child)

    # Rebuild the named imports
    out.append("{ ")
    for i, spec in enumerate(specifiers):
        if i > 0:
            out.append(", ")
        _emit_node(spec, src, out)
    out.append(" }")


def _emit_enum(node: Node, src: bytes, out: list[str]):
    """Transform enum declaration to const object.

    enum Color { Red, Green, Blue }
    → const Color = { Red: 0, Green: 1, Blue: 2 };
    """
    name = None
    members: list[tuple[str, str]] = []

    for child in node.children:
        if child.type == "identifier":
            name = child.text.decode()
        elif child.type == "enum_body":
            counter = 0
            for member in child.children:
                if member.type == "property_identifier":
                    members.append((member.text.decode(), str(counter)))
                    counter += 1
                elif member.type == "enum_assignment":
                    member_name = None
                    member_value = None
                    for mc in member.children:
                        if mc.type == "property_identifier":
                            member_name = mc.text.decode()
                        elif mc.type not in ("=", ","):
                            member_value = mc.text.decode()
                    if member_name:
                        members.append((member_name, member_value or str(counter)))
                        try:
                            counter = int(member_value) + 1
                        except (ValueError, TypeError):
                            counter += 1

    if name:
        pairs = ", ".join(f"{m}: {v}" for m, v in members)
        out.append(f"const {name} = {{ {pairs} }}")
