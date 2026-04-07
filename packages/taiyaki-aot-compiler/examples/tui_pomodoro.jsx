// TUI Pomodoro Timer — Productivity timer with Clay + termbox2
// Work 25min → Short break 5min → repeat, Long break after 4 cycles
// Compile: tsuchi compile examples/tui_pomodoro.jsx --tui

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  let ms = String(m);
  let ss = String(s);
  if (m < 10) ms = "0" + ms;
  if (s < 10) ss = "0" + ss;
  return ms + ":" + ss;
}

function drawBar(pct, barW, r, g, b) {
  const filled = Math.floor(pct * barW / 100);
  let bar = "";
  let i = 0;
  while (i < barW) {
    if (i < filled) {
      bar = bar + "#";
    } else {
      bar = bar + "-";
    }
    i = i + 1;
  }
  <Box growX bg={[20, 20, 30]} padding={[0, 1, 0, 1]}>
    <Text color={[r, g, b]}>{bar}</Text>
  </Box>
}

function drawPhaseLabel(phase) {
  let label = "WORK";
  let r = 255;
  let g = 100;
  let b = 80;
  if (phase === 1) {
    label = "SHORT BREAK";
    r = 80;
    g = 220;
    b = 140;
  }
  if (phase === 2) {
    label = "LONG BREAK";
    r = 80;
    g = 160;
    b = 255;
  }
  <Box id="phase" growX bg={[35, 35, 50]} padding={[0, 2, 0, 2]}>
    <Text color={[r, g, b]}>{" >> " + label + " <<"}</Text>
  </Box>
}

function drawTimer(timeStr, phase) {
  let r = 255;
  let g = 120;
  let b = 80;
  if (phase === 1) {
    r = 80;
    g = 230;
    b = 150;
  }
  if (phase === 2) {
    r = 100;
    g = 180;
    b = 255;
  }
  <Box id="timer" growX bg={[28, 28, 40]} padding={[1, 2, 1, 2]}>
    <Text color={[r, g, b]}>{"        " + timeStr}</Text>
  </Box>
}

function drawCycles(completed, total) {
  let dots = "  Cycles: ";
  let i = 0;
  while (i < total) {
    if (i < completed) {
      dots = dots + "[*] ";
    } else {
      dots = dots + "[ ] ";
    }
    i = i + 1;
  }
  <Box growX bg={[25, 25, 36]} padding={[0, 1, 0, 1]}>
    <Text color={[180, 140, 220]}>{dots}</Text>
  </Box>
}

function drawHistory(totalWork, totalBreak) {
  <Box growX bg={[28, 28, 38]} padding={[0, 1, 0, 1]}>
    <Text color={[140, 140, 160]}>{"  Total work:  " + formatTime(totalWork)}</Text>
  </Box>
  <Box growX bg={[28, 28, 38]} padding={[0, 1, 0, 1]}>
    <Text color={[140, 140, 160]}>{"  Total break: " + formatTime(totalBreak)}</Text>
  </Box>
}

function draw(phase, remaining, paused, cycles, totalWork, totalBreak, tick) {
  const timeStr = formatTime(remaining);

  let phaseDur = 1500;
  if (phase === 1) phaseDur = 300;
  if (phase === 2) phaseDur = 900;
  const elapsed = phaseDur - remaining;
  const pct = Math.floor(elapsed * 100 / phaseDur);

  let barR = 255;
  let barG = 100;
  let barB = 80;
  if (phase === 1) {
    barR = 80;
    barG = 220;
    barB = 140;
  }
  if (phase === 2) {
    barR = 80;
    barG = 160;
    barB = 255;
  }

  const pauseLabel = paused === 1 ? "  ** PAUSED **" : "";

  <Box grow vertical bg={[18, 18, 26]} padding={[1, 2, 1, 2]} gap={1}>

    <Box id="hdr" growX bg={[40, 40, 60]} padding={[0, 1, 0, 1]}>
      <Text color={[200, 160, 100]}>Pomodoro Timer</Text>
    </Box>

    {drawPhaseLabel(phase)}

    <Box grow vertical padding={[0, 0, 0, 0]} gap={0}>
      {drawTimer(timeStr, phase)}
      {drawBar(pct, 40, barR, barG, barB)}

      <Box growX bg={[24, 24, 34]} padding={[0, 1, 0, 1]}>
        <Text color={[220, 180, 80]}>{pauseLabel}</Text>
      </Box>

      {drawCycles(cycles, 4)}

      <Box id="sep" growX bg={[30, 30, 42]} padding={[0, 1, 0, 1]}>
        <Text color={[60, 60, 80]}>--- Stats ---</Text>
      </Box>

      {drawHistory(totalWork, totalBreak)}
    </Box>

    <Box id="foot" growX bg={[30, 30, 42]} padding={[0, 1, 0, 1]}>
      <Text color={[70, 90, 130]}>[Space] Pause/Resume  [R] Reset  [S] Skip  [Q] Quit</Text>
    </Box>

  </Box>
}

function main() {
  clayTuiInit(2);

  // Phase: 0=work, 1=short break, 2=long break
  let phase = 0;
  let remaining = 1500;
  let paused = 1;
  let cycles = 0;
  let totalWork = 0;
  let totalBreak = 0;
  let running = 1;
  let tick = 0;
  let lastTime = Date.now();

  while (running === 1) {
    const tw = clayTuiTermWidth();
    const th = clayTuiTermHeight();
    clayTuiSetDimensions(tw, th);

    // Timer logic
    const now = Date.now();
    if (paused === 0 && now - lastTime >= 1000) {
      lastTime = now;
      remaining = remaining - 1;

      // Track stats
      if (phase === 0) {
        totalWork = totalWork + 1;
      } else {
        totalBreak = totalBreak + 1;
      }

      // Phase transition
      if (remaining <= 0) {
        if (phase === 0) {
          cycles = cycles + 1;
          if (cycles >= 4) {
            phase = 2;
            remaining = 900;
            cycles = 0;
          } else {
            phase = 1;
            remaining = 300;
          }
        } else {
          phase = 0;
          remaining = 1500;
        }
        paused = 1;
      }
    }

    const evt = clayTuiPeekEvent(100);
    if (evt === TB_EVENT_KEY) {
      const key = clayTuiEventKey();
      const ch = clayTuiEventCh();

      // Quit
      if (key === TB_KEY_ESC || ch === 113) {
        running = 0;
      }

      // Space = pause/resume
      if (key === TB_KEY_SPACE || ch === 32) {
        if (paused === 1) {
          paused = 0;
          lastTime = Date.now();
        } else {
          paused = 1;
        }
      }

      // R = reset current phase
      if (ch === 114) {
        if (phase === 0) {
          remaining = 1500;
        } else if (phase === 1) {
          remaining = 300;
        } else {
          remaining = 900;
        }
        paused = 1;
      }

      // S = skip to next phase
      if (ch === 115) {
        if (phase === 0) {
          cycles = cycles + 1;
          if (cycles >= 4) {
            phase = 2;
            remaining = 900;
            cycles = 0;
          } else {
            phase = 1;
            remaining = 300;
          }
        } else {
          phase = 0;
          remaining = 1500;
        }
        paused = 1;
      }
    }

    tick = tick + 1;

    clayTuiBeginLayout();
    draw(phase, remaining, paused, cycles, totalWork, totalBreak, tick);
    clayTuiEndLayout();
    clayTuiRender();
  }

  clayTuiDestroy();
}

main();
