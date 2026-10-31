import os
from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, UniqueConstraint, create_engine


def now():
    return datetime.now(timezone.utc)


class Business(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    wallet_id: str | None = None
    low_stock_threshold: int = 5


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id")
    name: str
    aliases: str = ""  # comma-separated
    price_minor: int
    stock_qty: int = 0


class StockMove(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    delta: int
    reason: str  # sale | restock | adjust
    receipt_id: int | None = Field(default=None, foreign_key="receipt.id")
    created_at: datetime = Field(default_factory=now)


class Receipt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int | None = Field(default=None, foreign_key="business.id")
    source: str = "photo"  # photo | counter
    merchant: str | None = None
    currency: str = "ZMW"
    subtotal_minor: int = 0
    tax_minor: int = 0
    service_minor: int = 0
    tip_minor: int = 0
    total_minor: int = 0
    image_path: str | None = None
    created_at: datetime = Field(default_factory=now)


class ReceiptItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int = Field(foreign_key="receipt.id", index=True)
    name: str
    qty: int
    unit_price_minor: int
    line_total_minor: int
    product_id: int | None = Field(default=None, foreign_key="product.id")


class Split(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    receipt_id: int = Field(foreign_key="receipt.id")
    host_name: str
    payee: str = "host"  # host | business
    status: str = "open"  # open | settling | paid | closed
    created_at: datetime = Field(default_factory=now)


class Participant(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    split_id: int = Field(foreign_key="split.id", index=True)
    name: str
    token: str = Field(unique=True, index=True)
    is_host: bool = False
    confirmed: bool = False
    share_minor: int | None = None


class Claim(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("participant_id", "item_id", "unit_index"),)
    id: int | None = Field(default=None, primary_key=True)
    participant_id: int = Field(foreign_key="participant.id", index=True)
    item_id: int = Field(foreign_key="receiptitem.id")
    unit_index: int


class Payment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    split_id: int | None = Field(default=None, foreign_key="split.id")
    participant_id: int | None = Field(default=None, foreign_key="participant.id")
    receipt_id: int = Field(foreign_key="receipt.id")
    amount_minor: int
    amount_usdc: str
    devdraft_link_id: str | None = None
    url: str | None = None
    status: str = "pending"  # pending | paid | failed | refunded | void
    created_at: datetime = Field(default_factory=now)
    paid_at: datetime | None = None


class Payout(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    split_id: int = Field(foreign_key="split.id")
    amount_usdc: str
    status: str = "proposed"  # proposed | approved | declined | sent | failed


engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///tracksplit.db"), connect_args={"check_same_thread": False})


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
