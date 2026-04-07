// Raycaster — Wolfenstein 3D-style first-person renderer
// WASD to move, LEFT/RIGHT arrows to turn
// 800 rays per frame, DDA algorithm, distance fog, wall sliding
// Pure trig + integer grid math — LLVM optimization showcase
// Compile: tsuchi compile examples/raycaster.js

function absVal(x) {
    if (x < 0) return -x;
    return x;
}

function main() {
    let W = 800;
    let H = 600;
    initWindow(W, H, "Tsuchi Raycaster");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // Map: 16x16 grid (0=empty, 1-4=wall types)
    let mapW = 16;
    let mapH = 16;
    let worldMap = [];

    // Row 0: outer walls
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    // Row 1
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(1);
    // Row 2
    worldMap.push(1); worldMap.push(0); worldMap.push(2); worldMap.push(2);
    worldMap.push(2); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(3); worldMap.push(3);
    worldMap.push(3); worldMap.push(3); worldMap.push(0); worldMap.push(1);
    // Row 3
    worldMap.push(1); worldMap.push(0); worldMap.push(2); worldMap.push(0);
    worldMap.push(2); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(3); worldMap.push(0);
    worldMap.push(0); worldMap.push(3); worldMap.push(0); worldMap.push(1);
    // Row 4
    worldMap.push(1); worldMap.push(0); worldMap.push(2); worldMap.push(0);
    worldMap.push(2); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(3); worldMap.push(0); worldMap.push(1);
    // Row 5
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(3); worldMap.push(0);
    worldMap.push(0); worldMap.push(3); worldMap.push(0); worldMap.push(1);
    // Row 6
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(4); worldMap.push(0);
    worldMap.push(4); worldMap.push(0); worldMap.push(3); worldMap.push(3);
    worldMap.push(3); worldMap.push(3); worldMap.push(0); worldMap.push(1);
    // Row 7
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(1);
    // Row 8
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(4); worldMap.push(0);
    worldMap.push(4); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(1);
    // Row 9
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(4); worldMap.push(4);
    worldMap.push(4); worldMap.push(0); worldMap.push(0); worldMap.push(2);
    worldMap.push(0); worldMap.push(2); worldMap.push(0); worldMap.push(1);
    // Row 10
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(2);
    worldMap.push(0); worldMap.push(2); worldMap.push(0); worldMap.push(1);
    // Row 11
    worldMap.push(1); worldMap.push(0); worldMap.push(3); worldMap.push(0);
    worldMap.push(3); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(2);
    worldMap.push(2); worldMap.push(2); worldMap.push(0); worldMap.push(1);
    // Row 12
    worldMap.push(1); worldMap.push(0); worldMap.push(3); worldMap.push(0);
    worldMap.push(3); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(1);
    // Row 13
    worldMap.push(1); worldMap.push(0); worldMap.push(3); worldMap.push(3);
    worldMap.push(3); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(1);
    // Row 14
    worldMap.push(1); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(0);
    worldMap.push(0); worldMap.push(0); worldMap.push(0); worldMap.push(1);
    // Row 15: outer walls
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);
    worldMap.push(1); worldMap.push(1); worldMap.push(1); worldMap.push(1);

    // Player state
    let px = 7.5;
    let py = 7.5;
    let pa = 0;
    let fov = 1.047;
    let moveSpeed = 3.0;
    let turnSpeed = 2.5;

    while (!windowShouldClose()) {
        let dt = getFrameTime();

        // ── Input ──
        if (isKeyDown(KEY_LEFT))  pa = pa - turnSpeed * dt;
        if (isKeyDown(KEY_RIGHT)) pa = pa + turnSpeed * dt;

        let dirX = Math.cos(pa);
        let dirY = Math.sin(pa);

        // Forward / backward with wall sliding
        if (isKeyDown(KEY_W) || isKeyDown(KEY_UP)) {
            let nx = px + dirX * moveSpeed * dt;
            let ny = py + dirY * moveSpeed * dt;
            if (worldMap[Math.floor(py) * mapW + Math.floor(nx)] == 0) px = nx;
            if (worldMap[Math.floor(ny) * mapW + Math.floor(px)] == 0) py = ny;
        }
        if (isKeyDown(KEY_S) || isKeyDown(KEY_DOWN)) {
            let nx = px - dirX * moveSpeed * dt;
            let ny = py - dirY * moveSpeed * dt;
            if (worldMap[Math.floor(py) * mapW + Math.floor(nx)] == 0) px = nx;
            if (worldMap[Math.floor(ny) * mapW + Math.floor(px)] == 0) py = ny;
        }

        // Strafe
        let strafeX = Math.cos(pa + 1.5708);
        let strafeY = Math.sin(pa + 1.5708);
        if (isKeyDown(KEY_D)) {
            let nx = px + strafeX * moveSpeed * dt;
            let ny = py + strafeY * moveSpeed * dt;
            if (worldMap[Math.floor(py) * mapW + Math.floor(nx)] == 0) px = nx;
            if (worldMap[Math.floor(ny) * mapW + Math.floor(px)] == 0) py = ny;
        }
        if (isKeyDown(KEY_A)) {
            let nx = px - strafeX * moveSpeed * dt;
            let ny = py - strafeY * moveSpeed * dt;
            if (worldMap[Math.floor(py) * mapW + Math.floor(nx)] == 0) px = nx;
            if (worldMap[Math.floor(ny) * mapW + Math.floor(px)] == 0) py = ny;
        }

        // ── Draw ──
        beginDrawing();
        clearBackground(BLACK);

        // Ceiling gradient (dark blue)
        drawRectangleGradientV(0, 0, W, H / 2,
            color(5, 5, 20, 255), color(40, 35, 80, 255));

        // Floor gradient (dark brown)
        drawRectangleGradientV(0, H / 2, W, H / 2,
            color(60, 55, 45, 255), color(15, 18, 12, 255));

        // ── Raycasting: 800 rays ──
        let col = 0;
        while (col < W) {
            let camX = 2 * col / W - 1;
            let rayA = pa + camX * fov / 2;
            let rdx = Math.cos(rayA);
            let rdy = Math.sin(rayA);

            let mapX = Math.floor(px);
            let mapY = Math.floor(py);

            // Delta distance
            let ddx = 100000;
            if (absVal(rdx) > 0.00001) ddx = absVal(1 / rdx);
            let ddy = 100000;
            if (absVal(rdy) > 0.00001) ddy = absVal(1 / rdy);

            let stepX = 1;
            let sideDistX = (mapX + 1 - px) * ddx;
            if (rdx < 0) {
                stepX = -1;
                sideDistX = (px - mapX) * ddx;
            }

            let stepY = 1;
            let sideDistY = (mapY + 1 - py) * ddy;
            if (rdy < 0) {
                stepY = -1;
                sideDistY = (py - mapY) * ddy;
            }

            // DDA loop
            let hit = 0;
            let side = 0;
            let steps = 0;
            while (hit == 0 && steps < 64) {
                if (sideDistX < sideDistY) {
                    sideDistX = sideDistX + ddx;
                    mapX = mapX + stepX;
                    side = 0;
                } else {
                    sideDistY = sideDistY + ddy;
                    mapY = mapY + stepY;
                    side = 1;
                }
                if (mapX >= 0 && mapX < mapW && mapY >= 0 && mapY < mapH) {
                    let cell = worldMap[mapY * mapW + mapX];
                    if (cell > 0) hit = cell;
                } else {
                    hit = 1;
                }
                steps = steps + 1;
            }

            // Perpendicular distance (fish-eye correction)
            let dist = 0;
            if (side == 0) {
                dist = sideDistX - ddx;
            } else {
                dist = sideDistY - ddy;
            }
            if (dist < 0.05) dist = 0.05;

            // Wall strip height
            let lineH = H / dist;
            if (lineH > H * 4) lineH = H * 4;
            let drawStart = H / 2 - lineH / 2;

            // Base wall color by type
            let wr = 200;
            let wg = 200;
            let wb = 200;
            if (hit == 2) { wr = 220; wg = 90;  wb = 80;  }
            if (hit == 3) { wr = 80;  wg = 200; wb = 100; }
            if (hit == 4) { wr = 80;  wg = 120; wb = 220; }

            // Darken one side for 3D depth
            if (side == 1) {
                wr = wr * 0.65;
                wg = wg * 0.65;
                wb = wb * 0.65;
            }

            // Distance fog
            let fog = 1.0 - dist / 14;
            if (fog < 0.08) fog = 0.08;
            wr = wr * fog;
            wg = wg * fog;
            wb = wb * fog;

            drawRectangle(col, drawStart, 1, lineH, color(wr, wg, wb, 255));

            col = col + 1;
        }

        // ── Minimap (top-right corner) ──
        let mmS = 5;
        let mmX = W - mapW * mmS - 10;
        let mmY0 = 10;

        // Background
        drawRectangle(mmX - 2, mmY0 - 2, mapW * mmS + 4, mapH * mmS + 4, color(0, 0, 0, 160));

        let my = 0;
        while (my < mapH) {
            let mx = 0;
            while (mx < mapW) {
                let cell = worldMap[my * mapW + mx];
                if (cell > 0) {
                    let cr = 100; let cg = 100; let cb = 120;
                    if (cell == 2) { cr = 180; cg = 70;  cb = 60;  }
                    if (cell == 3) { cr = 60;  cg = 160; cb = 80;  }
                    if (cell == 4) { cr = 60;  cg = 90;  cb = 180; }
                    drawRectangle(mmX + mx * mmS, mmY0 + my * mmS, mmS, mmS, color(cr, cg, cb, 220));
                }
                mx = mx + 1;
            }
            my = my + 1;
        }

        // Player on minimap
        drawCircle(mmX + px * mmS, mmY0 + py * mmS, 3, YELLOW);
        drawLine(
            mmX + px * mmS, mmY0 + py * mmS,
            mmX + (px + Math.cos(pa) * 2) * mmS,
            mmY0 + (py + Math.sin(pa) * 2) * mmS,
            YELLOW
        );

        // ── HUD ──
        drawText("TSUCHI RAYCASTER", 10, 10, 24, WHITE);
        drawText("WASD + Arrows to explore", 10, 40, 14, GRAY);
        drawText(String(getFPS()) + " FPS", 10, H - 30, 20, LIME);

        endDrawing();
    }

    closeWindow();
}

main();
