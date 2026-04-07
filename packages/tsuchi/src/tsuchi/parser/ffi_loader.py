"""FFI declaration loader: extract @ffi-annotated declarations from .ts/.d.ts sources.

Parses TypeScript sources for `// @ffi "<link-spec>"` pragmas followed by
`declare function`, `declare interface`, or `declare class` ambient declarations,
producing FFIInfo for the pipeline.

Supports:
- `declare function` → FFI function (scalar params/returns)
- `declare interface` → FFI struct (pass by value)
- `// @opaque` + `declare class` → opaque pointer class (i8* in LLVM)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Parser, Node

from tsuchi.type_checker.types import (
    MonoType, NumberType, BooleanType, StringType, VoidType, TypeVar,
    FunctionType, FFIStructType, OpaquePointerType,
    NUMBER, BOOLEAN, STRING, VOID,
)

TS_LANGUAGE = Language(ts_ts.language_typescript())


@dataclass
class FFIFunction:
    """A single FFI-bound C function."""
    js_name: str            # JS-side function name
    c_name: str             # C symbol name (@c_name override or js_name)
    param_types: list[MonoType]
    param_names: list[str]
    return_type: MonoType
    link_spec: str          # @ffi pragma value (e.g. "-lm", "mylib.c")


@dataclass
class FFIStruct:
    """A by-value struct declared via `declare interface` under @ffi."""
    name: str
    fields: list[tuple[str, MonoType]]  # ordered (name, type) pairs


@dataclass
class FFIOpaqueClass:
    """An opaque pointer class declared via `declare class` under @ffi @opaque."""
    name: str
    static_methods: dict[str, FFIFunction]    # js_name → FFIFunction
    instance_methods: dict[str, FFIFunction]  # js_name → FFIFunction


@dataclass
class FFIInfo:
    """Collected FFI information for a compilation unit."""
    functions: dict[str, FFIFunction] = field(default_factory=dict)
    structs: dict[str, FFIStruct] = field(default_factory=dict)
    opaque_classes: dict[str, FFIOpaqueClass] = field(default_factory=dict)
    link_libs: list[str] = field(default_factory=list)
    c_sources: list[str] = field(default_factory=list)
    lib_paths: list[str] = field(default_factory=list)


def extract_ffi_declarations(source: str) -> FFIInfo:
    """Extract FFI declarations from TypeScript source with @ffi pragmas."""
    parser = Parser(TS_LANGUAGE)
    tree = parser.parse(source.encode("utf-8"))

    info = FFIInfo()
    current_ffi_link: str | None = None
    pending_c_name: str | None = None
    pending_opaque: bool = False
    link_specs_seen: set[str] = set()

    # Known struct/opaque names for resolving type references
    known_structs: dict[str, FFIStruct] = {}
    known_opaques: set[str] = set()

    root = tree.root_node
    children = list(root.children)

    for i, child in enumerate(children):
        # Detect comment pragmas
        if child.type == "comment":
            text = child.text.decode().strip()
            if text.startswith("// @ffi "):
                spec = text[len("// @ffi "):].strip().strip('"').strip("'")
                current_ffi_link = spec
                if spec not in link_specs_seen:
                    link_specs_seen.add(spec)
                    if spec.endswith(".c"):
                        info.c_sources.append(spec)
                    elif spec.startswith("-l"):
                        info.link_libs.append(spec)
                    else:
                        info.link_libs.append(spec)
            elif text.startswith("// @c_name "):
                pending_c_name = text[len("// @c_name "):].strip()
            elif text.strip() == "// @opaque":
                pending_opaque = True
            continue

        # ambient_declaration
        if child.type == "ambient_declaration" and current_ffi_link is not None:
            result = _parse_ambient_declaration(
                child, current_ffi_link, pending_c_name, pending_opaque,
                known_structs, known_opaques)
            if result is not None:
                kind, value = result
                if kind == "function":
                    info.functions[value.js_name] = value
                elif kind == "struct":
                    info.structs[value.name] = value
                    known_structs[value.name] = value
                elif kind == "opaque_class":
                    info.opaque_classes[value.name] = value
                    known_opaques.add(value.name)
                    # Register all methods as top-level FFI functions too
                    for m in value.static_methods.values():
                        info.functions[f"{value.name}.{m.js_name}"] = m
                    for m in value.instance_methods.values():
                        info.functions[f"{value.name}#{m.js_name}"] = m
            pending_c_name = None
            pending_opaque = False
            continue

        # Export-wrapped
        if child.type == "export_statement" and current_ffi_link is not None:
            for sub in child.children:
                if sub.type == "ambient_declaration":
                    result = _parse_ambient_declaration(
                        sub, current_ffi_link, pending_c_name, pending_opaque,
                        known_structs, known_opaques)
                    if result is not None:
                        kind, value = result
                        if kind == "function":
                            info.functions[value.js_name] = value
                        elif kind == "struct":
                            info.structs[value.name] = value
                            known_structs[value.name] = value
                        elif kind == "opaque_class":
                            info.opaque_classes[value.name] = value
                            known_opaques.add(value.name)
                            for m in value.static_methods.values():
                                info.functions[f"{value.name}.{m.js_name}"] = m
                            for m in value.instance_methods.values():
                                info.functions[f"{value.name}#{m.js_name}"] = m
                    pending_c_name = None
                    pending_opaque = False
            continue

        # Non-comment, non-ambient resets one-shot pragmas
        pending_c_name = None
        pending_opaque = False

    return info


def _parse_ambient_declaration(node: Node, link_spec: str, c_name_override: str | None,
                                is_opaque: bool, known_structs: dict, known_opaques: set):
    """Parse an ambient_declaration node. Returns (kind, value) or None."""
    for child in node.children:
        if child.type == "function_signature":
            fn = _parse_function_sig(child, link_spec, c_name_override,
                                      known_structs, known_opaques)
            return ("function", fn) if fn else None
        if child.type == "interface_declaration":
            struct = _parse_interface_as_struct(child, known_structs, known_opaques)
            return ("struct", struct) if struct else None
        if child.type == "class_declaration" and is_opaque:
            oc = _parse_opaque_class(child, link_spec, known_structs, known_opaques)
            return ("opaque_class", oc) if oc else None
    return None


def _parse_interface_as_struct(node: Node, known_structs: dict, known_opaques: set) -> FFIStruct | None:
    """Parse `interface Foo { x: number; y: number; }` as FFI struct."""
    name: str | None = None
    fields: list[tuple[str, MonoType]] = []

    for child in node.children:
        if child.type == "type_identifier":
            name = child.text.decode()
        elif child.type == "interface_body" or child.type == "object_type":
            for member in child.children:
                if member.type == "property_signature":
                    fname, ftype = _parse_property_signature(member, known_structs, known_opaques)
                    if fname:
                        fields.append((fname, ftype))

    if name is None:
        return None
    return FFIStruct(name=name, fields=fields)


def _parse_property_signature(node: Node, known_structs: dict, known_opaques: set) -> tuple[str, MonoType]:
    """Parse a property_signature: `x: number`."""
    fname = ""
    ftype: MonoType = NUMBER  # default to number
    for child in node.children:
        if child.type == "property_identifier":
            fname = child.text.decode()
        elif child.type == "type_annotation":
            ftype = _parse_type_annotation(child, known_structs, known_opaques)
    return fname, ftype


def _parse_opaque_class(node: Node, link_spec: str,
                         known_structs: dict, known_opaques: set) -> FFIOpaqueClass | None:
    """Parse `class Foo { static open(...): Foo; close(): void; }` as opaque class."""
    name: str | None = None
    static_methods: dict[str, FFIFunction] = {}
    instance_methods: dict[str, FFIFunction] = {}

    for child in node.children:
        if child.type == "type_identifier":
            name = child.text.decode()
        elif child.type == "class_body":
            if name:
                known_opaques.add(name)
            pending_method_c_name: str | None = None
            for member in child.children:
                if member.type == "comment":
                    text = member.text.decode().strip()
                    if text.startswith("// @c_name "):
                        pending_method_c_name = text[len("// @c_name "):].strip()
                    continue
                if member.type == "method_signature":
                    is_static, mfn = _parse_method_signature(
                        member, link_spec, pending_method_c_name,
                        known_structs, known_opaques, name)
                    if mfn:
                        if is_static:
                            static_methods[mfn.js_name] = mfn
                        else:
                            instance_methods[mfn.js_name] = mfn
                    pending_method_c_name = None
                elif member.type in ("public_field_definition", "property_signature"):
                    pending_method_c_name = None

    if name is None:
        return None
    return FFIOpaqueClass(name=name, static_methods=static_methods,
                          instance_methods=instance_methods)


def _parse_method_signature(node: Node, link_spec: str, c_name_override: str | None,
                             known_structs: dict, known_opaques: set,
                             class_name: str | None) -> tuple[bool, FFIFunction | None]:
    """Parse a method_signature. Returns (is_static, FFIFunction)."""
    name: str | None = None
    param_types: list[MonoType] = []
    param_names: list[str] = []
    return_type: MonoType = VOID
    is_static = False

    for child in node.children:
        if child.type == "identifier" or child.type == "property_identifier":
            name = child.text.decode()
        elif child.type == "formal_parameters":
            param_types, param_names = _parse_params(child, known_structs, known_opaques)
        elif child.type == "type_annotation":
            return_type = _parse_type_annotation(child, known_structs, known_opaques)
        elif child.text and child.text.decode() == "static":
            is_static = True

    if name is None:
        return False, None

    c_name = c_name_override or name
    return is_static, FFIFunction(
        js_name=name, c_name=c_name,
        param_types=param_types, param_names=param_names,
        return_type=return_type, link_spec=link_spec,
    )


def _parse_function_sig(node: Node, link_spec: str, c_name_override: str | None,
                         known_structs: dict, known_opaques: set) -> FFIFunction | None:
    """Parse function_signature: `function foo(x: number): number`."""
    name: str | None = None
    param_types: list[MonoType] = []
    param_names: list[str] = []
    return_type: MonoType = VOID

    for child in node.children:
        if child.type == "identifier":
            name = child.text.decode()
        elif child.type == "formal_parameters":
            param_types, param_names = _parse_params(child, known_structs, known_opaques)
        elif child.type == "type_annotation":
            return_type = _parse_type_annotation(child, known_structs, known_opaques)

    if name is None:
        return None

    c_name = c_name_override or name
    return FFIFunction(
        js_name=name, c_name=c_name,
        param_types=param_types, param_names=param_names,
        return_type=return_type, link_spec=link_spec,
    )


def _parse_params(node: Node, known_structs: dict, known_opaques: set) -> tuple[list[MonoType], list[str]]:
    """Parse formal_parameters → (types, names)."""
    types: list[MonoType] = []
    names: list[str] = []
    for child in node.children:
        if child.type in ("required_parameter", "optional_parameter"):
            pname = ""
            ptype: MonoType = TypeVar()
            for pc in child.children:
                if pc.type == "identifier":
                    pname = pc.text.decode()
                elif pc.type == "type_annotation":
                    ptype = _parse_type_annotation(pc, known_structs, known_opaques)
            names.append(pname)
            types.append(ptype)
    return types, names


def _parse_type_annotation(node: Node, known_structs: dict, known_opaques: set) -> MonoType:
    """Parse `: type` annotation."""
    for child in node.children:
        if child.type == ":":
            continue
        return _parse_type_node(child, known_structs, known_opaques)
    return TypeVar()


def _parse_type_node(node: Node, known_structs: dict, known_opaques: set) -> MonoType:
    """Parse a type node into MonoType."""
    t = node.type
    if t == "predefined_type":
        name = node.text.decode()
        if name == "number":
            return NUMBER
        elif name == "boolean":
            return BOOLEAN
        elif name == "string":
            return STRING
        elif name == "void":
            return VOID
        return TypeVar()
    if t == "type_identifier":
        name = node.text.decode()
        # Check if it's a known FFI struct
        if name in known_structs:
            st = known_structs[name]
            return FFIStructType(name=name, fields=dict(st.fields))
        # Check if it's a known opaque class
        if name in known_opaques:
            return OpaquePointerType(name=name)
        return TypeVar()
    return TypeVar()
