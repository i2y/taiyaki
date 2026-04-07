// Breakout — Brick-breaking arcade game
// Controls: LEFT/RIGHT arrow keys to move paddle, SPACE to launch ball
// Compile: tsuchi compile examples/breakout.js

function clamp(val, min, max) {
    if (val < min) return min;
    if (val > max) return max;
    return val;
}

function absVal(x) {
    if (x < 0) return -x;
    return x;
}

function main() {
    initWindow(800, 600, "Tsuchi Breakout");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // Paddle
    let paddleX = 350;
    let paddleW = 100;
    let paddleH = 14;
    let paddleY = 560;
    let paddleSpeed = 8;

    // Ball
    let ballX = 400;
    let ballY = 545;
    let ballR = 6;
    let ballDX = 4;
    let ballDY = -5;
    let ballLaunched = 0;

    // Bricks: 10 columns x 6 rows
    let brickW = 72;
    let brickH = 24;
    let brickGap = 4;
    let brickOffX = 20;
    let brickOffY = 60;
    let totalBricks = 60;

    // Brick alive flags (1=alive, 0=dead)
    let bricks = [];
    let brickColors = [];
    let i = 0;
    while (i < totalBricks) {
        bricks.push(1);
        let row = Math.floor(i / 10);
        if (row === 0) {
            brickColors.push(0xFF3333FF);   // red
        } else if (row === 1) {
            brickColors.push(0xFF8800FF);   // orange
        } else if (row === 2) {
            brickColors.push(0xFFDD00FF);   // yellow
        } else if (row === 3) {
            brickColors.push(0x33DD33FF);   // green
        } else if (row === 4) {
            brickColors.push(0x3388FFFF);   // blue
        } else {
            brickColors.push(0xAA44FFFF);   // purple
        }
        i = i + 1;
    }

    let score = 0;
    let lives = 3;
    let gameOver = 0;
    let won = 0;

    while (!windowShouldClose()) {
        let dt = getFrameTime();

        if (gameOver === 0) {
            // === Paddle input ===
            if (isKeyDown(KEY_LEFT)) paddleX = paddleX - paddleSpeed;
            if (isKeyDown(KEY_RIGHT)) paddleX = paddleX + paddleSpeed;
            paddleX = clamp(paddleX, 0, 800 - paddleW);

            // Launch ball
            if (ballLaunched === 0) {
                ballX = paddleX + paddleW / 2;
                ballY = paddleY - ballR - 1;
                if (isKeyPressed(KEY_SPACE)) {
                    ballLaunched = 1;
                    ballDX = 4;
                    ballDY = -5;
                }
            }

            if (ballLaunched === 1) {
                // === Ball movement ===
                ballX = ballX + ballDX;
                ballY = ballY + ballDY;

                // Wall bounces
                if (ballX < ballR) {
                    ballX = ballR;
                    ballDX = absVal(ballDX);
                }
                if (ballX > 800 - ballR) {
                    ballX = 800 - ballR;
                    ballDX = -absVal(ballDX);
                }
                if (ballY < ballR) {
                    ballY = ballR;
                    ballDY = absVal(ballDY);
                }

                // Ball fell below paddle
                if (ballY > 620) {
                    lives = lives - 1;
                    ballLaunched = 0;
                    if (lives <= 0) {
                        gameOver = 1;
                    }
                }

                // Paddle collision
                if (ballDY > 0 && ballY + ballR >= paddleY && ballY + ballR <= paddleY + paddleH + 4) {
                    if (ballX >= paddleX - ballR && ballX <= paddleX + paddleW + ballR) {
                        ballDY = -absVal(ballDY);
                        // Angle based on hit position
                        let hitRatio = (ballX - paddleX) / paddleW;
                        ballDX = (hitRatio - 0.5) * 10;
                        ballY = paddleY - ballR - 1;
                    }
                }

                // Brick collision
                let b = 0;
                while (b < totalBricks) {
                    if (bricks[b] === 1) {
                        let row = Math.floor(b / 10);
                        let col = b % 10;
                        let bx = brickOffX + col * (brickW + brickGap);
                        let by = brickOffY + row * (brickH + brickGap);

                        // AABB check
                        if (ballX + ballR > bx && ballX - ballR < bx + brickW) {
                            if (ballY + ballR > by && ballY - ballR < by + brickH) {
                                bricks[b] = 0;
                                score = score + (6 - row) * 10;

                                // Determine bounce direction
                                let overlapLeft = (ballX + ballR) - bx;
                                let overlapRight = (bx + brickW) - (ballX - ballR);
                                let overlapTop = (ballY + ballR) - by;
                                let overlapBot = (by + brickH) - (ballY - ballR);

                                let minOverlapX = overlapLeft;
                                if (overlapRight < minOverlapX) minOverlapX = overlapRight;
                                let minOverlapY = overlapTop;
                                if (overlapBot < minOverlapY) minOverlapY = overlapBot;

                                if (minOverlapX < minOverlapY) {
                                    ballDX = -ballDX;
                                } else {
                                    ballDY = -ballDY;
                                }
                            }
                        }
                    }
                    b = b + 1;
                }

                // Check win
                let alive = 0;
                let c = 0;
                while (c < totalBricks) {
                    alive = alive + bricks[c];
                    c = c + 1;
                }
                if (alive === 0) {
                    gameOver = 1;
                    won = 1;
                }
            }
        } else {
            // Restart
            if (isKeyPressed(KEY_SPACE)) {
                gameOver = 0;
                won = 0;
                score = 0;
                lives = 3;
                ballLaunched = 0;
                paddleX = 350;
                let r = 0;
                while (r < totalBricks) {
                    bricks[r] = 1;
                    r = r + 1;
                }
            }
        }

        // === Draw ===
        beginDrawing();
        clearBackground(color(16, 16, 24, 255));

        // Bricks
        let d = 0;
        while (d < totalBricks) {
            if (bricks[d] === 1) {
                let row = Math.floor(d / 10);
                let col = d % 10;
                let bx = brickOffX + col * (brickW + brickGap);
                let by = brickOffY + row * (brickH + brickGap);
                drawRectangleRounded(bx, by, brickW, brickH, 0.3, 4, brickColors[d]);
            }
            d = d + 1;
        }

        // Paddle
        drawRectangleRounded(paddleX, paddleY, paddleW, paddleH, 0.5, 4, WHITE);

        // Ball
        drawCircle(ballX, ballY, ballR, YELLOW);

        // HUD
        drawText("SCORE: " + String(score), 20, 15, 20, LIGHTGRAY);

        // Lives as dots
        let lv = 0;
        while (lv < lives) {
            drawCircle(780 - lv * 24, 25, 8, RED);
            lv = lv + 1;
        }

        // Ball trail hint
        if (ballLaunched === 0 && gameOver === 0) {
            drawText("SPACE to launch", 310, 500, 20, GRAY);
        }

        // Game over / win screen
        if (gameOver === 1) {
            drawRectangle(200, 220, 400, 160, color(0, 0, 0, 180));
            if (won === 1) {
                drawText("YOU WIN!", 290, 250, 40, GREEN);
            } else {
                drawText("GAME OVER", 270, 250, 40, RED);
            }
            drawText("Score: " + String(score), 320, 310, 24, WHITE);
            drawText("SPACE to restart", 295, 350, 18, GRAY);
        }

        // FPS
        drawText(String(getFPS()), 760, 580, 14, DARKGRAY);

        endDrawing();
    }

    closeWindow();
}

main();
