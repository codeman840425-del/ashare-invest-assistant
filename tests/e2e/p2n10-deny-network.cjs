// Descendant Node processes may connect only to the three private test ports.
const net = require('node:net');
const dns = require('node:dns');
const ports = new Set([15580, 18580, 15582]);
const hosts = new Set(['127.0.0.1', '::1', 'localhost']);
const original = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
  const a = Array.isArray(args[0]) ? args[0][0] : args[0];
  if (typeof a === 'string' && a.startsWith('/')) return original.apply(this, args);
  let host = 'localhost', port;
  if (typeof a === 'object') { if (a.path) return original.apply(this, args); host = a.host ?? 'localhost'; port = Number(a.port); }
  else { port = Number(a); if (typeof args[1] === 'string') host = args[1]; }
  if (!hosts.has(host) || !ports.has(port)) throw new Error('P2N10 non-local or foreign-port connection denied');
  return original.apply(this, args);
};
const lookup = dns.lookup;
dns.lookup = function(host, ...args) { if (!hosts.has(host)) throw new Error('P2N10 external DNS denied'); return lookup.call(this, host, ...args); };
