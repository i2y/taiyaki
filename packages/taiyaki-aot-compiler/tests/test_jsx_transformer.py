"""Tests for JSX transformer: JSX syntax → createElement() function calls."""

import pytest
from taiyaki_aot_compiler.parser.jsx_transformer import transform_jsx
from taiyaki_aot_compiler.parser.ts_stripper import strip_types


class TestBasicElements:
    """Basic JSX element transformation."""

    def test_self_closing_html(self):
        result = transform_jsx('<br />')
        assert result == 'createElement("br", null)'

    def test_self_closing_component(self):
        result = transform_jsx('<MyComponent />')
        assert result == 'createElement(MyComponent, null)'

    def test_simple_element(self):
        result = transform_jsx('<div>hello</div>')
        assert 'createElement("div", null, "hello")' in result

    def test_nested_elements(self):
        result = transform_jsx('<div><span>text</span></div>')
        assert 'createElement("div"' in result
        assert 'createElement("span"' in result

    def test_member_expression_tag(self):
        result = transform_jsx('<React.Fragment />')
        assert 'createElement(React.Fragment, null)' in result


class TestProps:
    """JSX attribute/prop handling."""

    def test_string_prop(self):
        result = transform_jsx('<div className="foo" />')
        assert 'className: "foo"' in result

    def test_expression_prop(self):
        result = transform_jsx('<div count={42} />')
        assert 'count: 42' in result

    def test_boolean_prop(self):
        result = transform_jsx('<input disabled />')
        assert 'disabled: true' in result

    def test_multiple_props(self):
        result = transform_jsx('<div id="a" className="b" />')
        assert 'id: "a"' in result
        assert 'className: "b"' in result

    def test_expression_prop_variable(self):
        result = transform_jsx('<div onClick={handler} />')
        assert 'onClick: handler' in result


class TestChildren:
    """JSX children handling."""

    def test_text_child(self):
        result = transform_jsx('<p>Hello World</p>')
        assert '"Hello World"' in result

    def test_expression_child(self):
        result = transform_jsx('<p>{name}</p>')
        assert 'name' in result

    def test_multiple_children(self):
        result = transform_jsx('<div><span>a</span><span>b</span></div>')
        assert result.count('createElement("span"') == 2

    def test_mixed_text_and_expression(self):
        result = transform_jsx('<p>Hello {name}</p>')
        assert '"Hello"' in result
        assert 'name' in result

    def test_nested_jsx_child(self):
        result = transform_jsx('<div><p>inner</p></div>')
        assert 'createElement("div"' in result
        assert 'createElement("p"' in result


class TestFragments:
    """JSX fragment handling."""

    def test_fragment(self):
        result = transform_jsx('<><span>a</span><span>b</span></>')
        assert 'createElement(Fragment, null' in result


class TestPreservesNonJSX:
    """Non-JSX code should pass through unchanged."""

    def test_plain_js(self):
        source = 'const x = 1 + 2;'
        result = transform_jsx(source)
        assert result == source

    def test_function_with_jsx_return(self):
        source = 'function App() { return <div />; }'
        result = transform_jsx(source)
        assert 'function App()' in result
        assert 'createElement("div", null)' in result

    def test_arrow_with_jsx(self):
        source = 'const App = () => <div>hello</div>;'
        result = transform_jsx(source)
        assert 'const App' in result
        assert 'createElement("div"' in result


class TestComplexScenarios:
    """Complex real-world JSX patterns."""

    def test_component_with_props_and_children(self):
        source = '<Button onClick={handleClick} size="lg">Click me</Button>'
        result = transform_jsx(source)
        assert 'createElement(Button' in result
        assert 'onClick: handleClick' in result
        assert 'size: "lg"' in result
        assert '"Click me"' in result

    def test_deeply_nested(self):
        source = '<div><ul><li>item</li></ul></div>'
        result = transform_jsx(source)
        assert 'createElement("div"' in result
        assert 'createElement("ul"' in result
        assert 'createElement("li"' in result

    def test_conditional_expression_child(self):
        source = '<div>{isOpen ? <span>open</span> : <span>closed</span>}</div>'
        result = transform_jsx(source)
        assert 'createElement("div"' in result
        assert 'createElement("span"' in result

    def test_map_expression_children(self):
        source = '''function List() {
  return <ul>{items.map(item => <li>{item}</li>)}</ul>;
}'''
        result = transform_jsx(source)
        assert 'createElement("ul"' in result
        assert 'createElement("li"' in result
        assert 'items.map' in result


class TestTSXSupport:
    """TSX: strip types first, then transform JSX."""

    def test_tsx_basic(self):
        tsx = 'function App(): JSX.Element { return <div>hello</div>; }'
        js = strip_types(tsx, tsx=True)
        result = transform_jsx(js)
        assert 'createElement("div"' in result
        assert "JSX.Element" not in result
        assert "hello" in result

    def test_tsx_typed_props(self):
        tsx = '''function Greet(props: { name: string }) {
  return <p>Hello {props.name}</p>;
}'''
        js = strip_types(tsx, tsx=True)
        result = transform_jsx(js)
        assert 'createElement("p"' in result
        assert ": string" not in result
        assert "props.name" in result

    def test_tsx_generic_component(self):
        tsx = 'function List<T>(items: T[]) { return <ul />; }'
        js = strip_types(tsx, tsx=True)
        result = transform_jsx(js)
        assert "<T>" not in result
        assert "T[]" not in result
        assert 'createElement("ul"' in result

    def test_tsx_as_expression_in_jsx(self):
        tsx = '<div>{(value as number).toFixed(2)}</div>'
        js = strip_types(tsx, tsx=True)
        result = transform_jsx(js)
        assert "as number" not in result
        assert 'createElement("div"' in result
