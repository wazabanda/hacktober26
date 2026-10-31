"""DevDraft payment links (live | mock), spend caps, webhook verification, and mark_paid."""

import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from decimal import Decimal

import httpx
from sqlmodel import Session, select

from . import hub
from .db import Payment, Payout, Split, engine, now
from .shop import commit_sale

log = logging.getLogger("devdraft")
BASE = "https://api.devdraft.ai"


class CapExceeded(ValueError):
    pass


def mode() -> str:
    return os.getenv("DEVDRAFT_MODE", "mock")


def _headers(post: bool = False) -> dict:
    h = {"x-client-key": os.environ["DEVDRAFT_CLIENT_KEY"], "x-client-secret": os.environ["DEVDRAFT_CLIENT_SECRET"]}
    if post:
        h["Idempotency-Key"] = str(uuid.uuid4())
    return h


def check_caps(amount: Decimal, live_total_so_far: Decimal):
    if amount > Decimal(os.getenv("MAX_TXN_USD", "5")):
        raise CapExceeded(f"${amount} is over the ${os.getenv('MAX_TXN_USD', '5')} per-payment cap")
    if live_total_so_far + amount > Decimal(os.getenv("MAX_TEAM_USD", "50")):
        raise CapExceeded(f"team total would be ${live_total_so_far + amount}, over the ${os.getenv('MAX_TEAM_USD', '50')} cap")


def pick_url(data: dict) -> str | None:
    for src in (data, data.get("data") or {}):
        for k in ("url", "paymentUrl", "link", "checkoutUrl"):
            v = src.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
    return None


def create_payment_link(s: Session, pay: Payment, title: str, description: str, slug: str,
                        base_url: str) -> tuple[str, str]:
    amount = Decimal(pay.amount_usdc)
    if mode() == "mock":
        return f"mock_{pay.id}", f"{base_url}/mock-pay/{pay.id}"
    spent = sum((Decimal(p.amount_usdc) for p in s.exec(select(Payment).where(
        Payment.status.in_(["pending", "paid"]), Payment.id != pay.id)).all()
        if p.devdraft_link_id and not p.devdraft_link_id.startswith("mock_")), Decimal(0))
    check_caps(amount, spent)
    body = {"title": title[:80], "url": f"ts-{slug}-{pay.id}", "linkType": "INVOICE", "amount": float(amount),
            "currency": "usdc", "allowQuantityAdjustment": False, "collectTax": False, "collectAddress": False,
            "allowMobilePayment": True, "limitPayments": True, "maxPayments": 1,
            "customFields": {"payment_id": str(pay.id)}, "description": description[:250]}
    r = httpx.post(f"{BASE}/api/v0/payment-links", json=body, headers=_headers(post=True), timeout=20)
    log.warning("devdraft create %s %s", r.status_code, r.text)  # raw response, keys are never in it
    r.raise_for_status()
    data = r.json()
    url = pick_url(data)
    link_id = str(data.get("id") or (data.get("data") or {}).get("id") or "")
    if not url or not link_id:
        raise RuntimeError(f"Unexpected DevDraft response shape: {r.text[:500]}")
    return link_id, url


def get_link(link_id: str) -> dict:
    r = httpx.get(f"{BASE}/api/v0/payment-links/{link_id}", headers=_headers(), timeout=15)
    log.info("devdraft get %s %s", r.status_code, r.text[:800])
    r.raise_for_status()
    return r.json()


PAID_WORDS = {"paid", "completed", "complete", "succeeded", "success", "settled"}


def looks_paid(data: dict) -> bool:
    """ponytail: heuristic until we see a real paid link; tighten once the shape is known."""
    d = data.get("data") if isinstance(data.get("data"), dict) else data
    if str(d.get("status", "")).lower() in PAID_WORDS or str(d.get("paymentStatus", "")).lower() in PAID_WORDS:
        return True
    for k in ("paymentsCount", "paymentCount", "totalPayments", "completedPayments", "timesPaid"):
        if isinstance(d.get(k), int) and d[k] > 0:
            return True
    return False


def list_wallets() -> list[dict]:
    if mode() == "mock":
        with Session(engine) as s:
            paid = sum(Decimal(p.amount_usdc) for p in s.exec(select(Payment).where(Payment.status == "paid")).all())
        return [{"id": "mock-wallet", "name": "Mock business wallet", "balance": str(paid), "currency": "USDC"}]
    r = httpx.get(f"{BASE}/api/v0/wallets", headers=_headers(), timeout=15)
    log.info("devdraft wallets %s %s", r.status_code, r.text[:800])
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data") or data.get("wallets") or [data]


def verify_signature(raw: bytes, header: str | None) -> bool:
    secret = os.getenv("DEVDRAFT_WEBHOOK_SECRET", "")
    if not secret or not header:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip().removeprefix("sha256="))


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)
    else:
        yield path, obj


def find_payment_id(s: Session, payload: dict) -> int | None:
    """Custom field first, then our link id, then the ts-{slug}-{id} url slug."""
    pairs = list(_walk(payload))
    for k, v in pairs:
        if k == "payment_id" and str(v).isdigit():
            return int(v)
    values = {str(v) for _, v in pairs}
    for p in s.exec(select(Payment).where(Payment.devdraft_link_id != None)).all():  # noqa: E711
        if p.devdraft_link_id in values:
            return p.id
    for v in values:
        if m := re.search(r"\bts-[a-z0-9]+-(\d+)\b", v):
            return int(m.group(1))
    return None


def finish_if_done(s: Session, split: Split) -> None:
    """All units claimed and everyone with a share paid -> split paid; propose host payout; shop stock moves."""
    if split.status == "paid":
        return
    receipt, items, people, claims, sh, payments = hub.compute(s, split)
    if sum(i.qty for i in items) > len({(c.item_id, c.unit_index) for c in claims}):
        return
    if not all(hub.is_paid(split, p, payments) or (not p.confirmed and sh.get(p.id, 0) == 0) for p in people):
        return
    split.status = "paid"
    s.add(split)
    if split.payee == "host" and not s.exec(select(Payout).where(Payout.split_id == split.id)).first():
        total = sum((Decimal(p.amount_usdc) for p in payments.values() if p.status == "paid"), Decimal(0))
        s.add(Payout(split_id=split.id, amount_usdc=str(total)))
        log.warning("payout proposed for split %s: $%s", split.slug, total)
    s.commit()
    if receipt.source == "counter":
        commit_sale(s, receipt.id)


async def mark_paid(payment_id: int, method: str = "devdraft", payer_ref: str | None = None) -> bool:
    """Idempotent. Used by the webhook, the poller and the mock checkout."""
    with Session(engine) as s:
        pay = s.get(Payment, payment_id)
        if not pay or pay.status == "paid":
            return False
        pay.status, pay.paid_at, pay.method, pay.payer_ref = "paid", now(), method, payer_ref
        s.add(pay)
        s.commit()
        if not pay.split_id:  # shop sale: stock moves now
            commit_sale(s, pay.receipt_id)
            return True
        split = s.get(Split, pay.split_id)
        finish_if_done(s, split)
        slug = split.slug
    await hub.broadcast_state(slug)
    return True


def event_failed(payload: dict) -> bool:
    return "fail" in json.dumps(payload.get("event") or payload.get("type") or "").lower()
