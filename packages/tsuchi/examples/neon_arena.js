// Neon Arena — Geometry Wars-style arcade shooter
// WASD: move  Arrows: shoot  SPACE: bomb (3 uses)  ENTER: restart
// 4 enemy types, wave system, multiplier, 3 lives
// Compile: tsuchi compile examples/neon_arena.js

function absVal(x) { if (x < 0) return -x; return x; }
function clamp(v, lo, hi) { if (v < lo) return lo; if (v > hi) return hi; return v; }

function main() {
    let W = 800;
    let H = 600;
    initWindow(W, H, "Neon Arena");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // Play area bounds
    let BL = 24; let BT = 24; let BR = W - 24; let BB = H - 24;

    // ── Bullets ──
    let maxBul = 60;
    let bx = []; let by = []; let bvx = []; let bvy = []; let balive = [];
    let i = 0;
    while (i < maxBul) {
        bx.push(0); by.push(0); bvx.push(0); bvy.push(0); balive.push(0);
        i = i + 1;
    }

    // ── Enemies ──
    let maxEn = 60;
    let ex = []; let ey = []; let evx = []; let evy = [];
    let ealive = []; let etype = []; let ehp = []; let eflash = [];
    i = 0;
    while (i < maxEn) {
        ex.push(0); ey.push(0); evx.push(0); evy.push(0);
        ealive.push(0); etype.push(0); ehp.push(0); eflash.push(0);
        i = i + 1;
    }

    // ── Particles ──
    let maxP = 500;
    let px = []; let py = []; let pvx = []; let pvy = [];
    let plife = []; let pr = []; let pg = []; let pb = [];
    i = 0;
    while (i < maxP) {
        px.push(0); py.push(0); pvx.push(0); pvy.push(0);
        plife.push(0); pr.push(0); pg.push(0); pb.push(0);
        i = i + 1;
    }
    let nextP = 0;

    // ── Game state ──
    let playerX = 400; let playerY = 300;
    let pSpeed = 220;
    let lives = 3;
    let invTimer = 0;
    let score = 0;
    let multi = 1;
    let killStreak = 0;
    let bombs = 3;
    let wave = 0;
    let waveEnemies = 0;
    let waveSpawned = 0;
    let spawnTimer = 0;
    let waveDelay = 2.0;
    let gameOver = 0;
    let shootCD = 0;
    let time = 0;
    let screenShake = 0;

    while (!windowShouldClose()) {
        let dt = getFrameTime();
        time = time + dt;

        // ── Restart ──
        if (gameOver == 1 && isKeyPressed(KEY_ENTER)) {
            gameOver = 0; score = 0; multi = 1; killStreak = 0;
            lives = 3; bombs = 3; wave = 0; waveSpawned = 0;
            waveEnemies = 0; waveDelay = 1.5;
            playerX = 400; playerY = 300; invTimer = 0;
            i = 0; while (i < maxEn) { ealive[i] = 0; i = i + 1; }
            i = 0; while (i < maxBul) { balive[i] = 0; i = i + 1; }
            i = 0; while (i < maxP) { plife[i] = 0; i = i + 1; }
        }

        if (gameOver == 0) {
            // ── Player movement ──
            let pmx = 0; let pmy = 0;
            if (isKeyDown(KEY_A)) pmx = pmx - 1;
            if (isKeyDown(KEY_D)) pmx = pmx + 1;
            if (isKeyDown(KEY_W)) pmy = pmy - 1;
            if (isKeyDown(KEY_S)) pmy = pmy + 1;
            // Normalize diagonal
            if (pmx != 0 && pmy != 0) {
                pmx = pmx * 0.707; pmy = pmy * 0.707;
            }
            playerX = clamp(playerX + pmx * pSpeed * dt, BL + 10, BR - 10);
            playerY = clamp(playerY + pmy * pSpeed * dt, BT + 10, BB - 10);

            // ── Shooting ──
            let sdx = 0; let sdy = 0;
            if (isKeyDown(KEY_LEFT))  sdx = sdx - 1;
            if (isKeyDown(KEY_RIGHT)) sdx = sdx + 1;
            if (isKeyDown(KEY_UP))    sdy = sdy - 1;
            if (isKeyDown(KEY_DOWN))  sdy = sdy + 1;
            if (sdx != 0 && sdy != 0) {
                sdx = sdx * 0.707; sdy = sdy * 0.707;
            }

            shootCD = shootCD - dt;
            if ((sdx != 0 || sdy != 0) && shootCD <= 0) {
                shootCD = 0.07;
                let bulSpeed = 500;
                i = 0;
                while (i < maxBul) {
                    if (balive[i] == 0) {
                        balive[i] = 1;
                        bx[i] = playerX; by[i] = playerY;
                        bvx[i] = sdx * bulSpeed; bvy[i] = sdy * bulSpeed;
                        i = maxBul;
                    }
                    i = i + 1;
                }
            }

            // ── Bomb ──
            if (isKeyPressed(KEY_SPACE) && bombs > 0) {
                bombs = bombs - 1;
                screenShake = 15;
                // Kill all enemies
                i = 0;
                while (i < maxEn) {
                    if (ealive[i] == 1) {
                        // Explosion
                        let b = 0;
                        while (b < 10) {
                            px[nextP] = ex[i]; py[nextP] = ey[i];
                            pvx[nextP] = getRandomValue(-200, 200);
                            pvy[nextP] = getRandomValue(-200, 200);
                            plife[nextP] = getRandomValue(15, 40);
                            pr[nextP] = 255; pg[nextP] = 255; pb[nextP] = 255;
                            nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                            b = b + 1;
                        }
                        ealive[i] = 0;
                        score = score + 5 * multi;
                    }
                    i = i + 1;
                }
            }

            // ── Update bullets ──
            i = 0;
            while (i < maxBul) {
                if (balive[i] == 1) {
                    bx[i] = bx[i] + bvx[i] * dt;
                    by[i] = by[i] + bvy[i] * dt;
                    if (bx[i] < BL || bx[i] > BR || by[i] < BT || by[i] > BB) {
                        balive[i] = 0;
                    }
                }
                i = i + 1;
            }

            // ── Wave spawning ──
            waveDelay = waveDelay - dt;
            if (waveDelay <= 0) {
                // Count alive enemies
                let aliveCount = 0;
                i = 0;
                while (i < maxEn) {
                    if (ealive[i] == 1) aliveCount = aliveCount + 1;
                    i = i + 1;
                }
                if (waveSpawned >= waveEnemies && aliveCount == 0) {
                    // Next wave
                    wave = wave + 1;
                    waveEnemies = 4 + wave * 3;
                    if (waveEnemies > 50) waveEnemies = 50;
                    waveSpawned = 0;
                    waveDelay = 2.0;
                    spawnTimer = 0;
                }
                // Spawn enemies
                spawnTimer = spawnTimer - dt;
                if (spawnTimer <= 0 && waveSpawned < waveEnemies) {
                    spawnTimer = 0.5 - wave * 0.02;
                    if (spawnTimer < 0.1) spawnTimer = 0.1;
                    i = 0;
                    while (i < maxEn) {
                        if (ealive[i] == 0) {
                            ealive[i] = 1;
                            // Spawn from random edge
                            let edge = getRandomValue(0, 3);
                            if (edge == 0) { ex[i] = BL; ey[i] = getRandomValue(BT, BB); }
                            if (edge == 1) { ex[i] = BR; ey[i] = getRandomValue(BT, BB); }
                            if (edge == 2) { ex[i] = getRandomValue(BL, BR); ey[i] = BT; }
                            if (edge == 3) { ex[i] = getRandomValue(BL, BR); ey[i] = BB; }

                            // Type based on wave
                            let typeRoll = getRandomValue(0, 100);
                            if (wave < 3) {
                                etype[i] = 0; // drifters only
                            } else if (wave < 5) {
                                if (typeRoll < 60) etype[i] = 0;
                                else etype[i] = 1;
                            } else if (wave < 8) {
                                if (typeRoll < 40) etype[i] = 0;
                                else if (typeRoll < 70) etype[i] = 1;
                                else etype[i] = 2;
                            } else {
                                if (typeRoll < 30) etype[i] = 0;
                                else if (typeRoll < 55) etype[i] = 1;
                                else if (typeRoll < 80) etype[i] = 2;
                                else etype[i] = 3;
                            }
                            // HP
                            if (etype[i] == 3) ehp[i] = 3;
                            else ehp[i] = 1;
                            eflash[i] = 0;
                            waveSpawned = waveSpawned + 1;
                            i = maxEn;
                        }
                        i = i + 1;
                    }
                }
            }

            // ── Update enemies ──
            i = 0;
            while (i < maxEn) {
                if (ealive[i] == 1) {
                    let dx = playerX - ex[i];
                    let dy = playerY - ey[i];
                    let dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 1) dist = 1;
                    let nx = dx / dist;
                    let ny = dy / dist;

                    if (etype[i] == 0) {
                        // Drifter: chase slowly
                        let spd = 65 + wave * 3;
                        evx[i] = nx * spd; evy[i] = ny * spd;
                    }
                    if (etype[i] == 1) {
                        // Bouncer: straight line, bounce
                        if (evx[i] == 0 && evy[i] == 0) {
                            evx[i] = nx * 140; evy[i] = ny * 140;
                        }
                        if (ex[i] < BL + 5 || ex[i] > BR - 5) evx[i] = -evx[i];
                        if (ey[i] < BT + 5 || ey[i] > BB - 5) evy[i] = -evy[i];
                    }
                    if (etype[i] == 2) {
                        // Rusher: slow then burst
                        let spd = 40;
                        if (dist < 200) spd = 250 + wave * 5;
                        evx[i] = nx * spd; evy[i] = ny * spd;
                    }
                    if (etype[i] == 3) {
                        // Tank: slow chase
                        let spd = 35 + wave * 2;
                        evx[i] = nx * spd; evy[i] = ny * spd;
                    }

                    ex[i] = clamp(ex[i] + evx[i] * dt, BL, BR);
                    ey[i] = clamp(ey[i] + evy[i] * dt, BT, BB);
                    if (eflash[i] > 0) eflash[i] = eflash[i] - 1;
                }
                i = i + 1;
            }

            // ── Collision: bullets vs enemies ──
            let bi = 0;
            while (bi < maxBul) {
                if (balive[bi] == 1) {
                    i = 0;
                    while (i < maxEn) {
                        if (ealive[i] == 1) {
                            let dx = bx[bi] - ex[i];
                            let dy = by[bi] - ey[i];
                            let hitR = 10;
                            if (etype[i] == 3) hitR = 16;
                            if (dx * dx + dy * dy < hitR * hitR) {
                                balive[bi] = 0;
                                ehp[i] = ehp[i] - 1;
                                eflash[i] = 5;
                                if (ehp[i] <= 0) {
                                    ealive[i] = 0;
                                    // Score
                                    let pts = 10;
                                    if (etype[i] == 1) pts = 15;
                                    if (etype[i] == 2) pts = 20;
                                    if (etype[i] == 3) pts = 50;
                                    score = score + pts * multi;
                                    killStreak = killStreak + 1;
                                    if (killStreak > 0 && killStreak - Math.floor(killStreak / 8) * 8 == 0) {
                                        multi = multi + 1;
                                        if (multi > 20) multi = 20;
                                    }
                                    screenShake = 4;
                                    // Explosion particles
                                    let cr = 255; let cg = 60; let cb = 60;
                                    if (etype[i] == 1) { cr = 255; cg = 160; cb = 40; }
                                    if (etype[i] == 2) { cr = 180; cg = 60; cb = 255; }
                                    if (etype[i] == 3) { cr = 60; cg = 255; cb = 100; }
                                    let b = 0;
                                    let burst = 15;
                                    if (etype[i] == 3) burst = 25;
                                    while (b < burst) {
                                        px[nextP] = ex[i]; py[nextP] = ey[i];
                                        pvx[nextP] = getRandomValue(-250, 250);
                                        pvy[nextP] = getRandomValue(-250, 250);
                                        plife[nextP] = getRandomValue(15, 45);
                                        pr[nextP] = cr; pg[nextP] = cg; pb[nextP] = cb;
                                        nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                        b = b + 1;
                                    }
                                }
                                i = maxEn;
                            }
                        }
                        i = i + 1;
                    }
                }
                bi = bi + 1;
            }

            // ── Collision: enemies vs player ──
            if (invTimer > 0) {
                invTimer = invTimer - dt;
            } else {
                i = 0;
                while (i < maxEn) {
                    if (ealive[i] == 1) {
                        let dx = playerX - ex[i];
                        let dy = playerY - ey[i];
                        if (dx * dx + dy * dy < 18 * 18) {
                            lives = lives - 1;
                            invTimer = 2.0;
                            multi = 1; killStreak = 0;
                            screenShake = 12;
                            // Damage particles
                            let b = 0;
                            while (b < 20) {
                                px[nextP] = playerX; py[nextP] = playerY;
                                pvx[nextP] = getRandomValue(-300, 300);
                                pvy[nextP] = getRandomValue(-300, 300);
                                plife[nextP] = getRandomValue(15, 35);
                                pr[nextP] = 0; pg[nextP] = 255; pb[nextP] = 255;
                                nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                b = b + 1;
                            }
                            if (lives <= 0) { lives = 0; gameOver = 1; }
                            i = maxEn;
                        }
                    }
                    i = i + 1;
                }
            }

            // ── Update particles ──
            i = 0;
            while (i < maxP) {
                if (plife[i] > 0) {
                    px[i] = px[i] + pvx[i] * dt;
                    py[i] = py[i] + pvy[i] * dt;
                    pvx[i] = pvx[i] * 0.97;
                    pvy[i] = pvy[i] * 0.97;
                    plife[i] = plife[i] - 1;
                }
                i = i + 1;
            }

            if (screenShake > 0) screenShake = screenShake - 1;
        }

        // ════════════════════════════════════
        //  DRAW
        // ════════════════════════════════════
        let shX = 0; let shY = 0;
        if (screenShake > 0) {
            shX = getRandomValue(-3, 3); shY = getRandomValue(-3, 3);
        }

        beginDrawing();
        clearBackground(color(4, 2, 8, 255));

        // ── Background grid ──
        let gx = BL;
        while (gx <= BR) {
            drawLine(gx + shX, BT + shY, gx + shX, BB + shY, color(15, 8, 25, 80));
            gx = gx + 40;
        }
        let gy = BT;
        while (gy <= BB) {
            drawLine(BL + shX, gy + shY, BR + shX, gy + shY, color(15, 8, 25, 80));
            gy = gy + 40;
        }

        // ── Particles (behind entities) ──
        i = 0;
        while (i < maxP) {
            if (plife[i] > 0) {
                let alpha = plife[i] * 6;
                if (alpha > 255) alpha = 255;
                let sz = 1 + plife[i] / 15;
                if (sz > 4) sz = 4;
                drawCircle(px[i] + shX, py[i] + shY, sz + 2,
                    color(pr[i], pg[i], pb[i], alpha / 4));
                drawCircle(px[i] + shX, py[i] + shY, sz,
                    color(pr[i], pg[i], pb[i], alpha));
            }
            i = i + 1;
        }

        // ── Enemies ──
        i = 0;
        while (i < maxEn) {
            if (ealive[i] == 1) {
                let exx = ex[i] + shX;
                let eyy = ey[i] + shY;
                let flash = eflash[i] > 0;

                if (etype[i] == 0) {
                    // Red drifter (circle)
                    drawCircle(exx, eyy, 14, color(255, 30, 30, 25));
                    drawCircle(exx, eyy, 10, color(255, 40, 40, 80));
                    if (flash) drawCircle(exx, eyy, 8, color(255, 255, 255, 200));
                    else drawCircle(exx, eyy, 7, color(255, 70, 60, 255));
                    drawCircle(exx, eyy, 3, color(255, 180, 160, 255));
                }
                if (etype[i] == 1) {
                    // Orange bouncer (diamond)
                    drawCircle(exx, eyy, 14, color(255, 140, 20, 25));
                    drawRectanglePro(exx, eyy, 16, 16, 8, 8, 45, color(255, 160, 40, 80));
                    if (flash) drawRectanglePro(exx, eyy, 12, 12, 6, 6, 45, color(255, 255, 255, 200));
                    else drawRectanglePro(exx, eyy, 12, 12, 6, 6, 45, color(255, 160, 40, 255));
                }
                if (etype[i] == 2) {
                    // Purple rusher (small fast)
                    drawCircle(exx, eyy, 12, color(160, 40, 255, 25));
                    drawCircle(exx, eyy, 8, color(180, 60, 255, 80));
                    if (flash) drawCircle(exx, eyy, 6, color(255, 255, 255, 200));
                    else drawCircle(exx, eyy, 5, color(200, 80, 255, 255));
                    drawCircle(exx, eyy, 2, color(230, 180, 255, 255));
                }
                if (etype[i] == 3) {
                    // Green tank (large)
                    drawCircle(exx, eyy, 22, color(40, 255, 80, 20));
                    drawCircle(exx, eyy, 16, color(60, 255, 100, 60));
                    if (flash) drawCircle(exx, eyy, 13, color(255, 255, 255, 200));
                    else drawCircle(exx, eyy, 13, color(60, 255, 100, 255));
                    drawCircle(exx, eyy, 7, color(120, 255, 160, 255));
                    // HP indicator
                    if (ehp[i] >= 2) drawCircle(exx, eyy, 4, color(200, 255, 220, 255));
                    if (ehp[i] >= 3) drawCircle(exx - 5, eyy, 2, color(200, 255, 220, 255));
                }
            }
            i = i + 1;
        }

        // ── Bullets ──
        i = 0;
        while (i < maxBul) {
            if (balive[i] == 1) {
                let bbx = bx[i] + shX;
                let bby = by[i] + shY;
                // Trail
                let tx = bbx - bvx[i] * 0.02;
                let ty = bby - bvy[i] * 0.02;
                drawLineEx(tx, ty, bbx, bby, 3, color(255, 255, 100, 60));
                drawLineEx(tx, ty, bbx, bby, 1, color(255, 255, 200, 200));
                // Head
                drawCircle(bbx, bby, 3, color(255, 255, 220, 255));
            }
            i = i + 1;
        }

        // ── Player ──
        let ppx = playerX + shX;
        let ppy = playerY + shY;
        let visible = 1;
        if (invTimer > 0) {
            // Blink during invulnerability
            let blinkPhase = time * 12;
            if (blinkPhase - Math.floor(blinkPhase / 2) * 2 < 1) visible = 0;
        }
        if (visible == 1) {
            drawCircle(ppx, ppy, 20, color(0, 255, 255, 20));
            drawCircle(ppx, ppy, 14, color(0, 255, 255, 40));
            drawCircle(ppx, ppy, 8, color(0, 255, 255, 255));
            drawCircle(ppx, ppy, 4, color(200, 255, 255, 255));
        }

        // ── Arena border ──
        // Glow
        drawRectangleLines(BL - 3, BT - 3, BR - BL + 6, BB - BT + 6,
            color(0, 180, 255, 40));
        // Frame
        drawRectangleLines(BL - 1, BT - 1, BR - BL + 2, BB - BT + 2,
            color(0, 200, 255, 150));
        // Corner accents
        let cornerSz = 12;
        // Top-left
        drawLine(BL, BT, BL + cornerSz, BT, color(0, 255, 255, 255));
        drawLine(BL, BT, BL, BT + cornerSz, color(0, 255, 255, 255));
        // Top-right
        drawLine(BR, BT, BR - cornerSz, BT, color(0, 255, 255, 255));
        drawLine(BR, BT, BR, BT + cornerSz, color(0, 255, 255, 255));
        // Bottom-left
        drawLine(BL, BB, BL + cornerSz, BB, color(0, 255, 255, 255));
        drawLine(BL, BB, BL, BB - cornerSz, color(0, 255, 255, 255));
        // Bottom-right
        drawLine(BR, BB, BR - cornerSz, BB, color(0, 255, 255, 255));
        drawLine(BR, BB, BR, BB - cornerSz, color(0, 255, 255, 255));

        // Damage flash on border
        if (invTimer > 1.5) {
            drawRectangleLines(BL - 2, BT - 2, BR - BL + 4, BB - BT + 4,
                color(255, 0, 60, 150));
        }

        // ════════════════════════════════════
        //  HUD
        // ════════════════════════════════════
        // Score
        drawText("SCORE", 30, 2, 10, color(0, 200, 255, 180));
        drawText(String(score), 30, 12, 18, color(0, 255, 255, 255));

        // Multiplier
        if (multi > 1) {
            drawText("x" + String(multi), 160, 10, 22, color(255, 255, 0, 255));
        }

        // Wave
        drawText("WAVE " + String(wave), W - 100, 4, 14, color(180, 80, 255, 255));

        // Lives
        let lx = W - 100;
        i = 0;
        while (i < lives) {
            drawCircle(lx + i * 18, H - 12, 5, color(0, 255, 255, 255));
            i = i + 1;
        }

        // Bombs
        drawText("BOMB: " + String(bombs), 30, H - 18, 12, color(255, 200, 0, 200));

        // FPS
        drawText(String(getFPS()) + " FPS", W - 70, H - 18, 12, color(0, 200, 100, 180));

        // Wave announcement
        if (waveDelay > 1.0 && wave > 0) {
            let wa = (waveDelay - 1.0) * 255;
            if (wa > 255) wa = 255;
            drawText("W A V E  " + String(wave), 310, 270, 30, color(0, 200, 255, wa));
        }

        // ── Game Over ──
        if (gameOver == 1) {
            drawRectangle(0, 0, W, H, color(0, 0, 0, 160));
            drawText("GAME OVER", 260, 220, 44, color(255, 0, 80, 255));
            drawText("Score: " + String(score), 310, 280, 24, color(0, 255, 255, 255));
            drawText("Wave: " + String(wave) + "  Best Multiplier: x" + String(multi), 260, 320, 16, WHITE);
            drawText("ENTER to restart", 310, 370, 16, color(100, 100, 120, 255));
        }

        endDrawing();
    }

    closeWindow();
}

main();
