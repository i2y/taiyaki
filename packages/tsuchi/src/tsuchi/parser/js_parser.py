"""JavaScript parser using tree-sitter: CST → Tsuchi AST."""

from __future__ import annotations

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Parser, Node

from tsuchi.parser.ast_nodes import (
    JSModule, Statement, Expression, Block,
    FunctionDecl, VarDecl, ObjectDestructure, ArrayDestructure, ReturnStmt, IfStmt, WhileStmt, DoWhileStmt, ForStmt,
    ForOfStmt, ForInStmt, ExpressionStmt, BreakStmt, ContinueStmt, LabeledStmt, Parameter,
    SwitchStmt, SwitchCase,
    ClassDecl, ClassField, MethodDecl, NewExpr, ThisExpr, SuperCall, ThrowStmt, TryCatchStmt,
    NumberLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    Identifier, BinaryExpr, UnaryExpr, UpdateExpr, CompareExpr,
    LogicalExpr, ConditionalExpr, CallExpr, MemberExpr, AssignExpr,
    ArrowFunction, AwaitExpr, ObjectLiteralExpr, ArrayLiteral, SpreadElement, SequenceExpr, TemplateLiteral,
    Location,
    ImportDeclaration, ImportSpecifier, ExportDeclaration,
)

JS_LANGUAGE = Language(ts_js.language())


