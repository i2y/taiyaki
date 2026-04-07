// Tsuchi Visualizer — animated spectrum with live resize + global state
// Compile: uv run tsuchi compile examples/ui_dashboard.jsx

var playing = 1;
var vol = 80;
var checked_glow = 1;
var checked_mirror = 0;
var style = 0;
var b0=0;var b1=0;var b2=0;var b3=0;var b4=0;var b5=0;var b6=0;var b7=0;
var b8=0;var b9=0;var b10=0;var b11=0;var b12=0;var b13=0;var b14=0;var b15=0;
var b16=0;var b17=0;var b18=0;var b19=0;var b20=0;var b21=0;var b22=0;var b23=0;
var b24=0;var b25=0;var b26=0;var b27=0;var b28=0;var b29=0;var b30=0;var b31=0;

function drawUI() {
    let playLabel = "Play";
    if (playing) { playLabel = "||"; }
    <VPanel gap={0}>
        <Box growX padding={[10,24,10,24]} gap={16} bg={[18,18,30]}>
            <Text size={22} color={[180,100,255]}>>> </Text>
            <Text size={20} color={[220,220,240]}>Tsuchi Visualizer</Text>
            <Spacer />
            <Text size={14} color={[100,100,130]}>Synthwave Dreams</Text>
        </Box>
        <Box id="viz" grow bg={[10,10,18]} />
        <Box growX padding={[10,24,10,24]} gap={20} bg={[22,22,36]}>
            <Button id="play" kind="primary" size={16}>{playLabel}</Button>
            <Slider id="vol" value={vol} min={0} max={100} w={160} />
            <Checkbox id="glow" checked={checked_glow} size={14}>Glow</Checkbox>
            <Checkbox id="mirror" checked={checked_mirror} size={14}>Mirror</Checkbox>
            <Spacer />
            <TabBar>
                <TabButton id="s0" index={0} active={style} size={14}>Bars</TabButton>
                <TabButton id="s1" index={1} active={style} size={14}>Wave</TabButton>
                <TabButton id="s2" index={2} active={style} size={14}>Dots</TabButton>
            </TabBar>
        </Box>
    </VPanel>
}

function drawBars() {
    let w = getScreenWidth();
    let h = getScreenHeight();
    let topH = 48;
    let botH = 52;
    let vizX = 16;
    let vizY = topH + 16;
    let vizW = w - 32;
    let vizH = h - topH - botH - 32;
    let baseline = vizY + vizH;
    let bands = 32;
    let gap = 3;
    let barW = (vizW - (bands - 1) * gap) / bands;
    let volF = vol / 100;
    let i = 0;
    while (i < bands) {
        let v = 0;
        if(i===0){v=b0;}if(i===1){v=b1;}if(i===2){v=b2;}if(i===3){v=b3;}
        if(i===4){v=b4;}if(i===5){v=b5;}if(i===6){v=b6;}if(i===7){v=b7;}
        if(i===8){v=b8;}if(i===9){v=b9;}if(i===10){v=b10;}if(i===11){v=b11;}
        if(i===12){v=b12;}if(i===13){v=b13;}if(i===14){v=b14;}if(i===15){v=b15;}
        if(i===16){v=b16;}if(i===17){v=b17;}if(i===18){v=b18;}if(i===19){v=b19;}
        if(i===20){v=b20;}if(i===21){v=b21;}if(i===22){v=b22;}if(i===23){v=b23;}
        if(i===24){v=b24;}if(i===25){v=b25;}if(i===26){v=b26;}if(i===27){v=b27;}
        if(i===28){v=b28;}if(i===29){v=b29;}if(i===30){v=b30;}if(i===31){v=b31;}
        v = v * volF;
        let bh = (v / 100) * vizH;
        if (bh < 2) { bh = 2; }
        let bx = vizX + i * (barW + gap);
        let by = baseline - bh;
        let frac = i / 31;
        let cr = 80 + frac * 175;
        let cg = 200 - frac * 160;
        let cb = 255 - frac * 30;
        if (style === 0) {
            if (checked_glow) {
                drawRectangle(bx-3, by-6, barW+6, bh+6, color(cr,cg,cb,20));
                drawRectangle(bx-1, by-2, barW+2, bh+2, color(cr,cg,cb,40));
            }
            drawRectangle(bx, by, barW, bh, color(cr,cg,cb,230));
            drawRectangle(bx, by, barW, 3, color(255,255,255,80));
            if (checked_mirror) {
                drawRectangle(bx, baseline, barW, bh*0.35, color(cr,cg,cb,40));
            }
        }
        if (style === 1) {
            let mid = vizY + vizH / 2;
            let amp = bh / 2;
            if (checked_glow) { drawRectangle(bx, mid-amp-3, barW, amp*2+6, color(cr,cg,cb,25)); }
            drawRectangle(bx, mid-amp, barW, amp*2, color(cr,cg,cb,200));
            drawCircle(bx+barW/2, mid-amp, barW/2+1, color(255,255,255,120));
            drawCircle(bx+barW/2, mid+amp, barW/2+1, color(255,255,255,60));
        }
        if (style === 2) {
            let dotR = barW / 2;
            if (dotR < 4) { dotR = 4; }
            let numDots = bh / (dotR * 2 + 3);
            if (numDots < 1) { numDots = 1; }
            let j = 0;
            while (j < numDots) {
                let dy = baseline - j * (dotR*2+3) - dotR;
                let alpha = 240 - j * 12;
                if (alpha < 40) { alpha = 40; }
                if (checked_glow) { drawCircle(bx+barW/2, dy, dotR+4, color(cr,cg,cb,alpha/5)); }
                drawCircle(bx+barW/2, dy, dotR, color(cr,cg,cb,alpha));
                j = j + 1;
            }
        }
        i = i + 1;
    }
}

