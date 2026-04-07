import { Hono } from 'hono';

const app = new Hono();

app.get('/', (c) => c.text('Hello from Hono ESM!'));
app.get('/json', (c) => c.json({ message: 'Hello', runtime: 'taiyaki' }));
app.get('/user/:name', (c) => c.text(`Hello, ${c.req.param('name')}!`));

Katana.serve({ port: 3000, fetch: app.fetch });
console.log('Hono on Taiyaki → http://localhost:3000');
