// Mandelbrot Set — Real-time fractal explorer
// Click to recenter, scroll to zoom
// Demonstrates pure FP performance (120K pixels/frame)
// Compile: tsuchi compile examples/mandelbrot.js

function main() {
    let W = 400;
    let H = 300;
    let totalPx = W * H;
    initWindow(W, H, "Tsuchi Mandelbrot");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    let centerX = -0.5;
    let centerY = 0;
    let zoom = 1;
    let maxIter = 100;
    let needsRedraw = 1;

    // Pixel color cache (parallel arrays)
    let pixR = [];
    let pixG = [];
    let pixB = [];
    let i = 0;
    while (i < totalPx) {
        pixR.push(0);
        pixG.push(0);
        pixB.push(0);
        i = i + 1;
    }

    while (!windowShouldClose()) {
        // Input: click to recenter
        if (isMouseButtonPressed(MOUSE_LEFT)) {
            let mx = getMouseX();
            let my = getMouseY();
            let scale = 3.0 / (zoom * W);
            centerX = centerX + (mx - W / 2) * scale;
            centerY = centerY + (my - H / 2) * scale;
            needsRedraw = 1;
        }

        // Input: scroll to zoom
        let wheel = getMouseWheelMove();
        if (wheel > 0) {
            zoom = zoom * 1.3;
            needsRedraw = 1;
        }
        if (wheel < 0) {
            zoom = zoom / 1.3;
            if (zoom < 0.1) zoom = 0.1;
            needsRedraw = 1;
        }

        // Reset with R
        if (isKeyPressed(KEY_R)) {
            centerX = -0.5;
            centerY = 0;
            zoom = 1;
            needsRedraw = 1;
        }

        // Increase/decrease max iterations
        if (isKeyPressed(KEY_UP)) {
            maxIter = maxIter + 50;
            needsRedraw = 1;
        }
        if (isKeyPressed(KEY_DOWN)) {
            maxIter = maxIter - 50;
            if (maxIter < 20) maxIter = 20;
            needsRedraw = 1;
        }

        // Recompute fractal only when view changes
        if (needsRedraw) {
            let scale = 3.0 / (zoom * W);
            let py = 0;
            while (py < H) {
                let ci = centerY + (py - H / 2) * scale;
                let px = 0;
                while (px < W) {
                    let cr = centerX + (px - W / 2) * scale;

                    // Mandelbrot iteration: z = z^2 + c
                    let zr = 0;
                    let zi = 0;
                    let iter = 0;
                    while (iter < maxIter) {
                        let zr2 = zr * zr;
                        let zi2 = zi * zi;
                        if (zr2 + zi2 > 4) {
                            iter = iter + maxIter + 1;
                        } else {
                            let newzr = zr2 - zi2 + cr;
                            zi = 2 * zr * zi + ci;
                            zr = newzr;
                            iter = iter + 1;
                        }
                    }

                    let idx = py * W + px;
                    if (iter <= maxIter) {
                        // Inside the set: black
                        pixR[idx] = 0;
                        pixG[idx] = 0;
                        pixB[idx] = 0;
                    } else {
                        // Outside: color based on escape iteration
                        let n = iter - maxIter - 1;
                        let t = n / maxIter;
                        pixR[idx] = Math.sin(t * 6.28) * 127 + 128;
                        pixG[idx] = Math.sin(t * 6.28 + 2.09) * 127 + 128;
                        pixB[idx] = Math.sin(t * 6.28 + 4.19) * 127 + 128;
                    }

                    px = px + 1;
                }
                py = py + 1;
            }
            needsRedraw = 0;
        }

        // Draw every frame from cache (avoids double-buffer flicker)
        beginDrawing();
        clearBackground(BLACK);

        let py = 0;
        while (py < H) {
            let px = 0;
            while (px < W) {
                let idx = py * W + px;
                let r = pixR[idx];
                let g = pixG[idx];
                let b = pixB[idx];
                if (r > 0 || g > 0 || b > 0) {
                    drawPixel(px, py, color(r, g, b, 255));
                }
                px = px + 1;
            }
            py = py + 1;
        }

        // HUD
        drawRectangle(0, 0, W, 30, color(0, 0, 0, 180));
        drawText("MANDELBROT", 8, 6, 16, WHITE);
        drawText("Click:center  Scroll:zoom  R:reset  Up/Down:detail", 120, 8, 12, GRAY);
        drawText("Zoom: " + String(Math.floor(zoom * 100) / 100) + "x", 8, H - 20, 12, GRAY);
        drawText("Iter: " + String(maxIter), W - 80, H - 20, 12, GRAY);
        drawText(String(getFPS()) + " FPS", W - 60, 8, 12, LIME);

        endDrawing();
    }

    closeWindow();
}

main();
