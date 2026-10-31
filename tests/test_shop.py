import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import Business, Product, Receipt, ReceiptItem, StockMove
from app.shop import OutOfStock, commit_sale, match, price_cart

P = [Product(id=1, business_id=1, name="Coke 500ml", aliases="coke,coca-cola,coca cola", price_minor=1500, stock_qty=12),
     Product(id=2, business_id=1, name="Mosi 375ml", aliases="mosi,mosi lager", price_minor=2500, stock_qty=24),
     Product(id=3, business_id=1, name="Samoosa", aliases="samosa", price_minor=800, stock_qty=30)]


def test_match():
    assert match("Coke", P).id == 1
    assert match("Coca-Cola 500ml bottle", P).id == 1
    assert match("Mosi lager 375ml", P).id == 2
    assert match("samosas", P).id == 3
    assert match("Bread loaf", P) is None


def test_price_cart_uses_db_price():
    cart = price_cart([(P[0], 3), (P[2], 0)])
    assert cart.total_minor == 4500 and len(cart.lines) == 1


def test_commit_sale_decrements_and_refuses_below_zero():
    eng = create_engine("sqlite://")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Business(id=1, name="b"))
        s.add(Product(id=1, business_id=1, name="Coke", price_minor=1500, stock_qty=12))
        s.add(Receipt(id=1, source="counter"))
        s.add(ReceiptItem(receipt_id=1, name="Coke", qty=3, unit_price_minor=1500, line_total_minor=4500, product_id=1))
        s.add(Receipt(id=2, source="counter"))
        s.add(ReceiptItem(receipt_id=2, name="Coke", qty=99, unit_price_minor=1500, line_total_minor=1, product_id=1))
        s.commit()
        commit_sale(s, 1)
        commit_sale(s, 1)  # idempotent
        assert s.get(Product, 1).stock_qty == 9
        with pytest.raises(OutOfStock):
            commit_sale(s, 2)
        assert s.get(Product, 1).stock_qty == 9
        assert len(s.exec(select(StockMove)).all()) == 1