// Full frame redraw — called from GLFW during live window resize
function _resizeFrame() {
    let w = getScreenWidth();
    let h = getScreenHeight();
    claySetDimensions(w, h);
    beginFrame();
    clayBeginLayout();
    drawUI();
    clayEndLayout();
    endFrame();
    beginDrawing();
    clearBackground(color(10, 10, 18, 255));
    clayRender();
    drawBars();
    endDrawing();
}

function main() {
    setConfigFlags(FLAG_WINDOW_RESIZABLE);
    initWindow(1100, 700, "Tsuchi Visualizer");
    clayInit(1100, 700);
    claySetMeasureTextRaylib();
    claySetBgColor(10, 10, 18);
    clayRegisterResizeCallback();
    let font = clayLoadFont("/System/Library/Fonts/Supplemental/Arial.ttf", 48);
    setTargetFPS(60);

    let t0=50;let t1=70;let t2=90;let t3=60;let t4=80;let t5=40;let t6=95;let t7=55;
    let t8=75;let t9=85;let t10=45;let t11=65;let t12=88;let t13=35;let t14=72;let t15=92;
    let t16=48;let t17=78;let t18=58;let t19=82;let t20=42;let t21=68;let t22=93;let t23=52;
    let t24=83;let t25=38;let t26=73;let t27=87;let t28=47;let t29=77;let t30=62;let t31=96;

    while (!windowShouldClose()) {
        let w = getScreenWidth();
        let h = getScreenHeight();
        claySetDimensions(w, h);
        claySetPointer(getMouseX(), getMouseY(), isMouseButtonDown(0));
        clayUpdateScroll(0, getMouseWheelMove() * 40, getFrameTime());

        let spd = 0.1;
        if (playing) {
            b0=b0+(t0-b0)*spd;b1=b1+(t1-b1)*spd;b2=b2+(t2-b2)*spd;b3=b3+(t3-b3)*spd;
            b4=b4+(t4-b4)*spd;b5=b5+(t5-b5)*spd;b6=b6+(t6-b6)*spd;b7=b7+(t7-b7)*spd;
            b8=b8+(t8-b8)*spd;b9=b9+(t9-b9)*spd;b10=b10+(t10-b10)*spd;b11=b11+(t11-b11)*spd;
            b12=b12+(t12-b12)*spd;b13=b13+(t13-b13)*spd;b14=b14+(t14-b14)*spd;b15=b15+(t15-b15)*spd;
            b16=b16+(t16-b16)*spd;b17=b17+(t17-b17)*spd;b18=b18+(t18-b18)*spd;b19=b19+(t19-b19)*spd;
            b20=b20+(t20-b20)*spd;b21=b21+(t21-b21)*spd;b22=b22+(t22-b22)*spd;b23=b23+(t23-b23)*spd;
            b24=b24+(t24-b24)*spd;b25=b25+(t25-b25)*spd;b26=b26+(t26-b26)*spd;b27=b27+(t27-b27)*spd;
            b28=b28+(t28-b28)*spd;b29=b29+(t29-b29)*spd;b30=b30+(t30-b30)*spd;b31=b31+(t31-b31)*spd;
            if(getRandomValue(0,6)===0){t0=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t1=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t2=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t3=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t4=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t5=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t6=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t7=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t8=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t9=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t10=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t11=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t12=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t13=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t14=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t15=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t16=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t17=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t18=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t19=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t20=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t21=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t22=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t23=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t24=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t25=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t26=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t27=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t28=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t29=getRandomValue(20,98);}
            if(getRandomValue(0,6)===0){t30=getRandomValue(20,98);}if(getRandomValue(0,6)===0){t31=getRandomValue(20,98);}
        } else {
            b0=b0*0.96;b1=b1*0.96;b2=b2*0.96;b3=b3*0.96;b4=b4*0.96;b5=b5*0.96;b6=b6*0.96;b7=b7*0.96;
            b8=b8*0.96;b9=b9*0.96;b10=b10*0.96;b11=b11*0.96;b12=b12*0.96;b13=b13*0.96;b14=b14*0.96;b15=b15*0.96;
            b16=b16*0.96;b17=b17*0.96;b18=b18*0.96;b19=b19*0.96;b20=b20*0.96;b21=b21*0.96;b22=b22*0.96;b23=b23*0.96;
            b24=b24*0.96;b25=b25*0.96;b26=b26*0.96;b27=b27*0.96;b28=b28*0.96;b29=b29*0.96;b30=b30*0.96;b31=b31*0.96;
        }

        beginFrame();
        clayBeginLayout();
        drawUI();
        clayEndLayout();
        endFrame();

        if (clicked("play")) { playing = 1 - playing; }
        vol = sliderValue("vol");
        if (toggled("glow")) { checked_glow = 1 - checked_glow; }
        if (toggled("mirror")) { checked_mirror = 1 - checked_mirror; }
        if (clicked("s0")) { style = 0; }
        if (clicked("s1")) { style = 1; }
        if (clicked("s2")) { style = 2; }

        beginDrawing();
        clearBackground(color(10, 10, 18, 255));
        clayRender();
        drawBars();
        endDrawing();
    }
    closeWindow();
}

main();
