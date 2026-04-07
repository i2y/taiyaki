// Clay UI hello world — layout-driven UI with raylib rendering

function main() {
    initWindow(800, 600, "Tsuchi + Clay UI");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 32);
    clayInit(800, 600);

    while (!windowShouldClose()) {
        // Update Clay pointer state
        claySetPointer(getMouseX(), getMouseY(), isMouseButtonDown(MOUSE_LEFT) ? 1 : 0);

        // Build layout
        clayBeginLayout();

        // Root container: full screen, dark background, vertical layout
        clayOpen("root", CLAY_GROW, CLAY_GROW, 16, 16, 16, 16, 12, CLAY_TOP_TO_BOTTOM,
                 50, 50, 50, 255, 0);

            // Header
            clayOpen("header", CLAY_GROW, 60, 12, 12, 12, 12, 0, CLAY_LEFT_TO_RIGHT,
                     30, 30, 80, 255, 8);
                clayText("Tsuchi + Clay UI", 28, 0, 255, 255, 255, 255);
            clayClose();

            // Content area
            clayOpen("content", CLAY_GROW, CLAY_GROW, 16, 16, 16, 16, 8, CLAY_TOP_TO_BOTTOM,
                     40, 40, 40, 255, 4);
                clayText("Hello from Clay layout engine!", 20, 0, 200, 200, 200, 255);
                clayText("This UI is computed by Clay and rendered by Raylib.", 16, 0, 150, 150, 150, 255);

                // Button
                clayOpen("button", 200, 40, 8, 16, 8, 16, 0, CLAY_LEFT_TO_RIGHT,
                         60, 100, 200, 255, 6);
                    clayText("Click Me!", 18, 0, 255, 255, 255, 255);
                clayClose();

            clayClose();

        clayClose();

        clayEndLayout();

        // Render
        beginDrawing();
        clearBackground(BLACK);
        clayRender();
        endDrawing();
    }

    closeWindow();
}

main();
