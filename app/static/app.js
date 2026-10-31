// Tiny shared helpers: snapshot websocket with reconnect, JSON POST, kwacha formatting, per-iframe token key.
function tokenKey(slug, host) {
  const d = host ? 'host' : (new URLSearchParams(location.search).get('d') || 'me');
  return `ts:${slug}:${d}`;
}

function connectState(slug, getToken, onMsg) {
  let ws, ping;
  const open = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/splits/${slug}?token=${encodeURIComponent(getToken() || '')}`);
    ws.onmessage = (e) => onMsg(JSON.parse(e.data));
    ws.onopen = () => { ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000); };
    ws.onclose = () => { clearInterval(ping); setTimeout(open, 2000); };
  };
  open();
  return { reconnect() { ws.onclose = null; clearInterval(ping); ws.close(); open(); } };
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
