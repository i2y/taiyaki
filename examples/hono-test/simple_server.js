Taiyaki.serve({
  port: 3000,
  fetch: (req) => {
    return new Response("Hello from simple server!");
  },
});

console.log("Simple server on http://localhost:3000");
