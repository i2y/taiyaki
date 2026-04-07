"""Clay JSX transformer: converts JSX to Clay imperative API calls.

Supports both low-level Box/Text elements and high-level UI widgets.

Low-level elements:
  <Box id="root" grow vertical bg={[24,24,32]} padding={16} gap={8} radius={8}>
    <Text size={24} color={[120,180,255]}>Dashboard</Text>
  </Box>

Layout containers (compile-time expansion to clayOpen/clayClose):
  <VPanel>, <HPanel>, <Row>, <CPanel>, <Card>, <Header>, <Footer>,
  <Sidebar>, <ScrollPanel>, <ScrollHPanel>, <GridRow>, <GridItem>,
  <ZStack>, <ZStackLayer>, <Modal>, <AspectPanel>, <FixedPanel>,
  <PctPanel>, <TabBar>, <TabContent>, <StatusBar>

Display widgets (compile-time):
  <Spacer />, <Divider />, <ProgressBar />, <Badge>, <Avatar>

Interactive widgets (IMGUI-style, emit widget* C builtins):
  <Button>, <Checkbox>, <Radio>, <Toggle>, <TextInput />,
  <Slider />, <MenuItem>, <TabButton>, <NumberStepper />,
  <SearchBar />, <ListItem>

Box props:
  id="name"           → element id (default "")
  grow                → w=CLAY_GROW, h=CLAY_GROW
  growX               → w=CLAY_GROW
  growY               → h=CLAY_GROW
  w={200}             → fixed width
  h={56}              → fixed height
  padding={16}        → all sides
  padding={[t,r,b,l]} → individual sides
  gap={8}             → child gap
  vertical            → CLAY_TOP_TO_BOTTOM (default: CLAY_LEFT_TO_RIGHT)
  bg={[r,g,b]} or bg={[r,g,b,a]}
  radius={8}          → corner radius
  border={[r,g,b]}    → border color
  scroll              → enable vertical scroll
  scrollH             → enable horizontal scroll

Text props:
  size={24}           → font size
  font={0}            → font id (default 0)
  color={[r,g,b]} or color={[r,g,b,a]}
"""

from __future__ import annotations

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Parser, Node

JS_LANGUAGE = Language(ts_js.language())

# ── Layout tag defaults ──────────────────────────────────────────────
# Each entry maps a tag name to default props that are merged with user props.
# User-specified props override these defaults.

_LAYOUT_DEFAULTS: dict[str, dict[str, str | None]] = {
    # Layout containers
    "VPanel": {"grow": None, "vertical": None},
    "HPanel": {"growX": None},
    "Row": {"grow": None},  # horizontal full-height row
    "CPanel": {"grow": None, "vertical": None},  # centered panel
    "FixedPanel": {"vertical": None},  # w/h from user props
    "ScrollPanel": {"grow": None, "vertical": None},
    "ScrollHPanel": {"growX": None},
    # Styled containers
    "Card": {"growX": None, "vertical": None, "padding": "12", "gap": "8",
             "bg": "[36,36,48,255]", "radius": "8"},
    "Header": {"growX": None, "padding": "[8,16,8,16]", "gap": "8",
               "bg": "[60,100,180,255]"},
    "Footer": {"growX": None, "padding": "[8,16,8,16]", "gap": "8",
               "bg": "[36,36,48,255]"},
    "Sidebar": {"growY": None, "vertical": None, "padding": "12", "gap": "4",
                "w": "200", "bg": "[36,36,48,255]"},
    "Modal": {"vertical": None, "padding": "16", "gap": "8",
              "bg": "[44,44,60,255]", "radius": "8"},
    # Grid
    "GridRow": {"growX": None},
    "GridItem": {"vertical": None},
    # ZStack
    "ZStack": {"grow": None, "vertical": None},
    "ZStackLayer": {"grow": None, "vertical": None},
    # Tab
    "TabBar": {"growX": None, "bg": "[36,36,48,255]"},
    "TabContent": {"grow": None, "vertical": None, "padding": "8", "gap": "4"},
    # Status bar
    "StatusBar": {"growX": None, "padding": "[4,8,4,8]", "gap": "0",
                  "bg": "[36,36,48,255]"},
    # Table
    "Table": {"growX": None, "vertical": None},
    "TableHeader": {"growX": None, "bg": "[60,100,180,255]", "padding": "[4,8,4,8]", "gap": "4"},
    "TableCell": {"vertical": None, "padding": "[4,8,4,8]"},
    "ListSection": {"growX": None, "padding": "[6,8,6,8]", "bg": "[44,44,60,255]"},
    # Segments/Nav
    "SegmentedControl": {"growX": None, "bg": "[36,36,48,255]"},
    "NavBar": {"growX": None, "padding": "[8,16,8,16]", "gap": "8", "bg": "[36,36,48,255]"},
    "BottomNav": {"growX": None, "padding": "[4,8,4,8]", "bg": "[36,36,48,255]"},
}

# Tags that need special post-open handling
_SCROLL_TAGS = {"ScrollPanel", "ScrollHPanel"}
_FLOATING_TAGS = {"Modal", "ZStackLayer"}

# All tags recognized as Clay JSX (layout + display + interactive)
CLAY_JSX_TAGS = (
    {"Box", "Text"}
    | set(_LAYOUT_DEFAULTS.keys())
    | {"Spacer", "Divider", "ProgressBar", "Badge", "Avatar", "AspectPanel", "PctPanel"}
    | {"Button", "Checkbox", "Radio", "Toggle", "TextInput",
       "Slider", "MenuItem", "TabButton", "NumberStepper",
       "SearchBar", "ListItem"}
    # Part 2A - Data display
    | {"Table", "TableHeader", "TableRow", "TableCell", "ProgressSteps",
       "ListSection", "Skeleton", "CircularProgress", "CarouselDots",
       "TimelineItem", "TimelineConnector", "SortableHeader", "ImagePlaceholder"}
    # Part 2B - Forms
    | {"Textarea", "Switch", "Rating", "ColorPicker", "DatePicker",
       "SegmentedControl", "SegmentButton"}
    # Part 2C - Navigation
    | {"NavBar", "BottomNav", "BottomNavItem", "Drawer", "BottomSheet"}
    # Part 2D - Overlay
    | {"Accordion", "Dropdown", "DropdownItem", "Tooltip", "Toast",
       "ContextMenu", "AlertDialog", "ConfirmDialog"}
    # Part 2E - Charts
    | {"BarChart", "LineChart", "PieChart"}
    # Part 2F - Markdown
    | {"Markdown"}
    # Part 2G - Other
    | {"Spinner"}
)


def transform_clay_jsx(source: str, tui: bool = False) -> str:
    """Transform Clay JSX (<Box>, <Text>, UI widgets) to Clay imperative API calls.

    When tui=True, emits clayTui* calls (termbox2 backend) instead of clay* (raylib).
    """
    parser = Parser(JS_LANGUAGE)
    tree = parser.parse(source.encode("utf-8"))
    src_bytes = source.encode("utf-8")
    result: list[str] = []
    prefix = "clayTui" if tui else "clay"
    _emit_node(tree.root_node, src_bytes, result, prefix)
    return "".join(result)


