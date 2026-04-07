// Load hono as IIFE bundle (no module system needed)
const code = readFile("bundle_iife.js");
eval(code);

const app = HonoApp.default;
console.log("app type:", typeof app);
console.log("app.fetch type:", typeof app.fetch);

Taiyaki.serve({
  port: 3000,
  fetch: app.fetch,
});

console.log("Server running on http://localhost:3000");
