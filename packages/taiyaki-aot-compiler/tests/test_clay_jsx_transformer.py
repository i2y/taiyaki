"""Tests for Clay JSX transformer including UI layout containers and interactive widgets."""

import pytest
from taiyaki_aot_compiler.parser.clay_jsx_transformer import transform_clay_jsx, CLAY_JSX_TAGS


class TestClayJSXTags:
    """Test that CLAY_JSX_TAGS contains all expected tags."""

    def test_contains_box_and_text(self):
        assert "Box" in CLAY_JSX_TAGS
        assert "Text" in CLAY_JSX_TAGS

    def test_contains_layout_containers(self):
        for tag in ["VPanel", "HPanel", "Row", "CPanel", "Card", "Header",
                     "Footer", "Sidebar", "ScrollPanel", "ScrollHPanel",
                     "GridRow", "GridItem", "ZStack", "ZStackLayer",
                     "Modal", "TabBar", "TabContent", "StatusBar",
                     "FixedPanel", "PctPanel", "AspectPanel"]:
            assert tag in CLAY_JSX_TAGS, f"{tag} missing from CLAY_JSX_TAGS"

    def test_contains_display_widgets(self):
        for tag in ["Spacer", "Divider", "ProgressBar", "Badge", "Avatar"]:
            assert tag in CLAY_JSX_TAGS, f"{tag} missing from CLAY_JSX_TAGS"

    def test_contains_interactive_widgets(self):
        for tag in ["Button", "Checkbox", "Radio", "Toggle", "TextInput",
                     "Slider", "MenuItem", "TabButton", "NumberStepper",
                     "SearchBar", "ListItem"]:
            assert tag in CLAY_JSX_TAGS, f"{tag} missing from CLAY_JSX_TAGS"


class TestBoxAndText:
    """Existing Box/Text behavior should not change."""

    def test_box_basic(self):
        src = '<Box id="root" grow vertical bg={[24,24,32]} gap={8}></Box>'
        result = transform_clay_jsx(src)
        assert 'clayOpen("root"' in result
        assert "CLAY_GROW" in result
        assert "CLAY_TOP_TO_BOTTOM" in result
        assert "clayClose()" in result

    def test_text_basic(self):
        src = '<Text size={24} color={[120,180,255]}>Hello</Text>'
        result = transform_clay_jsx(src)
        assert 'clayText("Hello"' in result
        assert "24" in result

    def test_box_tui_mode(self):
        src = '<Box id="x" grow></Box>'
        result = transform_clay_jsx(src, tui=True)
        assert "clayTuiOpen" in result
        assert "clayTuiCloseElement()" in result


class TestLayoutContainers:
    """Test Layout containers expand to correct clayOpen calls."""

    def test_vpanel(self):
        src = '<VPanel gap={8}><Text>Hello</Text></VPanel>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        assert "CLAY_TOP_TO_BOTTOM" in result
        assert "CLAY_GROW" in result
        assert "clayClose()" in result

    def test_hpanel(self):
        src = '<HPanel gap={4}><Text>A</Text></HPanel>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        assert "CLAY_LEFT_TO_RIGHT" in result

    def test_row(self):
        src = '<Row><Text>Item</Text></Row>'
        result = transform_clay_jsx(src)
        assert "CLAY_GROW" in result

    def test_card(self):
        src = '<Card><Text>Content</Text></Card>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        # Card has default bg color (with spaces between args)
        assert "36, 36, 48" in result or "36,36,48" in result
        # Card has default radius
        assert "8" in result

    def test_card_custom_bg(self):
        src = '<Card bg={[50,50,70]}><Text>X</Text></Card>'
        result = transform_clay_jsx(src)
        # User bg overrides default (may have spaces)
        assert "50, 50, 70" in result or "50,50,70" in result

    def test_header(self):
        src = '<Header><Text>Title</Text></Header>'
        result = transform_clay_jsx(src)
        assert "60, 100, 180" in result or "60,100,180" in result

    def test_footer(self):
        src = '<Footer><Text>Footer</Text></Footer>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        assert "clayClose" in result

    def test_sidebar(self):
        src = '<Sidebar w={250}><Text>Nav</Text></Sidebar>'
        result = transform_clay_jsx(src)
        assert "250" in result  # user-specified width

    def test_sidebar_default_width(self):
        src = '<Sidebar><Text>Nav</Text></Sidebar>'
        result = transform_clay_jsx(src)
        assert "200" in result  # default width

    def test_scroll_panel(self):
        src = '<ScrollPanel><Text>Content</Text></ScrollPanel>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        assert "clayScroll(0, 1)" in result
        assert "clayClose" in result

    def test_scroll_h_panel(self):
        src = '<ScrollHPanel><Text>Content</Text></ScrollHPanel>'
        result = transform_clay_jsx(src)
        assert "clayScroll(1, 0)" in result

    def test_modal(self):
        src = '<Modal w={400} h={300}><Text>Dialog</Text></Modal>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        assert "clayFloating(0, 0, 100)" in result

    def test_zstack(self):
        src = '<ZStack><Text>Base</Text></ZStack>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result
        assert "CLAY_GROW" in result

    def test_zstack_layer(self):
        src = '<ZStackLayer z={5}><Text>Overlay</Text></ZStackLayer>'
        result = transform_clay_jsx(src)
        assert "clayFloating(0, 0, 5)" in result

    def test_tab_bar(self):
        src = '<TabBar><Text>Tab1</Text></TabBar>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result

    def test_tab_content(self):
        src = '<TabContent><Text>Content</Text></TabContent>'
        result = transform_clay_jsx(src)
        assert "CLAY_GROW" in result

    def test_grid_row(self):
        src = '<GridRow gap={4}><Text>A</Text></GridRow>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result

    def test_cpanel(self):
        src = '<CPanel><Text>Centered</Text></CPanel>'
        result = transform_clay_jsx(src)
        assert "clayOpen" in result

    def test_tui_mode(self):
        src = '<VPanel gap={4}><Text>Hello</Text></VPanel>'
        result = transform_clay_jsx(src, tui=True)
        assert "clayTuiOpen" in result
        assert "clayTuiCloseElement()" in result


