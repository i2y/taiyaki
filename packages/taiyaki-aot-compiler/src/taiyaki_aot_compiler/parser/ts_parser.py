"""TypeScript parser using tree-sitter: CST → Tsuchi AST."""

from __future__ import annotations

import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Parser, Node

from taiyaki_aot_compiler.parser.ast_nodes import (
    TSModule, Statement, Expression, Block,
    FunctionDecl, VarDecl, ObjectDestructure, ReturnStmt, IfStmt, WhileStmt, ForStmt,
    ExpressionStmt, Parameter, InterfaceDecl,
    NumberLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    Identifier, BinaryExpr, UnaryExpr, UpdateExpr, CompareExpr,
    LogicalExpr, ConditionalExpr, CallExpr, MemberExpr, AssignExpr,
    ArrowFunction, ObjectLiteralExpr,
    TypeAnnotation, NamedType, ArrayTypeAnnotation, FunctionTypeAnnotation,
    ObjectTypeAnnotation,
    Location,
)

TS_LANGUAGE = Language(ts_ts.language_typescript())


class TSParser:
    """Parse TypeScript source into Tsuchi AST."""

    def __init__(self):
        self._parser = Parser(TS_LANGUAGE)

    def parse(self, source: str, filename: str = "<input>") -> TSModule:
        tree = self._parser.parse(source.encode("utf-8"))
        body = self._convert_children(tree.root_node)
        return TSModule(body=body, source=source)

    def _loc(self, node: Node) -> Location:
        return Location(
            line=node.start_point.row + 1,
            col=node.start_point.column,
            end_line=node.end_point.row + 1,
            end_col=node.end_point.column,
        )

    def _convert_children(self, node: Node) -> list[Statement]:
        stmts: list[Statement] = []
        for child in node.children:
            stmt = self._convert_stmt(child)
            if stmt is not None:
                stmts.append(stmt)
        return stmts

    def _convert_stmt(self, node: Node) -> Statement | None:
        t = node.type
        if t == "function_declaration":
            return self._convert_function_decl(node)
        elif t in ("lexical_declaration", "variable_declaration"):
            return self._convert_var_decl(node)
        elif t == "return_statement":
            return self._convert_return(node)
        elif t == "if_statement":
            return self._convert_if(node)
        elif t == "while_statement":
            return self._convert_while(node)
        elif t == "for_statement":
            return self._convert_for(node)
        elif t == "expression_statement":
            return self._convert_expression_stmt(node)
        elif t == "statement_block":
            return self._convert_block(node)
        elif t == "interface_declaration":
            return self._convert_interface_decl(node)
        elif t == "comment":
            return None
        elif t == "empty_statement":
            return None
        elif t == "export_statement":
            # Unwrap: export function foo() {} → function_declaration
            for child in node.children:
                stmt = self._convert_stmt(child)
                if stmt is not None:
                    return stmt
            return None
        return None

    def _convert_function_decl(self, node: Node) -> FunctionDecl:
        name = ""
        params: list[Parameter] = []
        return_type: TypeAnnotation | None = None
        body = Block()
        loc = self._loc(node)

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode()
            elif child.type == "formal_parameters":
                params = self._convert_params(child)
            elif child.type == "type_annotation":
                return_type = self._convert_type_annotation(child)
            elif child.type == "statement_block":
                body = self._convert_block(child)

        return FunctionDecl(name=name, params=params, return_type=return_type, body=body, loc=loc)

    def _convert_params(self, node: Node) -> list[Parameter]:
        params: list[Parameter] = []
        for child in node.children:
            if child.type in ("required_parameter", "optional_parameter"):
                p = self._convert_single_param(child)
                if p:
                    params.append(p)
        return params

    def _convert_single_param(self, node: Node) -> Parameter | None:
        name = ""
        type_ann: TypeAnnotation | None = None
        default: Expression | None = None

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode()
            elif child.type == "type_annotation":
                type_ann = self._convert_type_annotation(child)
            elif child.type == "=":
                pass
            elif child.type not in ("?", ",", "(", ")"):
                # Default value
                if name and type_ann is not None:
                    default = self._convert_expr(child)
                elif not name:
                    name = child.text.decode()

        if not name:
            return None
        return Parameter(name=name, type_annotation=type_ann, default=default)

    def _convert_type_annotation(self, node: Node) -> TypeAnnotation | None:
        """Convert a type_annotation node (: type) to TypeAnnotation."""
        for child in node.children:
            if child.type == ":":
                continue
            return self._convert_type_node(child)
        return None

    def _convert_type_node(self, node: Node) -> TypeAnnotation | None:
        t = node.type
        if t == "predefined_type":
            name = node.text.decode()
            return NamedType(name=name)
        elif t == "type_identifier":
            return NamedType(name=node.text.decode())
        elif t == "array_type":
            # number[]
            for child in node.children:
                if child.type not in ("[", "]"):
                    elem = self._convert_type_node(child)
                    if elem:
                        return ArrayTypeAnnotation(element_type=elem)
            return None
        elif t == "generic_type":
            # Array<number>
            type_name = None
            type_args = []
            for child in node.children:
                if child.type == "type_identifier":
                    type_name = child.text.decode()
                elif child.type == "type_arguments":
                    for arg_child in child.children:
                        if arg_child.type not in ("<", ">", ","):
                            ta = self._convert_type_node(arg_child)
                            if ta:
                                type_args.append(ta)
            if type_name == "Array" and type_args:
                return ArrayTypeAnnotation(element_type=type_args[0])
            return NamedType(name=type_name or "unknown")
        elif t == "function_type":
            # (a: number) => number
            param_types: list[TypeAnnotation] = []
            ret_type: TypeAnnotation | None = None
            for child in node.children:
                if child.type == "formal_parameters":
                    for p_child in child.children:
                        if p_child.type in ("required_parameter", "optional_parameter"):
                            for pc in p_child.children:
                                if pc.type == "type_annotation":
                                    pt = self._convert_type_annotation(pc)
                                    if pt:
                                        param_types.append(pt)
                elif child.type not in ("=>",):
                    rt = self._convert_type_node(child)
                    if rt:
                        ret_type = rt
            return FunctionTypeAnnotation(
                param_types=param_types,
                return_type=ret_type or NamedType(name="void"),
            )
        elif t == "object_type":
            return self._convert_object_type(node)
        elif t == "parenthesized_type":
            for child in node.children:
                if child.type not in ("(", ")"):
                    return self._convert_type_node(child)
        return None

    def _convert_var_decl(self, node: Node) -> VarDecl | ObjectDestructure | None:
        kind = "const"
        for child in node.children:
            if child.type in ("const", "let", "var"):
                kind = child.type
            elif child.type == "variable_declarator":
                return self._convert_variable_declarator(child, kind)
        return None

    def _convert_variable_declarator(self, node: Node, kind: str) -> VarDecl | ObjectDestructure:
        name = ""
        type_ann: TypeAnnotation | None = None
        init: Expression | None = None
        loc = self._loc(node)

        # Check for object destructuring pattern: const { x, y } = expr
        for child in node.children:
            if child.type == "object_pattern":
                return self._convert_object_destructure(child, node, kind)

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode()
            elif child.type == "type_annotation":
                type_ann = self._convert_type_annotation(child)
            elif child.type == "=":
                continue
            elif not name:
                name = child.text.decode()
            else:
                init = self._convert_expr(child)

        return VarDecl(kind=kind, name=name, type_annotation=type_ann, init=init, loc=loc)

    def _convert_object_destructure(self, pattern_node: Node, declarator_node: Node, kind: str) -> ObjectDestructure:
        """Convert object destructuring pattern: const { x, y } = expr"""
        fields: list[str] = []
        init = Expression()
        loc = self._loc(declarator_node)

        # Extract field names from object_pattern
        for child in pattern_node.children:
            if child.type == "shorthand_property_identifier_pattern":
                fields.append(child.text.decode())
            elif child.type == "pair_pattern":
                # { x: localName } - use the key name
                for pc in child.children:
                    if pc.type == "property_identifier":
                        fields.append(pc.text.decode())
                        break

        # Extract initializer from the declarator node
        found_eq = False
        for child in declarator_node.children:
            if child.type == "=":
                found_eq = True
            elif found_eq and child.type != "object_pattern":
                init = self._convert_expr(child)

        return ObjectDestructure(kind=kind, fields=fields, init=init, loc=loc)

    def _convert_return(self, node: Node) -> ReturnStmt:
        value: Expression | None = None
        for child in node.children:
            if child.type not in ("return", ";"):
                value = self._convert_expr(child)
        return ReturnStmt(value=value, loc=self._loc(node))

    def _convert_if(self, node: Node) -> IfStmt:
        condition = Expression()
        consequent = Block()
        alternate: Block | IfStmt | None = None
        loc = self._loc(node)

        # Collect condition (parenthesized_expression), consequence (statement_block),
        # and optional else_clause
        for child in node.children:
            if child.type in ("if", "(", ")", ";"):
                continue
            elif child.type == "parenthesized_expression":
                condition = self._convert_expr(self._unwrap_parens(child))
            elif child.type == "statement_block" and isinstance(consequent, Block) and not consequent.body:
                consequent = self._convert_block(child)
            elif child.type == "else_clause":
                # else_clause contains: "else" keyword + statement_block or if_statement
                for ec in child.children:
                    if ec.type == "else":
                        continue
                    elif ec.type == "if_statement":
                        alternate = self._convert_if(ec)
                    elif ec.type == "statement_block":
                        alternate = self._convert_block(ec)
                    else:
                        alternate = self._ensure_block(ec)
            elif child.type not in ("else",):
                # Fallback for condition without parens
                if isinstance(condition, Expression) and condition.__class__ == Expression:
                    condition = self._convert_expr(child)
                elif isinstance(consequent, Block) and not consequent.body:
                    consequent = self._ensure_block(child)

        return IfStmt(condition=condition, consequent=consequent, alternate=alternate, loc=loc)

    def _convert_while(self, node: Node) -> WhileStmt:
        condition = Expression()
        body = Block()
        loc = self._loc(node)

        paren = node.child_by_field_name("condition")
        if paren:
            condition = self._convert_expr(self._unwrap_parens(paren))
        else:
            children = [c for c in node.children if c.type not in ("while", "(", ")", ";")]
            if children:
                condition = self._convert_expr(children[0])

        for child in node.children:
            if child.type == "statement_block":
                body = self._convert_block(child)

        return WhileStmt(condition=condition, body=body, loc=loc)

    def _convert_for(self, node: Node) -> ForStmt:
        init_node = None
        cond_node = None
        update_node = None
        body = Block()
        loc = self._loc(node)

        # tree-sitter for_statement fields: initializer, condition, increment, body
        for child in node.children:
            if child.type in ("for", "(", ")", ";"):
                continue
            if child.type == "statement_block":
                body = self._convert_block(child)
            elif child.type in ("lexical_declaration", "variable_declaration"):
                init_node = self._convert_var_decl(child)
            elif child.type == "expression_statement":
                # Could be condition or update depending on position
                inner = self._get_inner_expr(child)
                if init_node is not None and cond_node is None:
                    cond_node = self._convert_expr(inner) if inner else None
                elif cond_node is not None:
                    update_node = self._convert_expr(inner) if inner else None
                else:
                    cond_node = self._convert_expr(inner) if inner else None
            elif child.type == "empty_statement":
                # Empty part of for (;;)
                if init_node is None:
                    init_node = None  # explicit skip
                elif cond_node is None:
                    cond_node = None
            else:
                # Remaining expression nodes
                expr = self._convert_expr(child)
                if init_node is not None and cond_node is None:
                    cond_node = expr
                elif cond_node is not None and update_node is None:
                    update_node = expr
                elif init_node is None:
                    init_node = ExpressionStmt(expression=expr)

        return ForStmt(init=init_node, condition=cond_node, update=update_node, body=body, loc=loc)

    def _convert_expression_stmt(self, node: Node) -> ExpressionStmt:
        inner = self._get_inner_expr(node)
        if inner:
            return ExpressionStmt(expression=self._convert_expr(inner), loc=self._loc(node))
        return ExpressionStmt(expression=Expression(), loc=self._loc(node))

    def _convert_block(self, node: Node) -> Block:
        stmts: list[Statement] = []
        for child in node.children:
            if child.type in ("{", "}"):
                continue
            stmt = self._convert_stmt(child)
            if stmt is not None:
                stmts.append(stmt)
        return Block(body=stmts, loc=self._loc(node))

    def _ensure_block(self, node: Node) -> Block:
        if node.type == "statement_block":
            return self._convert_block(node)
        stmt = self._convert_stmt(node)
        if stmt:
            return Block(body=[stmt], loc=self._loc(node))
        return Block()

    def _get_inner_expr(self, node: Node) -> Node | None:
        for child in node.children:
            if child.type != ";":
                return child
        return None

    def _unwrap_parens(self, node: Node) -> Node:
        if node.type == "parenthesized_expression":
            for child in node.children:
                if child.type not in ("(", ")"):
                    return self._unwrap_parens(child)
        return node

    def _convert_expr(self, node: Node) -> Expression:
        t = node.type
        loc = self._loc(node)

        if t == "number":
            text = node.text.decode()
            return NumberLiteral(value=float(text), loc=loc)

        if t == "string" or t == "template_string":
            # Remove quotes
            text = node.text.decode()
            if text.startswith('"') or text.startswith("'"):
                text = text[1:-1]
            elif text.startswith("`"):
                text = text[1:-1]
            return StringLiteral(value=text, loc=loc)

        if t == "true":
            return BooleanLiteral(value=True, loc=loc)

        if t == "false":
            return BooleanLiteral(value=False, loc=loc)

        if t == "null":
            return NullLiteral(loc=loc)

        if t == "identifier":
            return Identifier(name=node.text.decode(), loc=loc)

        if t == "parenthesized_expression":
            for child in node.children:
                if child.type not in ("(", ")"):
                    return self._convert_expr(child)
            return Expression(loc=loc)

        if t == "binary_expression":
            return self._convert_binary(node, loc)

        if t == "unary_expression":
            return self._convert_unary(node, loc)

        if t == "update_expression":
            return self._convert_update(node, loc)

        if t == "ternary_expression":
            return self._convert_ternary(node, loc)

        if t == "call_expression":
            return self._convert_call(node, loc)

        if t == "member_expression":
            return self._convert_member(node, loc)

        if t == "subscript_expression":
            return self._convert_subscript(node, loc)

        if t == "assignment_expression":
            return self._convert_assignment(node, loc)

        if t == "augmented_assignment_expression":
            return self._convert_augmented_assignment(node, loc)

        if t == "object":
            return self._convert_object_literal(node, loc)

        if t == "arrow_function":
            return self._convert_arrow_function(node, loc)

        if t == "sequence_expression":
            # (a, b) → return last
            exprs = [self._convert_expr(c) for c in node.children if c.type != ","]
            return exprs[-1] if exprs else Expression(loc=loc)

        # Fallback: try to read text as identifier
        text = node.text.decode()
        if text and text.isidentifier():
            return Identifier(name=text, loc=loc)

        return Expression(loc=loc)

    def _convert_binary(self, node: Node, loc: Location) -> Expression:
        children = [c for c in node.children if c.type not in ("(", ")")]
        if len(children) < 3:
            return Expression(loc=loc)

        left = self._convert_expr(children[0])
        op = children[1].text.decode()
        right = self._convert_expr(children[2])

        # Classify: comparison, logical, or arithmetic
        if op in ("===", "!==", "==", "!=", "<", ">", "<=", ">="):
            # Normalize == to ===, != to !==
            if op == "==":
                op = "==="
            elif op == "!=":
                op = "!=="
            return CompareExpr(op=op, left=left, right=right, loc=loc)
        elif op in ("&&", "||"):
            return LogicalExpr(op=op, left=left, right=right, loc=loc)
        else:
            return BinaryExpr(op=op, left=left, right=right, loc=loc)

    def _convert_unary(self, node: Node, loc: Location) -> Expression:
        op = ""
        operand = Expression()
        for child in node.children:
            if child.type in ("!", "-", "+", "~", "typeof", "void"):
                op = child.text.decode()
            else:
                operand = self._convert_expr(child)
        return UnaryExpr(op=op, operand=operand, prefix=True, loc=loc)

    def _convert_update(self, node: Node, loc: Location) -> Expression:
        op = ""
        operand = Expression()
        prefix = True
        children = list(node.children)
        if children and children[0].type in ("++", "--"):
            op = children[0].text.decode()
            operand = self._convert_expr(children[1]) if len(children) > 1 else Expression()
            prefix = True
        elif len(children) >= 2 and children[-1].type in ("++", "--"):
            op = children[-1].text.decode()
            operand = self._convert_expr(children[0])
            prefix = False
        return UpdateExpr(op=op, operand=operand, prefix=prefix, loc=loc)

    def _convert_ternary(self, node: Node, loc: Location) -> ConditionalExpr:
        parts = [c for c in node.children if c.type not in ("?", ":")]
        condition = self._convert_expr(parts[0]) if len(parts) > 0 else Expression()
        consequent = self._convert_expr(parts[1]) if len(parts) > 1 else Expression()
        alternate = self._convert_expr(parts[2]) if len(parts) > 2 else Expression()
        return ConditionalExpr(condition=condition, consequent=consequent, alternate=alternate, loc=loc)

    def _convert_call(self, node: Node, loc: Location) -> CallExpr:
        callee = Expression()
        args: list[Expression] = []

        for child in node.children:
            if child.type == "arguments":
                for arg in child.children:
                    if arg.type not in ("(", ")", ","):
                        args.append(self._convert_expr(arg))
            elif child.type not in ("(", ")", ",", "type_arguments"):
                callee = self._convert_expr(child)

        return CallExpr(callee=callee, arguments=args, loc=loc)

    def _convert_member(self, node: Node, loc: Location) -> MemberExpr:
        obj = Expression()
        prop = Expression()
        children = [c for c in node.children if c.type not in (".", "?.")]
        if len(children) >= 2:
            obj = self._convert_expr(children[0])
            prop_node = children[1]
            if prop_node.type == "property_identifier":
                prop = Identifier(name=prop_node.text.decode(), loc=self._loc(prop_node))
            else:
                prop = self._convert_expr(prop_node)
        return MemberExpr(object=obj, property=prop, computed=False, loc=loc)

    def _convert_subscript(self, node: Node, loc: Location) -> MemberExpr:
        obj = Expression()
        index = Expression()
        parts = [c for c in node.children if c.type not in ("[", "]")]
        if len(parts) >= 2:
            obj = self._convert_expr(parts[0])
            index = self._convert_expr(parts[1])
        return MemberExpr(object=obj, property=index, computed=True, loc=loc)

    def _convert_assignment(self, node: Node, loc: Location) -> AssignExpr:
        children = [c for c in node.children if c.type != "="]
        left = self._convert_expr(children[0]) if children else Expression()
        right = self._convert_expr(children[1]) if len(children) > 1 else Expression()
        return AssignExpr(op="=", left=left, right=right, loc=loc)

    def _convert_augmented_assignment(self, node: Node, loc: Location) -> AssignExpr:
        left = Expression()
        right = Expression()
        op = "="
        for child in node.children:
            if child.type in ("+=", "-=", "*=", "/=", "%=", "**=",
                              "&=", "|=", "^=", "<<=", ">>=", ">>>="):
                op = child.text.decode()
            elif isinstance(left, Expression) and left.__class__ == Expression:
                left = self._convert_expr(child)
            else:
                right = self._convert_expr(child)
        return AssignExpr(op=op, left=left, right=right, loc=loc)

    def _convert_arrow_function(self, node: Node, loc: Location) -> ArrowFunction:
        params: list[Parameter] = []
        body: Expression | Block = Block()
        return_type: TypeAnnotation | None = None

        for child in node.children:
            if child.type == "formal_parameters":
                params = self._convert_params(child)
            elif child.type == "identifier":
                # Single param arrow: x => x + 1
                params = [Parameter(name=child.text.decode())]
            elif child.type == "type_annotation":
                return_type = self._convert_type_annotation(child)
            elif child.type == "statement_block":
                body = self._convert_block(child)
            elif child.type == "=>":
                continue
            elif not params and child.type == "identifier":
                params = [Parameter(name=child.text.decode())]
            elif child.type not in ("(", ")", "=>", ","):
                # Expression body
                body = self._convert_expr(child)

        return ArrowFunction(params=params, body=body, return_type=return_type, loc=loc)

    def _convert_interface_decl(self, node: Node) -> InterfaceDecl:
        name = ""
        fields: list[tuple[str, TypeAnnotation]] = []
        extends: list[str] = []
        optional_fields: set[str] = set()
        loc = self._loc(node)

        for child in node.children:
            if child.type == "type_identifier":
                name = child.text.decode()
            elif child.type == "extends_type_clause":
                # Parse parent interface names
                for ec in child.children:
                    if ec.type == "type_identifier":
                        extends.append(ec.text.decode())
            elif child.type in ("object_type", "interface_body"):
                obj_ann = self._convert_object_type(child)
                if isinstance(obj_ann, ObjectTypeAnnotation):
                    fields = obj_ann.fields
                    optional_fields = obj_ann.optional_fields

        return InterfaceDecl(name=name, fields=fields, extends=extends,
                             optional_fields=optional_fields, loc=loc)

    def _convert_object_type(self, node: Node) -> ObjectTypeAnnotation:
        fields: list[tuple[str, TypeAnnotation]] = []
        optional_fields: set[str] = set()
        for child in node.children:
            if child.type == "property_signature":
                fname = ""
                ftype: TypeAnnotation | None = None
                is_optional = False
                for pc in child.children:
                    if pc.type == "property_identifier":
                        fname = pc.text.decode()
                    elif pc.type == "type_annotation":
                        ftype = self._convert_type_annotation(pc)
                    elif pc.type == "?":
                        is_optional = True
                if fname and ftype:
                    fields.append((fname, ftype))
                    if is_optional:
                        optional_fields.add(fname)
        return ObjectTypeAnnotation(fields=fields, optional_fields=optional_fields)

    def _convert_object_literal(self, node: Node, loc: Location) -> ObjectLiteralExpr:
        properties: list[tuple[str, Expression]] = []
        spreads: list[tuple[int, Expression]] = []
        for child in node.children:
            if child.type == "pair":
                key = ""
                value = Expression()
                for pc in child.children:
                    if pc.type == "property_identifier":
                        key = pc.text.decode()
                    elif pc.type == ":":
                        continue
                    elif key:
                        value = self._convert_expr(pc)
                if key:
                    properties.append((key, value))
            elif child.type == "shorthand_property_identifier":
                name = child.text.decode()
                properties.append((name, Identifier(name=name, loc=self._loc(child))))
            elif child.type == "spread_element":
                # ...expr — record position index and the spread expression
                for pc in child.children:
                    if pc.type == "...":
                        continue
                    spread_expr = self._convert_expr(pc)
                    spreads.append((len(properties), spread_expr))
                    break
        return ObjectLiteralExpr(properties=properties, spreads=spreads, loc=loc)
