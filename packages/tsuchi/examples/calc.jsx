// Calculator — style composition demo
// Compile: uv run tsuchi compile examples/calc.jsx

var disp = 0;
var stored = 0;
var op = 0;
var fresh = 1;
var dotMode = 0;

function main() {
    initWindow(320, 480, "Calculator");
    clayInit(320, 480);
    claySetMeasureTextRaylib();
    let font = clayLoadFont("/System/Library/Fonts/Supplemental/Arial.ttf", 48);
    setTargetFPS(60);

    // Style composition
    let btn  = uiStyle(32, 0, 25);
    let op_s = uiStyleMerge(btn, uiStyle(0, 3, 0));
    let ac   = uiStyleMerge(btn, uiStyle(0, 4, 75));
    let eq   = uiStyleMerge(btn, uiStyle(0, 2, 25));
    let wide = uiStyleMerge(btn, uiStyle(0, 0, 50));

    while (!windowShouldClose()) {
        claySetDimensions(getScreenWidth(), getScreenHeight());
        claySetPointer(getMouseX(), getMouseY(), isMouseButtonDown(0));
        clayUpdateScroll(0, getMouseWheelMove() * 40, getFrameTime());

        beginFrame();
        clayBeginLayout();

        <VPanel padding={4} gap={4}>
            <CPanel bg={[44,44,60]} padding={12} radius={4}>
                <Box growX>
                    <Spacer />
                    <Text size={40} color={[255,255,255]}>{String(disp)}</Text>
                </Box>
            </CPanel>

            <Row gap={4}>
                <Button id="ac" style={ac}>AC</Button>
                <Button id="div" style={op_s}>/</Button>
            </Row>
            <Row gap={4}>
                <Button id="d7" style={btn}>7</Button>
                <Button id="d8" style={btn}>8</Button>
                <Button id="d9" style={btn}>9</Button>
                <Button id="mul" style={op_s}>x</Button>
            </Row>
            <Row gap={4}>
                <Button id="d4" style={btn}>4</Button>
                <Button id="d5" style={btn}>5</Button>
                <Button id="d6" style={btn}>6</Button>
                <Button id="sub" style={op_s}>-</Button>
            </Row>
            <Row gap={4}>
                <Button id="d1" style={btn}>1</Button>
                <Button id="d2" style={btn}>2</Button>
                <Button id="d3" style={btn}>3</Button>
                <Button id="add" style={op_s}>+</Button>
            </Row>
            <Row gap={4}>
                <Button id="d0" style={wide}>0</Button>
                <Button id="dot" style={btn}>.</Button>
                <Button id="eq" style={eq}>=</Button>
            </Row>
        </VPanel>

        clayEndLayout();
        endFrame();

        // Digits
        let i = 0;
        while (i < 10) {
            let ids = "d" + String(i);
            if (clicked(ids)) {
                if (fresh) { disp = i; fresh = 0; dotMode = 0; }
                else if (dotMode > 0) { disp = disp + i / dotMode; dotMode = dotMode * 10; }
                else { disp = disp * 10 + i; }
            }
            i = i + 1;
        }

        // Dot
        if (clicked("dot")) {
            if (fresh) { disp = 0; fresh = 0; dotMode = 10; }
            else if (dotMode === 0) { dotMode = 10; }
        }

        // Operators
        if (clicked("add")) { stored = disp; op = 1; fresh = 1; }
        if (clicked("sub")) { stored = disp; op = 2; fresh = 1; }
        if (clicked("mul")) { stored = disp; op = 3; fresh = 1; }
        if (clicked("div")) { stored = disp; op = 4; fresh = 1; }

        // Equals
        if (clicked("eq")) {
            if (op === 1) { disp = stored + disp; }
            if (op === 2) { disp = stored - disp; }
            if (op === 3) { disp = stored * disp; }
            if (op === 4) { if (disp !== 0) { disp = stored / disp; } }
            op = 0; fresh = 1;
        }

        // AC
        if (clicked("ac")) { disp = 0; stored = 0; op = 0; fresh = 1; dotMode = 0; }

        beginDrawing();
        clearBackground(color(24, 24, 32, 255));
        clayRender();
        endDrawing();
    }
    closeWindow();
}

main();
