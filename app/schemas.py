from decimal import Decimal

from pydantic import BaseModel, Field


# ---- LLM IO ----
class ExtractedItem(BaseModel):
    name: str
    qty: int = Field(ge=1)
    unit_price: Decimal | None = None
    line_total: Decimal


class ReceiptExtract(BaseModel):
    merchant: str | None = None
    currency: str = "ZMW"
    items: list[ExtractedItem] = Field(min_length=1)
    subtotal: Decimal
    tax: Decimal = Decimal(0)
    tax_included: bool = Field(False, description="true if the tax is already inside the item prices (e.g. 'VAT incl.')")
    service: Decimal = Decimal(0)
    total: Decimal
    unreadable: list[str] = []  # anything the model could not read, shown to host


class SeenItem(BaseModel):
    label: str  # what the model sees, e.g. "Mosi lager 375ml"
    qty: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class CounterExtract(BaseModel):
    items: list[SeenItem]


# ---- live split snapshot ----
class Claimer(BaseModel):
    id: int
    name: str


class UnitState(BaseModel):
    index: int
    cost: int
    claimers: list[Claimer]


class ItemState(BaseModel):
    id: int
    name: str
    qty: int
    line_total: int
    units: list[UnitState]


class ParticipantState(BaseModel):
    id: int
    name: str
    is_host: bool
    confirmed: bool
    paid: bool
    share: int
    share_usdc: str
    paid_with: str | None = None  # masked payer reference once paid
    pay_url: str | None = None  # only filled on the owner's own socket


class SplitState(BaseModel):
    slug: str
    receipt_id: int
    merchant: str | None
    status: str
    payee: str
    host_name: str
    items: list[ItemState]
    participants: list[ParticipantState]
    subtotal: int
    extras: int
    total: int
    claimed: int  # minor units of item cost claimed so far (incl. extras share)
    paid: int
    unclaimed: int
    demo_scale: bool
    payout: dict | None = None
