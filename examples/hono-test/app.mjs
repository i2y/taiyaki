import { Hono } from 'hono';

const app = new Hono();

app.get('/', (c) => {
  return c.text('Hello from Hono on Taiyaki!');
});

app.get('/json', (c) => {
  return c.json({ message: 'Hello', runtime: 'taiyaki' });
});

app.get('/user/:name', (c) => {
  const name = c.req.param('name');
  return c.text(`Hello, ${name}!`);
});

export default app;
