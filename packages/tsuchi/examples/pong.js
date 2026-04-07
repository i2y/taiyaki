// Pong — Classic two-paddle game
// Controls: W/S for left paddle, UP/DOWN for right paddle

function clamp(val, min, max) {
    if (val < min) return min;
    if (val > max) return max;
    return val;
}

function main() {
    initWindow(800, 500, "Tsuchi Pong");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // Paddles
    let paddleW = 12;
    let paddleH = 80;
    let p1Y = 210;
    let p2Y = 210;
    let paddleSpeed = 6;

    // Ball
    let ballX = 400;
    let ballY = 250;
    let ballR = 8;
    let ballDX = 5;
    let ballDY = 3;

    // Score
    let score1 = 0;
    let score2 = 0;

    while (!windowShouldClose()) {
        // === Input ===
        if (isKeyDown(KEY_W)) p1Y = p1Y - paddleSpeed;
        if (isKeyDown(KEY_S)) p1Y = p1Y + paddleSpeed;
        if (isKeyDown(KEY_UP)) p2Y = p2Y - paddleSpeed;
        if (isKeyDown(KEY_DOWN)) p2Y = p2Y + paddleSpeed;

        p1Y = clamp(p1Y, 0, 500 - paddleH);
        p2Y = clamp(p2Y, 0, 500 - paddleH);

        // === Ball update ===
        ballX = ballX + ballDX;
        ballY = ballY + ballDY;

        // Top/bottom bounce
        if (ballY < ballR) {
            ballY = ballR;
            ballDY = -ballDY;
        }
        if (ballY > 500 - ballR) {
            ballY = 500 - ballR;
            ballDY = -ballDY;
        }

        // Left paddle collision
        if (ballX - ballR < 30 + paddleW && ballX - ballR > 30) {
            if (ballY > p1Y && ballY < p1Y + paddleH) {
                ballDX = -ballDX;
                ballX = 30 + paddleW + ballR;
                // Add spin based on hit position
                let hitPos = (ballY - p1Y) / paddleH;
                ballDY = (hitPos - 0.5) * 10;
            }
        }

        // Right paddle collision
        if (ballX + ballR > 758 - paddleW && ballX + ballR < 758) {
            if (ballY > p2Y && ballY < p2Y + paddleH) {
                ballDX = -ballDX;
                ballX = 758 - paddleW - ballR;
                let hitPos = (ballY - p2Y) / paddleH;
                ballDY = (hitPos - 0.5) * 10;
            }
        }

        // Scoring
        if (ballX < 0) {
            score2 = score2 + 1;
            ballX = 400;
            ballY = 250;
            ballDX = 5;
            ballDY = 3;
        }
        if (ballX > 800) {
            score1 = score1 + 1;
            ballX = 400;
            ballY = 250;
            ballDX = -5;
            ballDY = -3;
        }

        // === Draw ===
        beginDrawing();
        clearBackground(BLACK);

        // Center line
        let i = 0;
        while (i < 500) {
            drawRectangle(397, i, 6, 15, DARKGRAY);
            i = i + 25;
        }

        // Paddles
        drawRectangle(30, p1Y, paddleW, paddleH, WHITE);
        drawRectangle(758 - paddleW, p2Y, paddleW, paddleH, WHITE);

        // Ball
        drawCircle(ballX, ballY, ballR, YELLOW);

        // Score
        drawText(String(score1), 320, 20, 48, WHITE);
        drawText(String(score2), 440, 20, 48, WHITE);

        // Instructions
        drawText("W/S", 50, 470, 16, GRAY);
        drawText("UP/DOWN", 680, 470, 16, GRAY);

        endDrawing();
    }

    closeWindow();
}

main();
