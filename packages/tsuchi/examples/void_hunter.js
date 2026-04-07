// Void Hunter — Side-scrolling space shooter
// WASD/Arrows: move  SPACE: shoot  1/2/3: switch weapon  ENTER: restart
// 6 enemy types, boss battles, 3 weapons, power-ups, parallax nebula
// Compile: tsuchi compile examples/void_hunter.js

function absVal(x) { if (x < 0) return -x; return x; }
function clamp(v, lo, hi) { if (v < lo) return lo; if (v > hi) return hi; return v; }
function lerp(a, b, t) { return a + (b - a) * t; }

function main() {
    let W = 900;
    let H = 650;
    initWindow(W, H, "Void Hunter");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // ════════════════════════════════════════
    //  BACKGROUND LAYERS
    // ════════════════════════════════════════
    // Layer 1: far stars (very slow)
    let nStar1 = 300;
    let s1x = []; let s1y = []; let s1b = [];
    let i = 0;
    while (i < nStar1) {
        s1x.push(getRandomValue(0, W));
        s1y.push(getRandomValue(0, H));
        s1b.push(getRandomValue(40, 140));
        i = i + 1;
    }
    // Layer 2: mid stars (medium)
    let nStar2 = 200;
    let s2x = []; let s2y = []; let s2b = [];
    i = 0;
    while (i < nStar2) {
        s2x.push(getRandomValue(0, W));
        s2y.push(getRandomValue(0, H));
        s2b.push(getRandomValue(80, 220));
        i = i + 1;
    }
    // Layer 3: near stars (fast, bright)
    let nStar3 = 80;
    let s3x = []; let s3y = []; let s3b = [];
    i = 0;
    while (i < nStar3) {
        s3x.push(getRandomValue(0, W));
        s3y.push(getRandomValue(0, H));
        s3b.push(getRandomValue(150, 255));
        i = i + 1;
    }
    // Nebula clouds (large transparent shapes)
    let nNeb = 18;
    let nebX = []; let nebY = []; let nebR = [];
    let nebCR = []; let nebCG = []; let nebCB = [];
    i = 0;
    while (i < nNeb) {
        nebX.push(getRandomValue(0, W * 2));
        nebY.push(getRandomValue(50, H - 50));
        nebR.push(getRandomValue(60, 180));
        let ntype = getRandomValue(0, 3);
        if (ntype == 0) { nebCR.push(40); nebCG.push(15); nebCB.push(80); }
        if (ntype == 1) { nebCR.push(80); nebCG.push(20); nebCB.push(50); }
        if (ntype == 2) { nebCR.push(15); nebCG.push(30); nebCB.push(70); }
        if (ntype == 3) { nebCR.push(50); nebCG.push(10); nebCB.push(60); }
        i = i + 1;
    }

    // ════════════════════════════════════════
    //  PLAYER
    // ════════════════════════════════════════
    let px = 120; let py = H / 2;
    let pSpeed = 240;
    let hp = 100; let maxHp = 100;
    let lives = 3;
    let invTimer = 0;
    let weapon = 0; // 0=rapid, 1=spread, 2=laser
    let shootCD = 0;
    let laserOn = 0;
    let energy = 100; let maxEnergy = 100;
    let shieldTimer = 0;
    let flame = 0;

    // ════════════════════════════════════════
    //  BULLETS (player)
    // ════════════════════════════════════════
    let maxBul = 80;
    let bx = []; let by = []; let bvx = []; let bvy = [];
    let balive = []; let bdmg = []; let btype = []; // 0=normal, 1=spread, 2=missile
    i = 0;
    while (i < maxBul) {
        bx.push(0); by.push(0); bvx.push(0); bvy.push(0);
        balive.push(0); bdmg.push(0); btype.push(0);
        i = i + 1;
    }

    // ════════════════════════════════════════
    //  ENEMY BULLETS
    // ════════════════════════════════════════
    let maxEBul = 40;
    let ebx = []; let eby = []; let ebvx = []; let ebvy = []; let ebalive = [];
    i = 0;
    while (i < maxEBul) {
        ebx.push(0); eby.push(0); ebvx.push(0); ebvy.push(0); ebalive.push(0);
        i = i + 1;
    }

    // ════════════════════════════════════════
    //  ENEMIES
    // ════════════════════════════════════════
    let maxEn = 40;
    let ex = []; let ey = []; let evx = []; let evy = [];
    let ealive = []; let etype = []; let ehp = []; let emaxhp = [];
    let eflash = []; let etimer = []; let efire = [];
    i = 0;
    while (i < maxEn) {
        ex.push(0); ey.push(0); evx.push(0); evy.push(0);
        ealive.push(0); etype.push(0); ehp.push(0); emaxhp.push(0);
        eflash.push(0); etimer.push(0); efire.push(0);
        i = i + 1;
    }

    // ════════════════════════════════════════
    //  PARTICLES
    // ════════════════════════════════════════
    let maxP = 600;
    let ppx = []; let ppy = []; let ppvx = []; let ppvy = [];
    let plife = []; let pR = []; let pG = []; let pB = []; let pSize = [];
    i = 0;
    while (i < maxP) {
        ppx.push(0); ppy.push(0); ppvx.push(0); ppvy.push(0);
        plife.push(0); pR.push(0); pG.push(0); pB.push(0); pSize.push(0);
        i = i + 1;
    }
    let nextP = 0;

    // ════════════════════════════════════════
    //  POWER-UPS
    // ════════════════════════════════════════
    let maxPow = 5;
    let powX = []; let powY = []; let powAlive = []; let powType = [];
    i = 0;
    while (i < maxPow) {
        powX.push(0); powY.push(0); powAlive.push(0); powType.push(0);
        i = i + 1;
    }

    // ════════════════════════════════════════
    //  GAME STATE
    // ════════════════════════════════════════
    let score = 0; let multi = 1; let killStreak = 0;
    let wave = 0; let waveEn = 0; let waveSpawned = 0;
    let spawnTimer = 0; let waveDelay = 2.0;
    let bossActive = 0; let bossHp = 0; let bossMaxHp = 0;
    let bossPhase = 0; let bossTimer = 0; let bossY = 0;
    let gameOver = 0; let time = 0;
    let screenShake = 0; let screenFlash = 0;
    let scrollX = 0;

    // Spawn helpers
    let spawnBullet = 0; // flag
    let spBx = 0; let spBy = 0; let spBvx = 0; let spBvy = 0; let spBdmg = 0; let spBtype = 0;

    while (!windowShouldClose()) {
        let dt = getFrameTime();
        time = time + dt;
        scrollX = scrollX + 60 * dt;

        // ── Restart ──
        if (gameOver == 1 && isKeyPressed(KEY_ENTER)) {
            gameOver = 0; score = 0; multi = 1; killStreak = 0;
            lives = 3; hp = maxHp; energy = maxEnergy;
            wave = 0; waveSpawned = 0; waveEn = 0; waveDelay = 1.5;
            bossActive = 0; weapon = 0;
            px = 120; py = H / 2; invTimer = 0; shieldTimer = 0;
            i = 0; while (i < maxEn) { ealive[i] = 0; i = i + 1; }
            i = 0; while (i < maxBul) { balive[i] = 0; i = i + 1; }
            i = 0; while (i < maxEBul) { ebalive[i] = 0; i = i + 1; }
            i = 0; while (i < maxP) { plife[i] = 0; i = i + 1; }
            i = 0; while (i < maxPow) { powAlive[i] = 0; i = i + 1; }
        }

        if (gameOver == 0) {
            // ── Player movement ──
            let mx = 0; let my = 0;
            if (isKeyDown(KEY_A) || isKeyDown(KEY_LEFT))  mx = mx - 1;
            if (isKeyDown(KEY_D) || isKeyDown(KEY_RIGHT)) mx = mx + 1;
            if (isKeyDown(KEY_W) || isKeyDown(KEY_UP))    my = my - 1;
            if (isKeyDown(KEY_S) || isKeyDown(KEY_DOWN))  my = my + 1;
            if (mx != 0 && my != 0) { mx = mx * 0.707; my = my * 0.707; }
            px = clamp(px + mx * pSpeed * dt, 30, W - 30);
            py = clamp(py + my * pSpeed * dt, 30, H - 80);

            // Engine flame animation
            flame = Math.sin(time * 20) * 2 + 3;
            if (mx > 0) flame = flame + 2;

            // Weapon switch
            if (isKeyPressed(KEY_1)) weapon = 0;
            if (isKeyPressed(KEY_2)) weapon = 1;
            if (isKeyPressed(KEY_3)) weapon = 2;

            // ── Shooting ──
            shootCD = shootCD - dt;
            let shooting = isKeyDown(KEY_SPACE);
            laserOn = 0;

            if (shooting && shootCD <= 0) {
                if (weapon == 0) {
                    // Rapid fire
                    shootCD = 0.08;
                    i = 0;
                    while (i < maxBul) {
                        if (balive[i] == 0) {
                            balive[i] = 1; bx[i] = px + 20; by[i] = py;
                            bvx[i] = 600; bvy[i] = 0; bdmg[i] = 8; btype[i] = 0;
                            i = maxBul;
                        }
                        i = i + 1;
                    }
                }
                if (weapon == 1) {
                    // Spread (3-way)
                    shootCD = 0.15;
                    let sAngles = 0;
                    while (sAngles < 3) {
                        let angle = (sAngles - 1) * 0.18;
                        i = 0;
                        while (i < maxBul) {
                            if (balive[i] == 0) {
                                balive[i] = 1; bx[i] = px + 18; by[i] = py;
                                bvx[i] = Math.cos(angle) * 500;
                                bvy[i] = Math.sin(angle) * 500;
                                bdmg[i] = 6; btype[i] = 1;
                                i = maxBul;
                            }
                            i = i + 1;
                        }
                        sAngles = sAngles + 1;
                    }
                }
                if (weapon == 2 && energy > 0) {
                    // Laser (continuous beam)
                    shootCD = 0.02;
                    laserOn = 1;
                    energy = energy - 30 * dt;
                    if (energy < 0) energy = 0;
                    // Laser hits enemies directly (check in collision)
                }
            }
            // Energy regen when not using laser
            if (weapon != 2 || shooting == 0) {
                energy = energy + 15 * dt;
                if (energy > maxEnergy) energy = maxEnergy;
            }

            // ── Update player bullets ──
            i = 0;
            while (i < maxBul) {
                if (balive[i] == 1) {
                    bx[i] = bx[i] + bvx[i] * dt;
                    by[i] = by[i] + bvy[i] * dt;
                    if (bx[i] > W + 20 || bx[i] < -20 || by[i] < -20 || by[i] > H + 20) balive[i] = 0;
                }
                i = i + 1;
            }

            // ── Update enemy bullets ──
            i = 0;
            while (i < maxEBul) {
                if (ebalive[i] == 1) {
                    ebx[i] = ebx[i] + ebvx[i] * dt;
                    eby[i] = eby[i] + ebvy[i] * dt;
                    if (ebx[i] < -20 || ebx[i] > W + 20 || eby[i] < -20 || eby[i] > H + 20) ebalive[i] = 0;
                }
                i = i + 1;
            }

            // ── Spawn waves ──
            waveDelay = waveDelay - dt;
            if (waveDelay <= 0 && bossActive == 0) {
                let aliveCount = 0;
                i = 0; while (i < maxEn) { if (ealive[i] == 1) aliveCount = aliveCount + 1; i = i + 1; }

                if (waveSpawned >= waveEn && aliveCount == 0) {
                    wave = wave + 1;
                    // Boss every 5 waves
                    if (wave > 0 && wave - Math.floor(wave / 5) * 5 == 0) {
                        // BOSS
                        bossActive = 1;
                        bossMaxHp = 200 + wave * 30;
                        bossHp = bossMaxHp;
                        bossPhase = 0; bossTimer = 0;
                        bossY = H / 2;
                        waveSpawned = 0; waveEn = 0;
                    } else {
                        waveEn = 5 + wave * 2;
                        if (waveEn > 35) waveEn = 35;
                        waveSpawned = 0;
                        waveDelay = 2.0;
                        spawnTimer = 0;
                    }
                }
                spawnTimer = spawnTimer - dt;
                if (spawnTimer <= 0 && waveSpawned < waveEn && bossActive == 0) {
                    spawnTimer = clamp(0.6 - wave * 0.03, 0.15, 0.8);
                    i = 0;
                    while (i < maxEn) {
                        if (ealive[i] == 0) {
                            ealive[i] = 1;
                            ex[i] = W + 30;
                            ey[i] = getRandomValue(40, H - 90);
                            eflash[i] = 0; etimer[i] = 0; efire[i] = 0;
                            // Type selection
                            let roll = getRandomValue(0, 100);
                            if (wave < 3) { etype[i] = 0; }
                            else if (wave < 6) {
                                if (roll < 50) etype[i] = 0; else if (roll < 80) etype[i] = 1; else etype[i] = 2;
                            } else {
                                if (roll < 25) etype[i] = 0; else if (roll < 50) etype[i] = 1;
                                else if (roll < 70) etype[i] = 2; else if (roll < 85) etype[i] = 3;
                                else etype[i] = 4;
                            }
                            // Stats by type
                            if (etype[i] == 0) { ehp[i] = 8; emaxhp[i] = 8; evx[i] = -100; evy[i] = 0; }    // Scout
                            if (etype[i] == 1) { ehp[i] = 20; emaxhp[i] = 20; evx[i] = -60; evy[i] = 0; }    // Fighter
                            if (etype[i] == 2) { ehp[i] = 15; emaxhp[i] = 15; evx[i] = -80; evy[i] = 0; }    // Swooper
                            if (etype[i] == 3) { ehp[i] = 35; emaxhp[i] = 35; evx[i] = -40; evy[i] = 0; }    // Heavy
                            if (etype[i] == 4) { ehp[i] = 50; emaxhp[i] = 50; evx[i] = -30; evy[i] = 0; }    // Carrier
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
                    etimer[i] = etimer[i] + dt;

                    if (etype[i] == 0) {
                        // Scout: fast, sine wave
                        ex[i] = ex[i] + evx[i] * dt;
                        ey[i] = ey[i] + Math.sin(etimer[i] * 4) * 120 * dt;
                    }
                    if (etype[i] == 1) {
                        // Fighter: approach, then hover and shoot
                        if (ex[i] > W * 0.65) ex[i] = ex[i] + evx[i] * dt;
                        else ex[i] = ex[i] + Math.sin(etimer[i] * 2) * 30 * dt;
                        ey[i] = ey[i] + Math.sin(etimer[i] * 1.5) * 60 * dt;
                        // Shoot
                        efire[i] = efire[i] - dt;
                        if (efire[i] <= 0 && ex[i] < W * 0.8) {
                            efire[i] = 1.2;
                            let fi = 0;
                            while (fi < maxEBul) {
                                if (ebalive[fi] == 0) {
                                    ebalive[fi] = 1;
                                    ebx[fi] = ex[i] - 15; eby[fi] = ey[i];
                                    ebvx[fi] = -250; ebvy[fi] = 0;
                                    fi = maxEBul;
                                }
                                fi = fi + 1;
                            }
                        }
                    }
                    if (etype[i] == 2) {
                        // Swooper: dive toward player
                        let dx = px - ex[i]; let dy = py - ey[i];
                        let dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 1) dist = 1;
                        ex[i] = ex[i] + evx[i] * dt + dx / dist * 50 * dt;
                        ey[i] = ey[i] + dy / dist * 80 * dt;
                    }
                    if (etype[i] == 3) {
                        // Heavy: slow, armored, shoots spread
                        ex[i] = ex[i] + evx[i] * dt;
                        ey[i] = ey[i] + Math.sin(etimer[i]) * 40 * dt;
                        efire[i] = efire[i] - dt;
                        if (efire[i] <= 0 && ex[i] < W * 0.85) {
                            efire[i] = 1.8;
                            let sa = 0;
                            while (sa < 3) {
                                let ang = (sa - 1) * 0.3 + 3.14;
                                let fi = 0;
                                while (fi < maxEBul) {
                                    if (ebalive[fi] == 0) {
                                        ebalive[fi] = 1;
                                        ebx[fi] = ex[i]; eby[fi] = ey[i];
                                        ebvx[fi] = Math.cos(ang) * 200;
                                        ebvy[fi] = Math.sin(ang) * 200;
                                        fi = maxEBul;
                                    }
                                    fi = fi + 1;
                                }
                                sa = sa + 1;
                            }
                        }
                    }
                    if (etype[i] == 4) {
                        // Carrier: very slow, spawns scouts
                        ex[i] = ex[i] + evx[i] * dt;
                        ey[i] = ey[i] + Math.sin(etimer[i] * 0.8) * 30 * dt;
                        efire[i] = efire[i] - dt;
                        if (efire[i] <= 0 && ex[i] < W * 0.9) {
                            efire[i] = 3.0;
                            let si = 0;
                            while (si < maxEn) {
                                if (ealive[si] == 0) {
                                    ealive[si] = 1; etype[si] = 0;
                                    ex[si] = ex[i] - 20; ey[si] = ey[i];
                                    evx[si] = -120; evy[si] = 0;
                                    ehp[si] = 5; emaxhp[si] = 5;
                                    etimer[si] = 0; eflash[si] = 0; efire[si] = 0;
                                    si = maxEn;
                                }
                                si = si + 1;
                            }
                        }
                    }

                    // Remove if off-screen left
                    if (ex[i] < -60) ealive[i] = 0;
                    if (eflash[i] > 0) eflash[i] = eflash[i] - 1;
                }
                i = i + 1;
            }

            // ── Boss update ──
            if (bossActive == 1) {
                bossTimer = bossTimer + dt;
                bossY = H / 2 + Math.sin(bossTimer * 1.2) * 150;
                // Boss shooting
                if (bossTimer - Math.floor(bossTimer / 1.5) * 1.5 < dt) {
                    let ba = 0;
                    while (ba < 5) {
                        let ang = 3.14 + (ba - 2) * 0.25;
                        let fi = 0;
                        while (fi < maxEBul) {
                            if (ebalive[fi] == 0) {
                                ebalive[fi] = 1;
                                ebx[fi] = W - 80; eby[fi] = bossY;
                                ebvx[fi] = Math.cos(ang) * 180;
                                ebvy[fi] = Math.sin(ang) * 180;
                                fi = maxEBul;
                            }
                            fi = fi + 1;
                        }
                        ba = ba + 1;
                    }
                }
                // Spiral attack in phase 2
                if (bossHp < bossMaxHp / 2) {
                    bossPhase = 1;
                    if (bossTimer - Math.floor(bossTimer / 0.3) * 0.3 < dt) {
                        let ang = bossTimer * 5;
                        let fi = 0;
                        while (fi < maxEBul) {
                            if (ebalive[fi] == 0) {
                                ebalive[fi] = 1;
                                ebx[fi] = W - 80; eby[fi] = bossY;
                                ebvx[fi] = Math.cos(ang) * 160;
                                ebvy[fi] = Math.sin(ang) * 160;
                                fi = maxEBul;
                            }
                            fi = fi + 1;
                        }
                    }
                }
            }

            // ── Collision: player bullets vs enemies ──
            let bi = 0;
            while (bi < maxBul) {
                if (balive[bi] == 1) {
                    // vs regular enemies
                    i = 0;
                    while (i < maxEn) {
                        if (ealive[i] == 1) {
                            let hitR = 12; if (etype[i] == 3) hitR = 18; if (etype[i] == 4) hitR = 22;
                            let dx = bx[bi] - ex[i]; let dy = by[bi] - ey[i];
                            if (dx * dx + dy * dy < hitR * hitR) {
                                balive[bi] = 0;
                                ehp[i] = ehp[i] - bdmg[bi];
                                eflash[i] = 4;
                                // Spark
                                let sp = 0;
                                while (sp < 3) {
                                    ppx[nextP] = bx[bi]; ppy[nextP] = by[bi];
                                    ppvx[nextP] = getRandomValue(-100, 100); ppvy[nextP] = getRandomValue(-100, 100);
                                    plife[nextP] = getRandomValue(5, 12); pR[nextP] = 255; pG[nextP] = 220; pB[nextP] = 100; pSize[nextP] = 1;
                                    nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                    sp = sp + 1;
                                }
                                if (ehp[i] <= 0) {
                                    ealive[i] = 0;
                                    let pts = 10; if (etype[i] == 1) pts = 25; if (etype[i] == 2) pts = 20;
                                    if (etype[i] == 3) pts = 50; if (etype[i] == 4) pts = 80;
                                    score = score + pts * multi;
                                    killStreak = killStreak + 1;
                                    if (killStreak > 0 && killStreak - Math.floor(killStreak / 6) * 6 == 0) {
                                        multi = multi + 1; if (multi > 16) multi = 16;
                                    }
                                    screenShake = 5;
                                    // Explosion
                                    let eR = 255; let eG = 80; let eB = 40;
                                    if (etype[i] == 2) { eR = 180; eG = 60; eB = 255; }
                                    if (etype[i] == 3) { eR = 100; eG = 255; eB = 100; }
                                    if (etype[i] == 4) { eR = 255; eG = 200; eB = 50; }
                                    let burst = 12 + etype[i] * 5;
                                    let sp2 = 0;
                                    while (sp2 < burst) {
                                        ppx[nextP] = ex[i]; ppy[nextP] = ey[i];
                                        ppvx[nextP] = getRandomValue(-250, 250); ppvy[nextP] = getRandomValue(-250, 250);
                                        plife[nextP] = getRandomValue(15, 45);
                                        pR[nextP] = eR; pG[nextP] = eG; pB[nextP] = eB; pSize[nextP] = getRandomValue(1, 3);
                                        nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                        sp2 = sp2 + 1;
                                    }
                                    // Drop power-up (15% chance)
                                    if (getRandomValue(0, 100) < 15) {
                                        let pi2 = 0;
                                        while (pi2 < maxPow) {
                                            if (powAlive[pi2] == 0) {
                                                powAlive[pi2] = 1; powX[pi2] = ex[i]; powY[pi2] = ey[i];
                                                powType[pi2] = getRandomValue(0, 3);
                                                pi2 = maxPow;
                                            }
                                            pi2 = pi2 + 1;
                                        }
                                    }
                                }
                                i = maxEn;
                            }
                        }
                        i = i + 1;
                    }
                    // vs boss
                    if (bossActive == 1 && balive[bi] == 1) {
                        let dx = bx[bi] - (W - 80); let dy = by[bi] - bossY;
                        if (dx * dx + dy * dy < 55 * 55) {
                            balive[bi] = 0;
                            bossHp = bossHp - bdmg[bi];
                            screenShake = 2;
                            let sp3 = 0;
                            while (sp3 < 2) {
                                ppx[nextP] = bx[bi]; ppy[nextP] = by[bi];
                                ppvx[nextP] = getRandomValue(-150, 50); ppvy[nextP] = getRandomValue(-100, 100);
                                plife[nextP] = getRandomValue(5, 15); pR[nextP] = 255; pG[nextP] = 100; pB[nextP] = 50; pSize[nextP] = 2;
                                nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                sp3 = sp3 + 1;
                            }
                            if (bossHp <= 0) {
                                bossActive = 0;
                                score = score + 500 * multi;
                                screenShake = 20; screenFlash = 15;
                                // Massive explosion
                                let sp4 = 0;
                                while (sp4 < 80) {
                                    ppx[nextP] = W - 80 + getRandomValue(-30, 30);
                                    ppy[nextP] = bossY + getRandomValue(-30, 30);
                                    ppvx[nextP] = getRandomValue(-350, 350); ppvy[nextP] = getRandomValue(-350, 350);
                                    plife[nextP] = getRandomValue(20, 60);
                                    pR[nextP] = getRandomValue(200, 255); pG[nextP] = getRandomValue(50, 200); pB[nextP] = getRandomValue(0, 80);
                                    pSize[nextP] = getRandomValue(2, 5);
                                    nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                    sp4 = sp4 + 1;
                                }
                                waveDelay = 3.0; waveSpawned = 0; waveEn = 0;
                            }
                        }
                    }
                }
                bi = bi + 1;
            }

            // ── Laser collision ──
            if (laserOn == 1) {
                i = 0;
                while (i < maxEn) {
                    if (ealive[i] == 1 && ex[i] > px && absVal(ey[i] - py) < 12) {
                        ehp[i] = ehp[i] - 25 * dt;
                        eflash[i] = 3;
                        if (ehp[i] <= 0) {
                            ealive[i] = 0;
                            score = score + 15 * multi;
                            screenShake = 3;
                            let sp5 = 0;
                            while (sp5 < 10) {
                                ppx[nextP] = ex[i]; ppy[nextP] = ey[i];
                                ppvx[nextP] = getRandomValue(-200, 200); ppvy[nextP] = getRandomValue(-200, 200);
                                plife[nextP] = getRandomValue(10, 30); pR[nextP] = 100; pG[nextP] = 200; pB[nextP] = 255; pSize[nextP] = 2;
                                nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                sp5 = sp5 + 1;
                            }
                        }
                    }
                    i = i + 1;
                }
                if (bossActive == 1 && absVal(bossY - py) < 40) {
                    bossHp = bossHp - 20 * dt;
                }
            }

            // ── Collision: enemy bullets vs player ──
            if (invTimer > 0) { invTimer = invTimer - dt; }
            else {
                i = 0;
                while (i < maxEBul) {
                    if (ebalive[i] == 1) {
                        let dx = ebx[i] - px; let dy = eby[i] - py;
                        if (dx * dx + dy * dy < 15 * 15) {
                            ebalive[i] = 0;
                            if (shieldTimer > 0) { shieldTimer = shieldTimer - 0.5; }
                            else { hp = hp - 15; invTimer = 0.3; screenShake = 6; }
                            if (hp <= 0) {
                                hp = 0; lives = lives - 1;
                                if (lives <= 0) { gameOver = 1; }
                                else { hp = maxHp; invTimer = 2.0; multi = 1; killStreak = 0; }
                                screenShake = 15;
                                let sp6 = 0;
                                while (sp6 < 25) {
                                    ppx[nextP] = px; ppy[nextP] = py;
                                    ppvx[nextP] = getRandomValue(-300, 300); ppvy[nextP] = getRandomValue(-300, 300);
                                    plife[nextP] = getRandomValue(15, 40); pR[nextP] = 0; pG[nextP] = 220; pB[nextP] = 255; pSize[nextP] = 2;
                                    nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
                                    sp6 = sp6 + 1;
                                }
                            }
                        }
                    }
                    i = i + 1;
                }
                // Enemy body collision
                i = 0;
                while (i < maxEn) {
                    if (ealive[i] == 1 && invTimer <= 0) {
                        let dx = ex[i] - px; let dy = ey[i] - py;
                        let cr = 20; if (etype[i] >= 3) cr = 28;
                        if (dx * dx + dy * dy < cr * cr) {
                            hp = hp - 25; invTimer = 0.5; screenShake = 8;
                            if (hp <= 0) {
                                hp = 0; lives = lives - 1;
                                if (lives <= 0) gameOver = 1;
                                else { hp = maxHp; invTimer = 2.0; multi = 1; killStreak = 0; }
                            }
                        }
                    }
                    i = i + 1;
                }
            }

            // ── Power-ups ──
            i = 0;
            while (i < maxPow) {
                if (powAlive[i] == 1) {
                    powX[i] = powX[i] - 40 * dt;
                    if (powX[i] < -20) powAlive[i] = 0;
                    let dx = powX[i] - px; let dy = powY[i] - py;
                    if (dx * dx + dy * dy < 25 * 25) {
                        powAlive[i] = 0;
                        if (powType[i] == 0) { hp = clamp(hp + 30, 0, maxHp); }
                        if (powType[i] == 1) { energy = maxEnergy; }
                        if (powType[i] == 2) { shieldTimer = 5; }
                        if (powType[i] == 3) { multi = multi + 1; if (multi > 16) multi = 16; }
                    }
                }
                i = i + 1;
            }

            // ── Update particles ──
            i = 0;
            while (i < maxP) {
                if (plife[i] > 0) {
                    ppx[i] = ppx[i] + ppvx[i] * dt;
                    ppy[i] = ppy[i] + ppvy[i] * dt;
                    ppvx[i] = ppvx[i] * 0.96; ppvy[i] = ppvy[i] * 0.96;
                    plife[i] = plife[i] - 1;
                }
                i = i + 1;
            }
            if (screenShake > 0) screenShake = screenShake - 1;
            if (screenFlash > 0) screenFlash = screenFlash - 1;
            if (shieldTimer > 0) shieldTimer = shieldTimer - dt;

            // Player engine particles
            {
                ppx[nextP] = px - 18 + getRandomValue(-3, 3);
                ppy[nextP] = py + getRandomValue(-4, 4);
                ppvx[nextP] = getRandomValue(-120, -60); ppvy[nextP] = getRandomValue(-20, 20);
                plife[nextP] = getRandomValue(5, 15);
                pR[nextP] = 0; pG[nextP] = 150; pB[nextP] = 255; pSize[nextP] = 1;
                nextP = nextP + 1; if (nextP >= maxP) nextP = 0;
            }
        }

        // ════════════════════════════════════════
        //  DRAW
        // ════════════════════════════════════════
        let shX = 0; let shY = 0;
        if (screenShake > 0) { shX = getRandomValue(-4, 4); shY = getRandomValue(-4, 4); }

        beginDrawing();
        clearBackground(color(3, 2, 8, 255));

        // ── Nebula clouds ──
        i = 0;
        while (i < nNeb) {
            let nx = nebX[i] - scrollX * 0.15;
            nx = nx - Math.floor(nx / (W * 2)) * (W * 2);
            drawCircle(nx + shX, nebY[i] + shY, nebR[i], color(nebCR[i], nebCG[i], nebCB[i], 20));
            drawCircle(nx + shX + 20, nebY[i] + shY - 10, nebR[i] * 0.7, color(nebCR[i], nebCG[i], nebCB[i], 15));
            i = i + 1;
        }

        // ── Stars layer 1 (far) ──
        i = 0;
        while (i < nStar1) {
            let sx = s1x[i] - scrollX * 0.05;
            sx = sx - Math.floor(sx / W) * W;
            drawPixel(sx + shX, s1y[i] + shY, color(s1b[i], s1b[i], s1b[i] + 20, 255));
            i = i + 1;
        }
        // ── Stars layer 2 (mid) ──
        i = 0;
        while (i < nStar2) {
            let sx = s2x[i] - scrollX * 0.2;
            sx = sx - Math.floor(sx / W) * W;
            let b = s2b[i];
            drawPixel(sx + shX, s2y[i] + shY, color(b, b, b + 15, 255));
            if (b > 160) drawPixel(sx + shX + 1, s2y[i] + shY, color(b * 0.5, b * 0.5, b * 0.6, 200));
            i = i + 1;
        }
        // ── Stars layer 3 (near, bright) ──
        i = 0;
        while (i < nStar3) {
            let sx = s3x[i] - scrollX * 0.6;
            sx = sx - Math.floor(sx / W) * W;
            let b = s3b[i];
            // Streak effect
            drawLineEx(sx + shX + 4, s3y[i] + shY, sx + shX, s3y[i] + shY, 2, color(b, b, b + 20, 200));
            i = i + 1;
        }

        // ── Particles (behind entities) ──
        i = 0;
        while (i < maxP) {
            if (plife[i] > 0) {
                let alpha = plife[i] * 6; if (alpha > 255) alpha = 255;
                let sz = pSize[i] + plife[i] / 20;
                if (sz > 5) sz = 5;
                if (sz > 2) drawCircle(ppx[i] + shX, ppy[i] + shY, sz + 2, color(pR[i], pG[i], pB[i], alpha / 5));
                drawCircle(ppx[i] + shX, ppy[i] + shY, sz, color(pR[i], pG[i], pB[i], alpha));
            }
            i = i + 1;
        }

        // ── Enemy bullets ──
        i = 0;
        while (i < maxEBul) {
            if (ebalive[i] == 1) {
                drawCircle(ebx[i] + shX, eby[i] + shY, 5, color(255, 50, 50, 40));
                drawCircle(ebx[i] + shX, eby[i] + shY, 3, color(255, 80, 50, 255));
                drawCircle(ebx[i] + shX, eby[i] + shY, 1, color(255, 200, 150, 255));
            }
            i = i + 1;
        }

        // ── Enemies (detailed rendering) ──
        i = 0;
        while (i < maxEn) {
            if (ealive[i] == 1) {
                let exx = ex[i] + shX; let eyy = ey[i] + shY;
                let fl = eflash[i] > 0;

                if (etype[i] == 0) {
                    // Scout: small sleek ship
                    drawCircle(exx, eyy, 10, color(255, 60, 40, 20));
                    drawRectangle(exx - 8, eyy - 3, 16, 6, color(180, 50, 40, 255));
                    drawRectangle(exx - 6, eyy - 2, 12, 4, color(220, 70, 50, 255));
                    drawRectangle(exx + 5, eyy - 1, 5, 2, color(255, 120, 80, 255));
                    drawRectangle(exx - 8, eyy - 6, 6, 3, color(160, 40, 30, 255));
                    drawRectangle(exx - 8, eyy + 3, 6, 3, color(160, 40, 30, 255));
                    // Engine
                    drawCircle(exx - 10, eyy, 2, color(255, 150, 50, 200));
                    if (fl) drawCircle(exx, eyy, 12, color(255, 255, 255, 120));
                }
                if (etype[i] == 1) {
                    // Fighter: angular medium ship
                    drawCircle(exx, eyy, 16, color(200, 120, 30, 15));
                    drawRectangle(exx - 14, eyy - 5, 28, 10, color(150, 100, 30, 255));
                    drawRectangle(exx - 12, eyy - 4, 24, 8, color(190, 130, 40, 255));
                    drawRectangle(exx + 8, eyy - 2, 6, 4, color(220, 160, 60, 255));
                    // Wings
                    drawRectangle(exx - 10, eyy - 10, 12, 4, color(160, 100, 30, 255));
                    drawRectangle(exx - 10, eyy + 6, 12, 4, color(160, 100, 30, 255));
                    // Cockpit
                    drawCircle(exx + 4, eyy, 3, color(255, 200, 100, 200));
                    // Engines
                    drawCircle(exx - 16, eyy - 2, 2, color(255, 180, 50, 200));
                    drawCircle(exx - 16, eyy + 2, 2, color(255, 180, 50, 200));
                    if (fl) drawCircle(exx, eyy, 18, color(255, 255, 255, 100));
                }
                if (etype[i] == 2) {
                    // Swooper: purple, agile
                    drawCircle(exx, eyy, 12, color(160, 50, 255, 20));
                    drawRectangle(exx - 10, eyy - 4, 20, 8, color(120, 40, 200, 255));
                    drawRectangle(exx - 8, eyy - 3, 16, 6, color(160, 60, 240, 255));
                    drawRectangle(exx + 6, eyy - 1, 5, 2, color(200, 120, 255, 255));
                    // Swept wings
                    drawRectangle(exx - 6, eyy - 8, 4, 5, color(140, 50, 220, 255));
                    drawRectangle(exx - 6, eyy + 3, 4, 5, color(140, 50, 220, 255));
                    drawCircle(exx - 12, eyy, 2, color(200, 100, 255, 200));
                    if (fl) drawCircle(exx, eyy, 14, color(255, 255, 255, 100));
                }
                if (etype[i] == 3) {
                    // Heavy: large green armored
                    drawCircle(exx, eyy, 22, color(50, 200, 80, 15));
                    drawRectangle(exx - 18, eyy - 8, 36, 16, color(40, 130, 60, 255));
                    drawRectangle(exx - 16, eyy - 7, 32, 14, color(50, 160, 70, 255));
                    drawRectangle(exx - 14, eyy - 5, 28, 10, color(60, 180, 80, 255));
                    drawRectangle(exx + 12, eyy - 3, 8, 6, color(80, 200, 100, 255));
                    // Armor plates
                    drawRectangle(exx - 16, eyy - 12, 20, 3, color(40, 120, 50, 255));
                    drawRectangle(exx - 16, eyy + 9, 20, 3, color(40, 120, 50, 255));
                    // Turret
                    drawRectangle(exx - 6, eyy - 4, 4, 8, color(70, 200, 90, 255));
                    drawCircle(exx - 4, eyy, 3, color(100, 255, 120, 200));
                    // HP bar
                    let hpPct = ehp[i] / emaxhp[i];
                    drawRectangle(exx - 16, eyy - 16, 32, 2, color(30, 30, 30, 200));
                    drawRectangle(exx - 16, eyy - 16, 32 * hpPct, 2, color(50, 255, 80, 255));
                    if (fl) drawCircle(exx, eyy, 24, color(255, 255, 255, 80));
                }
                if (etype[i] == 4) {
                    // Carrier: massive, orange
                    drawCircle(exx, eyy, 30, color(200, 150, 40, 12));
                    drawRectangle(exx - 25, eyy - 12, 50, 24, color(150, 100, 30, 255));
                    drawRectangle(exx - 22, eyy - 10, 44, 20, color(180, 120, 40, 255));
                    drawRectangle(exx - 20, eyy - 8, 40, 16, color(200, 140, 50, 255));
                    // Bay doors
                    drawRectangle(exx - 18, eyy - 4, 8, 8, color(80, 50, 20, 255));
                    // Bridge
                    drawRectangle(exx + 15, eyy - 5, 10, 10, color(220, 160, 60, 255));
                    drawCircle(exx + 20, eyy, 4, color(255, 200, 100, 200));
                    // Engines (4)
                    drawCircle(exx - 27, eyy - 6, 3, color(255, 180, 50, 200));
                    drawCircle(exx - 27, eyy + 6, 3, color(255, 180, 50, 200));
                    drawCircle(exx - 27, eyy - 2, 2, color(255, 200, 80, 150));
                    drawCircle(exx - 27, eyy + 2, 2, color(255, 200, 80, 150));
                    // HP bar
                    let hpPct2 = ehp[i] / emaxhp[i];
                    drawRectangle(exx - 22, eyy - 18, 44, 3, color(30, 30, 30, 200));
                    drawRectangle(exx - 22, eyy - 18, 44 * hpPct2, 3, color(255, 180, 50, 255));
                    if (fl) drawCircle(exx, eyy, 32, color(255, 255, 255, 60));
                }
            }
            i = i + 1;
        }

        // ── Boss ──
        if (bossActive == 1) {
            let bxx = W - 80 + shX;
            let byy = bossY + shY;
            // Massive boss ship
            drawCircle(bxx, byy, 65, color(200, 40, 40, 10));
            drawCircle(bxx, byy, 50, color(200, 40, 40, 20));
            // Main hull
            drawRectangle(bxx - 40, byy - 20, 80, 40, color(120, 30, 30, 255));
            drawRectangle(bxx - 35, byy - 18, 70, 36, color(150, 40, 35, 255));
            drawRectangle(bxx - 30, byy - 15, 60, 30, color(180, 50, 40, 255));
            // Core
            drawCircle(bxx, byy, 12, color(255, 80, 60, 200));
            drawCircle(bxx, byy, 7, color(255, 150, 100, 255));
            if (bossPhase == 1) {
                drawCircle(bxx, byy, 15, color(255, 50, 30, 80));
                drawCircle(bxx, byy, 9, color(255, 200, 150, 255));
            }
            // Wings
            drawRectangle(bxx - 30, byy - 35, 30, 12, color(140, 35, 30, 255));
            drawRectangle(bxx - 30, byy + 23, 30, 12, color(140, 35, 30, 255));
            drawRectangle(bxx - 25, byy - 40, 20, 8, color(120, 30, 25, 255));
            drawRectangle(bxx - 25, byy + 32, 20, 8, color(120, 30, 25, 255));
            // Turrets
            drawCircle(bxx - 20, byy - 28, 5, color(255, 80, 60, 255));
            drawCircle(bxx - 20, byy + 28, 5, color(255, 80, 60, 255));
            drawCircle(bxx + 20, byy - 12, 4, color(255, 100, 70, 255));
            drawCircle(bxx + 20, byy + 12, 4, color(255, 100, 70, 255));
            // Engines
            let engFlame = Math.sin(time * 15) * 3 + 5;
            drawCircle(bxx - 42, byy - 10, engFlame, color(255, 120, 30, 150));
            drawCircle(bxx - 42, byy + 10, engFlame, color(255, 120, 30, 150));
            drawCircle(bxx - 42, byy, engFlame + 2, color(255, 150, 50, 120));
            // Armor details
            drawRectangle(bxx - 38, byy - 2, 76, 4, color(200, 60, 50, 200));
            drawLine(bxx - 38, byy - 20, bxx + 38, byy - 20, color(255, 80, 60, 100));
            drawLine(bxx - 38, byy + 20, bxx + 38, byy + 20, color(255, 80, 60, 100));
            // Boss HP bar
            let bHpPct = bossHp / bossMaxHp;
            drawRectangle(W / 2 - 150, 12, 300, 10, color(30, 10, 10, 200));
            drawRectangle(W / 2 - 150, 12, 300 * bHpPct, 10, color(255, 50, 40, 255));
            drawRectangleLines(W / 2 - 150, 12, 300, 10, color(255, 80, 60, 200));
            drawText("BOSS", W / 2 - 22, 1, 10, color(255, 80, 60, 255));
        }

        // ── Player bullets ──
        i = 0;
        while (i < maxBul) {
            if (balive[i] == 1) {
                let bbx = bx[i] + shX; let bby = by[i] + shY;
                if (btype[i] == 0) {
                    drawLineEx(bbx - 8, bby, bbx, bby, 2, color(255, 255, 100, 80));
                    drawCircle(bbx, bby, 2, color(255, 255, 200, 255));
                }
                if (btype[i] == 1) {
                    drawCircle(bbx, bby, 4, color(100, 255, 200, 40));
                    drawCircle(bbx, bby, 2, color(150, 255, 220, 255));
                }
            }
            i = i + 1;
        }

        // ── Laser beam ──
        if (laserOn == 1 && gameOver == 0) {
            let lw = 4 + Math.sin(time * 30) * 2;
            drawRectangle(px + 20 + shX, py - lw + shY, W, lw * 2, color(50, 150, 255, 30));
            drawRectangle(px + 20 + shX, py - lw / 2 + shY, W, lw, color(100, 200, 255, 80));
            drawRectangle(px + 20 + shX, py - 1 + shY, W, 2, color(200, 240, 255, 255));
            drawCircle(px + 20 + shX, py + shY, lw + 2, color(100, 200, 255, 60));
        }

        // ── Player ship (detailed) ──
        let visible = 1;
        if (invTimer > 0.5) {
            let bl = time * 14;
            if (bl - Math.floor(bl / 2) * 2 < 1) visible = 0;
        }
        if (visible == 1 && gameOver == 0) {
            let ppxx = px + shX; let ppyy = py + shY;
            // Engine glow
            let fl2 = flame + Math.sin(time * 18) * 1.5;
            drawCircle(ppxx - 20, ppyy, fl2 + 6, color(0, 100, 255, 20));
            drawCircle(ppxx - 20, ppyy, fl2 + 3, color(0, 150, 255, 50));
            drawCircle(ppxx - 18, ppyy, fl2, color(100, 200, 255, 150));
            drawCircle(ppxx - 16, ppyy, fl2 * 0.5, color(200, 240, 255, 200));
            // Main body
            drawRectangle(ppxx - 14, ppyy - 5, 28, 10, color(50, 70, 100, 255));
            drawRectangle(ppxx - 12, ppyy - 4, 24, 8, color(70, 90, 130, 255));
            drawRectangle(ppxx - 10, ppyy - 3, 20, 6, color(90, 110, 150, 255));
            // Nose
            drawRectangle(ppxx + 12, ppyy - 3, 8, 6, color(100, 130, 170, 255));
            drawRectangle(ppxx + 16, ppyy - 2, 6, 4, color(120, 150, 190, 255));
            drawRectangle(ppxx + 20, ppyy - 1, 4, 2, color(150, 180, 210, 255));
            // Top wing
            drawRectangle(ppxx - 10, ppyy - 10, 16, 5, color(50, 70, 100, 255));
            drawRectangle(ppxx - 8, ppyy - 9, 12, 3, color(70, 90, 130, 255));
            // Bottom wing
            drawRectangle(ppxx - 10, ppyy + 5, 16, 5, color(50, 70, 100, 255));
            drawRectangle(ppxx - 8, ppyy + 6, 12, 3, color(70, 90, 130, 255));
            // Cockpit
            drawCircle(ppxx + 6, ppyy, 4, color(0, 180, 255, 150));
            drawCircle(ppxx + 6, ppyy, 2, color(150, 240, 255, 255));
            // Wing tips
            drawCircle(ppxx + 2, ppyy - 10, 2, color(0, 200, 255, 200));
            drawCircle(ppxx + 2, ppyy + 10, 2, color(0, 200, 255, 200));
            // Shield
            if (shieldTimer > 0) {
                let sa = 100 + Math.sin(time * 8) * 40;
                drawCircle(ppxx, ppyy, 26, color(0, 200, 255, sa / 5));
                drawCircleLines(ppxx, ppyy, 26, color(0, 200, 255, sa));
            }
        }

        // ── Power-ups ──
        i = 0;
        while (i < maxPow) {
            if (powAlive[i] == 1) {
                let pwx = powX[i] + shX; let pwy = powY[i] + shY;
                let pulse = Math.sin(time * 5) * 3 + 10;
                if (powType[i] == 0) { // Health (green)
                    drawCircle(pwx, pwy, pulse, color(0, 255, 80, 30));
                    drawCircle(pwx, pwy, 6, color(0, 255, 80, 200));
                    drawText("+", pwx - 3, pwy - 5, 10, WHITE);
                }
                if (powType[i] == 1) { // Energy (blue)
                    drawCircle(pwx, pwy, pulse, color(50, 100, 255, 30));
                    drawCircle(pwx, pwy, 6, color(50, 150, 255, 200));
                    drawText("E", pwx - 3, pwy - 5, 10, WHITE);
                }
                if (powType[i] == 2) { // Shield (cyan)
                    drawCircle(pwx, pwy, pulse, color(0, 200, 255, 30));
                    drawCircleLines(pwx, pwy, 7, color(0, 255, 255, 200));
                }
                if (powType[i] == 3) { // Multiplier (yellow)
                    drawCircle(pwx, pwy, pulse, color(255, 200, 0, 30));
                    drawCircle(pwx, pwy, 6, color(255, 200, 0, 200));
                    drawText("x", pwx - 3, pwy - 5, 10, WHITE);
                }
            }
            i = i + 1;
        }

        // ── Screen flash ──
        if (screenFlash > 0) {
            drawRectangle(0, 0, W, H, color(255, 200, 100, screenFlash * 12));
        }

        // ════════════════════════════════════════
        //  HUD
        // ════════════════════════════════════════
        // Bottom HUD bar
        drawRectangle(0, H - 50, W, 50, color(8, 5, 15, 230));
        drawRectangle(0, H - 50, W, 1, color(0, 150, 255, 100));

        // HP bar
        drawText("HP", 12, H - 44, 10, color(0, 200, 100, 200));
        drawRectangle(30, H - 42, 160, 10, color(20, 15, 25, 255));
        let hpPct3 = hp / maxHp;
        let hpR = 0; let hpG = 220;
        if (hpPct3 < 0.5) { hpR = 255; hpG = 150; }
        if (hpPct3 < 0.25) { hpR = 255; hpG = 50; }
        drawRectangle(30, H - 42, 160 * hpPct3, 10, color(hpR, hpG, 60, 255));
        // HP segments
        let hSeg = 0;
        while (hSeg < 10) {
            drawRectangle(30 + hSeg * 16, H - 42, 1, 10, color(8, 5, 15, 150));
            hSeg = hSeg + 1;
        }

        // Energy bar
        drawText("EN", 12, H - 28, 10, color(50, 120, 255, 200));
        drawRectangle(30, H - 26, 160, 8, color(20, 15, 25, 255));
        let enPct = energy / maxEnergy;
        drawRectangle(30, H - 26, 160 * enPct, 8, color(50, 150, 255, 255));

        // Weapon indicator
        let wpnNames = "RAPID";
        if (weapon == 1) wpnNames = "SPREAD";
        if (weapon == 2) wpnNames = "LASER";
        drawRectangle(210, H - 45, 70, 30, color(15, 10, 25, 255));
        drawRectangleLines(210, H - 45, 70, 30, color(0, 150, 255, 100));
        drawText(wpnNames, 218, H - 38, 12, color(0, 255, 200, 255));
        drawText("1/2/3", 225, H - 22, 8, color(80, 80, 100, 200));

        // Score
        drawText("SCORE", 310, H - 44, 10, color(0, 200, 255, 180));
        drawText(String(score), 310, H - 30, 20, color(0, 255, 255, 255));

        // Multiplier
        if (multi > 1) {
            drawText("x" + String(multi), 440, H - 38, 22, color(255, 255, 0, 255));
        }

        // Wave
        drawText("WAVE " + String(wave), 520, H - 40, 14, color(180, 80, 255, 255));

        // Lives
        let lvi = 0;
        while (lvi < lives) {
            drawCircle(620 + lvi * 16, H - 30, 5, color(0, 255, 255, 255));
            drawCircle(620 + lvi * 16, H - 30, 2, color(200, 255, 255, 255));
            lvi = lvi + 1;
        }

        // Shield timer
        if (shieldTimer > 0) {
            drawText("SHIELD " + String(Math.floor(shieldTimer)), 700, H - 40, 12, color(0, 255, 255, 200));
        }

        // FPS
        drawText(String(getFPS()) + " FPS", W - 70, H - 18, 10, color(0, 180, 100, 180));

        // Wave announcement
        if (waveDelay > 1.0 && wave > 0 && bossActive == 0) {
            let wa = (waveDelay - 1.0) * 255;
            if (wa > 255) wa = 255;
            drawText("W A V E  " + String(wave), W / 2 - 80, H / 2 - 60, 32, color(0, 200, 255, wa));
        }
        if (bossActive == 1 && bossTimer < 2) {
            let wa2 = (2 - bossTimer) * 200;
            if (wa2 > 255) wa2 = 255;
            drawText("W A R N I N G", W / 2 - 90, H / 2 - 60, 32, color(255, 50, 30, wa2));
        }

        // Game Over
        if (gameOver == 1) {
            drawRectangle(0, 0, W, H, color(0, 0, 0, 180));
            drawText("GAME OVER", W / 2 - 130, H / 2 - 60, 44, color(255, 40, 40, 255));
            drawText("Score: " + String(score), W / 2 - 80, H / 2, 24, color(0, 255, 255, 255));
            drawText("Wave: " + String(wave), W / 2 - 50, H / 2 + 35, 18, WHITE);
            drawText("ENTER to restart", W / 2 - 80, H / 2 + 70, 14, color(100, 100, 120, 255));
        }

        endDrawing();
    }

    closeWindow();
}

main();