def _emit_node(node: Node, src: bytes, out: list[str], prefix: str = "clay"):
    """Recursively emit node, transforming Clay JSX elements."""
    if node.type == "jsx_element":
        _transform_element(node, src, out, prefix)
        return
    if node.type == "jsx_self_closing_element":
        _transform_self_closing(node, src, out, prefix)
        return

    if not node.children:
        out.append(node.text.decode())
        return

    prev_end = node.start_byte
    for child in node.children:
        gap = src[prev_end:child.start_byte].decode()
        out.append(gap)
        _emit_node(child, src, out, prefix)
        prev_end = child.end_byte
    gap = src[prev_end:node.end_byte].decode()
    out.append(gap)


def _get_tag_name(node: Node) -> str:
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode()
    return ""


def _parse_props(opening: Node, src: bytes) -> dict[str, str | None]:
    """Parse JSX attributes into a dict. Boolean props have value None."""
    props: dict[str, str | None] = {}
    for child in opening.children:
        if child.type == "jsx_attribute":
            name = ""
            value = None
            for c in child.children:
                if c.type == "property_identifier":
                    name = c.text.decode()
                elif c.type == "=":
                    continue
                elif c.type == "string":
                    value = c.text.decode()  # includes quotes
                elif c.type == "jsx_expression":
                    # Extract content between { and }
                    parts = []
                    for sc in c.children:
                        if sc.type not in ("{", "}"):
                            parts.append(sc.text.decode())
                    value = "".join(parts)
            if name:
                props[name] = value
    return props


# ── CSS style prop support ────────────────────────────────────────────

# CSS property name → existing prop name mapping
_CSS_PROP_MAP = {
    "backgroundColor": "bg",
    "padding": "padding",
    "paddingTop": "pt",
    "paddingRight": "pr",
    "paddingBottom": "pb",
    "paddingLeft": "pl",
    "gap": "gap",
    "borderRadius": "radius",
    "width": "w",
    "height": "h",
    "color": "color",
    "fontSize": "size",
}

# Properties that should have color parsing applied
_CSS_COLOR_PROPS = {"backgroundColor", "bg", "color"}


def _parse_css_color(value: str) -> str:
    """Convert CSS color string to [R,G,B] or [R,G,B,A] array literal.

    Supports: "#RGB", "#RRGGBB", "#RRGGBBAA", "rgb(R,G,B)", "rgba(R,G,B,A)".
    Passes through [R,G,B] arrays and expressions unchanged.
    """
    v = value.strip().strip('"').strip("'")

    if v.startswith("#"):
        h = v[1:]
        try:
            if len(h) == 3:
                r, g, b = int(h[0], 16) * 17, int(h[1], 16) * 17, int(h[2], 16) * 17
                return f"[{r},{g},{b}]"
            elif len(h) == 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return f"[{r},{g},{b}]"
            elif len(h) == 8:
                r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
                return f"[{r},{g},{b},{a}]"
        except ValueError:
            pass
        return value

    if v.startswith("rgb(") and v.endswith(")"):
        parts = [p.strip() for p in v[4:-1].split(",")]
        if len(parts) == 3:
            return f"[{parts[0]},{parts[1]},{parts[2]}]"

    if v.startswith("rgba(") and v.endswith(")"):
        parts = [p.strip() for p in v[5:-1].split(",")]
        if len(parts) == 4:
            return f"[{parts[0]},{parts[1]},{parts[2]},{parts[3]}]"

    return value


