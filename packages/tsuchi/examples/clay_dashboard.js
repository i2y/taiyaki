// Clay UI Dashboard — Interactive layout demo
// Shows Clay's flex-like layout with nested containers, text, and hover effects

function main() {
    initWindow(900, 600, "Tsuchi Clay Dashboard");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 32);
    clayInit(900, 600);

    let frame = 0;

    while (!windowShouldClose()) {
        frame = frame + 1;

        // Update Clay with mouse state
        let mx = getMouseX();
        let my = getMouseY();
        let mDown = isMouseButtonDown(MOUSE_LEFT) ? 1 : 0;
        claySetPointer(mx, my, mDown);

        // Build layout
        clayBeginLayout();

        // Root: full screen, vertical, dark bg
        clayOpen("root", CLAY_GROW, CLAY_GROW, 0, 0, 0, 0, 0, CLAY_TOP_TO_BOTTOM,
                 24, 24, 32, 255, 0);

            // ── Top bar ──
            clayOpen("topbar", CLAY_GROW, 56, 12, 20, 12, 20, 0, CLAY_LEFT_TO_RIGHT,
                     32, 32, 44, 255, 0);
                clayText("Tsuchi Dashboard", 24, 0, 120, 180, 255, 255);
            clayClose();

            // ── Main content area (horizontal split) ──
            clayOpen("main", CLAY_GROW, CLAY_GROW, 12, 12, 12, 12, 12, CLAY_LEFT_TO_RIGHT,
                     0, 0, 0, 0, 0);

                // ── Sidebar ──
                clayOpen("sidebar", 200, CLAY_GROW, 16, 16, 16, 16, 8, CLAY_TOP_TO_BOTTOM,
                         36, 36, 48, 255, 8);

                    clayText("Navigation", 18, 0, 140, 140, 160, 255);

                    // Nav items
                    sidebarItem("nav1", "Overview");
                    sidebarItem("nav2", "Analytics");
                    sidebarItem("nav3", "Settings");
                    sidebarItem("nav4", "Help");

                clayClose();

                // ── Content ──
                clayOpen("content", CLAY_GROW, CLAY_GROW, 0, 0, 0, 0, 12, CLAY_TOP_TO_BOTTOM,
                         0, 0, 0, 0, 0);

                    // Stats row
                    clayOpen("stats", CLAY_GROW, 100, 0, 0, 0, 0, 12, CLAY_LEFT_TO_RIGHT,
                             0, 0, 0, 0, 0);
                        statCard("stat1", "Users", "1,284", 80, 200, 120);
                        statCard("stat2", "Revenue", "$42.8K", 100, 160, 255);
                        statCard("stat3", "Growth", "+18%", 220, 180, 80);
                    clayClose();

                    // Main panel
                    clayOpen("panel", CLAY_GROW, CLAY_GROW, 20, 20, 20, 20, 12, CLAY_TOP_TO_BOTTOM,
                             36, 36, 48, 255, 8);
                        clayText("Welcome back!", 22, 0, 230, 230, 240, 255);
                        clayText("Your dashboard is powered by Tsuchi + Clay + Raylib.", 15, 0, 140, 140, 160, 255);
                        clayText("All compiled to a native binary from JavaScript.", 15, 0, 140, 140, 160, 255);

                        // Info box
                        clayOpen("info", CLAY_GROW, 0, 12, 16, 12, 16, 6, CLAY_TOP_TO_BOTTOM,
                                 44, 44, 60, 255, 6);
                            clayText("System Info", 16, 0, 180, 180, 200, 255);
                            clayText("Engine: Clay (flex-like layout)", 13, 0, 120, 120, 140, 255);
                            clayText("Renderer: Raylib 5.5", 13, 0, 120, 120, 140, 255);
                            clayText("Compiler: Tsuchi (LLVM + QuickJS)", 13, 0, 120, 120, 140, 255);
                        clayClose();

                    clayClose();

                clayClose();

            clayClose();

            // ── Bottom bar ──
            clayOpen("bottombar", CLAY_GROW, 32, 8, 20, 8, 20, 0, CLAY_LEFT_TO_RIGHT,
                     32, 32, 44, 255, 0);
                clayText("Tsuchi v0.5 | Clay UI | Raylib 5.5", 12, 0, 80, 80, 100, 255);
            clayClose();

        clayClose();

        clayEndLayout();

        // Render
        beginDrawing();
        clearBackground(color(24, 24, 32, 255));
        clayRender();

        // FPS overlay (direct raylib drawing on top)
        drawText(String(getFPS()), 860, 8, 16, GRAY);

        endDrawing();
    }

    closeWindow();
}

function sidebarItem(id, label) {
    let hovered = clayPointerOver(id);
    let bgR = 48;
    let bgG = 48;
    let bgB = 64;
    if (hovered) {
        bgR = 60;
        bgG = 80;
        bgB = 120;
    }
    clayOpen(id, CLAY_GROW, 36, 8, 12, 8, 12, 0, CLAY_LEFT_TO_RIGHT,
             bgR, bgG, bgB, 255, 4);
        let tr = 180;
        let tg = 180;
        let tb = 200;
        if (hovered) {
            tr = 255;
            tg = 255;
            tb = 255;
        }
        clayText(label, 15, 0, tr, tg, tb, 255);
    clayClose();
}

function statCard(id, label, value, r, g, b) {
    let hovered = clayPointerOver(id);
    let alpha = 255;
    if (hovered) {
        alpha = 200;
    }
    clayOpen(id, CLAY_GROW, CLAY_GROW, 14, 16, 14, 16, 6, CLAY_TOP_TO_BOTTOM,
             r / 4, g / 4, b / 4, alpha, 8);
        clayText(label, 13, 0, r, g, b, 200);
        clayText(value, 28, 0, 240, 240, 250, 255);
    clayClose();
}

main();
