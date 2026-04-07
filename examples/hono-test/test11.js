const code = readFile("bundle_iife.js");
const result = (new Function(code + "; return HonoApp;"))();
console.log("result:", typeof result);
console.log("default:", typeof result.default);

const app = result.default;
console.log("app.fetch:", typeof app.fetch);

// Quick test: create a Request and call fetch
const req = new Request("http://localhost:3000/");
console.log("Request created:", req.url);

const response = app.fetch(req);
console.log("response:", typeof response);

response.then(r => {
  console.log("status:", r.status);
  return r.text();
}).then(t => {
  console.log("body:", t);
}).catch(e => {
  console.log("fetch error:", e.message || String(e));
});
