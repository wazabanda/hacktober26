"""Shop mode: match what Gemma saw to the catalogue, price from the DB, move stock."""

import difflib

from pydantic import BaseModel
from sqlmodel import Session, select

from .db import Product, ReceiptItem, StockMove


def _names(p: Product) -> list[str]:
    return [n.strip().lower() for n in [p.name, *p.aliases.split(",")] if n.strip()]


def match(label: str, products: list[Product]) -> Product | None:
    """Fuzzy match over name + aliases. Falls back to the longest alias contained in the label."""
    label = label.lower().strip()
    by_name = {n: p for p in products for n in _names(p)}
    hit = difflib.get_close_matches(label, by_name, n=1, cutoff=0.6)
    if hit:
        return by_name[hit[0]]
    inside = [n for n in by_name if len(n) >= 3 and n in label]
    return by_name[max(inside, key=len)] if inside else None


class CartLine(BaseModel):
    product_id: int
    name: str
    qty: int
    unit_price_minor: int
    line_total_minor: int
    stock_qty: int


class Cart(BaseModel):
    lines: list[CartLine]
    total_minor: int


def price_cart(lines: list[tuple[Product, int]]) -> Cart:
    """Prices always come from the DB product, never from the model."""
    out = [CartLine(product_id=p.id, name=p.name, qty=q, unit_price_minor=p.price_minor,
                    line_total_minor=p.price_minor * q, stock_qty=p.stock_qty) for p, q in lines if q > 0]
    return Cart(lines=out, total_minor=sum(line.line_total_minor for line in out))


class OutOfStock(ValueError):
    pass


def commit_sale(session: Session, receipt_id: int) -> None:
    """Decrement stock for every product line on the receipt in one transaction. Idempotent per receipt."""
    if session.exec(select(StockMove).where(StockMove.receipt_id == receipt_id)).first():
        return
    items = session.exec(select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id,
                                                   ReceiptItem.product_id != None)).all()  # noqa: E711
    for it in items:
        p = session.get(Product, it.product_id)
        if p.stock_qty < it.qty:
            session.rollback()
            raise OutOfStock(f"{p.name}: only {p.stock_qty} left, sale needs {it.qty}")
        p.stock_qty -= it.qty
        session.add(p)
        session.add(StockMove(product_id=p.id, delta=-it.qty, reason="sale", receipt_id=receipt_id))
    session.commit()
