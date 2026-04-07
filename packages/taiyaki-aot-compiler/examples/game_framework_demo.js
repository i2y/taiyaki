// Game Framework Demo — particles, tweens, screen shake, FSM
// Compile: uv run tsuchi compile examples/game_framework_demo.js

function main() {
    initWindow(800, 600, "Game Framework Demo");
    setTargetFPS(60);

    // FSM: 0=idle, 1=playing, 2=gameover
    gfFsmInit(0, 0);

    let px = 400;
    let py = 300;
    let score = 0;

    while (!windowShouldClose()) {
        let dt = getFrameTime();
        let state = gfFsmState(0);

        // Update FSM
        gfFsmTick(0);

        // Update timers and tweens
        gfTimerTick(dt);
        gfTweenTick(dt);

        // Update shake
        gfShakeUpdate(dt);

        // Update transitions
        gfTransitionUpdate(dt);

        // Update particles
        gfParticleUpdate(dt, 200);

        // Input
        let dir = gfGetDirection();
        let speed = 200;

        if (state === 0) {
            // Idle state
            if (gfConfirmPressed()) {
                gfFsmSet(0, 1);
                gfTweenStart(0, 0.5, 2); // outQuad fade in
            }
        }

        if (state === 1) {
            // Playing state
            if (dir === 0) { px = px + speed * dt; }
            if (dir === 1) { py = py - speed * dt; }
            if (dir === 2) { px = px - speed * dt; }
            if (dir === 3) { py = py + speed * dt; }

            // Clamp position
            px = gfClamp(px, 10, 790);
            py = gfClamp(py, 10, 590);

            // Emit particles on Space
            if (isKeyPressed(KEY_SPACE)) {
                let i = 0;
                while (i < 10) {
                    let vx = gfRandRange(-100, 100);
                    let vy = gfRandRange(-200, -50);
                    gfParticleEmit(px, py, vx, vy, 1.0, gfRgba(255, 200, 50, 255));
                    i = i + 1;
                }
                gfShakeStart(5, 0.3);
                score = score + 1;
            }

            if (gfCancelPressed()) {
                gfTransitionStart(1.0, 2);
            }
        }

        if (state === 2) {
            // Game over
            if (gfConfirmPressed()) {
                gfFsmSet(0, 0);
                score = 0;
                gfParticleClear();
            }
        }

        // Check transition
        if (gfTransitionDone() && gfTransitionNextScene() === 2) {
            gfFsmSet(0, 2);
        }

        // Draw
        beginDrawing();
        clearBackground(color(24, 24, 32, 255));

        if (state === 0) {
            drawText("Press ENTER to start", 250, 280, 24, WHITE);
            drawText("Arrow keys to move, Space for particles", 180, 320, 16, GRAY);
        }

        if (state === 1) {
            // Draw player (with shake offset)
            let sx = gfShakeX();
            let sy = gfShakeY();
            drawRectangle(px - 10 + sx, py - 10 + sy, 20, 20, GREEN);

            // Draw particles
            gfParticleDraw(3);

            // Draw score bar
            gfDrawBar(10, 10, 200, 16, score, 50, gfRgba(80, 200, 120, 255), gfRgba(40, 40, 50, 255));
            gfDrawNum(220, 10, score, 16, gfRgba(255, 255, 255, 255));

            // Draw FPS
            gfDrawFPS(740, 10, 14, gfRgba(100, 100, 120, 255));

            // Draw active particles count
            let pc = gfParticleCount();
            drawText("Particles:", 10, 560, 14, GRAY);
            gfDrawNum(100, 560, pc, 14, gfRgba(200, 200, 220, 255));
        }

        if (state === 2) {
            drawText("GAME OVER", 300, 250, 32, RED);
            drawText("Score:", 340, 300, 20, WHITE);
            gfDrawNum(410, 300, score, 20, gfRgba(255, 255, 100, 255));
            drawText("Press ENTER to restart", 260, 350, 16, GRAY);
        }

        // Draw transition fade
        let alpha = gfTransitionAlpha();
        if (alpha > 0) {
            gfDrawFade(alpha, 800, 600);
        }

        endDrawing();
    }

    closeWindow();
}

main();