class TestDisplayWidgets:
    """Test self-closing display widgets."""

    def test_spacer(self):
        src = '<Spacer />'
        result = transform_clay_jsx(src)
        assert "CLAY_GROW, CLAY_GROW" in result
        assert "clayClose()" in result

    def test_divider(self):
        src = '<Divider />'
        result = transform_clay_jsx(src)
        assert "CLAY_GROW" in result
        assert "80,80,100" in result  # default divider color
        assert "clayClose()" in result

    def test_divider_vertical(self):
        src = '<Divider vertical />'
        result = transform_clay_jsx(src)
        # vertical divider: w=1, h=GROW
        assert "1" in result

    def test_divider_custom_color(self):
        src = '<Divider color={[255,0,0]} />'
        result = transform_clay_jsx(src)
        assert "255,0,0" in result

    def test_progress_bar(self):
        src = '<ProgressBar value={50} max={100} w={200} h={8} />'
        result = transform_clay_jsx(src)
        # Should have two clayOpen/clayClose pairs (bg + fill)
        assert result.count("clayOpen") == 2
        assert result.count("clayClose") == 2

    def test_badge(self):
        src = '<Badge kind="success">Active</Badge>'
        result = transform_clay_jsx(src)
        assert "80,200,120" in result  # success green
        assert "clayText" in result
        assert "Active" in result

    def test_badge_warning(self):
        src = '<Badge kind="warning">Pending</Badge>'
        result = transform_clay_jsx(src)
        assert "220,180,80" in result  # warning yellow

    def test_avatar(self):
        src = '<Avatar size={40}>JD</Avatar>'
        result = transform_clay_jsx(src)
        assert "40" in result
        assert "clayText" in result
        assert "JD" in result


