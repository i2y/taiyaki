const resp = await fetch('https://httpbin.org/get');
console.log('status:', resp.status);
console.log('ok:', resp.ok);
const data = await resp.json();
console.log('url:', data.url);
