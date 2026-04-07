// Raylib keyboard input — move a rectangle with arrow keys

function main() {
    initWindow(800, 600, "Tsuchi: Keyboard Input");
    setTargetFPS(60);

    let x = 380;
    let y = 280;
    let speed = 5;

    while (!windowShouldClose()) {
        // Input
        if (isKeyDown(KEY_RIGHT)) x = x + speed;
        if (isKeyDown(KEY_LEFT)) x = x - speed;
        if (isKeyDown(KEY_DOWN)) y = y + speed;
        if (isKeyDown(KEY_UP)) y = y - speed;

        // Draw
        beginDrawing();
        clearBackground(BLACK);
        drawRectangle(x, y, 40, 40, GREEN);
        drawText("Arrow keys to move", 10, 10, 20, LIGHTGRAY);
        endDrawing();
    }

    closeWindow();
}

main();
