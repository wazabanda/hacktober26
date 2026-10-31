import asyncio
import io
import logging
import os
import secrets
import string
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import qrcode
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, select

from . import devdraft, hub, llm, pdf
from .db import (Business, Claim, Participant, Payment, Payout, Product, Receipt, ReceiptItem, Split, engine,
                 get_session, init_db)
from .schemas import CounterExtract, ReceiptExtract
from .icons import icon
from .shop import OutOfStock, match, price_cart
from .split import kwacha, to_minor, to_usdc

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tracksplit")
HERE = Path(__file__).parent
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_BYTES = 8 * 1024 * 1024


async def poll_links():
    """Fallback for missed webhooks: check pending live links every 5 s."""
    while True:
        await asyncio.sleep(5)
        if devdraft.mode() != "live":
            continue
        with Session(engine) as s:
            pending = [(p.id, p.devdraft_link_id) for p in s.exec(select(Payment).where(Payment.status == "pending")).all()
                       if p.devdraft_link_id and not p.devdraft_link_id.startswith("mock_")]
        for pid, link_id in pending:
            try:
                if devdraft.looks_paid(await asyncio.to_thread(devdraft.get_link, link_id)):
                    await devdraft.mark_paid(pid)
            except Exception as e:
                log.warning("poll %s failed: %s", link_id, e)


@asynccontextmanager
async def lifespan(_app):
    init_db()
    from seed import seed
    seed()
    task = asyncio.create_task(poll_links())
    yield
    task.cancel()


app = FastAPI(title="TrackSplit", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["k"] = kwacha
templates.env.globals["icon"] = icon


def page(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"mode": devdraft.mode(), **ctx})


def new_slug() -> str:
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def get_split(s: Session, slug: str) -> Split:
    split = s.exec(select(Split).where(Split.slug == slug)).first()
    if not split:
        raise HTTPException(404, "No such split")
    return split


def get_person(s: Session, split: Split, token: str) -> Participant:
    p = s.exec(select(Participant).where(Participant.token == token, Participant.split_id == split.id)).first()
    if not p:
        raise HTTPException(403, "Unknown participant; join first")
    return p


async def read_image(file: UploadFile) -> tuple[bytes, str]:
    if file.content_type not in IMAGE_TYPES:
        raise HTTPException(415, "Send a JPEG, PNG or WebP photo")
    data = await file.read()
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, "Photo is empty or larger than 8 MB")
    return data, file.content_type


# ---------------- pages ----------------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index(request: Request):
    return page(request, "index.html")


@app.get("/new")
def new(request: Request):
    return page(request, "new.html")


@app.get("/s/{slug}")
def split_page(request: Request, slug: str, s: Session = Depends(get_session)):
    get_split(s, slug)
    return page(request, "split.html", slug=slug, host=False)


@app.get("/s/{slug}/host")
def host_page(request: Request, slug: str, s: Session = Depends(get_session)):
    get_split(s, slug)
    return page(request, "split.html", slug=slug, host=True, share_url=f"{base_url(request)}/s/{slug}")


def base_url(request: Request) -> str:
    return os.getenv("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")


@app.get("/qr.png")
def qr_png(data: str):
    buf = io.BytesIO()
    qrcode.make(data, border=2).save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.get("/s/{slug}/qr.png")
def split_qr(request: Request, slug: str):
    return qr_png(f"{base_url(request)}/s/{slug}")


@app.get("/demo")
def demo(request: Request, slug: str | None = None, s: Session = Depends(get_session)):
    host_token = None
    if not slug:  # fresh sample bill so judges can play right away
        biz = s.exec(select(Business)).first()
        prods = {p.name: p for p in s.exec(select(Product)).all()}
        picks = [("Nshima & chicken", 2), ("T-bone", 1), ("Chips", 2), ("Mosi 375ml", 3), ("Coke 500ml", 1)]
        items = [(n, q, prods[n].price_minor * q, prods[n].id) for n, q in picks]
        sub = sum(i[2] for i in items)
        split, host_token = create_split(s, "Host", "host", biz.name, items, round(sub * 0.16), round(sub * 0.10),
                                         sub + round(sub * 0.16) + round(sub * 0.10), business_id=biz.id)
        slug = split.slug
    return page(request, "demo.html", slug=slug, host_token=host_token)


