// Inline a minimal part of hono to test what breaks
console.log("step 1: basic eval works");

// Test: does the bundle eval work at all?
const code = readFile("bundle.js");
console.log("step 2: bundle read, length:", code.length);
