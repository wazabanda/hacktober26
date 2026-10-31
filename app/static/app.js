// Tiny shared helpers: snapshot websocket with reconnect, JSON POST, kwacha formatting, token key.
function tokenKey(slug, host) {
  return `ts:${slug}:${host ? 'host' : 'me'}`;
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

const DISHES = [[/beer|mosi|castle|lager|cider/i, '🍺'], [/wine/i, '🍷'], [/coke|fanta|sprite|soda|juice|maheu/i, '🥤'],
  [/water/i, '💧'], [/tea|coffee/i, '☕'], [/chips|fries/i, '🍟'], [/t-?bone|steak|beef|burger/i, '🥩'],
  [/chicken|wings/i, '🍗'], [/fish|kapenta|bream/i, '🐟'], [/samoo?sa/i, '🥟'], [/roll|bread|bun/i, '🍞'],
  [/pizza/i, '🍕'], [/salad|veg/i, '🥗'], [/rice/i, '🍚'], [/cake|dessert|ice ?cream/i, '🍰']];
const dish = (name) => (DISHES.find(([re]) => re.test(name || '')) || [0, '🍽️'])[1];

const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

// Count a kwacha amount up/down to its new value (x-effect="tween($el, minor)").
function tween(el, minor) {
  const to = minor || 0, from = el._cur ?? to;
  el._anim?.stop();
  if (from === to || !window.Motion || calm()) { el._cur = to; el.textContent = k(to); return; }
  el._anim = Motion.animate(from, to, {
    duration: 0.7, ease: [0.22, 1, 0.36, 1],
    onUpdate: (v) => { el._cur = Math.round(v); el.textContent = k(el._cur); },
  });
}

// Confetti once per tab for a given moment (key), when `on` turns true.
function celebrate(key, on) {
  if (!on || !window.confetti) return;
  try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, '1'); } catch { /* storage blocked: still celebrate */ }
  const colors = ['#0b7a66', '#2bb38f', '#e8b931', '#c8642a', '#ffffff'];
  confetti({ particleCount: 90, spread: 70, startVelocity: 38, origin: { y: 0.8 }, colors, disableForReducedMotion: true });
  setTimeout(() => confetti({ particleCount: 60, spread: 110, origin: { y: 0.7 }, colors, disableForReducedMotion: true }), 250);
}