@app.get("/r/{receipt_id}")
def receipt_page(request: Request, receipt_id: int, s: Session = Depends(get_session)):
    r = s.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404)
    items = s.exec(select(ReceiptItem).where(ReceiptItem.receipt_id == r.id)).all()
    pays = s.exec(select(Payment).where(Payment.receipt_id == r.id, Payment.status != "void")).all()
    names = {p.id: p.name for p in s.exec(select(Participant).where(
        Participant.id.in_([p.participant_id for p in pays if p.participant_id]))).all()}
    stock = {p.id: p for p in s.exec(select(Product)).all()} if r.source == "counter" else {}
    return page(request, "receipt.html", r=r, items=items, pays=pays, names=names, stock=stock,
                url=f"{base_url(request)}/r/{r.id}")


@app.get("/r/{receipt_id}/receipt.pdf")
def receipt_pdf(request: Request, receipt_id: int, s: Session = Depends(get_session)):
    r = s.get(Receipt, receipt_id)
    if not r:
        raise HTTPException(404)
    items = s.exec(select(ReceiptItem).where(ReceiptItem.receipt_id == r.id)).all()
    pays = s.exec(select(Payment).where(Payment.receipt_id == r.id, Payment.status != "void")).all()
    names = {p.id: p.name for p in s.exec(select(Participant).where(
        Participant.id.in_([p.participant_id for p in pays if p.participant_id]))).all()}
    data = pdf.receipt_pdf(r, items, pays, names, f"{base_url(request)}/r/{r.id}")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="tracksplit-receipt-{r.id}.pdf"'})


@app.get("/mock-pay/{payment_id}")
def mock_pay_page(request: Request, payment_id: int, back: str = "", s: Session = Depends(get_session)):
    pay = s.get(Payment, payment_id)
    if not pay:
        raise HTTPException(404)
    return page(request, "mock_pay.html", pay=pay, back=back)


@app.post("/mock-pay/{payment_id}")
async def mock_pay(payment_id: int, back: str = ""):
    if devdraft.mode() != "mock":
        raise HTTPException(403, "mock payments are off")
    await devdraft.mark_paid(payment_id)
    return RedirectResponse(back if back.startswith("/") else f"/mock-pay/{payment_id}", status_code=303)


@app.get("/shop")
def shop(request: Request, s: Session = Depends(get_session)):
    biz = s.exec(select(Business)).first()
    try:
        wallets = devdraft.list_wallets()
    except Exception as e:
        log.warning("wallets: %s", e)
        wallets = []
    return page(request, "shop.html", biz=biz, wallets=wallets)


# ---------------- extraction ----------------
@app.post("/api/extract/receipt", response_model=ReceiptExtract)
async def extract_receipt(file: UploadFile):
    data, mime = await read_image(file)
    try:
        return await llm.read_receipt(data, mime)
    except Exception as e:
        log.exception("receipt extraction failed")
        raise HTTPException(422, f"Couldn't read the bill ({type(e).__name__}). Retake the photo or enter it by hand.")


@app.post("/api/extract/counter")
async def extract_counter(file: UploadFile, s: Session = Depends(get_session)):
    data, mime = await read_image(file)
    try:
        seen: CounterExtract = await llm.read_counter(data, mime)
    except Exception as e:
        log.exception("counter extraction failed")
        raise HTTPException(422, f"Couldn't read the photo ({type(e).__name__}). Try again or add items by hand.")
    products = s.exec(select(Product)).all()
    out = []
    for it in seen.items:
        p = match(it.label, products)
        out.append({"label": it.label, "qty": it.qty, "confidence": it.confidence,
                    "product_id": p.id if p else None, "name": p.name if p else None})
    return {"lines": out}


