// UI Widgets Showcase — demonstrates all layout and interactive widgets
// Compile: uv run tsuchi compile examples/widgets.jsx

function main() {
    initWindow(800, 600, "UI Widgets Showcase");
    clayInit(800, 600);
    claySetMeasureTextRaylib();
    let font = clayLoadFont("", 16);
    setTargetFPS(60);

    let tab = 0;
    let checked = 0;
    let toggle_on = 0;
    let slider_val = 50;
    let radio_sel = 0;
    let cursor = 0;

    while (!windowShouldClose()) {
        let w = getScreenWidth();
        let h = getScreenHeight();
        claySetDimensions(w, h);
        claySetPointer(getMouseX(), getMouseY(), isMouseButtonDown(0));
        let wheel = getMouseWheelMove();
        clayUpdateScroll(0, wheel * 40, getFrameTime());

        beginFrame();
        clayBeginLayout();

        <VPanel gap={0}>
            <Header padding={[8,16,8,16]}>
                <Text size={20} color={[255,255,255]}>UI Widgets Showcase</Text>
                <Spacer />
                <Badge kind="info">v1.0</Badge>
            </Header>

            <HPanel grow gap={0}>
                <Sidebar w={180}>
                    <Text size={14} color={[180,180,200]}>Navigation</Text>
                    <Divider />
                    <MenuItem id="nav0" index={0} cursor={cursor}>Dashboard</MenuItem>
                    <MenuItem id="nav1" index={1} cursor={cursor}>Settings</MenuItem>
                    <MenuItem id="nav2" index={2} cursor={cursor}>About</MenuItem>
                </Sidebar>

                <VPanel grow padding={16} gap={12}>
                    <TabBar>
                        <TabButton id="tab0" index={0} active={tab}>Buttons</TabButton>
                        <TabButton id="tab1" index={1} active={tab}>Forms</TabButton>
                        <TabButton id="tab2" index={2} active={tab}>Data</TabButton>
                    </TabBar>

                    <TabContent>
                        {tab === 0 ? (
                            <VPanel gap={8}>
                                <Card>
                                    <Text size={18} color={[200,200,220]}>Button Variants</Text>
                                    <HPanel gap={8}>
                                        <Button id="btn_default">Default</Button>
                                        <Button id="btn_primary" kind="primary">Primary</Button>
                                        <Button id="btn_success" kind="success">Success</Button>
                                        <Button id="btn_warning" kind="warning">Warning</Button>
                                        <Button id="btn_danger" kind="danger">Danger</Button>
                                    </HPanel>
                                </Card>

                                <Card>
                                    <Text size={18} color={[200,200,220]}>Toggles</Text>
                                    <Checkbox id="chk1" checked={checked}>Enable notifications</Checkbox>
                                    <Toggle id="tgl1" on={toggle_on}>Auto-save</Toggle>
                                    <HPanel gap={8}>
                                        <Radio id="r0" index={0} selected={radio_sel}>Small</Radio>
                                        <Radio id="r1" index={1} selected={radio_sel}>Medium</Radio>
                                        <Radio id="r2" index={2} selected={radio_sel}>Large</Radio>
                                    </HPanel>
                                </Card>
                            </VPanel>
                        ) : 0}
                    </TabContent>
                </VPanel>
            </HPanel>

            <StatusBar>
                <Text size={12} color={[140,140,160]}>Ready</Text>
                <Spacer />
                <Text size={12} color={[140,140,160]}>FPS: </Text>
            </StatusBar>
        </VPanel>

        clayEndLayout();
        endFrame();

        // Handle interactions
        if (clicked("tab0")) { tab = 0; }
        if (clicked("tab1")) { tab = 1; }
        if (clicked("tab2")) { tab = 2; }
        if (toggled("chk1")) { checked = 1 - checked; }
        if (toggled("tgl1")) { toggle_on = 1 - toggle_on; }
        if (clicked("r0")) { radio_sel = 0; }
        if (clicked("r1")) { radio_sel = 1; }
        if (clicked("r2")) { radio_sel = 2; }
        if (clicked("nav0")) { cursor = 0; }
        if (clicked("nav1")) { cursor = 1; }
        if (clicked("nav2")) { cursor = 2; }

        beginDrawing();
        clearBackground(BLACK);
        clayRender();
        endDrawing();
    }
    closeWindow();
}

main();
