"""Demo business + Lusaka products. Safe to run twice."""

from dotenv import load_dotenv

load_dotenv()

from sqlmodel import Session, select

from app.db import Business, Product, engine, init_db

PRODUCTS = [  # name, aliases, price (ngwee), stock
    ("Mosi 375ml", "mosi,mosi lager,mosi beer", 2500, 24),
    ("Castle Lite", "castle,castle lite beer", 3000, 24),
    ("Coke 500ml", "coke,coca-cola,coca cola,cocacola,coke bottle", 1500, 12),
    ("Fanta", "fanta orange,fanta 500ml", 1500, 12),
    ("Maheu", "super maheu,maheu drink", 1200, 10),
    ("Fruticana", "frutecana,fruticana juice,fruticana 500ml", 1000, 30),
    ("Nshima & chicken", "nshima chicken,nshima with chicken", 7500, 30),
    ("Nshima & beef", "nshima beef,nshima with beef", 8000, 30),
    ("Chips", "fries,french fries,chips portion", 3500, 40),
    ("Village chicken", "village chicken stew,road runner", 12000, 8),
    ("T-bone", "t bone,t-bone steak,steak", 15000, 6),
    ("Kapenta", "kapenta with nshima,dry kapenta", 6000, 15),
    ("Samoosa", "samosa,samoosas,samosas", 800, 30),
    ("Bottled water", "water,water 500ml,aqua", 1000, 20),
    ("Rolls", "roll,bread roll,bun", 500, 25),
    ("Tea", "cup of tea,tea cup,black tea", 1000, 50),
]


def seed() -> int:
    init_db()
    with Session(engine) as s:
        biz = s.exec(select(Business).where(Business.name == "Kaizen Café")).first()
        if not biz:
            biz = Business(name="Kaizen Café")
            s.add(biz)
            s.flush()
        have = set(s.exec(select(Product.name).where(Product.business_id == biz.id)))
        new = [Product(business_id=biz.id, name=n, aliases=a, price_minor=p, stock_qty=q)
               for n, a, p, q in PRODUCTS if n not in have]
        s.add_all(new)
        s.commit()
        return len(new)


if __name__ == "__main__":
    print(f"added {seed()} products")