# ---------------- splits ----------------
def create_split(s: Session, host_name, payee, merchant, items, tax, service, total, tip=0, business_id=None,
                 source="photo"):
    """items: [(name, qty, line_total_minor, product_id|None)]"""
    r = Receipt(business_id=business_id, source=source, merchant=merchant, subtotal_minor=sum(i[2] for i in items),
                tax_minor=tax, service_minor=service, tip_minor=tip, total_minor=total)
    s.add(r)
    s.flush()
    for name, qty, line, pid in items:
        s.add(ReceiptItem(receipt_id=r.id, name=name, qty=qty, unit_price_minor=line // qty, line_total_minor=line,
                          product_id=pid))
    split = Split(slug=new_slug(), receipt_id=r.id, host_name=host_name, payee=payee)
    s.add(split)
    s.flush()
    token = secrets.token_urlsafe(16)
    s.add(Participant(split_id=split.id, name=host_name, token=token, is_host=True))
    s.commit()
    return split, token


class ItemIn(BaseModel):
    name: str
    qty: int = 1
    line_total: Decimal


class SplitIn(BaseModel):
    host_name: str
    payee: str = "host"
    merchant: str | None = None
    items: list[ItemIn]
    tax: Decimal = Decimal(0)
    tax_included: bool = False
    service: Decimal = Decimal(0)
    tip: Decimal = Decimal(0)
    total: Decimal


@app.post("/api/splits")
def post_split(body: SplitIn, s: Session = Depends(get_session)):
    items = [(i.name.strip()[:80], max(1, i.qty), to_minor(i.line_total), None) for i in body.items if i.name.strip()]
    if not items:
        raise HTTPException(400, "Add at least one item")
    tip = to_minor(body.tip)
    split, token = create_split(s, body.host_name.strip()[:40] or "Host", "business" if body.payee == "business" else "host",
                                body.merchant, items, to_minor(body.tax), to_minor(body.service),
                                to_minor(body.total) + tip, tip=tip)
    return {"slug": split.slug, "token": token, "participant_id": None}


class JoinIn(BaseModel):
    name: str


class TokenIn(BaseModel):
    token: str


class ClaimIn(TokenIn):
    item_id: int
    unit_index: int


class LeftoverIn(TokenIn):
    mode: str = "host"


@app.post("/api/splits/{slug}/join")
async def join(slug: str, body: JoinIn, s: Session = Depends(get_session)):
    split = get_split(s, slug)
    p = Participant(split_id=split.id, name=body.name.strip()[:40] or "Friend", token=secrets.token_urlsafe(16))
    s.add(p)
    s.commit()
    await hub.broadcast_state(slug)
    return {"participant_id": p.id, "token": p.token}


@app.get("/api/splits/{slug}/me")
def me(slug: str, token: str, s: Session = Depends(get_session)):
    p = get_person(s, get_split(s, slug), token)
    return {"participant_id": p.id, "name": p.name, "is_host": p.is_host}


@app.post("/api/splits/{slug}/claim")
async def claim(slug: str, body: ClaimIn, s: Session = Depends(get_session)):
    split = get_split(s, slug)
    me_ = get_person(s, split, body.token)
    if me_.confirmed:
        raise HTTPException(409, "You've confirmed; unconfirm to change your items")
    item = s.get(ReceiptItem, body.item_id)
    if not item or item.receipt_id != split.receipt_id or not 0 <= body.unit_index < item.qty:
        raise HTTPException(400, "No such item")
    others = s.exec(select(Claim, Participant).join(Participant).where(
        Claim.item_id == item.id, Claim.unit_index == body.unit_index)).all()
    mine = next((c for c, p in others if p.id == me_.id), None)
    if mine:
        s.delete(mine)
    else:
        if any(p.confirmed for _, p in others):
            raise HTTPException(409, "Someone who shares this already confirmed their share")
        s.add(Claim(participant_id=me_.id, item_id=item.id, unit_index=body.unit_index))
    s.commit()
    await hub.broadcast_state(slug)
    return {"ok": True}


