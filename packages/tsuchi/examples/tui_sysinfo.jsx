// TUI System Info Dashboard — exec() + httpGet() demo
// Compile with: tsuchi compile examples/tui_sysinfo.jsx --tui

function getHostname() {
  return exec("hostname").trim();
}

function getUptime() {
  const raw = exec("uptime");
  const idx = raw.indexOf("up ");
  if (idx >= 0) {
    const rest = raw.slice(idx + 3);
    const comma = rest.indexOf(",");
    if (comma >= 0) {
      return rest.slice(0, comma).trim();
    }
    return rest.trim();
  }
  return raw.trim();
}

function getDiskUsage() {
  const line = exec("df -h / | tail -1");
  const parts = line.trim().split(" ");
  let nums = [];
  for (let i = 0; i < parts.length; i = i + 1) {
    if (parts[i].length > 0) {
      nums.push(parts[i]);
    }
  }
  return nums[4] + " used of " + nums[1];
}

function getMemInfo() {
  return exec("vm_stat | head -5 | tail -4").trim();
}

function getCpuModel() {
  return exec("sysctl -n machdep.cpu.brand_string").trim();
}

function getProcessCount() {
  return exec("ps aux | wc -l").trim();
}

function getPublicIP() {
  const body = httpGet("https://api.ipify.org");
  if (body.length > 0) {
    return body.trim();
  }
  return "(unavailable)";
}

function draw(hostname, uptime, disk, cpu, procs, ip, tick) {
  const blink = tick % 2 === 0;

  <Box grow vertical bg={[20, 20, 30]} padding={[1, 2, 1, 2]} gap={1}>
    <Box id="header" growX bg={[40, 50, 80]} padding={[0, 1, 0, 1]}>
      <Text color={[100, 200, 255]}>System Dashboard</Text>
    </Box>

    <Box grow vertical gap={1}>
      <Box growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
        <Text color={[180, 180, 200]}>{"  Host: " + hostname}</Text>
      </Box>
      <Box growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
        <Text color={[180, 180, 200]}>{"  CPU:  " + cpu}</Text>
      </Box>
      <Box growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
        <Text color={[120, 220, 120]}>{"  Up:   " + uptime}</Text>
      </Box>
      <Box growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
        <Text color={[220, 180, 100]}>{"  Disk: " + disk}</Text>
      </Box>
      <Box growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
        <Text color={[180, 140, 220]}>{"  Proc: " + procs + " processes"}</Text>
      </Box>
      <Box growX bg={[30, 30, 45]} padding={[0, 1, 0, 1]}>
        <Text color={[100, 200, 200]}>{"  IP:   " + ip}</Text>
      </Box>
    </Box>

    <Box id="footer" growX bg={[30, 30, 40]} padding={[0, 1, 0, 1]}>
      <Text color={[80, 80, 100]}>Press [R] to refresh  [Q] to quit</Text>
    </Box>
  </Box>
}

function main() {
  clayTuiInit(2);

  let hostname = getHostname();
  let uptime = getUptime();
  let disk = getDiskUsage();
  let cpu = getCpuModel();
  let procs = getProcessCount();
  let ip = getPublicIP();
  let running = 1;
  let tick = 0;

  while (running === 1) {
    const tw = clayTuiTermWidth();
    const th = clayTuiTermHeight();
    clayTuiSetDimensions(tw, th);

    const evt = clayTuiPeekEvent(500);
    if (evt === TB_EVENT_KEY) {
      const key = clayTuiEventKey();
      const ch = clayTuiEventCh();
      if (key === TB_KEY_ESC || ch === 113) {
        running = 0;
      }
      if (ch === 114) {
        hostname = getHostname();
        uptime = getUptime();
        disk = getDiskUsage();
        cpu = getCpuModel();
        procs = getProcessCount();
        ip = getPublicIP();
      }
    }

    tick = tick + 1;

    clayTuiBeginLayout();
    draw(hostname, uptime, disk, cpu, procs, ip, tick);
    clayTuiEndLayout();
    clayTuiRender();
  }

  clayTuiDestroy();
}

main();