class TestInteractiveWidgets:
    """Test interactive widgets emit widget* C builtins."""

    def test_button(self):
        src = '<Button id="save" kind="primary">Save</Button>'
        result = transform_clay_jsx(src)
        assert 'buttonOpen("save", 1, 16, 0)' in result
        assert "buttonClose()" in result
        assert "clayText" in result

    def test_button_default_kind(self):
        src = '<Button id="ok">OK</Button>'
        result = transform_clay_jsx(src)
        assert 'buttonOpen("ok", 0, 16, 0)' in result

    def test_button_grow(self):
        src = '<Button id="b1" grow>Click</Button>'
        result = transform_clay_jsx(src)
        assert 'buttonOpen("b1", 0, 16, -1)' in result

    def test_button_custom_size(self):
        src = '<Button id="big" size={24}>Big</Button>'
        result = transform_clay_jsx(src)
        assert "24" in result

    def test_checkbox(self):
        src = '<Checkbox id="opt" checked={val}>Dark Mode</Checkbox>'
        result = transform_clay_jsx(src)
        assert 'checkboxOpen("opt", val, 16)' in result
        assert "checkboxClose()" in result

    def test_radio(self):
        src = '<Radio id="r1" index={0} selected={sel}>Option A</Radio>'
        result = transform_clay_jsx(src)
        assert 'radioOpen("r1", 0, sel, 16)' in result
        assert "radioClose()" in result

    def test_toggle(self):
        src = '<Toggle id="t1" on={val}>Auto Save</Toggle>'
        result = transform_clay_jsx(src)
        assert 'toggleOpen("t1", val, 16)' in result
        assert "toggleClose()" in result

    def test_text_input(self):
        src = '<TextInput id="name" buf={0} w={200} />'
        result = transform_clay_jsx(src)
        assert 'textInput("name", 0, 200, 16)' in result

    def test_slider(self):
        src = '<Slider id="vol" value={vol} min={0} max={100} w={200} />'
        result = transform_clay_jsx(src)
        assert 'slider("vol", vol, 0, 100, 200)' in result

    def test_menu_item(self):
        src = '<MenuItem id="m1" index={0} cursor={cursor}>New File</MenuItem>'
        result = transform_clay_jsx(src)
        assert 'menuItemOpen("m1", 0, cursor, 16)' in result
        assert "menuItemClose()" in result

    def test_tab_button(self):
        src = '<TabButton id="t1" index={0} active={tab}>Home</TabButton>'
        result = transform_clay_jsx(src)
        assert 'tabButtonOpen("t1", 0, tab, 16)' in result
        assert "tabButtonClose()" in result

    def test_number_stepper(self):
        src = '<NumberStepper id="qty" value={qty} min={0} max={99} />'
        result = transform_clay_jsx(src)
        assert 'numberStepper("qty", qty, 0, 99, 16)' in result

    def test_search_bar(self):
        src = '<SearchBar id="search" buf={0} w={300} />'
        result = transform_clay_jsx(src)
        assert 'searchBar("search", 0, 300, 16)' in result

    def test_list_item(self):
        src = '<ListItem id="item1" index={0} selected={sel}>File.js</ListItem>'
        result = transform_clay_jsx(src)
        assert 'listItemOpen("item1", 0, sel, 16)' in result
        assert "listItemClose()" in result


class TestCompositeLayouts:
    """Test realistic composite layouts."""

    def test_dashboard_layout(self):
        src = """
        <VPanel gap={0}>
            <Header><Text size={20}>Dashboard</Text></Header>
            <HPanel grow gap={0}>
                <Sidebar w={200}>
                    <Text>Nav</Text>
                </Sidebar>
                <VPanel grow padding={16} gap={8}>
                    <Card><Text>Card Content</Text></Card>
                    <Spacer />
                </VPanel>
            </HPanel>
            <Footer><Text size={12}>Status</Text></Footer>
        </VPanel>
        """
        result = transform_clay_jsx(src)
        # Should have multiple clayOpen/clayClose pairs
        assert result.count("clayOpen") >= 6
        assert result.count("clayClose") >= 6
        assert "Dashboard" in result
        assert "Nav" in result

    def test_form_layout(self):
        src = """
        <VPanel padding={16} gap={8}>
            <TextInput id="name" buf={0} w={300} />
            <Checkbox id="agree" checked={agreed}>I agree</Checkbox>
            <Button id="submit" kind="primary">Submit</Button>
        </VPanel>
        """
        result = transform_clay_jsx(src)
        assert "textInput" in result
        assert "checkboxOpen" in result
        assert "buttonOpen" in result

    def test_non_jsx_code_preserved(self):
        src = """
        let x = 42;
        function draw() {
            return <VPanel><Text>{x}</Text></VPanel>;
        }
        draw();
        """
        result = transform_clay_jsx(src)
        assert "let x = 42" in result
        assert "function draw()" in result
        assert "clayOpen" in result


