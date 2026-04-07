// TUI Counter — Clay + termbox2 terminal UI demo
// Compile with: tsuchi compile examples/tui_counter.jsx --tui

function draw(count) {
  <Box grow vertical bg={[24, 24, 32]} padding={[1, 2, 1, 2]} gap={1}>
    <Box id="header" growX bg={[40, 40, 60]} padding={[0, 1, 0, 1]}>
      <Text color={[120, 180, 255]}>Counter App (TUI)</Text>
    </Box>

    <Box grow vertical padding={[1, 2, 1, 2]} gap={1}>
      <Text color={[200, 200, 200]}>Press UP/DOWN to change count, Q to quit</Text>
      <Text color={[100, 200, 255]}>{"Count: " + count}</Text>
    </Box>

    <Box id="footer" growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
      <Text color={[120, 120, 140]}>Tsuchi TUI Demo  [UP/DOWN] Count  [Q] Quit</Text>
    </Box>
  </Box>
}

function main() {
  clayTuiInit(2);

  let count = 0;
  let running = 1;

  while (running === 1) {
    const tw = clayTuiTermWidth();
    const th = clayTuiTermHeight();
    clayTuiSetDimensions(tw, th);

    const evt = clayTuiPeekEvent(50);
    if (evt === TB_EVENT_KEY) {
      const key = clayTuiEventKey();
      const ch = clayTuiEventCh();
      if (key === TB_KEY_ESC || ch === 113) {
        running = 0;
      }
      if (key === TB_KEY_ARROW_UP) {
        count = count + 1;
      }
      if (key === TB_KEY_ARROW_DOWN) {
        count = count - 1;
      }
    }

    clayTuiBeginLayout();
    draw(count);
    clayTuiEndLayout();
    clayTuiRender();
  }

  clayTuiDestroy();
}

main();
