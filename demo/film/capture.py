"""Run the real TrackSplit story against a throwaway server and screenshot each state at phone size.

Server: DATABASE_URL=sqlite:////tmp/film.db DEVDRAFT_MODE=mock uvicorn app.main:app --port 8010
Chrome: google-chrome-stable --headless=new --remote-debugging-port=9333
Run:    uv run python demo/film/capture.py     -> demo/work/shots/*.png
"""

import asyncio
import json
from pathlib import Path

import httpx
import websockets

from cdp import Page

BASE = "http://localhost:8010"
OUT = Path(__file__).resolve().parents[1] / "work" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
api = httpx.Client(base_url=BASE, timeout=20)

BILL = {  # fictional restaurant, same as samples/bill-grill-vat-service.pdf
    "host_name": "Mwila", "payee": "host", "merchant": "Mwezi Grill House",
    "items": [{"name": "Nshima & chicken", "qty": 2, "line_total": "150.00"},
              {"name": "T-bone steak", "qty": 1, "line_total": "150.00"},
              {"name": "Chips", "qty": 2, "line_total": "70.00"},
              {"name": "Mosi 375ml", "qty": 3, "line_total": "75.00"},
              {"name": "Coke 500ml", "qty": 1, "line_total": "15.00"}],
    "tax": "73.60", "service": "46.00", "total": "579.60",
}


async def as_person(p: Page, slug: str, key: str, token: str, path: str, wait: float = 1.8):
    await p.goto(BASE + "/health", wait=0.2)
    await p.eval(f"localStorage.clear(); localStorage.setItem('ts:{slug}:{key}', {json.dumps(token)})")
    await p.goto(BASE + path, wait=wait)


async def scroll_to_text(p: Page, text: str, offset: int = 90):
    await p.eval(f"""(() => {{ const el = [...document.querySelectorAll('h1,h2,h3,div,span')].find(e => e.children.length === 0 && e.textContent.trim().startsWith({json.dumps(text)}));
        if (el) window.scrollTo(0, el.getBoundingClientRect().top + scrollY - {offset}); }})()""")
    await asyncio.sleep(0.6)


