// TUI File Manager — Terminal file browser with Clay + termbox2
// Navigate directories, view file info
// Compile: tsuchi compile examples/tui_filemanager.jsx --tui

function getFileList(dir) {
  const raw = exec("ls -1ap " + dir + " 2>/dev/null");
  if (raw.length === 0) return [];
  return raw.trim().split("\n");
}

function getPreview(path) {
  const info = exec("file -b '" + path + "' 2>/dev/null").trim();
  if (info.indexOf("directory") >= 0) {
    const ls = exec("ls -1 '" + path + "' 2>/dev/null | head -15");
    if (ls.length === 0) return "(empty directory)";
    return ls.trim();
  }
  if (info.indexOf("text") >= 0 || info.indexOf("JSON") >= 0 || info.indexOf("script") >= 0) {
    return exec("head -15 '" + path + "' 2>/dev/null").trimEnd();
  }
  return "[" + info + "]";
}

function drawEntry(name, selected) {
  let bgR = 24;
  let bgG = 24;
  let bgB = 32;
  if (selected === 1) {
    bgR = 40;
    bgG = 65;
    bgB = 120;
  }

  let cr = 180;
  let cg = 180;
  let cb = 200;
  let prefix = "  ";

  if (name.endsWith("/")) {
    cr = 80;
    cg = 180;
    cb = 255;
    prefix = "> ";
  } else if (name.endsWith(".js") || name.endsWith(".ts") || name.endsWith(".jsx") || name.endsWith(".tsx")) {
    cr = 255;
    cg = 210;
    cb = 80;
    prefix = "# ";
  } else if (name.endsWith(".py") || name.endsWith(".rs") || name.endsWith(".go") || name.endsWith(".c")) {
    cr = 120;
    cg = 220;
    cb = 160;
    prefix = "# ";
  } else if (name.endsWith(".md") || name.endsWith(".txt")) {
    cr = 160;
    cg = 160;
    cb = 180;
    prefix = "= ";
  } else if (name.startsWith(".")) {
    cr = 90;
    cg = 90;
    cb = 110;
  }

  <Box growX bg={[bgR, bgG, bgB]} padding={[0, 1, 0, 1]}>
    <Text color={[cr, cg, cb]}>{prefix + name}</Text>
  </Box>
}

function main() {
  clayTuiInit(2);

  let cwd = exec("pwd").trim();
  let files = getFileList(cwd);
  let sel = 0;
  let preview = "";
  let selName = "";
  let dirty = 1;
  let running = 1;

  while (running === 1) {
    const tw = clayTuiTermWidth();
    const th = clayTuiTermHeight();
    clayTuiSetDimensions(tw, th);

    // Refresh preview when selection changes
    if (dirty === 1 && files.length > 0) {
      selName = files[sel];
      preview = getPreview(cwd + "/" + selName);
      dirty = 0;
    }

    const evt = clayTuiPeekEvent(50);
    if (evt === TB_EVENT_KEY) {
      const key = clayTuiEventKey();
      const ch = clayTuiEventCh();

      if (key === TB_KEY_ESC || ch === 113) {
        running = 0;
      }
      if (key === TB_KEY_ARROW_UP && sel > 0) {
        sel = sel - 1;
        dirty = 1;
      }
      if (key === TB_KEY_ARROW_DOWN && sel < files.length - 1) {
        sel = sel + 1;
        dirty = 1;
      }
      if (key === TB_KEY_PGUP) {
        sel = sel - 10;
        if (sel < 0) sel = 0;
        dirty = 1;
      }
      if (key === TB_KEY_PGDN) {
        sel = sel + 10;
        if (sel >= files.length) sel = files.length - 1;
        dirty = 1;
      }
      if (key === TB_KEY_HOME) {
        sel = 0;
        dirty = 1;
      }
      if (key === TB_KEY_END) {
        sel = files.length - 1;
        dirty = 1;
      }

      // Enter directory
      if (key === TB_KEY_ENTER && files.length > 0) {
        if (selName.endsWith("/")) {
          cwd = exec("cd '" + cwd + "/" + selName + "' && pwd").trim();
          files = getFileList(cwd);
          sel = 0;
          dirty = 1;
        }
      }

      // Backspace = parent dir
      if (key === TB_KEY_BACKSPACE) {
        cwd = exec("cd '" + cwd + "/..' && pwd").trim();
        files = getFileList(cwd);
        sel = 0;
        dirty = 1;
      }
    }

    if (evt === TB_EVENT_RESIZE) {
      dirty = 1;
    }

    // --- Render ---
    clayTuiBeginLayout();

    <Box grow vertical bg={[20, 20, 28]} gap={0}>

      <Box id="header" growX bg={[35, 50, 80]} padding={[0, 1, 0, 1]}>
        <Text color={[80, 180, 255]}>File Manager</Text>
      </Box>
      <Box id="pathbar" growX bg={[28, 28, 40]} padding={[0, 1, 0, 1]}>
        <Text color={[180, 180, 210]}>{" " + cwd}</Text>
      </Box>

      <Box grow gap={0}>
        <Box w={-40} vertical bg={[24, 24, 32]} gap={0}>
          {drawList(files, sel)}
        </Box>

        <Box w={-60} vertical bg={[26, 26, 36]} padding={[0, 1, 0, 1]} gap={0}>
          <Box id="pv-name" growX bg={[36, 36, 50]} padding={[0, 1, 0, 1]}>
            <Text color={[140, 170, 220]}>{selName}</Text>
          </Box>
          <Box grow vertical bg={[22, 22, 32]} padding={[0, 1, 0, 1]}>
            <Text color={[150, 150, 170]}>{preview}</Text>
          </Box>
        </Box>
      </Box>

      <Box id="status" growX bg={[30, 35, 50]} padding={[0, 1, 0, 1]}>
        <Text color={[70, 100, 150]}>{"  " + String(sel + 1) + "/" + String(files.length) + "  |  Up/Down  Enter  Backspace  Q"}</Text>
      </Box>

    </Box>

    clayTuiEndLayout();
    clayTuiRender();
  }

  clayTuiDestroy();
}

function drawList(files, sel) {
  let i = 0;
  while (i < files.length) {
    let s = 0;
    if (i === sel) s = 1;
    drawEntry(files[i], s);
    i = i + 1;
  }
}

main();