class TestCSSStyleProp:
    """Test CSS style={{...}} prop support."""

    def test_style_bg_hex6(self):
        src = '<Box style={{bg: "#181820"}}></Box>'
        result = transform_clay_jsx(src)
        assert "24, 24, 32" in result or "24,24,32" in result

    def test_style_bg_hex3(self):
        src = '<Box style={{bg: "#f00"}}></Box>'
        result = transform_clay_jsx(src)
        assert "255, 0, 0" in result or "255,0,0" in result

    def test_style_bg_hex8(self):
        src = '<Box style={{bg: "#181820CC"}}></Box>'
        result = transform_clay_jsx(src)
        assert "24, 24, 32, 204" in result or "24,24,32,204" in result

    def test_style_bg_rgb(self):
        src = '<Box style={{bg: "rgb(100,200,50)"}}></Box>'
        result = transform_clay_jsx(src)
        assert "100, 200, 50" in result or "100,200,50" in result

    def test_style_bg_rgba(self):
        src = '<Box style={{bg: "rgba(100,200,50,128)"}}></Box>'
        result = transform_clay_jsx(src)
        assert "100, 200, 50, 128" in result or "100,200,50,128" in result

    def test_style_padding(self):
        src = '<Box style={{padding: 16}}></Box>'
        result = transform_clay_jsx(src)
        assert "16, 16, 16, 16" in result

    def test_style_gap(self):
        src = '<Box style={{gap: 8}}></Box>'
        result = transform_clay_jsx(src)
        assert ", 8," in result

    def test_style_flex_direction_column(self):
        src = '<Box style={{flexDirection: "column"}}></Box>'
        result = transform_clay_jsx(src)
        assert "CLAY_TOP_TO_BOTTOM" in result

    def test_style_flex_grow(self):
        src = '<Box style={{flexGrow: 1}}></Box>'
        result = transform_clay_jsx(src)
        assert "CLAY_GROW" in result

    def test_style_width_height(self):
        src = '<Box style={{width: 200, height: 100}}></Box>'
        result = transform_clay_jsx(src)
        assert "200" in result
        assert "100" in result

    def test_style_border_radius(self):
        src = '<Box style={{borderRadius: 8}}></Box>'
        result = transform_clay_jsx(src)
        assert ", 8)" in result

    def test_style_align_center(self):
        src = '<Box style={{alignItems: "center", justifyContent: "center"}}></Box>'
        result = transform_clay_jsx(src)
        assert "clayOpenAligned" in result

    def test_style_overflow_scroll(self):
        src = '<Box style={{overflow: "scroll"}}></Box>'
        result = transform_clay_jsx(src)
        assert "clayScroll(0, 1)" in result

    def test_style_does_not_override_explicit_props(self):
        src = '<Box padding={4} style={{padding: 16}}></Box>'
        result = transform_clay_jsx(src)
        # Explicit padding=4 should win over style padding=16
        assert "4, 4, 4, 4" in result

    def test_style_background_color_alias(self):
        src = '<Box style={{backgroundColor: "#ff0000"}}></Box>'
        result = transform_clay_jsx(src)
        assert "255, 0, 0" in result or "255,0,0" in result

    def test_style_text_color(self):
        src = '<Text style={{color: "#00ff00", fontSize: 24}}>Hi</Text>'
        result = transform_clay_jsx(src)
        assert "0, 255, 0" in result or "0,255,0" in result
        assert "24" in result

    def test_style_combined(self):
        src = '<Box style={{bg: "#181820", padding: 16, gap: 8, borderRadius: 4}}></Box>'
        result = transform_clay_jsx(src)
        assert "24, 24, 32" in result or "24,24,32" in result
        assert "16, 16, 16, 16" in result


class TestTernaryInJSX:
    """Test ternary expressions containing JSX are converted to if/else."""

    def test_ternary_with_jsx_becomes_if_else(self):
        src = '''
        function draw() {
            <VPanel>
                {scene === 0 ? (<VPanel><Text>Hello</Text></VPanel>) : 0}
            </VPanel>
        }
        '''
        result = transform_clay_jsx(src)
        assert "if (scene === 0)" in result
        assert "} else {" in result
        assert "clayOpen" in result
        # Should NOT have a bare ternary ? in the output
        assert "scene === 0 ?" not in result

    def test_ternary_without_jsx_preserved(self):
        src = '''
        function draw() {
            <VPanel>
                {x > 0 ? 1 : 0}
            </VPanel>
        }
        '''
        result = transform_clay_jsx(src)
        # No JSX in ternary branches → keep as expression
        assert "x > 0 ? 1 : 0" in result

    def test_ternary_jsx_in_both_branches(self):
        src = '''
        <VPanel>
            {active ? (<Text>On</Text>) : (<Text>Off</Text>)}
        </VPanel>
        '''
        result = transform_clay_jsx(src)
        assert "if (active)" in result
        assert "} else {" in result
        assert "On" in result
        assert "Off" in result

    def test_ternary_jsx_direct_no_parens(self):
        src = '''
        <VPanel>
            {mode === 1 ? <Text>A</Text> : 0}
        </VPanel>
        '''
        result = transform_clay_jsx(src)
        assert "if (mode === 1)" in result
        assert "clayText" in result
