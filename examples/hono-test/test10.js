const code = readFile("bundle_iife.js");
try {
  eval(code);
  console.log("eval OK, HonoApp:", typeof HonoApp);
} catch(e) {
  console.log("eval error:", e.message);
  console.log("stack:", e.stack);
}
