import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import devdraft
from app.db import Payment, Payout, Product, engine
from app.main import app


def test_verify_signature(monkeypatch):
    monkeypatch.setenv("DEVDRAFT_WEBHOOK_SECRET", "s3cret")
    raw = b'{"event":"payment.completed"}'
    sig = hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    assert devdraft.verify_signature(raw, sig)
    assert not devdraft.verify_signature(raw, "00" * 32)
    assert not devdraft.verify_signature(raw, None)


def test_caps():
    devdraft.check_caps(Decimal("4.99"), Decimal("45"))
    with pytest.raises(devdraft.CapExceeded):
        devdraft.check_caps(Decimal("5.01"), Decimal(0))
    with pytest.raises(devdraft.CapExceeded):
        devdraft.check_caps(Decimal("1"), Decimal("49.50"))


def test_pick_url_and_looks_paid():
    assert devdraft.pick_url({"id": "x", "paymentUrl": "https://pay/x"}) == "https://pay/x"
    assert devdraft.pick_url({"data": {"checkoutUrl": "https://c/1"}}) == "https://c/1"
    assert devdraft.pick_url({"url": "ts-abc-1", "link": "https://l/1"}) == "https://l/1"  # url slug isn't a link
    assert devdraft.looks_paid({"status": "COMPLETED"}) and not devdraft.looks_paid({"status": "ACTIVE"})


def flow(c, slug, d, name):
    r = c.post(f"/api/splits/{slug}/join", json={"name": name}).json()
    return r["token"]


def test_full_mock_flow():
    with TestClient(app) as c:
        r = c.post("/api/splits", json={"host_name": "Host", "payee": "host", "merchant": "Marlin",
                                        "items": [{"name": "Chips", "qty": 2, "line_total": "70"},
                                                  {"name": "Mosi", "qty": 1, "line_total": "25.01"}],
                                        "tax": "15.2", "service": "9.5", "total": "119.71"}).json()
        slug, host = r["slug"], r["token"]
        a, b = flow(c, slug, "alice", "Alice"), flow(c, slug, "bwalya", "Bwalya")
        state = c.get(f"/s/{slug}")  # page renders
        assert state.status_code == 200
        with c.websocket_connect(f"/ws/splits/{slug}?token={a}") as ws:
            snap = ws.receive_json()["split"]
            chips, mosi = snap["items"]
            for tok, item, unit in [(a, chips, 0), (b, chips, 0), (b, chips, 1), (host, mosi, 0)]:
                assert c.post(f"/api/splits/{slug}/claim", json={"token": tok, "item_id": item["id"], "unit_index": unit}).status_code == 200
            for _ in range(4):
                snap = ws.receive_json()["split"]
            assert snap["unclaimed"] == 0 and sum(p["share"] for p in snap["participants"]) == 11971
            ca = c.post(f"/api/splits/{slug}/confirm", json={"token": a}).json()
            assert "/mock-pay/" in ca["url"]
            # confirmed person's claims are locked, and units they share are locked for others
            assert c.post(f"/api/splits/{slug}/claim", json={"token": a, "item_id": chips["id"], "unit_index": 1}).status_code == 409
            cb = c.post(f"/api/splits/{slug}/confirm", json={"token": b}).json()
            c.post(f"/api/splits/{slug}/confirm", json={"token": host})
            for u in (ca["url"], cb["url"]):
                c.post(u.split("8000")[-1] if "8000" in u else u[u.index("/mock-pay"):], follow_redirects=False)
        with Session(engine) as s:
            assert {p.status for p in s.exec(select(Payment)).all()} == {"paid"}
            po = s.exec(select(Payout)).one()
            assert po.status == "proposed"
        assert c.post(f"/api/splits/{slug}/payout", json={"token": a, "approve": True}).status_code == 403
        assert c.post(f"/api/splits/{slug}/payout", json={"token": host, "approve": True}).json()["status"] == "approved"


def test_shop_sale_decrements_stock_and_webhook():
    with TestClient(app) as c:
        with Session(engine) as s:
            coke = s.exec(select(Product).where(Product.name == "Coke 500ml")).one()
            before = coke.stock_qty
        r = c.post("/api/shop/charge", json={"lines": [{"product_id": coke.id, "qty": 3}]}).json()
        assert r["total"] == "K45.00"
        body = json.dumps({"event": "payment.completed", "data": {"customFields": {"payment_id": str(r["payment_id"])}}}).encode()
        assert c.post("/webhooks/devdraft", content=body, headers={"x-webhook-signature": "bad"}).status_code == 401
        sig = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
        assert c.post("/webhooks/devdraft", content=body, headers={"x-webhook-signature": sig}).json()["payment_id"] == r["payment_id"]
        with Session(engine) as s:
            assert s.get(Product, coke.id).stock_qty == before - 3
        assert "left" in c.get(f"/r/{r['receipt_id']}").text
        assert c.get(f"/r/{r['receipt_id']}/receipt.pdf").content.startswith(b"%PDF")
