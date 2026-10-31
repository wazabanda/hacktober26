// Tiny shared helpers: snapshot websocket with reconnect, JSON POST, kwacha formatting, per-iframe token key.
function tokenKey(slug, host) {
  const d = host ? 'host' : (new URLSearchParams(location.search).get('d') || 'me');
  return `ts:${slug}:${d}`;
}

// Phones freeze background tabs and drop Wi-Fi sockets without firing onclose, so: ping every 10 s (server
// answers "pong"), reconnect if nothing arrived for 25 s, and reconnect whenever the page comes back to the front.
// Every (re)connect starts with a full snapshot, so nothing is lost.
function connectState(slug, getToken, onMsg) {
  let ws, last = Date.now();
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/splits/${slug}?token=${encodeURIComponent(getToken() || '')}`);
    last = Date.now();
    ws.onmessage = (e) => { last = Date.now(); if (e.data !== 'pong') onMsg(JSON.parse(e.data)); };
    ws.onclose = () => setTimeout(() => ws.readyState === 3 && open(), 2000);
  };
  const reconnect = () => { ws.onclose = null; try { ws.close(); } catch {} open(); };
  setInterval(() => {
    if (ws.readyState === 1) ws.send('ping');
    if (Date.now() - last > 25000) reconnect();
  }, 10000);
  document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && reconnect());
  addEventListener('online', reconnect);
  addEventListener('pageshow', (e) => e.persisted && reconnect());
  open();
  return { reconnect };
}

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : r.statusText);
  return j;
}

const k = (m) => 'K' + ((m || 0) / 100).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const initials = (n) => (n || '?').trim().split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
const COLORS = ['bg-primary text-primary-content', 'bg-secondary text-secondary-content', 'bg-accent text-accent-content',
  'bg-info text-info-content', 'bg-warning text-warning-content', 'bg-error text-error-content', 'bg-neutral text-neutral-content'];
const colorFor = (id) => COLORS[id % COLORS.length];