async def main():
    p = await Page.open()
    await p.viewport(390, 844, dpr=2, mobile=True)

    # 1. new bill: empty, then what the edit screen looks like after Gemini read the photo
    await p.goto(BASE + "/new")
    await p.shot(OUT / "01_new_empty.png")
    data = {"merchant": BILL["merchant"], "tax": BILL["tax"], "service": BILL["service"], "total": BILL["total"],
            "host_name": "Mwila", "items": BILL["items"]}
    await p.eval(f"Object.assign(Alpine.$data(document.querySelector('[x-data]')), {json.dumps(data)})")
    await asyncio.sleep(1.0)
    await p.shot(OUT / "02_new_items.png")
    await p.eval("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(0.6)
    await p.shot(OUT / "03_new_totals.png")

    # 2. create the split, host page with QR
    r = api.post("/api/splits", json=BILL).json()
    slug, host = r["slug"], r["token"]
    await as_person(p, slug, "host", host, f"/s/{slug}/host")
    await p.shot(OUT / "04_host_qr.png")

    # 3. friends join and claim, captured on every phone after each person
    people = {n: api.post(f"/api/splits/{slug}/join", json={"name": n}).json()["token"] for n in ("Alice", "Bwalya", "Chanda")}
    items = {i["name"]: i["id"] for i in api.get(f"/api/splits/{slug}/me", params={"token": host}).json() and []} or None
    state = None

    async def snap_all(tag):
        for n, tok in people.items():
            await as_person(p, slug, "me", tok, f"/s/{slug}")
            await scroll_to_text(p, "What did you have?")
            await p.shot(OUT / f"10_{n.lower()}_{tag}.png")

    # item ids from the receipt page order (same order as created)
    async with websockets.connect(f"ws://localhost:8010/ws/splits/{slug}?token={host}") as ws:
        state = json.loads(await ws.recv())["split"]
    ids = {i["name"]: i["id"] for i in state["items"]}
    claims = {
        "Alice": [("Nshima & chicken", 0), ("Chips", 0), ("Mosi 375ml", 0)],
        "Bwalya": [("Nshima & chicken", 1), ("Chips", 0), ("Mosi 375ml", 1), ("Coke 500ml", 0)],
        "Chanda": [("T-bone steak", 0), ("Chips", 1), ("Mosi 375ml", 2)],
    }
    await snap_all("s0")
    for n in ("Alice", "Bwalya", "Chanda"):
        for name, unit in claims[n]:
            api.post(f"/api/splits/{slug}/claim", json={"token": people[n], "item_id": ids[name], "unit_index": unit}).raise_for_status()
        await snap_all("s" + {"Alice": "1", "Bwalya": "2", "Chanda": "3"}[n])

    # 4. everyone confirms; checkout screens for each payment method
    urls = {n: api.post(f"/api/splits/{slug}/confirm", json={"token": t}).json()["url"] for n, t in people.items()}
    await as_person(p, slug, "me", people["Alice"], f"/s/{slug}")
    await p.shot(OUT / "20_alice_confirmed.png")

    def pay_path(n):
        return urls[n][urls[n].index("/mock-pay"):]

    await p.goto(BASE + pay_path("Alice"))
    await p.shot(OUT / "21_pay_momo_empty.png")
    await p.eval("""(() => { const i = document.querySelector('input[type=tel]'); i.value = '0961234567'; i.dispatchEvent(new Event('input')); })()""")
    await asyncio.sleep(0.4)
    await p.shot(OUT / "22_pay_momo_number.png")
    await p.eval("document.querySelector('form button').click()")
    await asyncio.sleep(0.6)
    await p.shot(OUT / "23_pay_momo_prompt.png")
    await asyncio.sleep(3.2)
    await p.shot(OUT / "24_pay_momo_done.png")

    await p.goto(BASE + pay_path("Bwalya"))
    await p.eval("""(async () => { [...document.querySelectorAll('[role=tab]')][1].click(); await new Promise(r => setTimeout(r, 200));
        const f = document.querySelectorAll('form')[1]; const [n, e, c] = f.querySelectorAll('input');
        for (const [el, v] of [[n, '4242424242424242'], [e, '1228'], [c, '123']]) { el.value = v; el.dispatchEvent(new Event('input')); } })()""")
    await asyncio.sleep(0.5)
    await p.shot(OUT / "25_pay_card.png")
    await p.eval("document.querySelectorAll('form')[1].querySelector('button').click()")
    await asyncio.sleep(2.6)

    await p.goto(BASE + pay_path("Chanda"))
    await p.eval("[...document.querySelectorAll('[role=tab]')][2].click()")
    await asyncio.sleep(0.5)
    await p.shot(OUT / "26_pay_usdc.png")
    await p.eval("[...document.querySelectorAll('button')].find(b => /sent/.test(b.innerText)).click()")
    await asyncio.sleep(2.6)

    # 5. all paid: a friend's phone and the host with the payout approval
    await as_person(p, slug, "me", people["Alice"], f"/s/{slug}", wait=3)
    await p.shot(OUT / "30_alice_paid.png")
    await as_person(p, slug, "host", host, f"/s/{slug}/host", wait=3)
    await p.shot(OUT / "31_host_payout.png")

    # 6. shop: catalogue, cart of 3 Cokes, charge QR, paid, receipt
    await p.goto(BASE + "/shop", wait=2)
    await p.shot(OUT / "40_shop.png")
    coke = next(x for x in api.get("/api/products").json()["products"] if x["name"] == "Coke 500ml")
    await p.eval(f"""(() => {{ const d = Alpine.$data(document.querySelector('[x-data]'));
        d.cart = [{{product_id: {coke['id']}, qty: 3, label: 'Coca-Cola 500ml bottle', confidence: 0.94}}]; d.open = true; }})()""")
    await asyncio.sleep(1.0)
    await p.shot(OUT / "41_shop_cart.png")
    await p.eval("[...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Charge').click()")
    await asyncio.sleep(1.5)
    await p.shot(OUT / "42_shop_qr.png")
    pay_id = max(x for x in range(1, 100) if api.get(f"/api/payments/{x}").status_code == 200)
    api.post(f"/mock-pay/{pay_id}", json={"method": "momo", "ref": "Airtel 097•••4567"}).raise_for_status()
    await asyncio.sleep(3)
    await p.shot(OUT / "43_shop_paid.png")
    rid = api.get(f"/api/payments/{pay_id}").json()["receipt_id"]
    await p.goto(BASE + f"/r/{rid}", wait=6)
    await p.shot(OUT / "44_receipt.png")
    await p.goto(BASE + "/shop", wait=2)
    await p.shot(OUT / "45_shop_after.png")
    print("slug", slug, "shots", len(list(OUT.glob("*.png"))))


asyncio.run(main())
