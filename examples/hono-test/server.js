const code = readFile("bundle_iife.js");
const HonoApp = (new Function(code + "; return HonoApp;"))();
const app = HonoApp.default;

Katana.serve({
  port: 3000,
  fetch: (req) => {
    return app.fetch(req);
  },
});

console.log("Hono on Taiyaki → http://localhost:3000");
