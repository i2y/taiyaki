const code = readFile("bundle_iife.js");
const HonoApp = (new Function(code + "; return HonoApp;"))();
const app = HonoApp.default;

// Direct fetch test
const req = new Request("http://localhost:3000/");
const response = await app.fetch(req);
const text = await response.text();
console.log("status:", response.status);
console.log("body:", text);