class JSParser:
    """Parse JavaScript source into Tsuchi AST."""

    def __init__(self):
        self._parser = Parser(JS_LANGUAGE)

    def parse(self, source: str, filename: str = "<input>") -> JSModule:
        tree = self._parser.parse(source.encode("utf-8"))
        if tree.root_node.has_error:
            errors = self._find_error_nodes(tree.root_node, source, filename)
            if errors:
                # Report but don't abort — let downstream phases handle it
                import sys
                for msg in errors:
                    print(msg, file=sys.stderr)
        body = self._convert_children(tree.root_node)
        return JSModule(body=body, source=source)

    def _find_error_nodes(self, node, source: str, filename: str) -> list[str]:
        """Find ERROR/MISSING nodes and return human-readable messages."""
        errors: list[str] = []
        self._collect_errors(node, source, filename, errors)
        return errors

    def _collect_errors(self, node, source: str, filename: str, errors: list[str]):
        if node.type == "ERROR" or node.is_missing:
            line = node.start_point.row + 1
            col = node.start_point.column + 1
            snippet = source.splitlines()[node.start_point.row] if node.start_point.row < len(source.splitlines()) else ""
            label = "missing node" if node.is_missing else "syntax error"
            errors.append(
                f"warning: {label} at {filename}:{line}:{col}\n"
                f"   | {snippet}\n"
                f"   | {' ' * (col - 1)}^"
            )
            return
        for child in node.children:
            self._collect_errors(child, source, filename, errors)

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
            result = self._convert_stmt(child)
            if result is not None:
                if isinstance(result, list):
                    stmts.extend(result)
                else:
                    stmts.append(result)
        return stmts

    def _convert_stmt(self, node: Node) -> Statement | list[Statement] | None:
        t = node.type
        if t == "generator_function_declaration":
            fd = self._convert_function_decl(node)
            fd.is_generator = True
            return fd
        if t == "function_declaration":
            return self._convert_function_decl(node)
        elif t in ("lexical_declaration", "variable_declaration"):
            decls = self._convert_var_decl(node)
            if len(decls) == 1:
                return decls[0]
            return decls if decls else None
        elif t == "return_statement":
            return self._convert_return(node)
        elif t == "if_statement":
            return self._convert_if(node)
        elif t == "while_statement":
            return self._convert_while(node)
        elif t == "do_statement":
            return self._convert_do_while(node)
        elif t == "for_statement":
            return self._convert_for(node)
        elif t == "for_in_statement":
            # tree-sitter uses for_in_statement for both for...of and for...in
            if any(c.type == "of" for c in node.children):
                return self._convert_for_of(node)
            else:
                return self._convert_for_in(node)
        elif t == "switch_statement":
            return self._convert_switch(node)
        elif t == "break_statement":
            label = None
            for child in node.children:
                if child.type == "statement_identifier":
                    label = child.text.decode()
            return BreakStmt(label=label, loc=self._loc(node))
        elif t == "continue_statement":
            label = None
            for child in node.children:
                if child.type == "statement_identifier":
                    label = child.text.decode()
            return ContinueStmt(label=label, loc=self._loc(node))
        elif t == "labeled_statement":
            return self._convert_labeled_stmt(node)
        elif t == "class_declaration":
            return self._convert_class_decl(node)
        elif t == "throw_statement":
            return self._convert_throw(node)
        elif t == "try_statement":
            return self._convert_try(node)
        elif t == "expression_statement":
            return self._convert_expression_stmt(node)
        elif t == "statement_block":
            return self._convert_block(node)
        elif t == "comment":
            return None
        elif t == "empty_statement":
            return None
        elif t == "export_statement":
            return self._convert_export(node)
        elif t == "import_statement":
            return self._convert_import(node)
        return None

    def _convert_import(self, node: Node) -> ImportDeclaration:
        """Convert import_statement to ImportDeclaration AST node."""
        specifiers: list[ImportSpecifier] = []
        source = ""
        namespace = None
        loc = self._loc(node)

        for child in node.children:
            if child.type == "string":
                # Module source path
                source = child.text.decode().strip("'\"")
            elif child.type == "import_clause":
                for clause_child in child.children:
                    if clause_child.type == "identifier":
                        # Default import: import foo from '...'
                        specifiers.append(ImportSpecifier(
                            imported="default",
                            local=clause_child.text.decode(),
                        ))
                    elif clause_child.type == "named_imports":
                        # Named imports: import { foo, bar as baz } from '...'
                        for spec_node in clause_child.children:
                            if spec_node.type == "import_specifier":
                                imported = ""
                                local = ""
                                parts = [c for c in spec_node.children
                                         if c.type == "identifier"]
                                if len(parts) == 1:
                                    imported = parts[0].text.decode()
                                    local = imported
                                elif len(parts) == 2:
                                    imported = parts[0].text.decode()
                                    local = parts[1].text.decode()
                                specifiers.append(ImportSpecifier(
                                    imported=imported, local=local,
                                ))
                    elif clause_child.type == "namespace_import":
                        # import * as ns from '...'
                        for ns_child in clause_child.children:
                            if ns_child.type == "identifier":
                                namespace = ns_child.text.decode()

        return ImportDeclaration(
            specifiers=specifiers, source=source,
            namespace=namespace, loc=loc,
        )

    def _convert_export(self, node: Node) -> ExportDeclaration | Statement | None:
        """Convert export_statement to ExportDeclaration AST node."""
        loc = self._loc(node)
        is_default = any(c.type == "default" for c in node.children)

        # export function/class/const/let/var
        for child in node.children:
            if child.type in ("function_declaration", "class_declaration",
                              "lexical_declaration", "variable_declaration"):
                decl = self._convert_stmt(child)
                if decl is not None:
                    if isinstance(decl, list):
                        decl = decl[0] if decl else None
                    return ExportDeclaration(
                        declaration=decl, is_default=is_default, loc=loc,
                    )

        # export { foo, bar as baz }
        for child in node.children:
            if child.type == "export_clause":
                specifiers: list[tuple[str, str]] = []
                for spec_node in child.children:
                    if spec_node.type == "export_specifier":
                        parts = [c for c in spec_node.children
                                 if c.type == "identifier"]
                        if len(parts) == 1:
                            name = parts[0].text.decode()
                            specifiers.append((name, name))
                        elif len(parts) == 2:
                            local = parts[0].text.decode()
                            exported = parts[1].text.decode()
                            specifiers.append((local, exported))
                return ExportDeclaration(specifiers=specifiers, loc=loc)

        # export default expression — fallback: try to get inner declaration
        if is_default:
            for child in node.children:
                stmt = self._convert_stmt(child)
                if stmt is not None:
                    return ExportDeclaration(
                        declaration=stmt, is_default=True, loc=loc,
                    )

        return None

    def _convert_function_decl(self, node: Node) -> FunctionDecl:
        name = ""
        params: list[Parameter] = []
        body = Block()
        loc = self._loc(node)
        destructure_stmts: list[Statement] = []
        is_async = False

        for child in node.children:
            if child.type == "async":
                is_async = True
            elif child.type == "identifier":
                name = child.text.decode()
            elif child.type == "formal_parameters":
                params, destructure_stmts = self._convert_params(child)
            elif child.type == "statement_block":
                body = self._convert_block(child)

        # Prepend destructuring statements to function body
        if destructure_stmts:
            body.body = destructure_stmts + body.body

        return FunctionDecl(name=name, params=params, body=body, loc=loc, is_async=is_async)

    def _convert_class_decl(self, node: Node) -> ClassDecl:
        name = ""
        extends = None
        constructor = None
        methods: list[MethodDecl] = []
        static_methods: list[MethodDecl] = []
        field_declarations: list[ClassField] = []
        loc = self._loc(node)

        for child in node.children:
            if child.type == "identifier":
                name = child.text.decode()
            elif child.type == "class_heritage":
                for hc in child.children:
                    if hc.type == "identifier":
                        extends = hc.text.decode()
            elif child.type == "class_body":
                for member in child.children:
                    if member.type == "method_definition":
                        md = self._convert_method_def(member)
                        if md.name == "constructor":
                            constructor = md
                        elif md.is_static:
                            static_methods.append(md)
                        else:
                            methods.append(md)
                    elif member.type == "field_definition":
                        cf = self._convert_field_def(member)
                        if cf:
                            field_declarations.append(cf)
        # If class extends another but has no explicit constructor,
        # generate implicit constructor(...args) { super(...args); }
        if extends and constructor is None:
            rest_param = Parameter(name="__args", is_rest=True)
            super_call = SuperCall(arguments=[Identifier(name="__args")])
            implicit_body = Block(body=[ExpressionStmt(expression=super_call)])
            constructor = MethodDecl(
                name="constructor",
                params=[rest_param],
                body=implicit_body,
            )

        return ClassDecl(name=name, extends=extends, constructor=constructor,
                         methods=methods, static_methods=static_methods,
                         field_declarations=field_declarations, loc=loc)

    def _convert_method_def(self, node: Node) -> MethodDecl:
        name = ""
        params: list[Parameter] = []
        body = Block()
        is_static = False
        is_getter = False
        is_setter = False
        destructure_stmts: list[Statement] = []

        for child in node.children:
            if child.type == "property_identifier":
                name = child.text.decode()
            elif child.type == "formal_parameters":
                params, destructure_stmts = self._convert_params(child)
            elif child.type == "statement_block":
                body = self._convert_block(child)
            elif child.type == "get":
                is_getter = True
            elif child.type == "set":
                is_setter = True
            elif child.text and child.text.decode() == "static":
                is_static = True

        if destructure_stmts:
            body.body = destructure_stmts + body.body

        return MethodDecl(name=name, params=params, body=body,
                         is_static=is_static, is_getter=is_getter, is_setter=is_setter)

    def _convert_field_def(self, node: Node) -> ClassField | None:
        name = ""
        initializer = None
        is_static = False

        for child in node.children:
            if child.type == "property_identifier":
                name = child.text.decode()
            elif child.type == "private_property_identifier":
                raw = child.text.decode()
                name = f"__private_{raw[1:]}"  # #name → __private_name
            elif child.type == "=":
                continue
            elif child.text and child.text.decode() == "static":
                is_static = True
            elif name and child.type not in (";",):
                initializer = self._convert_expr(child)

        if name:
            return ClassField(name=name, initializer=initializer, is_static=is_static)
        return None

    def _convert_new_expr(self, node: Node, loc: Location) -> NewExpr:
        class_name = ""
        args: list[Expression] = []

        for child in node.children:
            if child.type == "new":
                continue
            elif child.type == "identifier":
                class_name = child.text.decode()
            elif child.type == "arguments":
                for ac in child.children:
                    if ac.type not in ("(", ")", ","):
                        args.append(self._convert_expr(ac))

        return NewExpr(class_name=class_name, arguments=args, loc=loc)

    def _convert_params(self, node: Node) -> tuple[list[Parameter], list[Statement]]:
        """Convert formal_parameters. Returns (params, destructure_stmts).

        Destructured params like ({x, y}) are desugared to a synthetic param
        (__param_N) plus a destructuring statement prepended to the function body.
        """
        params: list[Parameter] = []
        destructure_stmts: list[Statement] = []
        synth_idx = 0
        for child in node.children:
            if child.type == "identifier":
                params.append(Parameter(name=child.text.decode()))
            elif child.type == "assignment_pattern":
                p = self._convert_default_param(child)
                if p:
                    params.append(p)
            elif child.type == "rest_pattern":
                # ...name → rest parameter
                for sc in child.children:
                    if sc.type == "identifier":
                        params.append(Parameter(name=sc.text.decode(), is_rest=True))
                        break
            elif child.type == "object_pattern":
                # Destructured object param: ({x, y}) → __param_N + destructure
                synth_name = f"__param_{synth_idx}"
                synth_idx += 1
                params.append(Parameter(name=synth_name))
                fields = []
                aliases = {}
                for pc in child.children:
                    if pc.type == "shorthand_property_identifier_pattern":
                        fields.append(pc.text.decode())
                    elif pc.type == "pair_pattern":
                        # { key: alias } — extract field 'key', bind to 'alias'
                        key = alias = ""
                        for ppc in pc.children:
                            if ppc.type == "property_identifier" and not key:
                                key = ppc.text.decode()
                            elif ppc.type == "identifier":
                                alias = ppc.text.decode()
                        if key:
                            fields.append(key)
                            if alias and alias != key:
                                aliases[key] = alias
                destructure_stmts.append(ObjectDestructure(
                    kind="const", fields=fields,
                    init=Identifier(name=synth_name),
                    loc=self._loc(child),
                    aliases=aliases,
                ))
            elif child.type == "array_pattern":
                # Destructured array param: ([a, b]) → __param_N + destructure
                synth_name = f"__param_{synth_idx}"
                synth_idx += 1
                params.append(Parameter(name=synth_name))
                names = []
                for pc in child.children:
                    if pc.type == "identifier":
                        names.append(pc.text.decode())
                destructure_stmts.append(ArrayDestructure(
                    kind="const", names=names,
                    init=Identifier(name=synth_name),
                    loc=self._loc(child),
                ))
        return params, destructure_stmts

    def _convert_default_param(self, node: Node) -> Parameter | None:
        """Convert assignment_pattern: name = default_value."""
        name = ""
        default = None
        for child in node.children:
            if child.type == "identifier" and not name:
                name = child.text.decode()
            elif child.type == "=":
                continue
            elif name:
                default = self._convert_expr(child)
        if name:
            return Parameter(name=name, default=default)
        return None

    def _convert_var_decl(self, node: Node) -> list[VarDecl | ObjectDestructure | ArrayDestructure]:
        kind = "const"
        results = []
        for child in node.children:
            if child.type in ("const", "let", "var"):
                kind = child.type
            elif child.type == "variable_declarator":
                results.append(self._convert_variable_declarator(child, kind))
        return results

    def _convert_variable_declarator(self, node: Node, kind: str) -> VarDecl | ObjectDestructure | ArrayDestructure:
        name = ""
        init: Expression | None = None
        loc = self._loc(node)

        # Check for object destructuring pattern
        for child in node.children:
            if child.type == "object_pattern":
                return self._convert_object_destructure(child, node, kind)
            if child.type == "array_pattern":
                return self._convert_array_destructure(child, node, kind)

        found_eq = False
        for child in node.children:
            if child.type == "=" and not found_eq:
                found_eq = True
            elif not found_eq:
                if child.type == "identifier" and not name:
                    name = child.text.decode()
                elif not name:
                    name = child.text.decode()
            else:
                init = self._convert_expr(child)

        return VarDecl(kind=kind, name=name, init=init, loc=loc)

    def _convert_object_destructure(self, pattern_node: Node, declarator_node: Node, kind: str) -> ObjectDestructure:
        """Convert object destructuring pattern: const { x, y: alias = default, ...rest } = expr"""
        fields: list[str] = []
        aliases: dict[str, str] = {}
        defaults: dict[str, Expression] = {}
        rest_name: str | None = None
        init = Expression()
        loc = self._loc(declarator_node)

        for child in pattern_node.children:
            if child.type == "shorthand_property_identifier_pattern":
                fields.append(child.text.decode())
            elif child.type == "pair_pattern":
                # { key: alias } or { key: alias = default }
                key = ""
                alias = ""
                default_expr = None
                for pc in child.children:
                    if pc.type == "property_identifier":
                        key = pc.text.decode()
                    elif pc.type == "identifier":
                        alias = pc.text.decode()
                    elif pc.type == "assignment_pattern":
                        # { key: alias = default }
                        for apc in pc.children:
                            if apc.type == "identifier":
                                alias = apc.text.decode()
                            elif apc.type != "=":
                                default_expr = self._convert_expr(apc)
                if key:
                    fields.append(key)
                    if alias and alias != key:
                        aliases[key] = alias
                    if default_expr:
                        defaults[key] = default_expr
            elif child.type == "object_assignment_pattern":
                # { x = default_value }
                fname = None
                default_expr = None
                found_eq = False
                for pc in child.children:
                    if pc.type == "shorthand_property_identifier_pattern":
                        fname = pc.text.decode()
                    elif pc.type == "=":
                        found_eq = True
                    elif found_eq and fname:
                        default_expr = self._convert_expr(pc)
                if fname:
                    fields.append(fname)
                    if default_expr:
                        defaults[fname] = default_expr
            elif child.type == "rest_pattern":
                for rc in child.children:
                    if rc.type == "identifier":
                        rest_name = rc.text.decode()

        found_eq = False
        for child in declarator_node.children:
            if child.type == "=":
                found_eq = True
            elif found_eq and child.type != "object_pattern":
                init = self._convert_expr(child)

        return ObjectDestructure(kind=kind, fields=fields, init=init, loc=loc, defaults=defaults, rest_name=rest_name, aliases=aliases)

    def _convert_array_destructure(self, pattern_node: Node, declarator_node: Node, kind: str) -> ArrayDestructure:
        """Convert array destructuring pattern: const [a, b = default, ...rest] = expr"""
        names: list[str] = []
        defaults: dict[str, Expression] = {}
        rest_name: str | None = None
        init = Expression()
        loc = self._loc(declarator_node)

        for child in pattern_node.children:
            if child.type == "identifier":
                names.append(child.text.decode())
            elif child.type == "assignment_pattern":
                # a = default_value
                vname = None
                default_expr = None
                found_eq = False
                for pc in child.children:
                    if pc.type == "identifier" and not found_eq:
                        vname = pc.text.decode()
                    elif pc.type == "=":
                        found_eq = True
                    elif found_eq and vname:
                        default_expr = self._convert_expr(pc)
                if vname:
                    names.append(vname)
                    if default_expr:
                        defaults[vname] = default_expr
            elif child.type == "rest_pattern":
                # ...rest pattern
                for rc in child.children:
                    if rc.type == "identifier":
                        rest_name = rc.text.decode()

        found_eq = False
        for child in declarator_node.children:
            if child.type == "=":
                found_eq = True
            elif found_eq and child.type != "array_pattern":
                init = self._convert_expr(child)

        return ArrayDestructure(kind=kind, names=names, init=init, loc=loc, rest_name=rest_name, defaults=defaults)

    def _convert_return(self, node: Node) -> ReturnStmt:
        value: Expression | None = None
        for child in node.children:
            if child.type not in ("return", ";"):
                value = self._convert_expr(child)
        return ReturnStmt(value=value, loc=self._loc(node))

    def _convert_throw(self, node: Node) -> ThrowStmt:
        argument = Expression()
        for child in node.children:
            if child.type not in ("throw", ";"):
                argument = self._convert_expr(child)
        return ThrowStmt(argument=argument, loc=self._loc(node))

    def _convert_try(self, node: Node) -> TryCatchStmt:
        try_block = Block()
        catch_param: str | None = None
        catch_block: Block | None = None
        finally_block: Block | None = None
        for child in node.children:
            if child.type == "try":
                continue
            elif child.type == "statement_block":
                try_block = self._convert_block(child)
            elif child.type == "catch_clause":
                for cc in child.children:
                    if cc.type == "identifier":
                        catch_param = cc.text.decode()
                    elif cc.type == "statement_block":
                        catch_block = self._convert_block(cc)
            elif child.type == "finally_clause":
                for fc in child.children:
                    if fc.type == "statement_block":
                        finally_block = self._convert_block(fc)
        return TryCatchStmt(
            try_block=try_block, catch_param=catch_param,
            catch_block=catch_block, finally_block=finally_block,
            loc=self._loc(node),
        )

    def _convert_if(self, node: Node) -> IfStmt:
        condition = Expression()
        consequent = Block()
        alternate: Block | IfStmt | None = None
        loc = self._loc(node)

        for child in node.children:
            if child.type in ("if", "(", ")", ";"):
                continue
            elif child.type == "parenthesized_expression":
                condition = self._convert_expr(self._unwrap_parens(child))
            elif child.type == "statement_block" and isinstance(consequent, Block) and not consequent.body:
                consequent = self._convert_block(child)
            elif child.type == "else_clause":
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

    def _convert_do_while(self, node: Node) -> DoWhileStmt:
        condition = Expression()
        body = Block()
        loc = self._loc(node)

        for child in node.children:
            if child.type == "statement_block":
                body = self._convert_block(child)
            elif child.type == "parenthesized_expression":
                condition = self._convert_expr(self._unwrap_parens(child))

        return DoWhileStmt(condition=condition, body=body, loc=loc)

    def _convert_for(self, node: Node) -> Block | ForStmt:
        init_node = None
        cond_node = None
        update_node = None
        body = Block()
        loc = self._loc(node)
        extra_inits: list[Statement] = []

        for child in node.children:
            if child.type in ("for", "(", ")", ";"):
                continue
            if child.type == "statement_block":
                body = self._convert_block(child)
            elif child.type in ("lexical_declaration", "variable_declaration"):
                decls = self._convert_var_decl(child)
                init_node = decls[0] if decls else None
                # Multiple declarations (e.g., let i = 0, j = 10)
                if len(decls) > 1:
                    extra_inits = list(decls[1:])
            elif child.type == "expression_statement":
                inner = self._get_inner_expr(child)
                if init_node is not None and cond_node is None:
                    cond_node = self._convert_expr(inner) if inner else None
                elif cond_node is not None:
                    update_node = self._convert_expr(inner) if inner else None
                else:
                    cond_node = self._convert_expr(inner) if inner else None
            elif child.type == "empty_statement":
                if init_node is None:
                    init_node = None
                elif cond_node is None:
                    cond_node = None
            else:
                expr = self._convert_expr(child)
                if init_node is not None and cond_node is None:
                    cond_node = expr
                elif cond_node is not None and update_node is None:
                    update_node = expr
                elif init_node is None:
                    init_node = ExpressionStmt(expression=expr)

        for_stmt = ForStmt(init=init_node, condition=cond_node, update=update_node, body=body, loc=loc)
        # If multiple init vars, wrap in a block: { let j = 10; for (let i = 0; ...) }
        if extra_inits:
            return Block(body=extra_inits + [for_stmt], loc=loc)
        return for_stmt

    def _convert_for_in(self, node: Node) -> ForInStmt:
        """Convert for_in_statement: for (const key in obj) { ... }"""
        var_name = ""
        kind = "const"
        obj = Expression()
        body = Block()
        loc = self._loc(node)

        found_in = False
        for child in node.children:
            if child.type in ("for", "(", ")"):
                continue
            if child.type in ("const", "let", "var"):
                kind = child.type
            elif child.type == "identifier" and not found_in:
                var_name = child.text.decode()
            elif child.type == "in":
                found_in = True
            elif found_in and child.type == "statement_block":
                body = self._convert_block(child)
            elif found_in and child.type != "statement_block":
                obj = self._convert_expr(child)

        return ForInStmt(var_name=var_name, kind=kind, object=obj, body=body, loc=loc)

    def _convert_for_of(self, node: Node) -> ForOfStmt | Block:
        """Convert for_in_statement used as for-of: for (const x of arr) { ... }
        For destructuring patterns, desugars to: for (const __item of arr) { const [a,b] = __item; ... }
        """
        var_name = ""
        kind = "const"
        iterable = Expression()
        body = Block()
        loc = self._loc(node)
        destructure_pattern = None  # array_pattern or object_pattern node

        # Structure: for ( const/let identifier of expression ) statement_block
        found_of = False
        for child in node.children:
            if child.type in ("for", "(", ")"):
                continue
            if child.type in ("const", "let", "var"):
                kind = child.type
            elif child.type == "identifier" and not found_of:
                var_name = child.text.decode()
            elif child.type == "array_pattern" and not found_of:
                destructure_pattern = ("array", child)
            elif child.type == "object_pattern" and not found_of:
                destructure_pattern = ("object", child)
            elif child.type == "of":
                found_of = True
            elif found_of and child.type == "statement_block":
                body = self._convert_block(child)
            elif found_of and child.type != "statement_block":
                iterable = self._convert_expr(child)

        # Desugar destructuring in for-of
        if destructure_pattern:
            pat_type, pat_node = destructure_pattern
            synth_name = "__for_item"
            if pat_type == "array":
                names = []
                for pc in pat_node.children:
                    if pc.type == "identifier":
                        names.append(pc.text.decode())
                destructure_stmt = ArrayDestructure(
                    kind=kind, names=names,
                    init=Identifier(name=synth_name), loc=loc,
                )
            else:  # object
                # Create a dummy declarator_node for reuse
                fields = []
                aliases = {}
                for pc in pat_node.children:
                    if pc.type == "shorthand_property_identifier_pattern":
                        fields.append(pc.text.decode())
                    elif pc.type == "pair_pattern":
                        key = alias = ""
                        for ppc in pc.children:
                            if ppc.type == "property_identifier" and not key:
                                key = ppc.text.decode()
                            elif ppc.type == "identifier":
                                alias = ppc.text.decode()
                        if key:
                            fields.append(key)
                            if alias and alias != key:
                                aliases[key] = alias
                destructure_stmt = ObjectDestructure(
                    kind=kind, fields=fields,
                    init=Identifier(name=synth_name), loc=loc,
                    aliases=aliases,
                )
            body.body = [destructure_stmt] + body.body
            return ForOfStmt(var_name=synth_name, kind=kind, iterable=iterable, body=body, loc=loc)

        return ForOfStmt(var_name=var_name, kind=kind, iterable=iterable, body=body, loc=loc)

    def _convert_labeled_stmt(self, node: Node) -> LabeledStmt:
        label_name = ""
        body = Statement()
        for child in node.children:
            if child.type == "statement_identifier":
                label_name = child.text.decode()
            elif child.type == ":":
                continue
            else:
                body_result = self._convert_stmt(child)
                if isinstance(body_result, list):
                    body = body_result[0] if body_result else Statement()
                elif body_result is not None:
                    body = body_result
        return LabeledStmt(label_name=label_name, body=body, loc=self._loc(node))

    def _convert_switch(self, node: Node) -> SwitchStmt:
        discriminant = Expression()
        cases: list[SwitchCase] = []
        loc = self._loc(node)

        for child in node.children:
            if child.type == "parenthesized_expression":
                discriminant = self._convert_expr(self._unwrap_parens(child))
            elif child.type == "switch_body":
                for case_child in child.children:
                    if case_child.type == "switch_case":
                        cases.append(self._convert_switch_case(case_child))
                    elif case_child.type == "switch_default":
                        cases.append(self._convert_switch_default(case_child))

        return SwitchStmt(discriminant=discriminant, cases=cases, loc=loc)

    def _convert_switch_case(self, node: Node) -> SwitchCase:
        test: Expression | None = None
        body: list[Statement] = []
        loc = self._loc(node)

        found_colon = False
        for child in node.children:
            if child.type == "case":
                continue
            elif child.type == ":":
                found_colon = True
                continue
            elif not found_colon:
                test = self._convert_expr(child)
            else:
                stmt = self._convert_stmt(child)
                if stmt is not None:
                    body.append(stmt)

        return SwitchCase(test=test, body=body, loc=loc)

    def _convert_switch_default(self, node: Node) -> SwitchCase:
        body: list[Statement] = []
        loc = self._loc(node)

        found_colon = False
        for child in node.children:
            if child.type in ("default", ":"):
                if child.type == ":":
                    found_colon = True
                continue
            if found_colon:
                stmt = self._convert_stmt(child)
                if stmt is not None:
                    body.append(stmt)

        return SwitchCase(test=None, body=body, loc=loc)

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
            result = self._convert_stmt(child)
            if result is not None:
                if isinstance(result, list):
                    stmts.extend(result)
                else:
                    stmts.append(result)
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
            if text.startswith(('0x', '0X', '0o', '0O', '0b', '0B')):
                value = float(int(text, 0))
            else:
                value = float(text)
            return NumberLiteral(value=value, loc=loc)

        if t == "string":
            text = node.text.decode()
            if text.startswith('"') or text.startswith("'"):
                text = text[1:-1]
            return StringLiteral(value=text, loc=loc)

        if t == "template_string":
            return self._convert_template_literal(node, loc)

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

        if t == "array":
            return self._convert_array_literal(node, loc)

        if t == "object":
            return self._convert_object_literal(node, loc)

        if t == "arrow_function":
            return self._convert_arrow_function(node, loc)

        if t == "await_expression":
            for child in node.children:
                if child.type != "await":
                    return AwaitExpr(argument=self._convert_expr(child), loc=loc)
            return AwaitExpr(loc=loc)

        if t == "function_expression":
            # function(x) { ... } — treat as arrow function equivalent
            params: list[Parameter] = []
            body = Block()
            destructure_stmts: list[Statement] = []
            for child in node.children:
                if child.type == "formal_parameters":
                    params, destructure_stmts = self._convert_params(child)
                elif child.type == "statement_block":
                    body = self._convert_block(child)
            if destructure_stmts:
                body.body = destructure_stmts + body.body
            return ArrowFunction(params=params, body=body, loc=loc)

        if t == "new_expression":
            return self._convert_new_expr(node, loc)

        if t == "this":
            return ThisExpr(loc=loc)

        if t == "sequence_expression":
            exprs = [self._convert_expr(c) for c in node.children if c.type != ","]
            if len(exprs) == 1:
                return exprs[0]
            return SequenceExpr(expressions=exprs, loc=loc)

        # Fallback
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

        if op in ("===", "!==", "==", "!=", "<", ">", "<=", ">="):
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

    def _convert_call(self, node: Node, loc: Location) -> CallExpr | SuperCall:
        callee = Expression()
        args: list[Expression] = []
        is_super = False

        for child in node.children:
            if child.type == "super":
                is_super = True
            elif child.type == "arguments":
                for arg in child.children:
                    if arg.type == "spread_element":
                        for sc in arg.children:
                            if sc.type != "...":
                                args.append(SpreadElement(argument=self._convert_expr(sc), loc=loc))
                                break
                    elif arg.type not in ("(", ")", ","):
                        args.append(self._convert_expr(arg))
            elif child.type not in ("(", ")", ","):
                callee = self._convert_expr(child)

        if is_super:
            return SuperCall(arguments=args, loc=loc)
        return CallExpr(callee=callee, arguments=args, loc=loc)

    def _convert_member(self, node: Node, loc: Location) -> MemberExpr:
        obj = Expression()
        prop = Expression()
        children = [c for c in node.children if c.type not in (".", "optional_chain")]
        if len(children) >= 2:
            obj = self._convert_expr(children[0])
            prop_node = children[1]
            if prop_node.type == "property_identifier":
                prop = Identifier(name=prop_node.text.decode(), loc=self._loc(prop_node))
            elif prop_node.type == "private_property_identifier":
                # #name → __private_name (strip # and add prefix)
                raw = prop_node.text.decode()
                prop = Identifier(name=f"__private_{raw[1:]}", loc=self._loc(prop_node))
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
                              "&=", "|=", "^=", "<<=", ">>=", ">>>=",
                              "&&=", "||=", "??="):
                op = child.text.decode()
            elif isinstance(left, Expression) and left.__class__ == Expression:
                left = self._convert_expr(child)
            else:
                right = self._convert_expr(child)
        return AssignExpr(op=op, left=left, right=right, loc=loc)

    def _convert_arrow_function(self, node: Node, loc: Location) -> ArrowFunction:
        params: list[Parameter] = []
        body: Expression | Block = Block()
        seen_arrow = False
        destructure_stmts: list[Statement] = []

        for child in node.children:
            if child.type == "=>":
                seen_arrow = True
                continue
            if not seen_arrow:
                # Before => : params
                if child.type == "formal_parameters":
                    params, destructure_stmts = self._convert_params(child)
                elif child.type == "identifier":
                    # Single param arrow: x => x + 1
                    params = [Parameter(name=child.text.decode())]
            else:
                # After => : body
                if child.type == "statement_block":
                    body = self._convert_block(child)
                elif child.type not in ("(", ")", ","):
                    body = self._convert_expr(child)

        if destructure_stmts and isinstance(body, Block):
            body.body = destructure_stmts + body.body

        return ArrowFunction(params=params, body=body, loc=loc)

    def _convert_template_literal(self, node: Node, loc: Location) -> Expression:
        """Convert template literal: `hello ${name} world`.

        Tree-sitter yields interleaved string_fragment and template_substitution
        children. We must produce quasis[0] expr[0] quasis[1] expr[1] ... quasis[n]
        where len(quasis) == len(expressions) + 1.
        """
        quasis: list[str] = []
        expressions: list[Expression] = []
        last_was_expr = True  # start true to force leading empty quasi if needed
        for child in node.children:
            if child.type == "string_fragment":
                quasis.append(child.text.decode())
                last_was_expr = False
            elif child.type == "template_substitution":
                if last_was_expr:
                    quasis.append("")  # empty quasi before consecutive/leading expr
                for sc in child.children:
                    if sc.type not in ("${", "}"):
                        expressions.append(self._convert_expr(sc))
                last_was_expr = True
            # Skip backtick nodes
        # Trailing quasi after last expression
        if last_was_expr and expressions:
            quasis.append("")
        # If no expressions, it's just a plain string
        if not expressions:
            return StringLiteral(value="".join(quasis), loc=loc)
        return TemplateLiteral(quasis=quasis, expressions=expressions, loc=loc)

    def _convert_array_literal(self, node: Node, loc: Location) -> ArrayLiteral:
        elements: list[Expression] = []
        for child in node.children:
            if child.type == "spread_element":
                # ...expr → SpreadElement(expr)
                for sc in child.children:
                    if sc.type != "...":
                        elements.append(SpreadElement(argument=self._convert_expr(sc), loc=loc))
                        break
            elif child.type not in ("[", "]", ","):
                elements.append(self._convert_expr(child))
        return ArrayLiteral(elements=elements, loc=loc)

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
                    elif pc.type == "computed_property_name":
                        # [expr]: value — extract string key if possible
                        for cpn in pc.children:
                            if cpn.type == "string":
                                key = self._extract_string_value(cpn)
                            elif cpn.type not in ("[", "]"):
                                # Non-string computed key: use text as key
                                key = cpn.text.decode()
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
                for pc in child.children:
                    if pc.type == "...":
                        continue
                    spread_expr = self._convert_expr(pc)
                    spreads.append((len(properties), spread_expr))
                    break
        return ObjectLiteralExpr(properties=properties, spreads=spreads, loc=loc)

    def _extract_string_value(self, node: Node) -> str:
        """Extract the string value from a tree-sitter 'string' node."""
        text = node.text.decode()
        if text.startswith('"') or text.startswith("'"):
            text = text[1:-1]
        return text
