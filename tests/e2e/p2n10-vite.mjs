import { createServer } from 'vite';
import http from 'node:http';
import net from 'node:net';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
const root = process.env.P2N10_REPO + '/src/frontend';
const output = process.env.P2N10_ARTIFACTS;
const allowed = 'http://127.0.0.1:15580';
const denied = [];
// Chromium is forced through this loopback proxy, including loopback URLs.
// Reject before DNS; never forward a non-test destination, HTTPS tunnel, or WS.
const proxy = http.createServer((req, res) => {
  const url = new URL(req.url ?? '/', allowed);
  if (url.origin !== allowed) { denied.push(url.origin); res.writeHead(403).end(); return; }
  const upstream = http.request({ hostname: '127.0.0.1', port: 15580, path: url.pathname + url.search, method: req.method, headers: req.headers }, (r) => { res.writeHead(r.statusCode ?? 502, r.headers); r.pipe(res); });
  upstream.on('error', () => res.writeHead(502).end());
  req.pipe(upstream);
});
proxy.on('connect', (req, socket, head) => {
  // APIRequestContext uses CONNECT even for HTTP. Only this precise loopback
  // frontend authority is allowed, never any foreign target, DNS or public tunnel.
  if (req.url !== '127.0.0.1:15580') { denied.push('CONNECT-foreign-denied-before-connect'); socket.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return; }
  const upstream = net.connect(15580, '127.0.0.1', () => { socket.write('HTTP/1.1 200 Connection Established\r\n\r\n'); if (head.length) upstream.write(head); socket.pipe(upstream); upstream.pipe(socket); });
  upstream.on('error', () => socket.destroy()); socket.on('error', () => upstream.destroy());
});
await new Promise((done) => proxy.listen(15582, '127.0.0.1', done));
const server = await createServer({ root, configFile: root + '/vite.config.ts', configLoader: 'runner', cacheDir: join(output, 'vite-cache'), server: { host: '127.0.0.1', port: 15580, strictPort: true, hmr: false } });
await server.listen();
console.log('P2N10 own frontend and deny-forward proxy ready');
process.on('SIGTERM', async () => { writeFileSync(join(output, 'browser-proxy-denials.json'), JSON.stringify(denied)); await server.close(); proxy.close(() => process.exit(0)); });