def _parse_style_object(s: str) -> dict[str, str]:
    """Parse JS object literal '{bg: "#181820", padding: 16}' into dict.

    Handles quoted/unquoted keys, string/number/array values.
    """
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    result: dict[str, str] = {}

    # Split on commas at top level
    pairs: list[str] = []
    current: list[str] = []
    depth = 0
    in_str = False
    str_ch = ""

    for ch in s:
        if in_str:
            current.append(ch)
            if ch == str_ch:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            str_ch = ch
            current.append(ch)
        elif ch in ("{", "[", "("):
            depth += 1
            current.append(ch)
        elif ch in ("}", "]", ")"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            pairs.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        rest = "".join(current).strip()
        if rest:
            pairs.append(rest)

    for pair in pairs:
        colon_idx = pair.find(":")
        if colon_idx == -1:
            continue
        key = pair[:colon_idx].strip().strip('"').strip("'")
        value = pair[colon_idx + 1:].strip()
        result[key] = value

    return result


def _apply_style_prop(props: dict[str, str | None]) -> None:
    """Extract style={{...}} and merge CSS properties into props.

    style={{bg: "#181820", padding: 16}} → props["bg"]="[24,24,32]", props["padding"]="16"
    """
    style_str = props.get("style")
    if style_str is None:
        return
    # Only process CSS object styles (starts with '{'), not packed integer styles
    if not style_str.strip().startswith("{"):
        return
    props.pop("style")

    style = _parse_style_object(style_str)

    for css_key, css_val in style.items():
        # flexDirection: "column" → vertical boolean prop
        if css_key == "flexDirection":
            val = css_val.strip().strip('"').strip("'")
            if val == "column":
                props.setdefault("vertical", None)
            continue

        # flexGrow: 1 / flex: 1 → grow boolean prop
        if css_key in ("flexGrow", "flex"):
            if css_val.strip() in ("1", "true"):
                props.setdefault("grow", None)
            continue

        # overflow: "scroll" → scroll boolean prop
        if css_key == "overflow":
            val = css_val.strip().strip('"').strip("'")
            if val == "scroll":
                props.setdefault("scroll", None)
            continue

        # alignItems → stored as _align_y for _emit_box_open
        if css_key == "alignItems":
            val = css_val.strip().strip('"').strip("'")
            if val == "center":
                props["_align_y"] = "2"
            elif val in ("flex-end", "end"):
                props["_align_y"] = "1"
            continue

        # justifyContent → stored as _align_x for _emit_box_open
        if css_key == "justifyContent":
            val = css_val.strip().strip('"').strip("'")
            if val == "center":
                props["_align_x"] = "2"
            elif val in ("flex-end", "end"):
                props["_align_x"] = "1"
            continue

        # Standard CSS → prop mapping
        prop_name = _CSS_PROP_MAP.get(css_key, css_key)

        # Apply color parsing for color properties
        if css_key in _CSS_COLOR_PROPS or prop_name in ("bg", "color"):
            css_val = _parse_css_color(css_val)

        # Don't override explicitly set props
        if prop_name not in props:
            props[prop_name] = css_val


def _parse_array_literal(s: str) -> list[str]:
    """Parse "[1, 2, 3]" into ["1", "2", "3"].

    Handles nested expressions like ternaries: [a ? 1 : 2, b ? 3 : 4].
    Only splits on commas at bracket depth 0 and paren depth 0.
    """
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    parts: list[str] = []
    current: list[str] = []
    depth = 0  # tracks [] and () nesting
    for ch in s:
        if ch in ("(", "["):
            depth += 1
            current.append(ch)
        elif ch in (")", "]"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        rest = "".join(current).strip()
        if rest:
            parts.append(rest)
    return parts


def _merge_defaults(tag: str, props: dict[str, str | None]) -> dict[str, str | None]:
    """Merge layout defaults with user-specified props (user wins)."""
    defaults = _LAYOUT_DEFAULTS.get(tag)
    if defaults is None:
        return props
    merged = dict(defaults)
    merged.update(props)
    return merged


def _transform_element(node: Node, src: bytes, out: list[str], prefix: str = "clay"):
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

    tag = _get_tag_name(opening)
    props = _parse_props(opening, src)
    _apply_style_prop(props)

    close_fn = f"{prefix}CloseElement" if prefix == "clayTui" else f"{prefix}Close"

    if tag == "Text":
        _emit_text(props, children, src, out, prefix)
        out.append(";\n")
        return

    # ── Interactive widgets ──
    if tag in _INTERACTIVE_HANDLERS:
        _INTERACTIVE_HANDLERS[tag](tag, props, children, src, out, prefix, close_fn)
        return

    # ── Layout containers (merge defaults) ──
    merged = _merge_defaults(tag, props)

    # CPanel: centered both axes
    if tag == "CPanel":
        _emit_box_open(merged, out, prefix, align_x="2", align_y="2")
    # PctPanel: percentage sizing
    elif tag == "PctPanel":
        _emit_pct_panel(merged, out, prefix)
    # AspectPanel: fixed aspect ratio
    elif tag == "AspectPanel":
        _emit_aspect_panel(merged, out, prefix)
    # Badge: inline styled text container
    elif tag == "Badge":
        _emit_badge(merged, children, src, out, prefix, close_fn)
        return
    # Avatar: square box with centered text
    elif tag == "Avatar":
        _emit_avatar(merged, children, src, out, prefix, close_fn)
        return
    else:
        _emit_box_open(merged, out, prefix)
    out.append(";\n")

    # Post-open extras: scroll
    if tag in _SCROLL_TAGS:
        if tag == "ScrollPanel":
            out.append(f"{prefix}Scroll(0, 1);\n")
        else:
            out.append(f"{prefix}Scroll(1, 0);\n")
    elif "scroll" in merged and merged["scroll"] is None:
        out.append(f"{prefix}Scroll(0, 1);\n")
    elif "scrollH" in merged and merged["scrollH"] is None:
        out.append(f"{prefix}Scroll(1, 0);\n")

    if tag == "ZStackLayer":
        z = merged.get("z", "1") or "1"
        out.append(f"{prefix}Floating(0, 0, {z});\n")
    elif tag == "Modal":
        out.append(f"{prefix}Floating(0, 0, 100);\n")

    if "border" in merged and merged["border"] is not None:
        bparts = _parse_array_literal(merged["border"])
        if len(bparts) >= 3:
            br, bg_, bb = bparts[0], bparts[1], bparts[2]
            out.append(f"{prefix}Border({br}, {bg_}, {bb}, 255, 1, 1, 1, 1, 0);\n")

    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f"{close_fn}();\n")


def _transform_self_closing(node: Node, src: bytes, out: list[str], prefix: str = "clay"):
    tag = _get_tag_name(node)
    props = _parse_props(node, src)
    _apply_style_prop(props)

    close_fn = f"{prefix}CloseElement" if prefix == "clayTui" else f"{prefix}Close"

    if tag == "Text":
        _emit_text(props, [], src, out, prefix)
        out.append(";\n")
        return

    # ── Self-closing interactive widgets ──
    if tag in _INTERACTIVE_HANDLERS:
        _INTERACTIVE_HANDLERS[tag](tag, props, [], src, out, prefix, close_fn)
        return

    # ── Self-closing display widgets ──
    if tag == "Spacer":
        _emit_spacer(out, prefix, close_fn)
        return

    if tag == "Divider":
        _emit_divider(props, out, prefix, close_fn)
        return

    if tag == "ProgressBar":
        _emit_progress_bar(props, out, prefix, close_fn)
        return

    # Generic self-closing Box or layout
    merged = _merge_defaults(tag, props)
    _emit_box_open(merged, out, prefix)
    out.append(";\n")
    out.append(f"{close_fn}();\n")


# ── Box emission ──────────────────────────────────────────────────────

def _emit_box_open(props: dict[str, str | None], out: list[str], prefix: str = "clay",
                   align_x: str = "0", align_y: str = "0"):
    """Emit clayOpen(...) or clayOpenAligned(...) from Box props."""
    # Check for alignment from style={{alignItems/justifyContent}}
    if align_x == "0" and "_align_x" in props:
        align_x = props.pop("_align_x")
    if align_y == "0" and "_align_y" in props:
        align_y = props.pop("_align_y")

    # id
    eid = props.get("id")
    if eid is not None:
        # eid is a quoted string like '"root"'
        id_str = eid
    else:
        id_str = '""'

    # sizing
    has_grow = "grow" in props and props["grow"] is None
    w = "CLAY_GROW" if has_grow or ("growX" in props and props["growX"] is None) else "0"
    h = "CLAY_GROW" if has_grow or ("growY" in props and props["growY"] is None) else "0"

    if "w" in props and props["w"] is not None:
        w = props["w"]
    if "h" in props and props["h"] is not None:
        h = props["h"]

    # padding
    pt, pr, pb, pl = "0", "0", "0", "0"
    pad = props.get("padding")
    if pad is not None:
        if pad.strip().startswith("["):
            parts = _parse_array_literal(pad)
            if len(parts) == 4:
                pt, pr, pb, pl = parts
            elif len(parts) == 2:
                pt = pb = parts[0]
                pr = pl = parts[1]
            elif len(parts) == 1:
                pt = pr = pb = pl = parts[0]
        else:
            pt = pr = pb = pl = pad.strip()

    # Individual padding overrides
    if "pt" in props and props["pt"] is not None:
        pt = props["pt"]
    if "pr" in props and props["pr"] is not None:
        pr = props["pr"]
    if "pb" in props and props["pb"] is not None:
        pb = props["pb"]
    if "pl" in props and props["pl"] is not None:
        pl = props["pl"]

    # gap
    gap = props.get("gap", "0") or "0"

    # direction
    vertical = "vertical" in props and props["vertical"] is None
    direction = "CLAY_TOP_TO_BOTTOM" if vertical else "CLAY_LEFT_TO_RIGHT"

    # bg color
    bgR, bgG, bgB, bgA = "0", "0", "0", "0"
    bg = props.get("bg")
    if bg is not None:
        parts = _parse_array_literal(bg)
        if len(parts) >= 3:
            bgR, bgG, bgB = parts[0], parts[1], parts[2]
            bgA = parts[3] if len(parts) >= 4 else "255"

    # corner radius
    radius = props.get("radius", "0") or "0"

    if align_x != "0" or align_y != "0":
        out.append(f"{prefix}OpenAligned({id_str}, {w}, {h}, {pt}, {pr}, {pb}, {pl}, {gap}, {direction}, {bgR}, {bgG}, {bgB}, {bgA}, {radius}, {align_x}, {align_y})")
    else:
        out.append(f"{prefix}Open({id_str}, {w}, {h}, {pt}, {pr}, {pb}, {pl}, {gap}, {direction}, {bgR}, {bgG}, {bgB}, {bgA}, {radius})")


# ── Text emission ─────────────────────────────────────────────────────

def _emit_text(props: dict[str, str | None], children: list[Node],
               src: bytes, out: list[str], prefix: str = "clay"):
    """Emit clayText(...) from Text props and text content."""
    # Collect text content from children
    text_parts: list[str] = []
    for child in children:
        if child.type == "jsx_text":
            t = child.text.decode().strip()
            if t:
                text_parts.append(t)
        elif child.type == "jsx_expression":
            # {expr} — dynamic text
            for c in child.children:
                if c.type not in ("{", "}"):
                    text_parts.append(c.text.decode())

    # If there's a "text" prop, use that instead
    text_prop = props.get("text")

    if text_prop is not None:
        text_str = text_prop
    elif len(text_parts) == 1 and children:
        # Single child — check if it was a {expression} or literal text
        child = children[0]
        if child.type == "jsx_expression":
            # Dynamic: {variable} or {expr} — pass as-is
            text_str = text_parts[0]
        else:
            # Literal text
            escaped = text_parts[0].replace("\\", "\\\\").replace('"', '\\"')
            text_str = f'"{escaped}"'
    elif text_parts:
        # Multiple parts — concatenation with +
        parts_out = []
        for child in children:
            if child.type == "jsx_text":
                t = child.text.decode().strip()
                if t:
                    escaped = t.replace("\\", "\\\\").replace('"', '\\"')
                    parts_out.append(f'"{escaped}"')
            elif child.type == "jsx_expression":
                for c in child.children:
                    if c.type not in ("{", "}"):
                        parts_out.append(c.text.decode())
        text_str = " + ".join(parts_out) if parts_out else '""'
    else:
        text_str = '""'

    size = props.get("size", "16") or "16"
    font = props.get("font", "0") or "0"

    # color
    r, g, b, a = "255", "255", "255", "255"
    color = props.get("color")
    if color is not None:
        parts = _parse_array_literal(color)
        if len(parts) >= 3:
            r, g, b = parts[0], parts[1], parts[2]
            a = parts[3] if len(parts) >= 4 else "255"

    out.append(f"{prefix}Text({text_str}, {size}, {font}, {r}, {g}, {b}, {a})")


def _contains_jsx(node: Node) -> bool:
    """Recursively check if a tree-sitter node contains JSX elements."""
    if node.type in ("jsx_element", "jsx_self_closing_element"):
        return True
    for c in node.children:
        if _contains_jsx(c):
            return True
    return False


def _emit_ternary_as_if_else(node: Node, src: bytes, out: list[str], prefix: str):
    """Emit ternary_expression as if/else when it contains JSX.

    condition ? <JSX> : alt  →  if (condition) { <JSX> } else { alt }
    """
    condition = None
    consequence = None
    alternative = None
    state = "cond"
    for c in node.children:
        if c.type == "?":
            state = "then"
            continue
        if c.type == ":":
            state = "else"
            continue
        if state == "cond":
            condition = c
        elif state == "then":
            consequence = c
        elif state == "else":
            alternative = c

    if condition is None or consequence is None:
        # Fallback: emit as raw expression
        _emit_node(node, src, out, prefix)
        out.append(";\n")
        return

    out.append("if (")
    _emit_node(condition, src, out, prefix)
    out.append(") {\n")
    if consequence.type in ("jsx_element", "jsx_self_closing_element"):
        _emit_node(consequence, src, out, prefix)
    elif consequence.type == "parenthesized_expression":
        # Unwrap parens: ( <JSX> ) → emit inner children
        for inner in consequence.children:
            if inner.type in ("(", ")"):
                continue
            _emit_node(inner, src, out, prefix)
    else:
        _emit_node(consequence, src, out, prefix)
        out.append(";\n")
    out.append("} else {\n")
    if alternative is not None:
        if alternative.type in ("jsx_element", "jsx_self_closing_element"):
            _emit_node(alternative, src, out, prefix)
        elif alternative.type == "parenthesized_expression" and _contains_jsx(alternative):
            for inner in alternative.children:
                if inner.type in ("(", ")"):
                    continue
                _emit_node(inner, src, out, prefix)
        else:
            _emit_node(alternative, src, out, prefix)
            out.append(";\n")
    out.append("}\n")


def _emit_child(child: Node, src: bytes, out: list[str], prefix: str = "clay"):
    """Emit a child node, skipping whitespace-only text."""
    if child.type == "jsx_text":
        t = child.text.decode().strip()
        if not t:
            return
    if child.type == "jsx_expression":
        # {expr} — emit just the expression as a statement
        for c in child.children:
            if c.type not in ("{", "}"):
                # Ternary with JSX inside → emit as if/else to avoid
                # semicolons inside expression context
                if c.type == "ternary_expression" and _contains_jsx(c):
                    _emit_ternary_as_if_else(c, src, out, prefix)
                else:
                    _emit_node(c, src, out, prefix)
                    out.append(";\n")
        return
    _emit_node(child, src, out, prefix)


# ── Display widget emitters ──────────────────────────────────────────

def _emit_spacer(out: list[str], prefix: str, close_fn: str):
    """Emit a spacer element (grow both axes, no content)."""
    out.append(f'{prefix}Open("", CLAY_GROW, CLAY_GROW, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    out.append(f"{close_fn}();\n")


def _emit_divider(props: dict[str, str | None], out: list[str], prefix: str, close_fn: str):
    """Emit a divider line (growX, h=1, bg=border color)."""
    # Default: horizontal divider (growX, h=1)
    vertical = "vertical" in props and props["vertical"] is None
    if vertical:
        w, h = "1", "CLAY_GROW"
    else:
        w, h = "CLAY_GROW", "1"

    # color
    r, g, b = "80", "80", "100"
    color = props.get("color")
    if color is not None:
        parts = _parse_array_literal(color)
        if len(parts) >= 3:
            r, g, b = parts[0], parts[1], parts[2]

    out.append(f'{prefix}Open("", {w}, {h}, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, {r},{g},{b},255, 0);\n')
    out.append(f"{close_fn}();\n")


def _emit_progress_bar(props: dict[str, str | None], out: list[str], prefix: str, close_fn: str):
    """Emit a progress bar with background + fill."""
    w = props.get("w", "200") or "200"
    h = props.get("h", "8") or "8"
    value = props.get("value", "0") or "0"
    max_val = props.get("max", "100") or "100"

    # Fill color (default: green)
    fr, fg_, fb = "80", "200", "120"
    color = props.get("color")
    if color is not None:
        parts = _parse_array_literal(color)
        if len(parts) >= 3:
            fr, fg_, fb = parts[0], parts[1], parts[2]

    # Background bar
    out.append(f'{prefix}Open("", {w}, {h}, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, 40,40,50,255, 4);\n')
    # Fill bar (computed width)
    out.append(f'{prefix}Open("", (({value}) * ({w}) / ({max_val})), {h}, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, {fr},{fg_},{fb},255, 4);\n')
    out.append(f"{close_fn}();\n")
    out.append(f"{close_fn}();\n")


def _emit_badge(props: dict[str, str | None], children: list[Node],
                src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit a badge (small colored indicator label)."""
    # Default accent color
    bg_r, bg_g, bg_b = "100", "80", "200"
    bg = props.get("bg")
    if bg is not None:
        parts = _parse_array_literal(bg)
        if len(parts) >= 3:
            bg_r, bg_g, bg_b = parts[0], parts[1], parts[2]

    # Kind-based colors
    kind = props.get("kind")
    if kind is not None:
        k = kind.strip("'\"")
        if k == "success":
            bg_r, bg_g, bg_b = "80", "200", "120"
        elif k == "warning":
            bg_r, bg_g, bg_b = "220", "180", "80"
        elif k == "error" or k == "danger":
            bg_r, bg_g, bg_b = "220", "80", "80"
        elif k == "info":
            bg_r, bg_g, bg_b = "80", "140", "220"

    size = props.get("size", "12") or "12"

    out.append(f'{prefix}Open("", 0, 0, 4,8,4,8, 0, CLAY_LEFT_TO_RIGHT, {bg_r},{bg_g},{bg_b},255, 4);\n')
    # Emit text children
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"{close_fn}();\n")


def _emit_avatar(props: dict[str, str | None], children: list[Node],
                 src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit an avatar (square box with centered initial)."""
    size = props.get("size", "32") or "32"
    bg_r, bg_g, bg_b = "60", "100", "180"
    bg = props.get("bg")
    if bg is not None:
        parts = _parse_array_literal(bg)
        if len(parts) >= 3:
            bg_r, bg_g, bg_b = parts[0], parts[1], parts[2]

    half_size = f"(({size}) / 2)"
    out.append(f'{prefix}Open("", {size}, {size}, 0,0,0,0, 0, CLAY_TOP_TO_BOTTOM, {bg_r},{bg_g},{bg_b},255, {size});\n')
    if children:
        _emit_text_from_children(children, src, out, prefix, half_size, center=True)
    out.append(f"{close_fn}();\n")


def _emit_pct_panel(props: dict[str, str | None], out: list[str], prefix: str):
    """Emit a percentage-width panel."""
    # PctPanel uses percentage sizing — we approximate via large fixed values
    # since Clay supports percentage sizing types
    wpct = props.get("wpct", "100") or "100"
    hpct = props.get("hpct")
    merged = dict(props)
    # For now, approximate: just use growX and let user control via parent sizing
    if "growX" not in merged and "w" not in merged:
        merged["growX"] = None
    if hpct and "growY" not in merged and "h" not in merged:
        merged["growY"] = None
    _emit_box_open(merged, out, prefix)


def _emit_aspect_panel(props: dict[str, str | None], out: list[str], prefix: str):
    """Emit a fixed aspect ratio panel."""
    w = props.get("w", "200") or "200"
    ratio = props.get("ratio", "75") or "75"  # height per 100 width units
    merged = dict(props)
    merged["w"] = w
    merged["h"] = f"(({w}) * ({ratio}) / 100)"
    if "vertical" not in merged:
        merged["vertical"] = None
    _emit_box_open(merged, out, prefix)


# ── Interactive widget emitters ──────────────────────────────────────

def _get_packed_style(props: dict[str, str | None]) -> str | None:
    """Extract packed style value if style prop is a non-object expression.

    Returns the expression string for packed integer style, or None if
    the style is a CSS object or not present.
    """
    style = props.get("style")
    if style is None:
        return None
    s = style.strip()
    # CSS object style starts with '{' — already handled by _apply_style_prop
    if s.startswith("{"):
        return None
    return s


def _emit_text_from_children(children: list[Node], src: bytes, out: list[str],
                             prefix: str, size: str = "16", center: bool = False):
    """Emit text elements from child nodes."""
    text_parts = []
    for child in children:
        if child.type == "jsx_text":
            t = child.text.decode().strip()
            if t:
                text_parts.append(("literal", t))
        elif child.type == "jsx_expression":
            for c in child.children:
                if c.type not in ("{", "}"):
                    text_parts.append(("expr", c.text.decode()))

    if len(text_parts) == 1:
        kind, val = text_parts[0]
        if kind == "expr":
            out.append(f"{prefix}Text({val}, {size}, 0, 255, 255, 255, 255);\n")
        else:
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            out.append(f'{prefix}Text("{escaped}", {size}, 0, 255, 255, 255, 255);\n')
    elif text_parts:
        parts_out = []
        for kind, val in text_parts:
            if kind == "expr":
                parts_out.append(val)
            else:
                escaped = val.replace("\\", "\\\\").replace('"', '\\"')
                parts_out.append(f'"{escaped}"')
        text_str = " + ".join(parts_out)
        out.append(f"{prefix}Text({text_str}, {size}, 0, 255, 255, 255, 255);\n")


def _emit_button(tag: str, props: dict[str, str | None], children: list[Node],
                 src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <Button> as buttonOpen/buttonClose C builtins.

    Supports packed style: <Button style={s}> where s = uiStyle(size, kind, flex).
    """
    eid = props.get("id", '""') or '""'

    # Packed style support: style={expr} (non-object) → unpack size/kind/flex
    packed = _get_packed_style(props)
    if packed is not None:
        out.append(f"buttonOpen({eid}, uiStyleKind({packed}), uiStyleSize({packed}), uiStyleFlex({packed}));\n")
        size = f"uiStyleSize({packed})"
        if children:
            _emit_text_from_children(children, src, out, prefix, size)
        out.append(f"buttonClose();\n")
        return

    size = props.get("size", "16") or "16"

    # kind: 0=default, 1=primary, 2=success, 3=warning, 4=danger
    kind_val = "0"
    kind = props.get("kind")
    if kind is not None:
        k = kind.strip("'\"")
        kind_map = {"default": "0", "primary": "1", "success": "2",
                    "warning": "3", "danger": "4"}
        kind_val = kind_map.get(k, "0")

    # flex: 0=FIT, -1=GROW both, >0=percentage width + GROW height
    flex_val = props.get("flex")
    if flex_val is not None:
        flex_str = flex_val
    elif "grow" in props and props["grow"] is None:
        flex_str = "-1"
    else:
        flex_str = "0"

    out.append(f"buttonOpen({eid}, {kind_val}, {size}, {flex_str});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"buttonClose();\n")


def _emit_checkbox(tag: str, props: dict[str, str | None], children: list[Node],
                   src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <Checkbox> as checkboxOpen/checkboxClose."""
    eid = props.get("id", '""') or '""'
    checked = props.get("checked", "0") or "0"
    size = props.get("size", "16") or "16"

    out.append(f"checkboxOpen({eid}, {checked}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"checkboxClose();\n")


def _emit_radio(tag: str, props: dict[str, str | None], children: list[Node],
                src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <Radio> as radioOpen/radioClose."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    selected = props.get("selected", "0") or "0"
    size = props.get("size", "16") or "16"

    out.append(f"radioOpen({eid}, {index}, {selected}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"radioClose();\n")


def _emit_toggle(tag: str, props: dict[str, str | None], children: list[Node],
                 src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <Toggle> as toggleOpen/toggleClose."""
    eid = props.get("id", '""') or '""'
    on = props.get("on", "0") or "0"
    size = props.get("size", "16") or "16"

    out.append(f"toggleOpen({eid}, {on}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"toggleClose();\n")


def _emit_text_input(tag: str, props: dict[str, str | None], children: list[Node],
                     src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <TextInput /> as textInput call."""
    eid = props.get("id", '""') or '""'
    buf = props.get("buf", "0") or "0"
    w = props.get("w", "200") or "200"
    size = props.get("size", "16") or "16"

    out.append(f"textInput({eid}, {buf}, {w}, {size});\n")


def _emit_slider(tag: str, props: dict[str, str | None], children: list[Node],
                 src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <Slider /> as slider call."""
    eid = props.get("id", '""') or '""'
    value = props.get("value", "0") or "0"
    min_val = props.get("min", "0") or "0"
    max_val = props.get("max", "100") or "100"
    w = props.get("w", "200") or "200"

    out.append(f"slider({eid}, {value}, {min_val}, {max_val}, {w});\n")


def _emit_menu_item(tag: str, props: dict[str, str | None], children: list[Node],
                    src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <MenuItem> as menuItemOpen/menuItemClose."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    cursor = props.get("cursor", "0") or "0"
    size = props.get("size", "16") or "16"

    out.append(f"menuItemOpen({eid}, {index}, {cursor}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"menuItemClose();\n")


def _emit_tab_button(tag: str, props: dict[str, str | None], children: list[Node],
                     src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <TabButton> as tabButtonOpen/tabButtonClose."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    active = props.get("active", "0") or "0"
    size = props.get("size", "16") or "16"

    out.append(f"tabButtonOpen({eid}, {index}, {active}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"tabButtonClose();\n")


def _emit_number_stepper(tag: str, props: dict[str, str | None], children: list[Node],
                         src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <NumberStepper /> as numberStepper call."""
    eid = props.get("id", '""') or '""'
    value = props.get("value", "0") or "0"
    min_val = props.get("min", "0") or "0"
    max_val = props.get("max", "100") or "100"
    size = props.get("size", "16") or "16"

    out.append(f"numberStepper({eid}, {value}, {min_val}, {max_val}, {size});\n")


def _emit_search_bar(tag: str, props: dict[str, str | None], children: list[Node],
                     src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <SearchBar /> as searchBar call."""
    eid = props.get("id", '""') or '""'
    buf = props.get("buf", "0") or "0"
    w = props.get("w", "200") or "200"
    size = props.get("size", "16") or "16"

    out.append(f"searchBar({eid}, {buf}, {w}, {size});\n")


def _emit_list_item(tag: str, props: dict[str, str | None], children: list[Node],
                    src: bytes, out: list[str], prefix: str, close_fn: str):
    """Emit <ListItem> as listItemOpen/listItemClose."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    selected = props.get("selected", "0") or "0"
    size = props.get("size", "16") or "16"

    out.append(f"listItemOpen({eid}, {index}, {selected}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"listItemClose();\n")


# ── Part 2A: Data display widget emitters ─────────────────────────────

def _emit_table_row(tag, props, children, src, out, prefix, close_fn):
    """Emit <TableRow> with alternating background based on index prop."""
    index = props.get("index", "0") or "0"
    merged = dict(props)
    merged["growX"] = None
    merged.setdefault("padding", "[2,8,2,8]")
    merged.setdefault("gap", "4")
    # Alternating bg: even=transparent, odd=surface2
    out.append(f'if (({index}) % 2 === 1) {{\n')
    merged_odd = dict(merged)
    merged_odd["bg"] = "[36,36,48,255]"
    _emit_box_open(merged_odd, out, prefix)
    out.append(f';\n}} else {{\n')
    _emit_box_open(merged, out, prefix)
    out.append(f';\n}}\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f"{close_fn}();\n")


def _emit_progress_steps(tag, props, children, src, out, prefix, close_fn):
    """Emit <ProgressSteps current={2} total={5} /> as text like (1)--(2)--(3)--4--5."""
    current = props.get("current", "0") or "0"
    total = props.get("total", "3") or "3"
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Open("", 0, 0, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    out.append(f'{prefix}Text("Steps: " + String({current}) + "/" + String({total}), {size}, 0, 180, 180, 200, 255);\n')
    out.append(f"{close_fn}();\n")


def _emit_skeleton(tag, props, children, src, out, prefix, close_fn):
    """Emit <Skeleton /> as a gray placeholder box."""
    w = props.get("w", "200") or "200"
    h = props.get("h", "16") or "16"
    radius = props.get("radius", "4") or "4"
    out.append(f'{prefix}Open("", {w}, {h}, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, 50,50,64,255, {radius});\n')
    out.append(f"{close_fn}();\n")


def _emit_circular_progress(tag, props, children, src, out, prefix, close_fn):
    """Emit <CircularProgress value={75} /> as text [75%]."""
    value = props.get("value", "0") or "0"
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Text("[" + String({value}) + "%]", {size}, 0, 120, 180, 255, 255);\n')


def _emit_carousel_dots(tag, props, children, src, out, prefix, close_fn):
    """Emit <CarouselDots current={1} total={5} /> as dot indicators."""
    current = props.get("current", "0") or "0"
    total = props.get("total", "3") or "3"
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Open("", 0, 0, 4,4,4,4, 4, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    # Generate dots using a loop-like pattern
    out.append(f'{{ let __cd_i = 0; while (__cd_i < {total}) {{ if (__cd_i === {current}) {{ {prefix}Text("o", {size}, 0, 120, 180, 255, 255); }} else {{ {prefix}Text(".", {size}, 0, 80, 80, 100, 255); }} __cd_i = __cd_i + 1; }} }}\n')
    out.append(f"{close_fn}();\n")


def _emit_timeline_item(tag, props, children, src, out, prefix, close_fn):
    """Emit <TimelineItem> as HPanel with bullet prefix."""
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Open("", -1, 0, 2,8,2,8, 4, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    out.append(f'{prefix}Text("* ", {size}, 0, 120, 180, 255, 255);\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f"{close_fn}();\n")


def _emit_timeline_connector(tag, props, children, src, out, prefix, close_fn):
    """Emit <TimelineConnector /> as vertical line text."""
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Open("", 0, 0, 0,0,0,16, 0, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    out.append(f'{prefix}Text("|", {size}, 0, 80, 80, 100, 255);\n')
    out.append(f"{close_fn}();\n")


def _emit_sortable_header(tag, props, children, src, out, prefix, close_fn):
    """Emit <SortableHeader> as TableCell with click detection."""
    eid = props.get("id", '""') or '""'
    w = props.get("w", "100") or "100"
    size = props.get("size", "14") or "14"
    sort = props.get("sort")
    arrow = ""
    if sort is not None:
        s = sort.strip().strip("'\"")
        if s == "asc":
            arrow = " ^"
        elif s == "desc":
            arrow = " v"
    out.append(f'{prefix}Open({eid}, {w}, 0, 4,8,4,8, 4, CLAY_LEFT_TO_RIGHT, 44,44,60,255, 0);\n')
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    if arrow:
        out.append(f'{prefix}Text("{arrow}", {size}, 0, 120, 180, 255, 255);\n')
    out.append(f"{close_fn}();\n")


def _emit_image_placeholder(tag, props, children, src, out, prefix, close_fn):
    """Emit <ImagePlaceholder /> as a box with [IMG] text."""
    w = props.get("w", "100") or "100"
    h = props.get("h", "80") or "80"
    out.append(f'{prefix}Open("", {w}, {h}, 0,0,0,0, 0, CLAY_TOP_TO_BOTTOM, 40,40,50,255, 4);\n')
    out.append(f'{prefix}Text("[IMG]", 14, 0, 80, 80, 100, 255);\n')
    out.append(f"{close_fn}();\n")


# ── Part 2B: Form widget emitters ─────────────────────────────────────

def _emit_textarea(tag, props, children, src, out, prefix, close_fn):
    """Emit <Textarea /> as textareaInput C builtin."""
    eid = props.get("id", '""') or '""'
    buf = props.get("buf", "0") or "0"
    w = props.get("w", "300") or "300"
    h = props.get("h", "100") or "100"
    size = props.get("size", "16") or "16"
    out.append(f"textareaInput({eid}, {buf}, {w}, {h}, {size});\n")


def _emit_switch(tag, props, children, src, out, prefix, close_fn):
    """Emit <Switch> as switchOpen/switchClose."""
    eid = props.get("id", '""') or '""'
    on = props.get("on", "0") or "0"
    size = props.get("size", "16") or "16"
    out.append(f"switchOpen({eid}, {on}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"switchClose();\n")


def _emit_rating(tag, props, children, src, out, prefix, close_fn):
    """Emit <Rating /> as ratingOpen/ratingClose."""
    eid = props.get("id", '""') or '""'
    value = props.get("value", "0") or "0"
    max_val = props.get("max", "5") or "5"
    size = props.get("size", "16") or "16"
    out.append(f"ratingOpen({eid}, {value}, {max_val}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"ratingClose();\n")


def _emit_color_picker(tag, props, children, src, out, prefix, close_fn):
    """Emit <ColorPicker /> as 3 sliders + preview box composite."""
    eid = props.get("id", '""') or '""'
    r_id = eid.replace('"', '') + "_r" if eid != '""' else "cpk_r"
    g_id = eid.replace('"', '') + "_g" if eid != '""' else "cpk_g"
    b_id = eid.replace('"', '') + "_b" if eid != '""' else "cpk_b"
    r_val = props.get("r", "128") or "128"
    g_val = props.get("g", "128") or "128"
    b_val = props.get("b", "128") or "128"
    w = props.get("w", "200") or "200"
    out.append(f'{prefix}Open("", 0, 0, 4,4,4,4, 4, CLAY_TOP_TO_BOTTOM, 36,36,48,255, 4);\n')
    out.append(f'slider("{r_id}", {r_val}, 0, 255, {w});\n')
    out.append(f'slider("{g_id}", {g_val}, 0, 255, {w});\n')
    out.append(f'slider("{b_id}", {b_val}, 0, 255, {w});\n')
    # Preview box
    out.append(f'{prefix}Open("", {w}, 24, 0,0,0,0, 0, CLAY_LEFT_TO_RIGHT, ({r_val}),({g_val}),({b_val}),255, 4);\n')
    out.append(f'{prefix}Close();\n')
    out.append(f"{close_fn}();\n")


def _emit_date_picker(tag, props, children, src, out, prefix, close_fn):
    """Emit <DatePicker /> as 3 NumberSteppers composite."""
    eid = props.get("id", '""') or '""'
    y_id = eid.replace('"', '') + "_y" if eid != '""' else "dp_y"
    m_id = eid.replace('"', '') + "_m" if eid != '""' else "dp_m"
    d_id = eid.replace('"', '') + "_d" if eid != '""' else "dp_d"
    year = props.get("year", "2024") or "2024"
    month = props.get("month", "1") or "1"
    day = props.get("day", "1") or "1"
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Open("", 0, 0, 4,4,4,4, 4, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    out.append(f'numberStepper("{y_id}", {year}, 1900, 2100, {size});\n')
    out.append(f'{prefix}Text("/", {size}, 0, 180, 180, 200, 255);\n')
    out.append(f'numberStepper("{m_id}", {month}, 1, 12, {size});\n')
    out.append(f'{prefix}Text("/", {size}, 0, 180, 180, 200, 255);\n')
    out.append(f'numberStepper("{d_id}", {day}, 1, 31, {size});\n')
    out.append(f"{close_fn}();\n")


def _emit_segment_button(tag, props, children, src, out, prefix, close_fn):
    """Emit <SegmentButton> as segmentButtonOpen/segmentButtonClose."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    active = props.get("active", "0") or "0"
    size = props.get("size", "16") or "16"
    out.append(f"segmentButtonOpen({eid}, {index}, {active}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"segmentButtonClose();\n")


# ── Part 2C: Navigation widget emitters ───────────────────────────────

def _emit_bottom_nav_item(tag, props, children, src, out, prefix, close_fn):
    """Emit <BottomNavItem> as a tab-button style nav item."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    active = props.get("active", "0") or "0"
    size = props.get("size", "12") or "12"
    out.append(f"tabButtonOpen({eid}, {index}, {active}, {size});\n")
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f"tabButtonClose();\n")


def _emit_drawer(tag, props, children, src, out, prefix, close_fn):
    """Emit <Drawer> as a sidebar that can be conditionally shown."""
    eid = props.get("id", '""') or '""'
    w = props.get("w", "240") or "240"
    open_val = props.get("open", "1") or "1"
    out.append(f'if ({open_val}) {{\n')
    out.append(f'{prefix}Open({eid}, {w}, -1, 12,12,12,12, 4, CLAY_TOP_TO_BOTTOM, 36,36,48,255, 0);\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f"{close_fn}();\n")
    out.append(f'}}\n')


def _emit_bottom_sheet(tag, props, children, src, out, prefix, close_fn):
    """Emit <BottomSheet> as a floating panel from bottom."""
    eid = props.get("id", '""') or '""'
    h = props.get("h", "200") or "200"
    open_val = props.get("open", "1") or "1"
    out.append(f'if ({open_val}) {{\n')
    out.append(f'{prefix}Open({eid}, -1, {h}, 12,12,12,12, 8, CLAY_TOP_TO_BOTTOM, 44,44,60,255, 8);\n')
    out.append(f'{prefix}Floating(0, 0, 50);\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f"{close_fn}();\n")
    out.append(f'}}\n')


# ── Part 2D: Overlay widget emitters ──────────────────────────────────

def _emit_accordion(tag, props, children, src, out, prefix, close_fn):
    """Emit <Accordion> with expandable/collapsible content."""
    eid = props.get("id", '""') or '""'
    expanded = props.get("expanded", "0") or "0"
    title = props.get("title")
    size = props.get("size", "16") or "16"
    # Header (always visible, clickable)
    out.append(f'accordionOpen({eid}, {expanded});\n')
    if title:
        out.append(f'{prefix}Text({title}, {size}, 0, 220, 220, 240, 255);\n')
    out.append(f'if ({expanded}) {{\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f'}}\n')
    out.append(f'accordionClose();\n')


def _emit_dropdown(tag, props, children, src, out, prefix, close_fn):
    """Emit <Dropdown> as a button + floating item list."""
    eid = props.get("id", '""') or '""'
    label = props.get("label", '"Select"') or '"Select"'
    size = props.get("size", "16") or "16"
    out.append(f'dropdownOpen({eid});\n')
    out.append(f'{prefix}Text({label}, {size}, 0, 220, 220, 240, 255);\n')
    out.append(f'if (dropdownIsOpen({eid})) {{\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f'}}\n')
    out.append(f'dropdownClose();\n')


def _emit_dropdown_item(tag, props, children, src, out, prefix, close_fn):
    """Emit <DropdownItem> as a clickable item in dropdown."""
    eid = props.get("id", '""') or '""'
    index = props.get("index", "0") or "0"
    size = props.get("size", "16") or "16"
    out.append(f'menuItemOpen({eid}, {index}, 0, {size});\n')
    if children:
        _emit_text_from_children(children, src, out, prefix, size)
    out.append(f'menuItemClose();\n')


def _emit_tooltip(tag, props, children, src, out, prefix, close_fn):
    """Emit <Tooltip> as content + floating tooltip text on hover."""
    eid = props.get("id", '""') or '""'
    text = props.get("text", '""') or '""'
    size = props.get("size", "12") or "12"
    out.append(f'tooltipBegin({eid});\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f'tooltipEnd();\n')
    out.append(f'if (hovered({eid})) {{\n')
    out.append(f'{prefix}Open("", 0, 0, 4,8,4,8, 0, CLAY_LEFT_TO_RIGHT, 60,60,80,240, 4);\n')
    out.append(f'{prefix}Floating(0, 0, 200);\n')
    out.append(f'{prefix}Text({text}, {size}, 0, 240, 240, 255, 255);\n')
    out.append(f"{close_fn}();\n")
    out.append(f'}}\n')


def _emit_toast(tag, props, children, src, out, prefix, close_fn):
    """Emit <Toast /> as a toastShow call."""
    msg = props.get("message", '""') or '""'
    kind = props.get("kind", "0") or "0"
    kind_str = kind
    if isinstance(kind, str):
        k = kind.strip("'\"")
        kind_map = {"info": "0", "success": "1", "warning": "2", "error": "3"}
        kind_str = kind_map.get(k, kind)
    duration = props.get("duration", "3") or "3"
    out.append(f"toastShow({msg}, {kind_str}, {duration});\n")


def _emit_context_menu(tag, props, children, src, out, prefix, close_fn):
    """Emit <ContextMenu> as a floating menu on right-click."""
    eid = props.get("id", '""') or '""'
    open_val = props.get("open", "0") or "0"
    out.append(f'if ({open_val}) {{\n')
    out.append(f'{prefix}Open({eid}, 0, 0, 4,4,4,4, 2, CLAY_TOP_TO_BOTTOM, 44,44,60,255, 4);\n')
    out.append(f'{prefix}Floating(0, 0, 150);\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f"{close_fn}();\n")
    out.append(f'}}\n')


def _emit_alert_dialog(tag, props, children, src, out, prefix, close_fn):
    """Emit <AlertDialog> as a modal dialog with OK button."""
    eid = props.get("id", '""') or '""'
    open_val = props.get("open", "0") or "0"
    title = props.get("title", '"Alert"') or '"Alert"'
    size = props.get("size", "16") or "16"
    out.append(f'if ({open_val}) {{\n')
    out.append(f'{prefix}Open({eid}, 0, 0, 16,16,16,16, 8, CLAY_TOP_TO_BOTTOM, 44,44,60,255, 8);\n')
    out.append(f'{prefix}Floating(0, 0, 200);\n')
    out.append(f'{prefix}Text({title}, 20, 0, 255, 255, 255, 255);\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f'buttonOpen({eid} + "_ok", 1, {size}, 0);\n')
    out.append(f'{prefix}Text("OK", {size}, 0, 255, 255, 255, 255);\n')
    out.append(f'buttonClose();\n')
    out.append(f"{close_fn}();\n")
    out.append(f'}}\n')


def _emit_confirm_dialog(tag, props, children, src, out, prefix, close_fn):
    """Emit <ConfirmDialog> as a modal dialog with OK/Cancel buttons."""
    eid = props.get("id", '""') or '""'
    open_val = props.get("open", "0") or "0"
    title = props.get("title", '"Confirm"') or '"Confirm"'
    size = props.get("size", "16") or "16"
    out.append(f'if ({open_val}) {{\n')
    out.append(f'{prefix}Open({eid}, 0, 0, 16,16,16,16, 8, CLAY_TOP_TO_BOTTOM, 44,44,60,255, 8);\n')
    out.append(f'{prefix}Floating(0, 0, 200);\n')
    out.append(f'{prefix}Text({title}, 20, 0, 255, 255, 255, 255);\n')
    for child in children:
        _emit_child(child, src, out, prefix)
    out.append(f'{prefix}Open("", 0, 0, 0,0,0,0, 8, CLAY_LEFT_TO_RIGHT, 0,0,0,0, 0);\n')
    out.append(f'buttonOpen({eid} + "_ok", 1, {size}, 0);\n')
    out.append(f'{prefix}Text("OK", {size}, 0, 255, 255, 255, 255);\n')
    out.append(f'buttonClose();\n')
    out.append(f'buttonOpen({eid} + "_cancel", 0, {size}, 0);\n')
    out.append(f'{prefix}Text("Cancel", {size}, 0, 255, 255, 255, 255);\n')
    out.append(f'buttonClose();\n')
    out.append(f"{close_fn}();\n")
    out.append(f"{close_fn}();\n")
    out.append(f'}}\n')


# ── Part 2E: Chart widget emitters ────────────────────────────────────

def _emit_chart(tag, props, children, src, out, prefix, close_fn):
    """Emit <BarChart/LineChart/PieChart> as chartRender calls."""
    eid = props.get("id", '""') or '""'
    w = props.get("w", "300") or "300"
    h = props.get("h", "200") or "200"
    chart_type = {"BarChart": "0", "LineChart": "1", "PieChart": "2"}.get(tag, "0")
    count = props.get("count", "0") or "0"
    max_val = props.get("max", "100") or "100"
    out.append(f"chartRender({eid}, {chart_type}, {count}, {max_val}, {w}, {h});\n")


# ── Part 2F: Markdown emitter ─────────────────────────────────────────

def _emit_markdown(tag, props, children, src, out, prefix, close_fn):
    """Emit <Markdown> as markdownRender call."""
    # Get text from children or text prop
    text = props.get("text")
    if text is None and children:
        text_parts = []
        for child in children:
            if child.type == "jsx_text":
                t = child.text.decode().strip()
                if t:
                    escaped = t.replace("\\", "\\\\").replace('"', '\\"')
                    text_parts.append(f'"{escaped}"')
            elif child.type == "jsx_expression":
                for c in child.children:
                    if c.type not in ("{", "}"):
                        text_parts.append(c.text.decode())
        text = " + ".join(text_parts) if text_parts else '""'
    elif text is None:
        text = '""'
    w = props.get("w", "0") or "0"
    size = props.get("size", "16") or "16"
    out.append(f"markdownRender({text}, {w}, {size});\n")


# ── Part 2G: Other widget emitters ────────────────────────────────────

def _emit_spinner(tag, props, children, src, out, prefix, close_fn):
    """Emit <Spinner /> as animated text character."""
    size = props.get("size", "16") or "16"
    out.append(f'{prefix}Text(uiSpinnerChar(), {size}, 0, 120, 180, 255, 255);\n')


# ── Interactive handler dispatch table ────────────────────────────────

_INTERACTIVE_HANDLERS = {
    "Button": _emit_button,
    "Checkbox": _emit_checkbox,
    "Radio": _emit_radio,
    "Toggle": _emit_toggle,
    "TextInput": _emit_text_input,
    "Slider": _emit_slider,
    "MenuItem": _emit_menu_item,
    "TabButton": _emit_tab_button,
    "NumberStepper": _emit_number_stepper,
    "SearchBar": _emit_search_bar,
    "ListItem": _emit_list_item,
    # Part 2A
    "TableRow": _emit_table_row,
    "ProgressSteps": _emit_progress_steps,
    "Skeleton": _emit_skeleton,
    "CircularProgress": _emit_circular_progress,
    "CarouselDots": _emit_carousel_dots,
    "TimelineItem": _emit_timeline_item,
    "TimelineConnector": _emit_timeline_connector,
    "SortableHeader": _emit_sortable_header,
    "ImagePlaceholder": _emit_image_placeholder,
    # Part 2B
    "Textarea": _emit_textarea,
    "Switch": _emit_switch,
    "Rating": _emit_rating,
    "ColorPicker": _emit_color_picker,
    "DatePicker": _emit_date_picker,
    "SegmentButton": _emit_segment_button,
    # Part 2C
    "BottomNavItem": _emit_bottom_nav_item,
    "Drawer": _emit_drawer,
    "BottomSheet": _emit_bottom_sheet,
    # Part 2D
    "Accordion": _emit_accordion,
    "Dropdown": _emit_dropdown,
    "DropdownItem": _emit_dropdown_item,
    "Tooltip": _emit_tooltip,
    "Toast": _emit_toast,
    "ContextMenu": _emit_context_menu,
    "AlertDialog": _emit_alert_dialog,
    "ConfirmDialog": _emit_confirm_dialog,
    # Part 2E
    "BarChart": _emit_chart,
    "LineChart": _emit_chart,
    "PieChart": _emit_chart,
    # Part 2F
    "Markdown": _emit_markdown,
    # Part 2G
    "Spinner": _emit_spinner,
}
