const code = readFile("bundle_iife.js");
const HonoApp = (new Function(code + "; return HonoApp;"))();
const app = HonoApp.default;

async function testRoute(path) {
  const req = new Request("http://localhost:3000" + path);
  const res = await app.fetch(req);
  const body = await res.text();
  console.log(`GET ${path} → ${res.status} ${body}`);
}

await testRoute("/");
await testRoute("/json");
await testRoute("/user/taiyaki");
await testRoute("/not-found");
