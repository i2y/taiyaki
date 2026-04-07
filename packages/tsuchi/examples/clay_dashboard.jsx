// Clay UI Dashboard — JSX version
// Shows Clay's flex-like layout with nested containers, text, and hover effects

function main() {
    initWindow(900, 600, "Tsuchi Clay Dashboard");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 32);
    clayInit(900, 600);

    let frame = 0;

    while (!windowShouldClose()) {
        frame = frame + 1;

        claySetPointer(getMouseX(), getMouseY(), isMouseButtonDown(MOUSE_LEFT) ? 1 : 0);

        clayBeginLayout();

        <Box id="root" grow vertical bg={[24, 24, 32]}>

            <Box id="topbar" growX h={56} padding={[12, 20, 12, 20]} bg={[32, 32, 44]}>
                <Text size={24} color={[120, 180, 255]}>Tsuchi Dashboard</Text>
            </Box>

            <Box id="main" grow padding={12} gap={12}>

                <Box id="sidebar" w={200} growY padding={16} gap={8} vertical bg={[36, 36, 48]} radius={8}>
                    <Text size={18} color={[140, 140, 160]}>Navigation</Text>
                    {sidebarItem("nav1", "Overview")}
                    {sidebarItem("nav2", "Analytics")}
                    {sidebarItem("nav3", "Settings")}
                    {sidebarItem("nav4", "Help")}
                </Box>

                <Box id="content" grow vertical gap={12}>

                    <Box id="stats" growX h={100} gap={12}>
                        {statCard("stat1", "Users", "1,284", 80, 200, 120)}
                        {statCard("stat2", "Revenue", "$42.8K", 100, 160, 255)}
                        {statCard("stat3", "Growth", "+18%", 220, 180, 80)}
                    </Box>

                    <Box id="panel" grow padding={20} gap={12} vertical bg={[36, 36, 48]} radius={8}>
                        <Text size={22} color={[230, 230, 240]}>Welcome back!</Text>
                        <Text size={15} color={[140, 140, 160]}>Your dashboard is powered by Tsuchi + Clay + Raylib.</Text>
                        <Text size={15} color={[140, 140, 160]}>All compiled to a native binary from JavaScript.</Text>

                        <Box id="info" growX padding={[12, 16, 12, 16]} gap={6} vertical bg={[44, 44, 60]} radius={6}>
                            <Text size={16} color={[180, 180, 200]}>System Info</Text>
                            <Text size={13} color={[120, 120, 140]}>Engine: Clay (flex-like layout)</Text>
                            <Text size={13} color={[120, 120, 140]}>Renderer: Raylib 5.5</Text>
                            <Text size={13} color={[120, 120, 140]}>Compiler: Tsuchi (LLVM + QuickJS)</Text>
                        </Box>
                    </Box>

                </Box>

            </Box>

            <Box id="bottombar" growX h={32} padding={[8, 20, 8, 20]} bg={[32, 32, 44]}>
                <Text size={12} color={[80, 80, 100]}>Tsuchi v0.5 | Clay UI | Raylib 5.5</Text>
            </Box>

        </Box>

        clayEndLayout();

        beginDrawing();
        clearBackground(color(24, 24, 32, 255));
        clayRender();
        drawText(String(getFPS()), 860, 8, 16, GRAY);
        endDrawing();
    }

    closeWindow();
}

function sidebarItem(id, label) {
    let hovered = clayPointerOver(id);

    <Box id={id} growX h={36} padding={[8, 12, 8, 12]}
         bg={[hovered ? 60 : 48, hovered ? 80 : 48, hovered ? 120 : 64]} radius={4}>
        <Text size={15} color={[hovered ? 255 : 180, hovered ? 255 : 180, hovered ? 255 : 200]}>{label}</Text>
    </Box>
}

function statCard(id, label, value, r, g, b) {
    let hovered = clayPointerOver(id);
    let alpha = hovered ? 200 : 255;

    <Box id={id} grow padding={[14, 16, 14, 16]} gap={6} vertical
         bg={[r / 4, g / 4, b / 4, alpha]} radius={8}>
        <Text size={13} color={[r, g, b, 200]}>{label}</Text>
        <Text size={28} color={[240, 240, 250]}>{value}</Text>
    </Box>
}

main();