@app.post("/api/splits/{slug}/confirm")
async def confirm(slug: str, body: TokenIn, s: Session = Depends(get_session)):
    split = get_split(s, slug)
    p = get_person(s, split, body.token)
    if p.confirmed:
        return {"ok": True}
    receipt, items, people, claims, sh, payments = hub.compute(s, split)
    share = sh.get(p.id, 0)
    if share <= 0:
        raise HTTPException(400, "Tap the items you had first")
    p.confirmed, p.share_minor = True, share
    if split.status == "open":
        split.status = "settling"
    s.add_all([p, split])
    url = None
    if not (p.is_host and split.payee == "host"):
        mine = [i.name for i in items if any(c.item_id == i.id and c.participant_id == p.id for c in claims)]
        pay = Payment(split_id=split.id, participant_id=p.id, receipt_id=receipt.id, amount_minor=share,
                      amount_usdc=str(to_usdc(share)))
        s.add(pay)
        s.flush()
        try:
            pay.devdraft_link_id, pay.url = devdraft.create_payment_link(
                s, pay, f"TrackSplit: {p.name} @ {receipt.merchant or 'the table'}",
                f"Your share {kwacha(share)}: " + ", ".join(mine), slug)
        except Exception as e:
            s.rollback()
            log.warning("payment link failed: %s", e)
            raise HTTPException(502, f"Payment link failed: {e}")
        s.add(pay)
        url = pay.url
    s.commit()
    await hub.broadcast_state(slug)
    if url:
        await hub.send_to(slug, p.id, {"type": "pay_link", "participant_id": p.id, "url": url})
    if not url:  # host-payee host confirming last can finish the split
        with Session(engine) as s2:
            devdraft.finish_if_done(s2, get_split(s2, slug))
        await hub.broadcast_state(slug)
    return {"ok": True, "url": url}


@app.post("/api/splits/{slug}/unconfirm")
async def unconfirm(slug: str, body: TokenIn, s: Session = Depends(get_session)):
    split = get_split(s, slug)
    p = get_person(s, split, body.token)
    pay = s.exec(select(Payment).where(Payment.participant_id == p.id, Payment.status.in_(["pending", "paid"]))).first()
    if pay and pay.status == "paid":
        raise HTTPException(409, "Already paid")
    if pay:
        pay.status = "void"  # ponytail: link stays live on DevDraft (maxPayments=1); deactivate if they add an endpoint
        s.add(pay)
    p.confirmed, p.share_minor = False, None
    s.add(p)
    s.commit()
    await hub.broadcast_state(slug)
    return {"ok": True}


@app.post("/api/splits/{slug}/assign-leftovers")
async def assign_leftovers(slug: str, body: LeftoverIn, s: Session = Depends(get_session)):
    split = get_split(s, slug)
    host = get_person(s, split, body.token)
    if not host.is_host:
        raise HTTPException(403, "Only the host can assign leftovers")
    _, items, people, claims, *_ = hub.compute(s, split)
    taken = {(c.item_id, c.unit_index) for c in claims}
    takers = [host] if body.mode == "host" else [p for p in people if not p.confirmed]
    if not takers or any(t.confirmed for t in takers):
        raise HTTPException(409, "Unconfirm first, or nobody unconfirmed is left to share with")
    for i in items:
        for u in range(i.qty):
            if (i.id, u) not in taken:
                s.add_all(Claim(participant_id=t.id, item_id=i.id, unit_index=u) for t in takers)
    s.commit()
    await hub.broadcast_state(slug)
    return {"ok": True}


class PayoutIn(TokenIn):
    approve: bool


@app.post("/api/splits/{slug}/payout")
async def decide_payout(slug: str, body: PayoutIn, s: Session = Depends(get_session)):
    split = get_split(s, slug)
    if not get_person(s, split, body.token).is_host:
        raise HTTPException(403, "Only the host approves the payout")
    po = s.exec(select(Payout).where(Payout.split_id == split.id, Payout.status == "proposed")).first()
    if not po:
        raise HTTPException(404, "No payout waiting")
    po.status = "approved" if body.approve else "declined"
    # ponytail: no confirmed DevDraft transfer endpoint yet; approval is recorded in the ledger only
    log.warning("payout %s for split %s: %s", po.id, slug, po.status)
    s.add(po)
    s.commit()
    await hub.broadcast_state(slug)
    return {"ok": True, "status": po.status}


@app.websocket("/ws/splits/{slug}")
async def ws_split(ws: WebSocket, slug: str, token: str = ""):
    await ws.accept()
    with Session(engine) as s:
        split = s.exec(select(Split).where(Split.slug == slug)).first()
        if not split:
            await ws.close(code=4404)
            return
        p = s.exec(select(Participant).where(Participant.token == token, Participant.split_id == split.id)).first()
        hub.join(slug, ws, p.id if p else None)
        await ws.send_json({"type": "state", "split": hub.build_state(s, split, p.id if p else None).model_dump(mode="json")})
    try:
        while True:
            await ws.receive_text()  # client pings only
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(slug, ws)


