"""Parse .d.ts type stub files to extract function type signatures."""

from __future__ import annotations

import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Parser, Node

from tsuchi.type_checker.types import (
    MonoType, NumberType, BooleanType, StringType, VoidType, NullType,
    TypeVar, FunctionType, ArrayType, ObjectType,
    NUMBER, BOOLEAN, STRING, VOID, NULL,
)

TS_LANGUAGE = Language(ts_ts.language_typescript())


class DTSParser:
    """Parse .d.ts files and extract function type signatures."""

    def __init__(self):
        self._parser = Parser(TS_LANGUAGE)

    def parse(self, source: str) -> dict[str, FunctionType]:
        """Parse .d.ts source and return {function_name: FunctionType}."""
        tree = self._parser.parse(source.encode("utf-8"))
        result: dict[str, FunctionType] = {}
        self._collect_signatures(tree.root_node, result)
        return result

    def parse_file(self, filepath: str) -> dict[str, FunctionType]:
        """Parse a .d.ts file and return {function_name: FunctionType}."""
        with open(filepath, encoding="utf-8") as f:
            return self.parse(f.read())

    def _collect_signatures(self, node: Node, result: dict[str, FunctionType]):
        """Walk the AST and collect function signatures."""
        for child in node.children:
            if child.type == "export_statement":
                self._collect_signatures(child, result)
            elif child.type == "function_signature":
                name, ft = self._parse_function_signature(child)
                if name and ft:
                    result[name] = ft
            elif child.type == "function_declaration":
                name, ft = self._parse_function_signature(child)
                if name and ft:
                    result[name] = ft

    def _parse_function_signature(self, node: Node) -> tuple[str | None, FunctionType | None]:
        """Parse a function_signature or function_declaration node."""
        name: str | None = None
        param_types: list[MonoType] = []
        return_type: MonoType = VOID

        # Collect generic type parameter names (e.g., <T, U>) and map to shared TypeVars
        self._generic_type_vars: dict[str, TypeVar] = {}
        for child in node.children:
            if child.type == "type_parameters":
                for tp_child in child.children:
                    if tp_child.type == "type_parameter":
                        for id_node in tp_child.children:
                            if id_node.type == "type_identifier":
                                tp_name = id_node.text.decode()
                                self._generic_type_vars[tp_name] = TypeVar()

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode()
            elif child.type == "formal_parameters":
                param_types = self._parse_params(child)
            elif child.type == "type_annotation":
                return_type = self._parse_type_annotation(child)

        self._generic_type_vars = {}  # clear after use

        if name is None:
            return None, None
        return name, FunctionType(param_types, return_type)

    def _parse_params(self, node: Node) -> list[MonoType]:
        """Parse formal_parameters and extract parameter types."""
        types: list[MonoType] = []
        for child in node.children:
            if child.type in ("required_parameter", "optional_parameter"):
                pt = self._parse_param_type(child)
                types.append(pt)
        return types

    def _parse_param_type(self, node: Node) -> MonoType:
        """Extract the type from a parameter node."""
        for child in node.children:
            if child.type == "type_annotation":
                return self._parse_type_annotation(child)
        return TypeVar()

    def _parse_type_annotation(self, node: Node) -> MonoType:
        """Parse a type_annotation node (: type)."""
        for child in node.children:
            if child.type == ":":
                continue
            return self._parse_type_node(child)
        return TypeVar()

    def _parse_type_node(self, node: Node) -> MonoType:
        """Parse a type node into a MonoType."""
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
            elif name == "null":
                return NULL
            return TypeVar()

        if t == "type_identifier":
            # Reuse shared TypeVar for generic type parameters (T, U, etc.)
            id_name = node.text.decode()
            generic_vars = getattr(self, '_generic_type_vars', {})
            if id_name in generic_vars:
                return generic_vars[id_name]
            return TypeVar()

        if t == "array_type":
            for child in node.children:
                if child.type not in ("[", "]"):
                    elem = self._parse_type_node(child)
                    return ArrayType(elem)
            return ArrayType(TypeVar())

        if t == "generic_type":
            type_name = None
            type_args: list[MonoType] = []
            for child in node.children:
                if child.type == "type_identifier":
                    type_name = child.text.decode()
                elif child.type == "type_arguments":
                    for arg_child in child.children:
                        if arg_child.type not in ("<", ">", ","):
                            type_args.append(self._parse_type_node(arg_child))
            if type_name == "Array" and type_args:
                return ArrayType(type_args[0])
            return TypeVar()

        if t == "object_type":
            return self._parse_object_type(node)

        if t == "parenthesized_type":
            for child in node.children:
                if child.type not in ("(", ")"):
                    return self._parse_type_node(child)

        return TypeVar()

    def _parse_object_type(self, node: Node) -> ObjectType:
        """Parse { x: number; y: string } into ObjectType."""
        fields: dict[str, MonoType] = {}
        for child in node.children:
            if child.type == "property_signature":
                fname = ""
                ftype: MonoType = TypeVar()
                for pc in child.children:
                    if pc.type == "property_identifier":
                        fname = pc.text.decode()
                    elif pc.type == "type_annotation":
                        ftype = self._parse_type_annotation(pc)
                if fname:
                    fields[fname] = ftype
        return ObjectType(fields=fields)
