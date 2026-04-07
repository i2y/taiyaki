// Particles — 2000+ particle physics simulation
// Click to emit particles from mouse position
// Demonstrates LLVM-compiled numeric loops at 60 FPS
// Compile: tsuchi compile examples/particles.js

function clamp(val, min, max) {
    if (val < min) return min;
    if (val > max) return max;
    return val;
}

function main() {
    initWindow(800, 600, "Tsuchi Particles");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    let maxParticles = 2000;

    // Parallel arrays for particle data
    let px = [];     // x position
    let py = [];     // y position
    let pvx = [];    // x velocity
    let pvy = [];    // y velocity
    let plife = [];  // remaining life (frames)
    let pr = [];     // red
    let pg = [];     // green
    let pb = [];     // blue

    let i = 0;
    while (i < maxParticles) {
        px.push(0);
        py.push(0);
        pvx.push(0);
        pvy.push(0);
        plife.push(0);
        pr.push(0);
        pg.push(0);
        pb.push(0);
        i = i + 1;
    }

    let nextSlot = 0;
    let gravity = 0.15;
    let damping = 0.995;
    let totalEmitted = 0;

    while (!windowShouldClose()) {
        let dt = getFrameTime();

        // Emit particles on mouse click
        if (isMouseButtonDown(MOUSE_LEFT)) {
            let mx = getMouseX();
            let my = getMouseY();
            let burst = 20;
            let b = 0;
            while (b < burst) {
                let slot = nextSlot;
                nextSlot = nextSlot + 1;
                if (nextSlot >= maxParticles) nextSlot = 0;

                px[slot] = mx;
                py[slot] = my;

                // Random radial velocity
                let angle = (getRandomValue(0, 628) - 314) / 100;
                let speed = getRandomValue(100, 500) / 100;
                pvx[slot] = speed * Math.cos(angle);
                pvy[slot] = speed * Math.sin(angle);
                plife[slot] = getRandomValue(60, 180);

                // Color based on angle
                let hue = (angle + 3.14) / 6.28;
                pr[slot] = clamp(Math.abs(hue * 6 - 3) - 1, 0, 1) * 255;
                pg[slot] = clamp(2 - Math.abs(hue * 6 - 2), 0, 1) * 255;
                pb[slot] = clamp(2 - Math.abs(hue * 6 - 4), 0, 1) * 255;

                totalEmitted = totalEmitted + 1;
                b = b + 1;
            }
        }

        // Update all particles
        let alive = 0;
        i = 0;
        while (i < maxParticles) {
            if (plife[i] > 0) {
                // Apply gravity
                pvy[i] = pvy[i] + gravity;

                // Apply damping
                pvx[i] = pvx[i] * damping;
                pvy[i] = pvy[i] * damping;

                // Move
                px[i] = px[i] + pvx[i];
                py[i] = py[i] + pvy[i];

                // Bounce off walls
                if (px[i] < 0) {
                    px[i] = 0;
                    pvx[i] = -pvx[i] * 0.7;
                }
                if (px[i] > 800) {
                    px[i] = 800;
                    pvx[i] = -pvx[i] * 0.7;
                }
                if (py[i] > 600) {
                    py[i] = 600;
                    pvy[i] = -pvy[i] * 0.7;
                }

                plife[i] = plife[i] - 1;
                alive = alive + 1;
            }
            i = i + 1;
        }

        // Draw
        beginDrawing();
        clearBackground(BLACK);

        // Draw particles
        i = 0;
        while (i < maxParticles) {
            if (plife[i] > 0) {
                // Alpha fades with life
                let alpha = plife[i] / 180;
                if (alpha > 1) alpha = 1;
                let r = pr[i] * alpha;
                let g = pg[i] * alpha;
                let b = pb[i] * alpha;
                let c = color(r, g, b, alpha * 255);

                // Size varies with remaining life
                let size = 2 + (plife[i] / 60);
                if (size > 5) size = 5;
                drawCircle(px[i], py[i], size, c);
            }
            i = i + 1;
        }

        // HUD
        drawText("TSUCHI PARTICLES", 20, 20, 24, WHITE);
        drawText("Click to emit", 20, 50, 16, GRAY);
        drawText(String(alive) + " alive", 20, 74, 16, GRAY);
        drawText(String(totalEmitted) + " total emitted", 20, 94, 16, GRAY);
        drawText(String(getFPS()) + " FPS", 700, 20, 20, LIME);

        endDrawing();
    }

    closeWindow();
}

main();
