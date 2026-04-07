try {
  const mod = await import('./bundle.js');
  console.log('loaded:', typeof mod.default);
  const app = mod.default;
  console.log('app.fetch:', typeof app.fetch);
} catch(e) {
  console.log('Error:', e.message);
  console.log('Stack:', e.stack);
}