# ---------------- payments ----------------
@app.post("/webhooks/devdraft")
async def devdraft_webhook(request: Request):
    raw = await request.body()
    log.warning("devdraft webhook headers=%s body=%s", {k: v for k, v in request.headers.items() if "sig" in k}, raw[:2000])
    if not devdraft.verify_signature(raw, request.headers.get("x-webhook-signature")):
        raise HTTPException(401, "bad signature")
    payload = await request.json()
    with Session(engine) as s:
        pid = devdraft.find_payment_id(s, payload)
        if pid and devdraft.event_failed(payload):
            pay = s.get(Payment, pid)
            if pay and pay.status == "pending":
                pay.status = "failed"
                s.add(pay)
                s.commit()
            return {"ok": True}
    if pid:
        await devdraft.mark_paid(pid)
    return {"ok": True, "payment_id": pid}


@app.get("/api/payments/{payment_id}")
def payment_status(payment_id: int, s: Session = Depends(get_session)):
    pay = s.get(Payment, payment_id)
    if not pay:
        raise HTTPException(404)
    return {"status": pay.status, "receipt_id": pay.receipt_id, "url": pay.url}


# ---------------- shop ----------------
@app.get("/api/products")
def products(s: Session = Depends(get_session)):
    biz = s.exec(select(Business)).first()
    return {"threshold": biz.low_stock_threshold, "products": [p.model_dump() for p in s.exec(select(Product).order_by(Product.name)).all()]}


class LineIn(BaseModel):
    product_id: int
    qty: int


class CartIn(BaseModel):
    lines: list[LineIn]
    host_name: str = "Counter"


def cart_receipt_items(s: Session, body: CartIn):
    pairs = [(s.get(Product, line.product_id), line.qty) for line in body.lines]
    cart = price_cart([(p, q) for p, q in pairs if p])
    if not cart.lines:
        raise HTTPException(400, "Cart is empty")
    for line in cart.lines:
        if line.qty > line.stock_qty:
            raise HTTPException(409, f"{line.name}: only {line.stock_qty} in stock")
    return cart


@app.post("/api/shop/charge")
async def shop_charge(body: CartIn, s: Session = Depends(get_session)):
    cart = cart_receipt_items(s, body)
    biz = s.exec(select(Business)).first()
    r = Receipt(business_id=biz.id, source="counter", merchant=biz.name, subtotal_minor=cart.total_minor,
                total_minor=cart.total_minor)
    s.add(r)
    s.flush()
    s.add_all(ReceiptItem(receipt_id=r.id, name=line.name, qty=line.qty, unit_price_minor=line.unit_price_minor,
                          line_total_minor=line.line_total_minor, product_id=line.product_id) for line in cart.lines)
    pay = Payment(receipt_id=r.id, amount_minor=cart.total_minor, amount_usdc=str(to_usdc(cart.total_minor)))
    s.add(pay)
    s.flush()
    try:
        pay.devdraft_link_id, pay.url = devdraft.create_payment_link(
            s, pay, f"{biz.name} sale #{r.id}", ", ".join(f"{line.qty}x {line.name}" for line in cart.lines), "shop")
    except Exception as e:
        s.rollback()
        raise HTTPException(502, f"Payment link failed: {e}")
    s.add(pay)
    s.commit()
    return {"payment_id": pay.id, "url": pay.url, "receipt_id": r.id, "amount_usdc": pay.amount_usdc,
            "total": kwacha(cart.total_minor)}


@app.post("/api/shop/split")
def shop_split(body: CartIn, s: Session = Depends(get_session)):
    cart = cart_receipt_items(s, body)
    biz = s.exec(select(Business)).first()
    split, token = create_split(s, body.host_name, "business", biz.name,
                                [(line.name, line.qty, line.line_total_minor, line.product_id) for line in cart.lines],
                                0, 0, cart.total_minor, business_id=biz.id, source="counter")
    return {"slug": split.slug, "token": token}
