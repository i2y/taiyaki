// Voxel Terrain — Comanche-style landscape renderer
// Fly over procedural mountains, valleys, and oceans
// 400 columns × ~150 depth steps per frame, perspective projection
// Compile: tsuchi compile examples/voxel_terrain.js

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
    let colW = 2;
    let numCols = W / colW;
    let mapSize = 256;
    let totalCells = mapSize * mapSize;
    let maxDist = 250;
    let scaleH = 220;

    initWindow(W, H, "Tsuchi Voxel Terrain");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // ── Pre-compute heightmap + colormap ──
    let hMap = [];
    let cR = [];
    let cG = [];
    let cB = [];

    let my = 0;
    while (my < mapSize) {
        let mx = 0;
        while (mx < mapSize) {
            let fx = mx * 0.08;
            let fy = my * 0.08;

            // 5-octave terrain with ridges
            let h = Math.sin(fx * 0.25 + fy * 0.18) * 45
                   + absVal(Math.sin(fx * 0.12 - fy * 0.15)) * 35
                   + Math.sin((fx + fy) * 0.2) * 20
                   + Math.sin(fx * 0.5 + fy * 0.4) * 10
                   + Math.sin(fx * 0.9 - fy * 0.7) * 5;

            hMap.push(h);

            // Terrain color by elevation
            if (h < -20) {
                // Deep water
                cR.push(20); cG.push(50); cB.push(140);
            } else if (h < -8) {
                // Shallow water
                cR.push(40); cG.push(90); cB.push(170);
            } else if (h < 0) {
                // Beach / sand
                cR.push(160); cG.push(150); cB.push(100);
            } else if (h < 18) {
                // Grass
                let g = 120 + h * 2;
                cR.push(50); cG.push(g); cB.push(45);
            } else if (h < 38) {
                // Forest (dark green)
                cR.push(35); cG.push(100); cB.push(35);
            } else if (h < 55) {
                // Rock
                let v = 80 + (h - 38) * 2;
                cR.push(v); cG.push(v - 10); cB.push(v - 20);
            } else {
                // Snow
                let v = 200 + (h - 55);
                if (v > 240) v = 240;
                cR.push(v); cG.push(v); cB.push(v + 10);
            }

            mx = mx + 1;
        }
        my = my + 1;
    }

    // Y-buffer (one per column)
    let yBuf = [];
    let c = 0;
    while (c < numCols) {
        yBuf.push(H);
        c = c + 1;
    }

    // Camera state
    let camX = 80;
    let camY = 80;
    let camAngle = 0.5;
    let camHeight = 90;
    let horizon = 280;
    let flySpeed = 40;
    let fov = 1.2;

    while (!windowShouldClose()) {
        let dt = getFrameTime();

        // ── Controls ──
        if (isKeyDown(KEY_LEFT))  camAngle = camAngle - 1.8 * dt;
        if (isKeyDown(KEY_RIGHT)) camAngle = camAngle + 1.8 * dt;
        if (isKeyDown(KEY_UP))    horizon = horizon - 200 * dt;
        if (isKeyDown(KEY_DOWN))  horizon = horizon + 200 * dt;
        if (isKeyDown(KEY_W))     camHeight = camHeight + 50 * dt;
        if (isKeyDown(KEY_S))     camHeight = camHeight - 50 * dt;
        if (isKeyDown(KEY_A))     flySpeed = flySpeed - 30 * dt;
        if (isKeyDown(KEY_D))     flySpeed = flySpeed + 30 * dt;

        horizon = clamp(horizon, 50, H - 50);
        camHeight = clamp(camHeight, 25, 200);
        flySpeed = clamp(flySpeed, 5, 120);

        // Auto-fly forward
        camX = camX + Math.cos(camAngle) * flySpeed * dt;
        camY = camY + Math.sin(camAngle) * flySpeed * dt;

        // Wrap to map bounds
        camX = camX - Math.floor(camX / mapSize) * mapSize;
        camY = camY - Math.floor(camY / mapSize) * mapSize;

        // ── Draw ──
        beginDrawing();
        clearBackground(BLACK);

        // Sky: gradient from deep blue (top) to hazy light blue (horizon)
        drawRectangleGradientV(0, 0, W, H,
            color(25, 50, 120, 255), color(140, 180, 220, 255));

        // Reset y-buffer
        c = 0;
        while (c < numCols) {
            yBuf[c] = H;
            c = c + 1;
        }

        // Pre-compute FOV edge directions (4 trig calls per frame)
        let cosL = Math.cos(camAngle - fov / 2);
        let sinL = Math.sin(camAngle - fov / 2);
        let cosR = Math.cos(camAngle + fov / 2);
        let sinR = Math.sin(camAngle + fov / 2);

        // Fog sky color (for blending)
        let fogR = 140;
        let fogG = 180;
        let fogB = 220;

        // ── Render terrain: front-to-back column rendering ──
        let z = 2;
        while (z < maxDist) {
            // Scanline endpoints at distance z
            let plx = camX + cosL * z;
            let ply = camY + sinL * z;
            let prx = camX + cosR * z;
            let pry = camY + sinR * z;

            let dx = (prx - plx) / numCols;
            let dy = (pry - ply) / numCols;

            let sx = plx;
            let sy = ply;

            // Fog: increases with distance
            let fog = z / maxDist;
            if (fog > 1) fog = 1;
            let fogSq = fog * fog;

            c = 0;
            while (c < numCols) {
                // Wrap world coords to heightmap
                let wx = sx - Math.floor(sx / mapSize) * mapSize;
                let wy = sy - Math.floor(sy / mapSize) * mapSize;
                let mi = Math.floor(wy) * mapSize + Math.floor(wx);
                if (mi < 0) mi = 0;
                if (mi >= totalCells) mi = totalCells - 1;

                let h = hMap[mi];

                // Project height to screen Y (integer to avoid sub-pixel gaps)
                let screenY = Math.floor((camHeight - h) / z * scaleH + horizon);
                if (screenY < 0) screenY = 0;

                if (screenY < yBuf[c]) {
                    // Blend terrain color with fog
                    let tr = cR[mi] + (fogR - cR[mi]) * fogSq;
                    let tg = cG[mi] + (fogG - cG[mi]) * fogSq;
                    let tb = cB[mi] + (fogB - cB[mi]) * fogSq;

                    let lineH = yBuf[c] - screenY;
                    drawRectangle(c * colW, screenY, colW, lineH,
                        color(tr, tg, tb, 255));
                    yBuf[c] = screenY;
                }

                sx = sx + dx;
                sy = sy + dy;
                c = c + 1;
            }

            // Uniform step for clean rendering
            z = z + 1;
        }

        // ── HUD ──
        drawRectangle(0, 0, W, 48, color(0, 0, 0, 120));
        drawText("TSUCHI VOXEL TERRAIN", 10, 6, 22, WHITE);
        drawText("LEFT/RIGHT: turn   UP/DOWN: pitch   W/S: altitude   A/D: speed", 10, 30, 12, color(180, 180, 180, 255));

        drawRectangle(0, H - 28, 200, 28, color(0, 0, 0, 140));
        drawText("Alt:" + String(Math.floor(camHeight)) + "  Spd:" + String(Math.floor(flySpeed)), 10, H - 22, 14, color(180, 220, 255, 255));
        drawText(String(getFPS()) + " FPS", 140, H - 22, 14, LIME);

        endDrawing();
    }

    closeWindow();
}

main();
