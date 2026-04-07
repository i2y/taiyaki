try {
  const m = require('./node_modules/hono/dist/cjs/index.js');
  console.log('loaded:', typeof m, Object.keys(m));
} catch(e) {
  console.log('Error loading hono CJS:', String(e));
}
