"""JSX transformer: converts JSX syntax to createElement() function calls.

<div className="foo">Hello {name}</div>
→ createElement("div", {className: "foo"}, "Hello ", name)

Uses tree-sitter-javascript which natively parses JSX.
"""

from __future__ import annotations

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Parser, Node

JS_LANGUAGE = Language(ts_js.language())


def transform_jsx(source: str) -> str:
    """Transform JSX syntax in source to createElement() function calls."""
    parser = Parser(JS_LANGUAGE)
    tree = parser.parse(source.encode("utf-8"))
    src_bytes = source.encode("utf-8")
    result: list[str] = []
    _emit_node(tree.root_node, src_bytes, result)
    return "".join(result)


def _emit_node(node: Node, src: bytes, out: list[str]):
    """Recursively emit node text, transforming JSX nodes."""
    if node.type == "jsx_element":
        _transform_element(node, src, out)
        return
    if node.type == "jsx_self_closing_element":
        _transform_self_closing(node, src, out)
        return

    # Leaf node — emit its text
    if not node.children:
        out.append(node.text.decode())
        return

    # Default: preserve whitespace and recurse
    prev_end = node.start_byte
    for child in node.children:
        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out)
        prev_end = child.end_byte
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _get_tag_name(node: Node) -> str:
    """Extract tag name from jsx_opening_element or jsx_self_closing_element."""
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode()
        if child.type == "member_expression":
            return child.text.decode()
    return ""


def _is_fragment(opening: Node) -> bool:
    """Check if opening element is a fragment (<> with no tag name)."""
    return _get_tag_name(opening) == ""


def _transform_element(node: Node, src: bytes, out: list[str]):
    """Transform <Tag props>children</Tag> → createElement(Tag, props, ...children)."""
    opening = None
    children: list[Node] = []

    for child in node.children:
        if child.type == "jsx_opening_element":
            opening = child
        elif child.type == "jsx_closing_element":
            pass
        else:
            children.append(child)

    if not opening:
        return

    if _is_fragment(opening):
        # Fragment: <>...</> → createElement(Fragment, null, ...children)
        out.append("createElement(Fragment, null")
        _emit_children(children, src, out)
        out.append(")")
        return

    tag = _get_tag_name(opening)
    _emit_create_element(tag, opening, children, src, out)


def _transform_self_closing(node: Node, src: bytes, out: list[str]):
    """Transform <Tag props /> → createElement(Tag, props)."""
    tag = _get_tag_name(node)
    _emit_create_element(tag, node, [], src, out)


def _emit_create_element(tag: str, opening: Node, children: list[Node],
                          src: bytes, out: list[str]):
    """Emit createElement(tag, props, ...children)."""
    # Tag name: lowercase → string, uppercase → identifier
    if tag and tag[0].islower():
        out.append(f'createElement("{tag}"')
    else:
        out.append(f"createElement({tag}")

    # Collect props
    attrs: list[Node] = []
    spreads: list[Node] = []
    for child in opening.children:
        if child.type == "jsx_attribute":
            attrs.append(child)
        elif child.type == "jsx_expression":
            # Spread: {...props}
            spreads.append(child)

    if attrs or spreads:
        out.append(", {")
        first = True
        for attr in attrs:
            if not first:
                out.append(", ")
            first = False
            _emit_prop(attr, src, out)
        for spread in spreads:
            if not first:
                out.append(", ")
            first = False
            # {…expr} → ...expr
            for c in spread.children:
                if c.type == "spread_element":
                    out.append("...")
                    for sc in c.children:
                        if sc.type != "...":
                            _emit_node(sc, src, out)
        out.append("}")
    else:
        out.append(", null")

    # Children
    _emit_children(children, src, out)
    out.append(")")


def _emit_prop(attr: Node, src: bytes, out: list[str]):
    """Emit a JSX attribute as object property: name: value."""
    name = ""
    value = None

    for child in attr.children:
        if child.type == "property_identifier":
            name = child.text.decode()
        elif child.type == "=":
            continue
        elif child.type in ("string", "jsx_expression"):
            value = child

    out.append(name)
    if value is None:
        # Boolean prop: <input disabled /> → disabled: true
        out.append(": true")
    elif value.type == "string":
        out.append(f": {value.text.decode()}")
    elif value.type == "jsx_expression":
        out.append(": ")
        for c in value.children:
            if c.type not in ("{", "}"):
                _emit_node(c, src, out)


def _emit_children(children: list[Node], src: bytes, out: list[str]):
    """Emit JSX children as additional createElement arguments."""
    for child in children:
        if child.type == "jsx_text":
            text = child.text.decode()
            stripped = text.strip()
            if stripped:
                escaped = stripped.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                out.append(f', "{escaped}"')
        elif child.type == "jsx_expression":
            # Check for empty expression {}
            has_content = False
            for c in child.children:
                if c.type not in ("{", "}"):
                    has_content = True
                    break
            if has_content:
                out.append(", ")
                for c in child.children:
                    if c.type not in ("{", "}"):
                        _emit_node(c, src, out)
        elif child.type in ("jsx_element", "jsx_self_closing_element"):
            out.append(", ")
            _emit_node(child, src, out)
