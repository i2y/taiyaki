// Star Voyager — 3D Space Combat with Full Cockpit
// Arrow keys to fly, SPACE to shoot, ENTER to restart
// Detailed cockpit, radar, planet, nebula — all drawn with layered shapes
// Compile: tsuchi compile examples/star_voyager.js

function absVal(x) {
    if (x < 0) return -x;
    return x;
}

function clamp(v, lo, hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

function main() {
    let W = 800;
    let H = 600;
    let halfW = 400;
    let halfH = 300;
    let focal = 300;

    initWindow(W, H, "Star Voyager");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // ── Object pools ──

    let numStars = 500;
    let starX = []; let starY = []; let starZ = []; let starB = [];
    let i = 0;
    while (i < numStars) {
        starX.push(getRandomValue(-700, 700));
        starY.push(getRandomValue(-500, 500));
        starZ.push(getRandomValue(20, 900));
        starB.push(getRandomValue(100, 255));
        i = i + 1;
    }

    let maxAst = 30;
    let astX = [];  let astY = [];  let astZ = [];
    let astVX = []; let astVY = [];
    let astRad = []; let astAlive = []; let astClr = [];
    i = 0;
    while (i < maxAst) {
        astX.push(0); astY.push(0); astZ.push(0);
        astVX.push(0); astVY.push(0);
        astRad.push(0); astAlive.push(0); astClr.push(0);
        i = i + 1;
    }

    let maxLaser = 20;
    let lasX = []; let lasY = []; let lasZ = []; let lasAlive = [];
    i = 0;
    while (i < maxLaser) {
        lasX.push(0); lasY.push(0); lasZ.push(0); lasAlive.push(0);
        i = i + 1;
    }

    let maxPart = 400;
    let pX = [];  let pY = [];  let pZ = [];
    let pVX = []; let pVY = []; let pVZ = [];
    let pLife = []; let pR = []; let pG = []; let pB = [];
    i = 0;
    while (i < maxPart) {
        pX.push(0); pY.push(0); pZ.push(0);
        pVX.push(0); pVY.push(0); pVZ.push(0);
        pLife.push(0); pR.push(0); pG.push(0); pB.push(0);
        i = i + 1;
    }
    let nextPart = 0;

    // ── Game state ──
    let shipX = 0;
    let shipY = 0;
    let shipSpeed = 280;
    let score = 0;
    let shield = 100;
    let wave = 1;
    let astSpeed = 90;
    let shootCD = 0;
    let gameOver = 0;
    let spawnTimer = 0;
    let spawned = 0;
    let waveSize = 6;
    let waveAnnounce = 120;
    let hitFlash = 0;
    let time = 0;

    // Planet background position
    let planetBX = 580;
    let planetBY = 140;

    while (!windowShouldClose()) {
        let dt = getFrameTime();
        time = time + dt;

        // ── Restart ──
        if (gameOver == 1 && isKeyPressed(KEY_ENTER)) {
            gameOver = 0;
            score = 0; shield = 100; wave = 1;
            astSpeed = 90; spawned = 0; waveSize = 6;
            shipX = 0; shipY = 0; waveAnnounce = 120;
            i = 0; while (i < maxAst) { astAlive[i] = 0; i = i + 1; }
            i = 0; while (i < maxLaser) { lasAlive[i] = 0; i = i + 1; }
            i = 0; while (i < maxPart) { pLife[i] = 0; i = i + 1; }
        }

        if (gameOver == 0) {
            if (isKeyDown(KEY_LEFT))  shipX = shipX - shipSpeed * dt;
            if (isKeyDown(KEY_RIGHT)) shipX = shipX + shipSpeed * dt;
            if (isKeyDown(KEY_UP))    shipY = shipY - shipSpeed * dt;
            if (isKeyDown(KEY_DOWN))  shipY = shipY + shipSpeed * dt;
            shipX = clamp(shipX, -350, 350);
            shipY = clamp(shipY, -250, 250);

            shootCD = shootCD - dt;
            if (isKeyDown(KEY_SPACE) && shootCD <= 0) {
                shootCD = 0.1;
                i = 0;
                while (i < maxLaser) {
                    if (lasAlive[i] == 0) {
                        lasAlive[i] = 1;
                        lasX[i] = shipX; lasY[i] = shipY; lasZ[i] = 10;
                        i = maxLaser;
                    }
                    i = i + 1;
                }
            }

            // Stars
            i = 0;
            while (i < numStars) {
                starZ[i] = starZ[i] - 180 * dt;
                if (starZ[i] < 1) {
                    starX[i] = getRandomValue(-700, 700);
                    starY[i] = getRandomValue(-500, 500);
                    starZ[i] = getRandomValue(700, 900);
                    starB[i] = getRandomValue(100, 255);
                }
                i = i + 1;
            }

            // Spawn asteroids
            spawnTimer = spawnTimer - dt;
            if (spawnTimer <= 0 && spawned < waveSize) {
                spawnTimer = 0.4 + 0.3 / wave;
                i = 0;
                while (i < maxAst) {
                    if (astAlive[i] == 0) {
                        astAlive[i] = 1;
                        astX[i] = getRandomValue(-350, 350);
                        astY[i] = getRandomValue(-250, 250);
                        astZ[i] = getRandomValue(500, 700);
                        astVX[i] = getRandomValue(-40, 40);
                        astVY[i] = getRandomValue(-30, 30);
                        astRad[i] = getRandomValue(14, 38);
                        astClr[i] = getRandomValue(0, 2);
                        spawned = spawned + 1;
                        i = maxAst;
                    }
                    i = i + 1;
                }
            }

            // Next wave
            let alive = 0;
            i = 0;
            while (i < maxAst) {
                if (astAlive[i] == 1) alive = alive + 1;
                i = i + 1;
            }
            if (spawned >= waveSize && alive == 0) {
                wave = wave + 1;
                waveSize = 6 + wave * 3;
                astSpeed = 90 + wave * 12;
                spawned = 0; spawnTimer = 2.0; waveAnnounce = 90;
            }
            if (waveAnnounce > 0) waveAnnounce = waveAnnounce - 1;

            // Update asteroids
            i = 0;
            while (i < maxAst) {
                if (astAlive[i] == 1) {
                    astZ[i] = astZ[i] - astSpeed * dt;
                    astX[i] = astX[i] + astVX[i] * dt;
                    astY[i] = astY[i] + astVY[i] * dt;
                    if (astZ[i] < 3) {
                        astAlive[i] = 0;
                        let dx = absVal(astX[i] - shipX);
                        let dy = absVal(astY[i] - shipY);
                        if (dx < 120 && dy < 100) {
                            shield = shield - 20;
                            hitFlash = 20;
                            if (shield <= 0) { shield = 0; gameOver = 1; }
                        }
                    }
                }
                i = i + 1;
            }

            // Update lasers
            i = 0;
            while (i < maxLaser) {
                if (lasAlive[i] == 1) {
                    lasZ[i] = lasZ[i] + 600 * dt;
                    if (lasZ[i] > 800) lasAlive[i] = 0;
                }
                i = i + 1;
            }

            // Collision
            let li = 0;
            while (li < maxLaser) {
                if (lasAlive[li] == 1) {
                    i = 0;
                    while (i < maxAst) {
                        if (astAlive[i] == 1) {
                            let dz = absVal(lasZ[li] - astZ[i]);
                            if (dz < 25) {
                                let dx = lasX[li] - astX[i];
                                let dy = lasY[li] - astY[i];
                                let distSq = dx * dx + dy * dy;
                                let thresh = astRad[i] * 2;
                                if (distSq < thresh * thresh) {
                                    astAlive[i] = 0;
                                    lasAlive[li] = 0;
                                    score = score + 10 * wave;
                                    let b = 0;
                                    while (b < 22) {
                                        pX[nextPart] = astX[i];
                                        pY[nextPart] = astY[i];
                                        pZ[nextPart] = astZ[i];
                                        pVX[nextPart] = getRandomValue(-180, 180);
                                        pVY[nextPart] = getRandomValue(-180, 180);
                                        pVZ[nextPart] = getRandomValue(-80, 80);
                                        pLife[nextPart] = getRandomValue(20, 55);
                                        pR[nextPart] = getRandomValue(200, 255);
                                        pG[nextPart] = getRandomValue(60, 200);
                                        pB[nextPart] = getRandomValue(0, 60);
                                        nextPart = nextPart + 1;
                                        if (nextPart >= maxPart) nextPart = 0;
                                        b = b + 1;
                                    }
                                    i = maxAst;
                                }
                            }
                        }
                        i = i + 1;
                    }
                }
                li = li + 1;
            }

            // Update particles
            i = 0;
            while (i < maxPart) {
                if (pLife[i] > 0) {
                    pX[i] = pX[i] + pVX[i] * dt;
                    pY[i] = pY[i] + pVY[i] * dt;
                    pZ[i] = pZ[i] + pVZ[i] * dt;
                    pLife[i] = pLife[i] - 1;
                }
                i = i + 1;
            }

            if (hitFlash > 0) hitFlash = hitFlash - 1;
            if (shield < 100 && shield > 0) {
                shield = shield + 2 * dt;
                if (shield > 100) shield = 100;
            }
        }

        // ════════════════════════════════════════
        //  DRAW
        // ════════════════════════════════════════
        beginDrawing();
        clearBackground(color(2, 2, 8, 255));

        // ── Deep space background ──
        drawRectangleGradientV(0, 0, W, H,
            color(3, 3, 14, 255), color(10, 5, 20, 255));

        // ── Distant nebula clouds ──
        drawCircle(150 - shipX * 0.02, 120 - shipY * 0.02, 120,
            color(20, 8, 40, 40));
        drawCircle(180 - shipX * 0.02, 100 - shipY * 0.02, 80,
            color(30, 10, 50, 30));
        drawCircle(600 - shipX * 0.015, 80 - shipY * 0.015, 100,
            color(10, 15, 45, 35));
        drawCircle(650 - shipX * 0.015, 60 - shipY * 0.015, 60,
            color(15, 20, 55, 25));
        // Warm nebula patch
        drawCircle(350 - shipX * 0.01, 400 - shipY * 0.01, 90,
            color(35, 12, 15, 25));

        // ── Background planet with atmosphere ──
        let plx = planetBX - shipX * 0.05;
        let ply = planetBY - shipY * 0.05;
        // Outer atmosphere glow
        drawCircle(plx, ply, 95, color(40, 80, 140, 15));
        drawCircle(plx, ply, 85, color(50, 90, 160, 25));
        // Planet body
        drawCircle(plx, ply, 70, color(25, 45, 80, 255));
        // Surface detail (bands)
        drawRectangle(plx - 68, ply - 8, 136, 5, color(30, 55, 95, 180));
        drawRectangle(plx - 65, ply + 12, 130, 3, color(20, 40, 75, 150));
        drawRectangle(plx - 60, ply - 25, 120, 4, color(35, 60, 100, 120));
        drawRectangle(plx - 55, ply + 28, 110, 3, color(22, 42, 78, 100));
        // Polar cap
        drawCircle(plx - 5, ply - 58, 20, color(60, 80, 120, 100));
        // Shadow (terminator line - dark right side)
        drawCircle(plx + 25, ply, 65, color(5, 10, 25, 150));
        // Atmosphere rim
        drawCircleLines(plx, ply, 72, color(60, 100, 170, 80));

        // ── Planet ring (ellipse via line segments) ──
        let ra = 0;
        while (ra < 6.28) {
            let rx = plx + Math.cos(ra) * 110;
            let ry = ply + Math.sin(ra) * 18;
            // Only draw ring parts not behind planet
            if (ry < ply - 10 || ry > ply + 10) {
                let ringB = 120 + Math.sin(ra * 3) * 30;
                drawPixel(rx, ry, color(ringB, ringB + 20, ringB + 40, 180));
                drawPixel(rx + 1, ry, color(ringB, ringB + 20, ringB + 40, 120));
            }
            ra = ra + 0.015;
        }

        // ── Stars ──
        i = 0;
        while (i < numStars) {
            if (starZ[i] > 1) {
                let sx = halfW + (starX[i] - shipX * 0.3) * focal / starZ[i];
                let sy = halfH + (starY[i] - shipY * 0.3) * focal / starZ[i];

                if (sx > 30 && sx < W - 30 && sy > 0 && sy < H - 130) {
                    let b = starB[i] * (1.0 - starZ[i] / 900);
                    if (b < 0) b = 0;

                    if (starZ[i] < 60) {
                        let z2 = starZ[i] + 30;
                        let sx2 = halfW + (starX[i] - shipX * 0.3) * focal / z2;
                        let sy2 = halfH + (starY[i] - shipY * 0.3) * focal / z2;
                        drawLineEx(sx2, sy2, sx, sy, 2, color(b, b, b + 40, 200));
                    } else if (starZ[i] < 250) {
                        drawCircle(sx, sy, 2, color(b, b, b + 20, 255));
                    } else {
                        drawPixel(sx, sy, color(b, b, b + 15, 255));
                    }
                }
            }
            i = i + 1;
        }

        // ── Asteroids with detail ──
        i = 0;
        while (i < maxAst) {
            if (astAlive[i] == 1 && astZ[i] > 8) {
                let ax = halfW + (astX[i] - shipX) * focal / astZ[i];
                let ay = halfH + (astY[i] - shipY) * focal / astZ[i];
                let ar = astRad[i] * focal / astZ[i];

                if (ax > 0 - ar && ax < W + ar && ay > 0 - ar && ay < H + ar && ar > 1) {
                    let depth = 1.0 - astZ[i] / 700;
                    if (depth < 0.12) depth = 0.12;

                    let cr = 140; let cg = 130; let cb = 115;
                    if (astClr[i] == 1) { cr = 155; cg = 115; cb = 80; }
                    if (astClr[i] == 2) { cr = 165; cg = 100; cb = 90; }
                    cr = cr * depth; cg = cg * depth; cb = cb * depth;

                    // Body
                    drawCircle(ax, ay, ar, color(cr, cg, cb, 255));
                    // Shadow (lower-right)
                    drawCircle(ax + ar * 0.2, ay + ar * 0.2, ar * 0.8,
                        color(cr * 0.5, cg * 0.5, cb * 0.5, 200));
                    // Crater 1
                    if (ar > 5) {
                        drawCircle(ax - ar * 0.25, ay + ar * 0.1, ar * 0.22,
                            color(cr * 0.4, cg * 0.4, cb * 0.4, 200));
                    }
                    // Crater 2
                    if (ar > 8) {
                        drawCircle(ax + ar * 0.1, ay - ar * 0.3, ar * 0.15,
                            color(cr * 0.45, cg * 0.45, cb * 0.45, 180));
                    }
                    // Highlight (upper-left)
                    drawCircle(ax - ar * 0.3, ay - ar * 0.3, ar * 0.25,
                        color(cr * 1.4, cg * 1.4, cb * 1.3, 80));

                    // Targeting bracket if close
                    if (astZ[i] < 200) {
                        let bsz = ar + 8;
                        let bc = color(0, 255, 120, 100);
                        // Top-left corner
                        drawLine(ax - bsz, ay - bsz, ax - bsz + 8, ay - bsz, bc);
                        drawLine(ax - bsz, ay - bsz, ax - bsz, ay - bsz + 8, bc);
                        // Top-right
                        drawLine(ax + bsz, ay - bsz, ax + bsz - 8, ay - bsz, bc);
                        drawLine(ax + bsz, ay - bsz, ax + bsz, ay - bsz + 8, bc);
                        // Bottom-left
                        drawLine(ax - bsz, ay + bsz, ax - bsz + 8, ay + bsz, bc);
                        drawLine(ax - bsz, ay + bsz, ax - bsz, ay + bsz - 8, bc);
                        // Bottom-right
                        drawLine(ax + bsz, ay + bsz, ax + bsz - 8, ay + bsz, bc);
                        drawLine(ax + bsz, ay + bsz, ax + bsz, ay + bsz - 8, bc);
                    }
                }
            }
            i = i + 1;
        }

        // ── Lasers with heavy glow ──
        i = 0;
        while (i < maxLaser) {
            if (lasAlive[i] == 1 && lasZ[i] > 5) {
                let lx1 = halfW + (lasX[i] - shipX) * focal / lasZ[i];
                let ly1 = halfH + (lasY[i] - shipY) * focal / lasZ[i];
                let lz2 = lasZ[i] - 35;
                if (lz2 < 5) lz2 = 5;
                let lx2 = halfW + (lasX[i] - shipX) * focal / lz2;
                let ly2 = halfH + (lasY[i] - shipY) * focal / lz2;

                // Wide outer glow
                drawLineEx(lx2, ly2, lx1, ly1, 14, color(0, 80, 255, 20));
                drawLineEx(lx2, ly2, lx1, ly1, 9, color(0, 140, 255, 40));
                // Bright body
                drawLineEx(lx2, ly2, lx1, ly1, 5, color(50, 200, 255, 140));
                // Hot core
                drawLineEx(lx2, ly2, lx1, ly1, 2, color(200, 250, 255, 255));

                // Muzzle flash at near end (close to camera)
                if (lasZ[i] < 60) {
                    let flashSize = (60 - lasZ[i]) / 6;
                    drawCircle(lx2, ly2, flashSize + 4, color(0, 120, 255, 30));
                    drawCircle(lx2, ly2, flashSize + 2, color(80, 200, 255, 60));
                    drawCircle(lx2, ly2, flashSize, color(220, 250, 255, 120));
                }
                // Tip glow at far end
                drawCircle(lx1, ly1, 3, color(100, 220, 255, 150));
            }
            i = i + 1;
        }

        // ── Explosion particles ──
        i = 0;
        while (i < maxPart) {
            if (pLife[i] > 0 && pZ[i] > 5) {
                let ex = halfW + (pX[i] - shipX) * focal / pZ[i];
                let ey = halfH + (pY[i] - shipY) * focal / pZ[i];
                let ea = pLife[i] * 5;
                if (ea > 255) ea = 255;
                let esize = 3.5 * focal / pZ[i];
                if (esize < 1) esize = 1;
                if (esize > 10) esize = 10;
                // Glow
                if (esize > 2) {
                    drawCircle(ex, ey, esize + 2, color(pR[i], pG[i], pB[i], ea / 4));
                }
                drawCircle(ex, ey, esize, color(pR[i], pG[i], pB[i], ea));
            }
            i = i + 1;
        }

        // ── Hit flash (red vignette) ──
        if (hitFlash > 0) {
            let ha = hitFlash * 10;
            drawRectangle(0, 0, W, 8, color(255, 30, 20, ha));
            drawRectangle(0, H - 8, W, 8, color(255, 30, 20, ha));
            drawRectangle(0, 0, 8, H, color(255, 30, 20, ha));
            drawRectangle(W - 8, 0, 8, H, color(255, 30, 20, ha));
        }

        // ════════════════════════════════════════
        //  COCKPIT OVERLAY
        // ════════════════════════════════════════
        let dashY = H - 130;
        let panelClr = color(18, 22, 28, 255);
        let panelLit = color(28, 34, 42, 255);
        let edgeClr = color(45, 55, 65, 255);
        let boltClr = color(50, 60, 70, 255);

        // ── Side struts ──
        drawRectangle(0, 0, 32, H, panelClr);
        drawRectangle(W - 32, 0, 32, H, panelClr);
        // Strut edges (highlight)
        drawRectangle(30, 0, 2, dashY, edgeClr);
        drawRectangle(W - 32, 0, 2, dashY, edgeClr);
        // Strut detail: small indicator lights
        let si = 0;
        while (si < 8) {
            let syy = 60 + si * 50;
            drawRectangle(10, syy, 8, 4, color(20, 60, 40, 200));
            drawRectangle(W - 18, syy, 8, 4, color(20, 60, 40, 200));
            // Active light (alternating)
            if (si * 7 + Math.floor(time * 2) - Math.floor(Math.floor(time * 2) / 2) * 2 == si - Math.floor(si / 2) * 2) {
                drawRectangle(10, syy, 8, 4, color(30, 180, 80, 150));
            }
            si = si + 1;
        }

        // Strut bolts
        drawCircle(16, 20, 3, boltClr);
        drawCircle(16, dashY - 10, 3, boltClr);
        drawCircle(W - 16, 20, 3, boltClr);
        drawCircle(W - 16, dashY - 10, 3, boltClr);

        // ── Top bar ──
        drawRectangle(32, 0, W - 64, 6, panelClr);
        drawRectangle(32, 4, W - 64, 2, edgeClr);

        // ── Dashboard base ──
        drawRectangle(0, dashY, W, 130, panelClr);
        drawRectangle(0, dashY, W, 2, edgeClr);
        // Dashboard inner panels
        drawRectangle(32, dashY + 4, W - 64, 122, panelLit);
        drawRectangle(32, dashY + 4, W - 64, 1, edgeClr);

        // ── Radar panel (left side of dashboard) ──
        let radarCX = 140;
        let radarCY = dashY + 65;
        let radarR = 50;
        // Radar background
        drawCircle(radarCX, radarCY, radarR + 3, edgeClr);
        drawCircle(radarCX, radarCY, radarR, color(8, 15, 10, 255));
        // Grid rings
        drawCircleLines(radarCX, radarCY, radarR * 0.33, color(20, 50, 30, 150));
        drawCircleLines(radarCX, radarCY, radarR * 0.66, color(20, 50, 30, 150));
        drawCircleLines(radarCX, radarCY, radarR, color(25, 60, 35, 200));
        // Cross lines
        drawLine(radarCX - radarR, radarCY, radarCX + radarR, radarCY, color(20, 50, 30, 120));
        drawLine(radarCX, radarCY - radarR, radarCX, radarCY + radarR, color(20, 50, 30, 120));
        // Sweep line
        let sweepAngle = time * 3;
        let sweepX = radarCX + Math.cos(sweepAngle) * radarR;
        let sweepY = radarCY + Math.sin(sweepAngle) * radarR;
        drawLine(radarCX, radarCY, sweepX, sweepY, color(0, 200, 60, 120));
        // Player dot
        drawCircle(radarCX, radarCY, 2, color(0, 255, 100, 255));
        // Asteroid blips on radar
        i = 0;
        while (i < maxAst) {
            if (astAlive[i] == 1) {
                let bx = radarCX + (astX[i] - shipX) / 700 * radarR;
                let by = radarCY - astZ[i] / 700 * radarR;
                let bdx = bx - radarCX;
                let bdy = by - radarCY;
                if (bdx * bdx + bdy * bdy < radarR * radarR) {
                    drawCircle(bx, by, 2, color(255, 80, 50, 200));
                }
            }
            i = i + 1;
        }
        drawText("RADAR", radarCX - 18, dashY + 8, 10, color(0, 150, 80, 200));

        // ── Shield gauge (center-left) ──
        let gaugeX = 230;
        let gaugeY = dashY + 20;
        drawRectangle(gaugeX, gaugeY, 160, 10, color(5, 10, 8, 255));
        drawRectangle(gaugeX, gaugeY, 160, 1, edgeClr);
        drawRectangle(gaugeX, gaugeY + 9, 160, 1, edgeClr);
        let shFill = shield * 156 / 100;
        let shR = 0; let shG = 180; let shB = 60;
        if (shield < 50) { shR = 200; shG = 160; shB = 30; }
        if (shield < 25) { shR = 240; shG = 50;  shB = 20; }
        drawRectangle(gaugeX + 2, gaugeY + 2, shFill, 6, color(shR, shG, shB, 255));
        // Segments
        let seg = 0;
        while (seg < 10) {
            drawRectangle(gaugeX + seg * 16, gaugeY, 1, 10, color(30, 40, 35, 200));
            seg = seg + 1;
        }
        drawText("SHIELD", gaugeX, gaugeY - 14, 10, color(0, 150, 80, 200));

        // ── Energy bar (center) ──
        let enX = 230;
        let enY = dashY + 52;
        drawRectangle(enX, enY, 160, 8, color(5, 8, 15, 255));
        let energy = 100 - shootCD * 200;
        if (energy < 0) energy = 0;
        if (energy > 100) energy = 100;
        let enFill = energy * 156 / 100;
        drawRectangle(enX + 2, enY + 2, enFill, 4, color(40, 100, 220, 200));
        drawText("ENERGY", enX, enY - 12, 10, color(40, 100, 200, 200));

        // ── Score display (right side) ──
        let scoreX = 450;
        drawRectangle(scoreX, dashY + 10, 150, 50, color(8, 12, 10, 255));
        drawRectangle(scoreX, dashY + 10, 150, 1, edgeClr);
        drawRectangle(scoreX, dashY + 59, 150, 1, edgeClr);
        drawText("SCORE", scoreX + 8, dashY + 14, 10, color(0, 150, 80, 200));
        drawText(String(score), scoreX + 8, dashY + 30, 24, color(0, 255, 180, 255));

        // ── Wave display (far right) ──
        let waveX = 620;
        drawRectangle(waveX, dashY + 10, 110, 50, color(8, 12, 10, 255));
        drawRectangle(waveX, dashY + 10, 110, 1, edgeClr);
        drawRectangle(waveX, dashY + 59, 110, 1, edgeClr);
        drawText("WAVE", waveX + 8, dashY + 14, 10, color(0, 150, 80, 200));
        drawText(String(wave), waveX + 8, dashY + 30, 24, color(0, 200, 255, 255));

        // ── FPS (bottom-right corner) ──
        drawText(String(getFPS()) + " FPS", W - 80, dashY + 100, 12, color(0, 200, 80, 200));

        // ── Dashboard bolts ──
        drawCircle(42, dashY + 10, 2, boltClr);
        drawCircle(W - 42, dashY + 10, 2, boltClr);
        drawCircle(42, H - 10, 2, boltClr);
        drawCircle(W - 42, H - 10, 2, boltClr);
        drawCircle(220, dashY + 10, 2, boltClr);
        drawCircle(420, dashY + 10, 2, boltClr);
        drawCircle(610, dashY + 10, 2, boltClr);

        // ── Targeting reticle ──
        let cx = halfW;
        let cy = (dashY) / 2;
        // Outer ring
        drawCircleLines(cx, cy, 35, color(0, 255, 120, 40));
        // Cross
        drawLine(cx - 28, cy, cx - 12, cy, color(0, 255, 120, 160));
        drawLine(cx + 12, cy, cx + 28, cy, color(0, 255, 120, 160));
        drawLine(cx, cy - 28, cx, cy - 12, color(0, 255, 120, 160));
        drawLine(cx, cy + 12, cx, cy + 28, color(0, 255, 120, 160));
        // Center dot
        drawCircle(cx, cy, 2, color(0, 255, 120, 200));
        // Corner ticks
        drawLine(cx - 24, cy - 24, cx - 18, cy - 18, color(0, 255, 120, 80));
        drawLine(cx + 24, cy - 24, cx + 18, cy - 18, color(0, 255, 120, 80));
        drawLine(cx - 24, cy + 24, cx - 18, cy + 18, color(0, 255, 120, 80));
        drawLine(cx + 24, cy + 24, cx + 18, cy + 18, color(0, 255, 120, 80));

        // ── Wave announcement ──
        if (waveAnnounce > 0) {
            let wa = waveAnnounce * 3;
            if (wa > 255) wa = 255;
            drawText("W A V E  " + String(wave), halfW - 80, cy - 60, 30, color(0, 200, 255, wa));
        }

        // ── Game Over ──
        if (gameOver == 1) {
            drawRectangle(32, 0, W - 64, dashY, color(0, 0, 0, 160));
            drawText("GAME OVER", halfW - 120, cy - 50, 40, color(255, 40, 30, 255));
            drawText("Score: " + String(score) + "   Wave: " + String(wave),
                halfW - 120, cy + 10, 20, WHITE);
            drawText("ENTER to restart", halfW - 80, cy + 50, 16, color(120, 120, 140, 255));
        }

        endDrawing();
    }

    closeWindow();
}

main();
