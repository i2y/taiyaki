import { Hono } from 'hono';

const app = new Hono();

app.get('/', (c) => c.text('Hello from Hono ESM!'));
app.get('/json', (c) => c.json({ ok: true }));

const req = new Request("http://localhost/");
const res = await app.fetch(req);
console.log(await res.text());
