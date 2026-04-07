// Test bare module resolution
try {
  import('./node_modules/hono/dist/hono.js').then(m => {
    console.log('Hono loaded via dynamic import:', typeof m.Hono);
  }).catch(e => {
    console.log('Dynamic import error:', e.message || String(e));
  });
} catch(e) {
  console.log('Error:', e.message || String(e));
}
