// Raylib hello world — bouncing ball

function main() {
    initWindow(800, 600, "Tsuchi + Raylib");
    setTargetFPS(60);

    let ballX = 400;
    let ballY = 300;
    let speedX = 5;
    let speedY = 4;

    while (!windowShouldClose()) {
        // Update
        ballX = ballX + speedX;
        ballY = ballY + speedY;
        if (ballX > 780 || ballX < 20) speedX = -speedX;
        if (ballY > 580 || ballY < 20) speedY = -speedY;

        // Draw
        beginDrawing();
        clearBackground(RAYWHITE);
        drawText("Tsuchi + Raylib!", 10, 10, 30, DARKGRAY);
        drawCircle(ballX, ballY, 20, RED);
        endDrawing();
    }

    closeWindow();
}

main();
