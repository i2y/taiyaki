// Neon Drive — Synthwave Racing
// Mode 7-style perspective ground grid, neon road, sun with bands
// UP/DOWN: accel/brake  LEFT/RIGHT: steer
// Compile: tsuchi compile examples/neon_drive.js

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
    let horizon = 235;
    let camH = 130;
    let focal = 160;
    let gridSp = 14;

    initWindow(W, H, "Neon Drive");
    setTargetFPS(60);
    loadFont("/System/Library/Fonts/SFNS.ttf", 48);

    // Stars
    let numStars = 200;
    let starX = [];
    let starY = [];
    let starB = [];
    let i = 0;
    while (i < numStars) {
        starX.push(getRandomValue(0, W));
        starY.push(getRandomValue(8, horizon - 40));
        starB.push(getRandomValue(60, 240));
        i = i + 1;
    }

    let posZ = 0;
    let posX = 0;
    let speed = 0;
    let maxSpeed = 300;
    let dist = 0;
    let time = 0;

    while (!windowShouldClose()) {
        let dt = getFrameTime();
        time = time + dt;

        // ── Controls ──
        if (isKeyDown(KEY_UP) || isKeyDown(KEY_W))    speed = speed + 150 * dt;
        if (isKeyDown(KEY_DOWN) || isKeyDown(KEY_S))   speed = speed - 250 * dt;
        speed = speed - 30 * dt;
        speed = clamp(speed, 0, maxSpeed);

        if (isKeyDown(KEY_LEFT) || isKeyDown(KEY_A))   posX = posX - 280 * dt;
        if (isKeyDown(KEY_RIGHT) || isKeyDown(KEY_D))  posX = posX + 280 * dt;

        posZ = posZ + speed * dt;
        dist = dist + speed * dt;

        // Road curve at camera position (for auto-steer feel)
        let camCurve = Math.sin(posZ * 0.004) * 0.6 + Math.sin(posZ * 0.011) * 0.3;

        beginDrawing();
        clearBackground(color(6, 2, 14, 255));

        // ════════════════════════════════════
        //  SKY
        // ════════════════════════════════════
        let sy = 0;
        while (sy < horizon) {
            let t = sy / horizon;
            drawRectangle(0, sy, W, 2,
                color(6 + t * 70, 2 + t * 10, 14 + t * 55, 255));
            sy = sy + 2;
        }

        // ── Stars ──
        i = 0;
        while (i < numStars) {
            let tw = starB[i] + Math.sin(time * 1.5 + i * 0.7) * 50;
            tw = clamp(tw, 40, 255);
            drawPixel(starX[i], starY[i], color(tw, tw, tw + 15, 255));
            if (starB[i] > 180) {
                drawPixel(starX[i] + 1, starY[i], color(tw * 0.5, tw * 0.5, tw * 0.6, 200));
                drawPixel(starX[i], starY[i] + 1, color(tw * 0.5, tw * 0.5, tw * 0.6, 200));
            }
            i = i + 1;
        }

        // ════════════════════════════════════
        //  SUN (with horizontal bands)
        // ════════════════════════════════════
        let sunX = halfW + 60;
        let sunY = horizon - 5;
        let sunR = 70;
        // Outer glow layers
        drawCircle(sunX, sunY, sunR + 50, color(255, 40, 10, 8));
        drawCircle(sunX, sunY, sunR + 35, color(255, 60, 15, 15));
        drawCircle(sunX, sunY, sunR + 20, color(255, 90, 25, 30));
        drawCircle(sunX, sunY, sunR + 8,  color(255, 130, 40, 50));
        // Body gradient (top=yellow, bottom=red-orange)
        drawCircle(sunX, sunY, sunR, color(255, 180, 60, 255));
        drawCircle(sunX, sunY + 15, sunR - 5, color(255, 120, 40, 200));
        drawCircle(sunX, sunY + 30, sunR - 15, color(255, 70, 30, 180));
        // Horizontal scan bands
        let band = 0;
        while (band < 9) {
            let by = sunY - sunR + 8 + band * 15;
            let bh = 2 + band;
            if (by > sunY - sunR && by + bh < sunY + sunR) {
                drawRectangle(sunX - sunR - 5, by, sunR * 2 + 10, bh,
                    color(6, 2, 14, 180 + band * 8));
            }
            band = band + 1;
        }

        // ════════════════════════════════════
        //  MOUNTAINS (layered silhouettes)
        // ════════════════════════════════════
        // Far mountains (darker, taller)
        let mx = 0;
        while (mx < W) {
            let mh = Math.sin(mx * 0.006 + 0.5) * 50
                    + Math.sin(mx * 0.015 + 2) * 30
                    + Math.sin(mx * 0.04 + 1) * 12 + 65;
            drawRectangle(mx, horizon - mh, 4, mh + 1, color(18, 6, 35, 255));
            mx = mx + 4;
        }
        // Near mountains (brighter, smaller)
        mx = 0;
        while (mx < W) {
            let mh = Math.sin(mx * 0.01 + 3) * 30
                    + Math.sin(mx * 0.03) * 18
                    + Math.sin(mx * 0.07 + 1.5) * 8 + 35;
            drawRectangle(mx, horizon - mh, 4, mh + 1, color(30, 12, 55, 255));
            mx = mx + 4;
        }

        // Horizon glow line
        drawRectangle(0, horizon - 2, W, 1, color(255, 50, 150, 100));
        drawRectangle(0, horizon - 1, W, 2, color(255, 0, 120, 200));
        drawRectangle(0, horizon + 1, W, 1, color(200, 0, 100, 100));

        // ════════════════════════════════════
        //  GROUND: dark base
        // ════════════════════════════════════
        drawRectangle(0, horizon + 2, W, H - horizon - 2, color(4, 1, 10, 255));

        // ════════════════════════════════════
        //  GRID: Vertical lines (converging)
        // ════════════════════════════════════
        let numV = 25;
        let vx = -numV;
        while (vx <= numV) {
            let worldGX = vx * gridSp * 3;
            // Bottom of screen position
            let botDepth = camH * focal / (H - horizon);
            let botSX = halfW + (worldGX - posX) * focal / botDepth;
            let vanishX = halfW - posX * 0.015;

            let alpha = 60;
            if (absVal(vx) > 15) alpha = 30;
            drawLine(vanishX, horizon + 2, botSX, H,
                color(0, 140, 255, alpha));
            vx = vx + 1;
        }

        // ════════════════════════════════════
        //  GRID: Horizontal lines (perspective)
        // ════════════════════════════════════
        let gzStart = posZ - (posZ - Math.floor(posZ / gridSp) * gridSp);
        let gz = gzStart;
        while (gz < posZ + 4000) {
            let relZ = gz - posZ;
            if (relZ > 2) {
                let sY = horizon + camH * focal / relZ;
                if (sY > horizon + 1 && sY < H) {
                    let fog = 1.0 - relZ / 3000;
                    if (fog < 0) fog = 0;
                    drawRectangle(0, sY, W, 1,
                        color(255 * fog, 0, 160 * fog, 255));
                }
            }
            gz = gz + gridSp;
        }

        // ════════════════════════════════════
        //  ROAD with curves
        // ════════════════════════════════════
        let ry = horizon + 2;
        while (ry < H) {
            let relZ = camH * focal / (ry - horizon);
            let wZ = posZ + relZ;

            // Road curve
            let curve = Math.sin(wZ * 0.004) * 250 + Math.sin(wZ * 0.011) * 120;
            let roadCX = halfW + (curve - posX) * focal / relZ;
            let roadW = 140 * focal / relZ;
            if (roadW > W * 2) roadW = W * 2;

            let fog = 1.0 - relZ / 2500;
            if (fog < 0.03) fog = 0.03;

            // Road surface
            if (roadW > 2) {
                drawRectangle(roadCX - roadW / 2, ry, roadW, 2,
                    color(15 * fog, 5 * fog, 28 * fog, 220));

                // Edge lines (neon magenta)
                let edgeA = fog * 255;
                drawRectangle(roadCX - roadW / 2, ry, 2, 2,
                    color(edgeA, 0, edgeA * 0.7, 255));
                drawRectangle(roadCX + roadW / 2 - 2, ry, 2, 2,
                    color(edgeA, 0, edgeA * 0.7, 255));

                // Center dashed line (yellow)
                let dashPhase = wZ - Math.floor(wZ / 12) * 12;
                if (dashPhase < 6 && roadW > 10) {
                    drawRectangle(roadCX - 1, ry, 2, 2,
                        color(255 * fog, 220 * fog, 0, 200));
                }
            }

            ry = ry + 2;
        }

        // ════════════════════════════════════
        //  Side glow strips (speed effect)
        // ════════════════════════════════════
        if (speed > 100) {
            let glowA = (speed - 100) / maxSpeed * 80;
            drawRectangleGradientH(0, horizon, 60, H - horizon,
                color(255, 0, 180, glowA), color(255, 0, 180, 0));
            drawRectangleGradientH(W - 60, horizon, 60, H - horizon,
                color(255, 0, 180, 0), color(255, 0, 180, glowA));
        }

        // ════════════════════════════════════
        //  HUD
        // ════════════════════════════════════
        // Title
        drawText("N E O N   D R I V E", 24, 16, 24, color(255, 0, 180, 255));

        // Speed
        drawRectangle(W - 200, H - 65, 180, 45, color(0, 0, 0, 150));
        drawRectangle(W - 200, H - 65, 180, 1, color(0, 200, 255, 100));
        let speedPct = speed / maxSpeed;
        let barW = speedPct * 170;
        let barR = speedPct * 255;
        let barG = (1 - speedPct) * 200;
        drawRectangle(W - 195, H - 52, barW, 14, color(barR, barG, 200, 200));
        drawText(String(Math.floor(speed)) + " km/h", W - 195, H - 38, 16,
            color(0, 255, 220, 255));

        // Distance
        drawText(String(Math.floor(dist / 50)) + " m", 24, H - 35, 18,
            color(255, 0, 180, 200));

        // Controls hint
        drawText("UP: accel  LEFT/RIGHT: steer", 24, 46, 12,
            color(80, 40, 100, 255));

        // FPS
        drawText(String(getFPS()) + " FPS", W - 80, 16, 14,
            color(0, 220, 180, 200));

        endDrawing();
    }

    closeWindow();
}

main();
