"""In-memory WebSocket rooms. ponytail: one process only; swap for Redis pub/sub to scale out."""

import asyncio
import logging
import os

from fastapi import WebSocket
from sqlmodel import Session, select

from .db import Claim, Participant, Payment, Payout, Receipt, ReceiptItem, Split, engine
from .schemas import Claimer, ItemState, ParticipantState, SplitState, UnitState
from .split import UNCLAIMED, shares, to_usdc, unit_costs

log = logging.getLogger("hub")
rooms: dict[str, dict[WebSocket, int | None]] = {}  # slug -> {socket: participant_id}


def join(slug: str, ws: WebSocket, participant_id: int | None):
    rooms.setdefault(slug, {})[ws] = participant_id


def leave(slug: str, ws: WebSocket):
    rooms.get(slug, {}).pop(ws, None)


def compute(s: Session, split: Split):
    """Everything the snapshot and the money routes need, from the DB."""
    receipt = s.get(Receipt, split.receipt_id)
    items = s.exec(select(ReceiptItem).where(ReceiptItem.receipt_id == receipt.id).order_by(ReceiptItem.id)).all()
    people = s.exec(select(Participant).where(Participant.split_id == split.id).order_by(Participant.id)).all()
    claims = s.exec(select(Claim).where(Claim.participant_id.in_([p.id for p in people]))).all() if people else []
    lines = sum(i.line_total_minor for i in items)
    sh = shares([(i.id, i.qty, i.line_total_minor) for i in items],
                [(c.participant_id, c.item_id, c.unit_index) for c in claims], receipt.total_minor - lines)
    for p in people:  # a confirmed share is locked at the amount they were charged
        if p.confirmed and p.share_minor is not None:
            sh[p.id] = p.share_minor
    payments = {p.participant_id: p for p in s.exec(select(Payment).where(
        Payment.split_id == split.id, Payment.status.in_(["pending", "paid"]))).all()}
    return receipt, items, people, claims, sh, payments


def is_paid(split: Split, p: Participant, payments: dict) -> bool:
    if p.is_host and split.payee == "host":
        return p.confirmed  # the host already paid the restaurant
    pay = payments.get(p.id)
    return bool(pay and pay.status == "paid")


def build_state(s: Session, split: Split, viewer: int | None) -> SplitState:
    receipt, items, people, claims, sh, payments = compute(s, split)
    names = {p.id: p.name for p in people}
    by_unit: dict = {}
    for c in claims:
        by_unit.setdefault((c.item_id, c.unit_index), []).append(Claimer(id=c.participant_id, name=names[c.participant_id]))
    item_states = [ItemState(id=i.id, name=i.name, qty=i.qty, line_total=i.line_total_minor, units=[
        UnitState(index=u, cost=cost, claimers=by_unit.get((i.id, u), []))
        for u, cost in enumerate(unit_costs(i.line_total_minor, i.qty))]) for i in items]
    ps = []
    for p in people:
        share = sh.get(p.id, 0)
        pay = payments.get(p.id)
        ps.append(ParticipantState(
            id=p.id, name=p.name, is_host=p.is_host, confirmed=p.confirmed, paid=is_paid(split, p, payments),
            share=share, share_usdc=str(pay.amount_usdc if pay else to_usdc(share)),
            paid_with=pay.payer_ref if pay and pay.status == "paid" else None,
            pay_url=pay.url if (pay and p.id == viewer and pay.status == "pending") else None))
    payout = s.exec(select(Payout).where(Payout.split_id == split.id)).first()
    allocated = sum(p.share for p in ps)
    return SplitState(
        slug=split.slug, receipt_id=receipt.id, merchant=receipt.merchant, status=split.status, payee=split.payee, host_name=split.host_name,
        items=item_states, participants=ps, subtotal=sum(i.line_total_minor for i in items),
        extras=receipt.total_minor - sum(i.line_total_minor for i in items), total=receipt.total_minor,
        claimed=allocated, paid=sum(p.share for p in ps if p.paid), unclaimed=receipt.total_minor - allocated,
        demo_scale=os.getenv("CHARGE_SCALE", "1") not in ("1", "1.0"),
        payout=payout.model_dump() if payout else None)


async def broadcast_state(slug: str):
    room = rooms.get(slug, {})
    if not room:
        return
    with Session(engine) as s:
        split = s.exec(select(Split).where(Split.slug == slug)).one()
        cache: dict = {}
        for ws, pid in list(room.items()):
            if pid not in cache:
                cache[pid] = {"type": "state", "split": build_state(s, split, pid).model_dump(mode="json")}
            try:
                await asyncio.wait_for(ws.send_json(cache[pid]), 5)
            except Exception as e:  # dead phone socket: drop it, the client reconnects and gets a fresh snapshot
                log.warning("broadcast %s to participant %s failed: %r", slug, pid, e)
                leave(slug, ws)
        log.info("broadcast %s to %d sockets", slug, len(room))


async def send_to(slug: str, participant_id: int, msg: dict):
    for ws, pid in list(rooms.get(slug, {}).items()):
        if pid == participant_id:
            try:
                await ws.send_json(msg)
            except Exception:
                leave(slug, ws)
