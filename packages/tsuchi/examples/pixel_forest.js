// Pixel Forest — Side-scrolling Platformer with Bitmap Graphics
// Arrow keys or WASD to move, SPACE or W to jump
// Collect all gems to open the exit portal
// Compile: tsuchi compile examples/pixel_forest.js

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
    let TILE = 32;
    let SRC_TILE = 16;
    let MAP_W = 100;
    let MAP_H = 19;

    initWindow(W, H, "Pixel Forest");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // ── Load textures ──
    let playerTex = loadTexture("examples/assets/player.png");
    let tilesetTex = loadTexture("examples/assets/tileset.png");
    let bgFarTex = loadTexture("examples/assets/bg_far.png");
    let bgMidTex = loadTexture("examples/assets/bg_mid.png");
    let bgNearTex = loadTexture("examples/assets/bg_near.png");
    let itemsTex = loadTexture("examples/assets/items.png");
    let enemiesTex = loadTexture("examples/assets/enemies.png");

    // ── Generate tile map ──
    let tiles = [];
    let totalTiles = MAP_W * MAP_H;
    let i = 0;
    while (i < totalTiles) {
        tiles.push(0);
        i = i + 1;
    }

    // Ground generation using sin waves
    let groundH = [];
    let col = 0;
    while (col < MAP_W) {
        let h = 5 + Math.sin(col * 0.08) * 2
                  + Math.sin(col * 0.15 + 1.2) * 1.5
                  + Math.sin(col * 0.03) * 3;
        h = Math.floor(h);
        if (h < 2) h = 2;
        if (h > 10) h = 10;
        groundH.push(h);
        col = col + 1;
    }

    // Flatten start area
    i = 0;
    while (i < 6) {
        groundH[i] = 5;
        i = i + 1;
    }

    // Fill terrain tiles
    col = 0;
    while (col < MAP_W) {
        let h = groundH[col];
        let baseRow = MAP_H - 1;

        // Grass top
        let grassTile = 0;
        if (col % 3 == 0) grassTile = 1;
        tiles[((baseRow - h) * MAP_W) + col] = grassTile + 1;

        // Dirt below grass
        let row = baseRow - h + 1;
        while (row <= baseRow) {
            let dirtTile = 2;
            if (row > baseRow - 2) dirtTile = 4; // stone at bottom
            if ((col + row) % 7 == 0) dirtTile = 3; // dirt variant
            tiles[(row * MAP_W) + col] = dirtTile + 1;
            row = row + 1;
        }
        col = col + 1;
    }

    // Floating platforms
    let platX = [10, 14, 20, 25, 30, 36, 42, 48, 52, 58, 64, 70, 76, 82, 88, 93];
    let platY = [11, 9,  10, 8,  11, 7,  10, 9,  8,  10, 7,  9,  11, 8,  10, 7];
    let platLen = [3, 2, 4, 3, 2, 3, 4, 2, 3, 3, 4, 2, 3, 3, 2, 4];
    let numPlats = 16;
    i = 0;
    while (i < numPlats) {
        let px = platX[i];
        let py = platY[i];
        let plen = platLen[i];
        let j = 0;
        while (j < plen) {
            if (px + j < MAP_W && py < MAP_H) {
                let tile = 5; // stone
                if (j == 0 || j == plen - 1) tile = 7; // mossy stone edges
                tiles[(py * MAP_W) + px + j] = tile;
            }
            j = j + 1;
        }
        i = i + 1;
    }

    // Water pools
    let waterCols = [35, 36, 37, 38, 39, 65, 66, 67, 68];
    let numWaterCols = 9;
    i = 0;
    while (i < numWaterCols) {
        let wc = waterCols[i];
        let wRow = MAP_H - groundH[wc];
        tiles[(wRow * MAP_W) + wc] = 9;   // water surface
        if (wRow + 1 < MAP_H) tiles[((wRow + 1) * MAP_W) + wc] = 10;
        i = i + 1;
    }

    // Decorations (encoded in high tile IDs)
    // Tile IDs: 1-7 = terrain, 9-10 = water, 15 = thorn
    // 17 = red flower, 18 = blue flower, 19 = mushroom, 20 = crystal
    // 21-22 = torch, 23 = grass blade, 24 = bush
    let decoX = [3,  8,  15, 22, 28, 33, 40, 45, 50, 56, 62, 68, 74, 80, 85, 90, 95];
    let decoY = [];
    let decoT = [24, 23, 17, 19, 18, 23, 17, 24, 18, 23, 19, 17, 24, 23, 18, 19, 17];
    let numDeco = 17;
    i = 0;
    while (i < numDeco) {
        let dx = decoX[i];
        // Place one row ABOVE ground (grass is at row MAP_H-1-h, so above = MAP_H-2-h)
        let dy = MAP_H - groundH[dx] - 2;
        decoY.push(dy);
        if (dy >= 0) tiles[(dy * MAP_W) + dx] = decoT[i];
        i = i + 1;
    }

    // Thorns (hazards)
    let thornX = [18, 19, 44, 45, 73, 74];
    let numThorns = 6;
    i = 0;
    while (i < numThorns) {
        let tx = thornX[i];
        // Place one row ABOVE ground
        let ty = MAP_H - groundH[tx] - 2;
        if (ty >= 0) tiles[(ty * MAP_W) + tx] = 15;
        i = i + 1;
    }

    // ── Collectible gems ──
    let maxGems = 20;
    let gemX = [];
    let gemY = [];
    let gemAlive = [];
    // Place gems above platforms and along the path
    let gemPosX = [4,  11, 15, 21, 26, 31, 37, 43, 49, 53, 59, 65, 71, 77, 83, 89, 94, 12, 47, 70];
    let gemPosY = [12, 10, 8,  9,  7,  10, 6,  9,  8,  7,  9,  6,  8,  10, 7,  9,  6, 8, 7, 7];
    i = 0;
    while (i < maxGems) {
        gemX.push(gemPosX[i] * TILE + TILE / 2);
        gemY.push(gemPosY[i] * TILE + 4);
        gemAlive.push(1);
        i = i + 1;
    }
    let collectedGems = 0;

    // ── Enemies (slimes) ──
    let maxSlimes = 8;
    let slimeX = [];
    let slimeY = [];
    let slimeStartX = [];
    let slimeEndX = [];
    let slimeDir = [];
    let slimeFrame = [];
    let slimeAnimT = [];

    let slimePosX =    [12, 28, 40, 55, 63, 75, 85, 92];
    let slimeRangeL =  [10, 26, 38, 53, 61, 73, 83, 90];
    let slimeRangeR =  [16, 32, 44, 58, 67, 79, 88, 96];
    i = 0;
    while (i < maxSlimes) {
        let sx = slimePosX[i];
        let sy = MAP_H - groundH[sx] - 1;
        slimeX.push(sx * TILE);
        slimeY.push(sy * TILE);
        slimeStartX.push(slimeRangeL[i] * TILE);
        slimeEndX.push(slimeRangeR[i] * TILE);
        slimeDir.push(1);
        slimeFrame.push(0);
        slimeAnimT.push(0);
        i = i + 1;
    }

    // ── Dust particles ──
    let maxDust = 40;
    let dustX = [];
    let dustY = [];
    let dustVX = [];
    let dustVY = [];
    let dustLife = [];
    let dustR = [];
    let dustG = [];
    let dustB = [];
    let nextDust = 0;
    i = 0;
    while (i < maxDust) {
        dustX.push(0); dustY.push(0);
        dustVX.push(0); dustVY.push(0);
        dustLife.push(0);
        dustR.push(0); dustG.push(0); dustB.push(0);
        i = i + 1;
    }

    // ── Fireflies ──
    let maxFF = 60;
    let ffX = [];
    let ffY = [];
    let ffPhase = [];
    i = 0;
    while (i < maxFF) {
        ffX.push(getRandomValue(0, MAP_W * TILE));
        ffY.push(getRandomValue(50, H - 100));
        ffPhase.push(getRandomValue(0, 628) / 100);
        i = i + 1;
    }

    // ── Player state ──
    let plX = 3 * TILE;
    let plY = (MAP_H - groundH[3] - 3) * TILE;
    let plVX = 0;
    let plVY = 0;
    let plDir = 1;
    let plFrame = 0;
    let plAnimT = 0;
    let plOnGround = 0;
    let plState = 0;  // 0=idle, 1=run, 2=jump, 3=fall
    let plCoyote = 0;
    let plJumpHeld = 0;
    let plW = 12;
    let plH = 20;

    // Physics
    let gravity = 800;
    let moveAccel = 1200;
    let maxSpeed = 220;
    let friction = 800;
    let jumpForce = -340;
    let jumpHoldForce = -50;

    // Camera
    let camX = 0;
    let maxCamX = (MAP_W * TILE) - W;

    // Checkpoint
    let checkX = 3 * TILE;
    let checkY = (MAP_H - groundH[3] - 3) * TILE;

    // Score & time
    let score = 0;
    let time = 0;
    let gameWon = 0;
    let waterFrame = 0;
    let waterTimer = 0;
    let portalOpen = 0;
    let portalX = 96 * TILE;
    let portalY = 5 * TILE;

    while (!windowShouldClose()) {
        let dt = getFrameTime();
        if (dt > 0.05) dt = 0.05;
        time = time + dt;

        if (gameWon == 0) {
            // ── Input ──
            let moveInput = 0;
            if (isKeyDown(KEY_LEFT) || isKeyDown(KEY_A))  moveInput = -1;
            if (isKeyDown(KEY_RIGHT) || isKeyDown(KEY_D)) moveInput = 1;

            // Horizontal movement
            if (moveInput != 0) {
                plVX = plVX + moveInput * moveAccel * dt;
                plDir = moveInput;
            } else {
                // Friction
                if (plVX > 0) {
                    plVX = plVX - friction * dt;
                    if (plVX < 0) plVX = 0;
                } else if (plVX < 0) {
                    plVX = plVX + friction * dt;
                    if (plVX > 0) plVX = 0;
                }
            }
            plVX = clamp(plVX, -maxSpeed, maxSpeed);

            // Jump
            if ((isKeyPressed(KEY_SPACE) || isKeyPressed(KEY_W) || isKeyPressed(KEY_UP)) && (plOnGround == 1 || plCoyote > 0)) {
                plVY = jumpForce;
                plOnGround = 0;
                plCoyote = 0;
                plJumpHeld = 1;
                // Spawn dust (jump)
                let jd = 0;
                while (jd < 5) {
                    dustX[nextDust] = plX + plW / 2; dustY[nextDust] = plY + plH;
                    dustVX[nextDust] = getRandomValue(-60, 60); dustVY[nextDust] = getRandomValue(-40, -10);
                    dustLife[nextDust] = getRandomValue(15, 30);
                    dustR[nextDust] = getRandomValue(140, 200); dustG[nextDust] = getRandomValue(120, 160); dustB[nextDust] = getRandomValue(80, 120);
                    nextDust = nextDust + 1; if (nextDust >= maxDust) nextDust = 0; jd = jd + 1;
                }
            }
            // Variable jump height
            if (plJumpHeld == 1 && (isKeyDown(KEY_SPACE) || isKeyDown(KEY_W) || isKeyDown(KEY_UP)) && plVY < 0) {
                plVY = plVY + jumpHoldForce * dt;
            }
            if (!isKeyDown(KEY_SPACE) && !isKeyDown(KEY_W) && !isKeyDown(KEY_UP)) {
                plJumpHeld = 0;
            }

            // Gravity
            plVY = plVY + gravity * dt;
            if (plVY > 600) plVY = 600;

            // Coyote time decay
            if (plCoyote > 0) plCoyote = plCoyote - 1;

            // ── Horizontal collision ──
            let newX = plX + plVX * dt;
            let leftCol = Math.floor(newX / TILE);
            let rightCol = Math.floor((newX + plW) / TILE);
            let topRow = Math.floor(plY / TILE);
            let botRow = Math.floor((plY + plH - 1) / TILE);

            let hBlocked = 0;
            let checkRow = topRow;
            while (checkRow <= botRow) {
                if (plVX > 0 && rightCol >= 0 && rightCol < MAP_W && checkRow >= 0 && checkRow < MAP_H) {
                    let ht = tiles[(checkRow * MAP_W) + rightCol];
                    if (ht >= 1 && ht <= 7) hBlocked = 1;
                }
                if (plVX < 0 && leftCol >= 0 && leftCol < MAP_W && checkRow >= 0 && checkRow < MAP_H) {
                    let ht = tiles[(checkRow * MAP_W) + leftCol];
                    if (ht >= 1 && ht <= 7) hBlocked = 1;
                }
                checkRow = checkRow + 1;
            }
            if (hBlocked == 1) {
                plVX = 0;
            } else {
                plX = newX;
            }

            // ── Vertical collision ──
            let wasOnGround = plOnGround;
            plOnGround = 0;
            let newY = plY + plVY * dt;
            leftCol = Math.floor((plX + 2) / TILE);
            rightCol = Math.floor((plX + plW - 2) / TILE);
            topRow = Math.floor(newY / TILE);
            botRow = Math.floor((newY + plH) / TILE);

            if (plVY >= 0) {
                // Falling: check below
                let checkCol = leftCol;
                while (checkCol <= rightCol) {
                    let vSolid = 0;
                    if (checkCol >= 0 && checkCol < MAP_W && botRow >= 0 && botRow < MAP_H) {
                        let vt = tiles[(botRow * MAP_W) + checkCol];
                        if (vt >= 1 && vt <= 7) vSolid = 1;
                    }
                    if (vSolid == 1) {
                        newY = (botRow * TILE) - plH;
                        plVY = 0;
                        plOnGround = 1;
                        if (wasOnGround == 0) {
                            // Spawn landing dust
                            let ld = 0;
                            while (ld < 4) {
                                dustX[nextDust] = plX + plW / 2; dustY[nextDust] = newY + plH;
                                dustVX[nextDust] = getRandomValue(-60, 60); dustVY[nextDust] = getRandomValue(-40, -10);
                                dustLife[nextDust] = getRandomValue(15, 30);
                                dustR[nextDust] = getRandomValue(140, 200); dustG[nextDust] = getRandomValue(120, 160); dustB[nextDust] = getRandomValue(80, 120);
                                nextDust = nextDust + 1; if (nextDust >= maxDust) nextDust = 0; ld = ld + 1;
                            }
                        }
                    }
                    checkCol = checkCol + 1;
                }
            } else {
                // Jumping: check above
                let checkCol = leftCol;
                while (checkCol <= rightCol) {
                    if (checkCol >= 0 && checkCol < MAP_W && topRow >= 0 && topRow < MAP_H) {
                        let vt = tiles[(topRow * MAP_W) + checkCol];
                        if (vt >= 1 && vt <= 7) {
                            newY = (topRow + 1) * TILE;
                            plVY = 0;
                        }
                    }
                    checkCol = checkCol + 1;
                }
            }
            plY = newY;

            // Coyote time: if just left ground
            if (wasOnGround == 1 && plOnGround == 0 && plVY >= 0) {
                plCoyote = 5;
            }

            // Update checkpoint when on ground
            if (plOnGround == 1) {
                checkX = plX;
                checkY = plY;
            }

            // Keep player in bounds
            if (plX < 0) { plX = 0; plVX = 0; }
            if (plX > MAP_W * TILE - plW) { plX = MAP_W * TILE - plW; plVX = 0; }

            // Fall death
            if (plY > MAP_H * TILE + 100) {
                plX = checkX;
                plY = checkY;
                plVX = 0;
                plVY = 0;
            }

            // ── Thorn collision ──
            let plTC = Math.floor((plX + plW / 2) / TILE);
            let plTR = Math.floor((plY + plH - 4) / TILE);
            if (plTC >= 0 && plTC < MAP_W && plTR >= 0 && plTR < MAP_H) {
                let tileBelow = tiles[(plTR * MAP_W) + plTC];
                if (tileBelow == 15) {
                    plX = checkX;
                    plY = checkY;
                    plVX = 0;
                    plVY = 0;
                    // Spawn thorn dust
                    let td = 0;
                    while (td < 8) {
                        dustX[nextDust] = plX + plW / 2; dustY[nextDust] = plY + plH;
                        dustVX[nextDust] = getRandomValue(-60, 60); dustVY[nextDust] = getRandomValue(-40, -10);
                        dustLife[nextDust] = getRandomValue(15, 30);
                        dustR[nextDust] = getRandomValue(180, 240); dustG[nextDust] = getRandomValue(60, 100); dustB[nextDust] = getRandomValue(60, 100);
                        nextDust = nextDust + 1; if (nextDust >= maxDust) nextDust = 0; td = td + 1;
                    }
                }
            }

            // ── Animation state ──
            if (plOnGround == 0) {
                if (plVY < 0) plState = 2; // jump
                else plState = 3; // fall
            } else if (absVal(plVX) > 10) {
                plState = 1; // run
            } else {
                plState = 0; // idle
            }

            plAnimT = plAnimT + dt;

            // Frame selection
            if (plState == 0) {
                plFrame = Math.floor(plAnimT * 2) % 2;
            } else if (plState == 1) {
                plFrame = Math.floor(plAnimT * 8) % 4;
            } else if (plState == 2) {
                plFrame = 0;
            } else {
                plFrame = 1;
            }

            // ── Gem collection ──
            i = 0;
            while (i < maxGems) {
                if (gemAlive[i] == 1) {
                    let dx = absVal((plX + plW / 2) - gemX[i]);
                    let dy = absVal((plY + plH / 2) - gemY[i]);
                    if (dx < 20 && dy < 20) {
                        gemAlive[i] = 0;
                        collectedGems = collectedGems + 1;
                        score = score + 100;
                        // Spawn gem sparkle
                        let gd = 0;
                        while (gd < 6) {
                            dustX[nextDust] = gemX[i]; dustY[nextDust] = gemY[i];
                            dustVX[nextDust] = getRandomValue(-80, 80); dustVY[nextDust] = getRandomValue(-60, -10);
                            dustLife[nextDust] = getRandomValue(15, 30);
                            dustR[nextDust] = getRandomValue(80, 140); dustG[nextDust] = getRandomValue(200, 255); dustB[nextDust] = getRandomValue(80, 140);
                            nextDust = nextDust + 1; if (nextDust >= maxDust) nextDust = 0; gd = gd + 1;
                        }
                        if (collectedGems >= maxGems) portalOpen = 1;
                    }
                }
                i = i + 1;
            }

            // ── Portal check ──
            if (portalOpen == 1) {
                let dx = absVal(plX + plW / 2 - portalX);
                let dy = absVal(plY + plH / 2 - portalY);
                if (dx < TILE && dy < TILE) {
                    gameWon = 1;
                }
            }

            // ── Slime AI ──
            i = 0;
            while (i < maxSlimes) {
                slimeX[i] = slimeX[i] + slimeDir[i] * 40 * dt;
                if (slimeX[i] <= slimeStartX[i]) { slimeDir[i] = 1; }
                if (slimeX[i] >= slimeEndX[i])   { slimeDir[i] = -1; }

                slimeAnimT[i] = slimeAnimT[i] + dt;
                slimeFrame[i] = Math.floor(slimeAnimT[i] * 4) % 4;

                // Slime-player collision
                let sdx = absVal(plX + plW / 2 - slimeX[i] - 8);
                let sdy = absVal(plY + plH / 2 - slimeY[i] - 8);
                if (sdx < 16 && sdy < 16 && gameWon == 0) {
                    plX = checkX;
                    plY = checkY;
                    plVX = 0;
                    plVY = 0;
                    // Spawn slime hit dust
                    let sd = 0;
                    while (sd < 6) {
                        dustX[nextDust] = plX + plW / 2; dustY[nextDust] = plY + plH;
                        dustVX[nextDust] = getRandomValue(-60, 60); dustVY[nextDust] = getRandomValue(-40, -10);
                        dustLife[nextDust] = getRandomValue(15, 30);
                        dustR[nextDust] = getRandomValue(140, 200); dustG[nextDust] = getRandomValue(120, 160); dustB[nextDust] = getRandomValue(80, 120);
                        nextDust = nextDust + 1; if (nextDust >= maxDust) nextDust = 0; sd = sd + 1;
                    }
                }
                i = i + 1;
            }

            // ── Update dust particles ──
            i = 0;
            while (i < maxDust) {
                if (dustLife[i] > 0) {
                    dustX[i] = dustX[i] + dustVX[i] * dt;
                    dustY[i] = dustY[i] + dustVY[i] * dt;
                    dustVY[i] = dustVY[i] + 60 * dt;
                    dustLife[i] = dustLife[i] - 1;
                }
                i = i + 1;
            }

            // ── Water animation ──
            waterTimer = waterTimer + dt;
            if (waterTimer > 0.3) {
                waterTimer = 0;
                waterFrame = (waterFrame + 1) % 4;
            }

            // ── Camera ──
            let camTarget = plX - W / 2 + plW / 2;
            camX = camX + (camTarget - camX) * 0.08;
            if (camX < 0) camX = 0;
            if (camX > maxCamX) camX = maxCamX;
        }

        // ════════════════════════════════════════
        //  DRAW
        // ════════════════════════════════════════
        beginDrawing();

        // ── Sky gradient ──
        drawRectangleGradientV(0, 0, W, H,
            color(20, 15, 50, 255), color(60, 40, 90, 255));

        // ── Far background (parallax 0.1x) ──
        let bgFarW = 256;
        let bgFarH = 200;
        let farScroll = camX * 0.1;
        let farX = -(farScroll % bgFarW);
        // Tile the far background across screen
        let bx = farX;
        while (bx < W) {
            drawTexturePro(bgFarTex,
                0, 0, bgFarW, bgFarH,
                bx, 0, W / 2, H * 0.7,
                0, 0, 0, WHITE);
            bx = bx + W / 2;
        }

        // ── Mid background (parallax 0.4x) ──
        let midScroll = camX * 0.4;
        let midX = -(midScroll % bgFarW);
        bx = midX;
        while (bx < W) {
            drawTexturePro(bgMidTex,
                0, 0, bgFarW, bgFarH,
                bx, H * 0.15, W / 2, H * 0.65,
                0, 0, 0, WHITE);
            bx = bx + W / 2;
        }

        // ── Near background (parallax 0.7x) ──
        let nearScroll = camX * 0.7;
        let nearX = -(nearScroll % bgFarW);
        bx = nearX;
        while (bx < W) {
            drawTexturePro(bgNearTex,
                0, 0, bgFarW, bgFarH,
                bx, H * 0.25, W / 2, H * 0.6,
                0, 0, 0, WHITE);
            bx = bx + W / 2;
        }

        // ── Tile map ──
        let startCol = Math.floor(camX / TILE);
        let endCol = startCol + Math.floor(W / TILE) + 2;
        if (endCol > MAP_W) endCol = MAP_W;
        if (startCol < 0) startCol = 0;

        let tileCol = startCol;
        while (tileCol < endCol) {
            let tileRow = 0;
            while (tileRow < MAP_H) {
                let tileID = tiles[(tileRow * MAP_W) + tileCol];
                if (tileID > 0) {
                    let screenX = tileCol * TILE - Math.floor(camX);
                    let screenY = tileRow * TILE;

                    // Map tile IDs to tileset positions
                    let srcTile = 0;
                    if (tileID == 1) srcTile = 0;       // grass top
                    else if (tileID == 2) srcTile = 1;   // grass top var2
                    else if (tileID == 3) srcTile = 2;   // dirt
                    else if (tileID == 4) srcTile = 3;   // dirt var2
                    else if (tileID == 5) srcTile = 4;   // stone
                    else if (tileID == 6) srcTile = 5;   // stone cracked
                    else if (tileID == 7) srcTile = 6;   // mossy stone
                    else if (tileID == 9) {
                        srcTile = 8 + waterFrame;        // water animated
                    }
                    else if (tileID == 10) srcTile = 8;  // water deep (static)
                    else if (tileID == 15) srcTile = 14;  // thorn
                    else if (tileID == 17) srcTile = 16;  // red flower
                    else if (tileID == 18) srcTile = 17;  // blue flower
                    else if (tileID == 19) srcTile = 18;  // mushroom
                    else if (tileID == 20) srcTile = 19;  // crystal
                    else if (tileID == 23) srcTile = 22;  // grass blade
                    else if (tileID == 24) srcTile = 23;  // bush
                    else {
                        srcTile = 2;  // fallback to dirt
                    }

                    let srcX = (srcTile % 8) * SRC_TILE;
                    let srcY = Math.floor(srcTile / 8) * SRC_TILE;

                    drawTexturePro(tilesetTex,
                        srcX, srcY, SRC_TILE, SRC_TILE,
                        screenX, screenY, TILE, TILE,
                        0, 0, 0, WHITE);
                }
                tileRow = tileRow + 1;
            }
            tileCol = tileCol + 1;
        }

        // ── Gems ──
        let gemAnimFrame = Math.floor(time * 4) % 4;
        i = 0;
        while (i < maxGems) {
            if (gemAlive[i] == 1) {
                let gx = gemX[i] - Math.floor(camX) - 6;
                let gy = gemY[i] + Math.sin(time * 3 + i) * 4 - 6;
                if (gx > -20 && gx < W + 20) {
                    // Glow effect
                    let glowA = 40 + Math.sin(time * 4 + i * 0.5) * 25;
                    drawCircle(gx + 6, gy + 6, 12, color(100, 240, 120, glowA));
                    // Gem sprite
                    drawTexturePro(itemsTex,
                        gemAnimFrame * 12, 0, 12, 12,
                        gx, gy, 24, 24,
                        0, 0, 0, WHITE);
                }
            }
            i = i + 1;
        }

        // ── Slimes ──
        i = 0;
        while (i < maxSlimes) {
            let sx = slimeX[i] - Math.floor(camX);
            let sy = slimeY[i];
            if (sx > -40 && sx < W + 40) {
                let sf = slimeFrame[i];
                drawTexturePro(enemiesTex,
                    sf * 16, 0, 16, 16,
                    sx, sy, TILE, TILE,
                    0, 0, 0, WHITE);
            }
            i = i + 1;
        }

        // ── Player ──
        let plScreenX = plX - Math.floor(camX);
        let plScreenY = plY;

        // Glow behind player
        drawCircle(plScreenX + plW / 2, plScreenY + plH / 2, 20,
            color(200, 220, 255, 20));

        // Player sprite
        let spriteRow = 0;
        if (plState == 1) spriteRow = 1;
        if (plState == 2 || plState == 3) spriteRow = 2;

        let srcPX = plFrame * 16;
        let srcPY = spriteRow * 24;
        let drawW = 32;
        let drawH = 48;

        // Flip horizontally if facing left (negative srcW)
        let srcW = 16;
        if (plDir < 0) srcW = -16;

        drawTexturePro(playerTex,
            srcPX, srcPY, srcW, 24,
            plScreenX - 10, plScreenY - 14, drawW, drawH,
            0, 0, 0, WHITE);

        // ── Dust particles ──
        i = 0;
        while (i < maxDust) {
            if (dustLife[i] > 0) {
                let dx = dustX[i] - Math.floor(camX);
                let dy = dustY[i];
                let da = dustLife[i] * 8;
                if (da > 255) da = 255;
                drawCircle(dx, dy, 2, color(dustR[i], dustG[i], dustB[i], da));
            }
            i = i + 1;
        }

        // ── Fireflies ──
        i = 0;
        while (i < maxFF) {
            let fx = ffX[i] - Math.floor(camX);
            let fy = ffY[i] + Math.sin(time * 1.5 + ffPhase[i]) * 8;
            if (fx > -10 && fx < W + 10) {
                let fb = 100 + Math.sin(time * 2.5 + ffPhase[i]) * 100;
                if (fb < 0) fb = 0;
                // Glow
                drawCircle(fx, fy, 4, color(255, 240, 100, fb * 0.2));
                // Core
                drawCircle(fx, fy, 1, color(255, 255, 180, fb));
            }
            i = i + 1;
        }

        // ── Portal ──
        if (portalOpen == 1) {
            let ptx = portalX - Math.floor(camX);
            let pty = portalY;
            if (ptx > -60 && ptx < W + 60) {
                // Outer glow
                let pa = 80 + Math.sin(time * 3) * 40;
                drawCircle(ptx, pty, 30, color(100, 200, 255, pa * 0.3));
                drawCircle(ptx, pty, 20, color(150, 230, 255, pa * 0.5));
                drawCircle(ptx, pty, 10, color(200, 250, 255, pa));
                // Rotating sparkles
                let a = 0;
                while (a < 6) {
                    let angle = time * 2 + a * 1.047;
                    let spx = ptx + Math.cos(angle) * 18;
                    let spy = pty + Math.sin(angle) * 18;
                    drawCircle(spx, spy, 2, color(255, 255, 255, 200));
                    a = a + 1;
                }
            }
        }

        // ── HUD ──
        drawRectangle(0, 0, W, 36, color(0, 0, 0, 140));

        // Gem counter
        drawTexturePro(itemsTex,
            0, 0, 12, 12,
            8, 6, 24, 24,
            0, 0, 0, WHITE);
        drawText(String(collectedGems) + "/" + String(maxGems), 36, 10, 18, color(100, 240, 120, 255));

        // Score
        drawText("SCORE: " + String(score), W / 2 - 60, 10, 18, WHITE);

        // FPS
        drawText(String(getFPS()) + " FPS", W - 80, 10, 14, color(0, 200, 80, 200));

        // Portal hint
        if (collectedGems >= maxGems && gameWon == 0) {
            let hintA = 150 + Math.sin(time * 4) * 100;
            drawText("Portal Open! Go right!", W / 2 - 100, 50, 20, color(100, 220, 255, hintA));
        }

        // ── Win screen ──
        if (gameWon == 1) {
            drawRectangle(0, 0, W, H, color(0, 0, 0, 160));
            drawText("YOU WIN!", W / 2 - 100, H / 2 - 60, 40, color(255, 220, 50, 255));
            drawText("Score: " + String(score), W / 2 - 80, H / 2, 24, WHITE);
            drawText("Time: " + String(Math.floor(time)) + "s", W / 2 - 60, H / 2 + 35, 20, color(180, 180, 200, 255));
            drawText("Press ENTER to restart", W / 2 - 110, H / 2 + 80, 18, color(150, 150, 170, 255));

            if (isKeyPressed(KEY_ENTER)) {
                // Reset game
                plX = 3 * TILE;
                plY = (MAP_H - 5 - 3) * TILE;
                plVX = 0; plVY = 0;
                plDir = 1;
                plState = 0;
                plOnGround = 0;
                camX = 0;
                score = 0;
                time = 0;
                collectedGems = 0;
                portalOpen = 0;
                gameWon = 0;
                i = 0;
                while (i < maxGems) { gemAlive[i] = 1; i = i + 1; }
            }
        }

        endDrawing();
    }

    unloadTexture(playerTex);
    unloadTexture(tilesetTex);
    unloadTexture(bgFarTex);
    unloadTexture(bgMidTex);
    unloadTexture(bgNearTex);
    unloadTexture(itemsTex);
    unloadTexture(enemiesTex);
    closeWindow();
}

main();
