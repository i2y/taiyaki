try {
  const { Hono } = require('hono');
  console.log('Hono loaded:', typeof Hono);
} catch(e) {
  console.log('Error:', e.message);
  console.log('Stack:', e.stack);
}
