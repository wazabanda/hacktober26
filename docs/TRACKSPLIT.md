# TrackSplit — Product & Technical Breakdown

> Snap a bill, share a link, everyone pays for what they ate.
> Snap the counter, the shop knows its prices, its stock and sends the receipt.

Built for **Hacktoberfest Hack Day Lusaka x Tech Kaizen** (31 Oct 2026). One project, three challenges:

| Challenge | How TrackSplit qualifies |
|---|---|
| **DigitalOcean: Best Open-Source AI Project** | MIT-licensed repo. Built on an open-source harness (Pydantic AI) with the model as a single env setting, so it runs on Google Gemini or an open-weight Gemma 4 model unchanged. We developed on DeepSeek and Gemma and ship Gemini in production. Ships a reusable `receipt-reader` agent skill other agents can call. Hosted on DigitalOcean App Platform. |
| **Google DeepMind** | Google Gemini does the multimodal work: it reads receipt photos and identifies products on a counter. That is the core of the product, not decoration. Setting `LLM_MODEL` to a Gemma 4 id runs the same flow on Gemma 4. |
| **DevDraft API Build Challenge** | Real DevDraft payment links, one per person. Webhooks mark people as paid. A host payout needs human approval before it runs. Fits two of DevDraft's build directions: "Snap. Chat. Get Paid" and "Give the Agent a Wallet". |

---

## 1. The problem

**Splitting the bill.** Eight friends at a restaurant in Lusaka get one bill. One person pays and then chases the others on WhatsApp for days. Splitting evenly is unfair to the person who only had a Fanta. Working out who had what, plus service charge and VAT, by hand is slow and error-prone.

**Small shops.** Kantemba owners and small restaurants track stock in a notebook or not at all. Prices live in the owner's head, receipts are handwritten or never given, and there is no record of what sold.

TrackSplit solves both with the same engine: **a photo goes in, typed line items come out, and the money and stock follow from those items.**

## 2. Users

| User | Wants |
|---|---|
| **Host** (person holding the bill) | Get paid back without chasing anyone |
| **Participant** (friend at the table) | Pay only for what they had, from their phone, no app install |
| **Shop / restaurant owner** | Fast checkout, correct prices, live stock, receipts, money straight to the business wallet |

## 3. Features

### Mode A: Split (real-time bill splitting)
1. The host takes a photo of the bill.
2. Gemini reads it into typed line items (name, quantity, unit price, line total) plus subtotal, tax, service charge and total.
3. The code checks the arithmetic. If the lines don't add up to the total, the agent re-reads the photo. If they still don't, the host fixes the bill on an edit screen.
4. The host picks where the money goes: **their own wallet** (they already paid) or the **business wallet** (the bill isn't paid yet; this is pay-at-table).
5. TrackSplit creates an interactive receipt at `/s/{slug}` and shows it as a link and a QR code.
6. Participants open the link, enter a name, and tap the items they had. Every phone updates live over WebSocket.
   - An item with quantity 3 has 3 separate units, each claimable by one person.
   - Several people can claim the same unit to share it, and its cost is divided equally between them.
7. Each participant presses **Confirm**. They see their share: their items plus a proportional slice of tax, service and tip.
8. Once a participant confirms, the server creates a **DevDraft payment link for their exact share** and pushes it to their phone.
9. When someone pays, a DevDraft webhook arrives, their row turns green on every screen, and they get a receipt.
10. When everyone has paid:
    - **Business payee:** the bill shows as settled at the counter.
    - **Host payee:** the agent proposes a payout to the host's wallet. The host approves it in the app, as DevDraft's rules require.

Unclaimed items: the host can assign them to themself or press "split the leftovers evenly".

### Mode B: Track (shop counter + stock)
1. The owner sets up a product catalogue: name, aliases, price and stock count. It can be seeded from a CSV file or a photo of the price board.
2. At checkout, the owner photographs the items on the counter, or a handwritten order.
3. Gemini identifies the items and quantities. The `match_products` tool matches them against the database. **Prices always come from the database, never from the model.**
4. The owner checks the cart and fixes anything unmatched. They can then:
   - **Charge**: one DevDraft payment link or QR code for the whole cart, or
   - **Split this**: turn the cart into a Mode A split, for a table of customers.
5. When payment completes, stock is decremented in the same database transaction and a receipt is sent as a link (and optionally as a WhatsApp share).
6. When stock falls below a set threshold, a low-stock badge appears and the agent mentions it ("Mosi: 4 left").
7. Restocking works by photographing the delivery note. Gemini reads it, the owner confirms, and stock goes up.

### Shared
- Every receipt has a public read-only page with a QR code.
- The ledger keeps a record of every payment, refund and stock movement.
- A `/demo` page shows 4 simulated phones side by side for judging.

## 4. Design principles

1. **The LLM only reads; code does the money.** Gemini pulls text and structure out of photos. All splitting, rounding, tax allocation, currency conversion and stock changes are plain Python with tests.
2. **Every input and output is a Pydantic model.** Pydantic AI `output_type` enforces it, and a failed validation triggers a `ModelRetry` so the model tries again.
3. **A human approves money going out.** Payment links only collect money. Any outbound transfer (the host payout) is a `requires_approval=True` tool. This matches DevDraft's rule that transfers over $1 need human approval.
4. **No accounts.** Participants are identified by an anonymous token kept in `localStorage`.
5. **Real time means a snapshot broadcast.** After any change, the server sends the full split state to everyone in the room. No diffs, no conflict logic.

## 5. Architecture

```
 phones / browser tabs                         DigitalOcean App Platform (1 container)
 ┌──────────────┐  HTTP POST (mutations)      ┌──────────────────────────────────────┐
 │ daisyUI +    │ ──────────────────────────▶ │ FastAPI                              │
 │ Alpine.js    │ ◀────────────────────────── │  ├─ routes (Jinja templates)         │
 │ pages        │  WebSocket (state push)     │  ├─ hub.py  (in-memory WS rooms)     │
 └──────────────┘                             │  ├─ split.py (pure money math)       │
                                              │  ├─ agents.py (Pydantic AI)  ────────┼──▶ Gemini API (Gemini 2.5 Flash)
                                              │  ├─ devdraft.py (live | mock) ───────┼──▶ api.devdraft.ai
                                              │  └─ SQLite (SQLModel)                │◀── DevDraft webhooks
                                              └──────────────────────────────────────┘
```

| Layer | Choice | Why |
|---|---|---|
| Web | FastAPI + Jinja2 | Native WebSockets, Pydantic everywhere, async LLM calls |
| Real-time | FastAPI WebSocket, in-memory room hub | Simple enough for one process; see the scaling note |
| DB | SQLite via SQLModel | SQLModel tables are Pydantic models, and a hackathon needs no Postgres |
| AI | Pydantic AI. Developed and tested on DeepSeek and Gemma; production runs Gemini 2.5 Flash | Typed outputs, tools, approval-gated tools |
| UI | Tailwind + daisyUI 5 from CDN, Alpine.js | No build step; works well on phones |
| Payments | DevDraft REST (`httpx`) | Payment links, webhooks, wallets |
| Hosting | DigitalOcean App Platform, 1 instance | Public HTTPS URL for phones and webhooks; supports the DO challenge |

**Scaling note:** the hub lives in memory, so the app must run as **one worker and one instance**. When it needs to scale out, swap the hub for Redis pub/sub.

## 6. Data model

All money is stored as **integers in minor units** (ngwee, K1 = 100 ngwee) so there are no floating-point errors.

```
Business(id, name, wallet_id?, low_stock_threshold=5)
Product(id, business_id, name, aliases: str (comma-sep), price_minor, stock_qty)
StockMove(id, product_id, delta, reason: sale|restock|adjust, receipt_id?, created_at)

Receipt(id, business_id?, source: photo|counter, merchant, currency="ZMW",
        subtotal_minor, tax_minor, service_minor, tip_minor, total_minor, image_path, created_at)
ReceiptItem(id, receipt_id, name, qty, unit_price_minor, line_total_minor, product_id?)

Split(id, slug, receipt_id, host_name, payee: host|business,
      status: open|settling|paid|closed, created_at)
Participant(id, split_id, name, token, confirmed: bool, share_minor?)
Claim(id, participant_id, item_id, unit_index)        # unique(participant_id, item_id, unit_index)

Payment(id, split_id?, participant_id?, receipt_id, amount_minor, amount_usdc: str,
        devdraft_link_id, url, status: pending|paid|failed|refunded, created_at, paid_at?)
Payout(id, split_id, amount_usdc, status: proposed|approved|sent|failed)
```

## 7. Money rules (`split.py`, pure functions, unit-tested)

1. **Unit cost** = `line_total_minor / qty`. Any remainder goes to the first units, so the unit costs always add up to the line total exactly.
2. **Shared unit**: when k people claim the same unit, divide its cost by k using largest-remainder allocation.
3. **Extras** (tax, service, tip) are allocated in proportion to each person's item subtotal, again with largest remainder. Everyone's shares added together **always equal `total_minor`**. That is the invariant the tests check.
4. **Currency**: `usdc = round(minor / 100 / FX_ZMW_PER_USD * CHARGE_SCALE, 2)`, with a minimum of 0.01.
   - `CHARGE_SCALE` defaults to `1`. For the live demo it is set to something like `0.01`, so a K450 bill charges cents (the UI shows a "demo scale" badge).
5. **Hard cap**: a single payment link over `MAX_TXN_USD` (5) is refused before calling DevDraft. A running team total over `MAX_TEAM_USD` (50) is also refused.

## 8. AI design (Pydantic AI)

### Model setup
```python
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
model = GoogleModel(os.environ["LLM_MODEL"], provider=GoogleProvider(api_key=os.environ["GEMINI_API_KEY"]))
# LLM_MODEL = "gemini-2.5-flash" (any Gemini API id, including Gemma 4 ids)
```
The code is written so a Gemma 4 id can be dropped in. Gemma on the Gemini API has had limited support for system instructions and native tool calling, so:
- The extraction agents use `PromptedOutput(...)`, which needs no tool calling, and put their instructions in the user message.
- The tool-using `counter_agent` reads its model from `AGENT_MODEL`. It can point at a different model from the vision reader if needed.

### Agents
| Agent | Input | Output (Pydantic) | Notes |
|---|---|---|---|
| `receipt_reader` | bill photo (`BinaryContent`) | `ReceiptExtract` | `output_validator` checks that the lines sum to the subtotal and that subtotal + extras = total (±1%). If not, it raises `ModelRetry` naming the mismatch. |
| `counter_reader` | counter or handwritten-order photo | `CounterExtract` (items + qty + confidence) | Prices are not requested |
| `counter_agent` | owner's chat + `CounterExtract` | `Cart` | Tools: `search_products`, `get_stock`, `create_payment_link` (approval), `adjust_stock` (approval), `send_receipt` |
| `restock_reader` | delivery-note photo | `RestockExtract` | The owner confirms before stock changes |

### Schemas (core)
```python
class ExtractedItem(BaseModel):
    name: str
    qty: int = Field(ge=1)
    unit_price: Decimal | None = None
    line_total: Decimal

class ReceiptExtract(BaseModel):
    merchant: str | None
    currency: str = "ZMW"
    items: list[ExtractedItem] = Field(min_length=1)
    subtotal: Decimal
    tax: Decimal = 0
    service: Decimal = 0
    total: Decimal
    unreadable: list[str] = []      # anything the model could not read, shown to host

class SeenItem(BaseModel):
    label: str                      # what the model sees, e.g. "Mosi lager 375ml"
    qty: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)

class CounterExtract(BaseModel):
    items: list[SeenItem]
```

### Open-source agent skill
`skills/receipt-reader/` contains `SKILL.md`, the prompt, the `ReceiptExtract` schema and a CLI (`python -m tracksplit.skills.receipt_reader photo.jpg`). It prints validated JSON. Any agent can use it on its own, which is the deliverable for the DigitalOcean track.

## 9. DevDraft integration

- **Base URL** `https://api.devdraft.ai`. Headers on every request: `x-client-key`, `x-client-secret`, and `Idempotency-Key` (a UUID v4) on POSTs.
- **Create payment link**: `POST /api/v0/payment-links`
  ```json
  {"title": "TrackSplit: Alice @ Marlin", "url": "ts-<split_slug>-<participant_id>",
   "linkType": "INVOICE", "amount": 0.17, "currency": "usdc",
   "allowQuantityAdjustment": false, "collectTax": false, "collectAddress": false,
   "allowMobilePayment": true, "limitPayments": true, "maxPayments": 1,
   "customFields": {"payment_id": "<our id>"},
   "description": "Your share: 1x Nshima & chicken, ½ chips + 10% service"}
  ```
- **Status**: the webhook `payment.completed` / `payment.failed` arrives at `POST /webhooks/devdraft`. Verify `x-webhook-signature` (HMAC-SHA256 of the raw body using `DEVDRAFT_WEBHOOK_SECRET`). The backup is polling `GET /api/v0/payment-links/{id}` every 5 seconds while a split is in `settling`.
- **Wallets**: `GET /api/v0/wallets` shows the business balance on the owner dashboard.
- **Host payout**: an approval-gated tool. It runs only after the host taps Approve. It uses whatever outbound transfer endpoint the DevDraft team confirms at kickoff (stablecoin wallet or Zambia mobile money). Until that is confirmed, the payout is recorded as `proposed/approved` in the ledger.
- **Mock mode**: `DEVDRAFT_MODE=mock` returns fake links pointing to `/mock-pay/{id}`, a page with a "Pay" button that fires the same internal webhook handler. The simulated-devices demo runs fully in mock mode, and one or two real payments are shown in live mode.

**Unknowns to verify with one live call at kickoff:**
1. The field in the response that holds the payment URL.
2. Which wallet a payment link pays into.
3. How a webhook payload identifies the payment link it belongs to.

The client logs the raw response, and the code reads the URL from the first of `url | paymentUrl | link | checkoutUrl` that exists.

**Event rules (must follow):**
- Use the production keys issued at kickoff.
- Maximum **$5 per transaction** and **$50 per team**.
- Use only your own funds.
- **Refund all test transactions before 3:30 PM CAT.**
- Never commit keys.
- **Human approval for any transfer over $1.**

## 10. Real-time protocol

- **WebSocket** `GET /ws/splits/{slug}`. The server only pushes: `{"type": "state", "split": SplitState}` after every change, and `{"type": "pay_link", "participant_id", "url"}` to the owning participant's socket. The client throws away its local state and renders from the snapshot.
- **Changes** go over HTTP and each one triggers a broadcast:

| Method | Path | Body |
|---|---|---|
| POST | `/api/splits/{slug}/join` | `{name}` returns `{participant_id, token}` |
| POST | `/api/splits/{slug}/claim` | `{token, item_id, unit_index}` toggles a claim |
| POST | `/api/splits/{slug}/confirm` | `{token}` locks that person's claims and creates their payment link |
| POST | `/api/splits/{slug}/unconfirm` | `{token}` only allowed while unpaid; voids the link |
| POST | `/api/splits/{slug}/assign-leftovers` | `{token(host), mode: host\|even}` |

`SplitState` contains the items with their units and claimers, the participants with name, share, confirmed/paid status and their payment URL (only included on that participant's own socket), the totals, and the counts of claimed and paid.

## 11. Pages (daisyUI)

| Route | Who | Content |
|---|---|---|
| `/` | everyone | Hero, "Split a bill" and "Open my shop" buttons |
| `/new` | host | Camera `file-input` (`capture="environment"`), spinner while Gemini reads, editable item table, payee toggle, "Create split" |
| `/s/{slug}` | participant | Name modal, then item cards (tap to claim, `avatar-group` shows claimers), sticky bottom bar with "My share Kxx.xx" and a Confirm button, then a Pay button, then a ✅ receipt |
| `/s/{slug}/host` | host | Same live receipt plus a QR code, a participant table (`badge` showing choosing/confirmed/paid), progress `radial-progress`, payout approval `modal` |
| `/shop` | owner | Products table with stock badges, "Snap counter" button, cart drawer, Charge / Split buttons, wallet balance `stat` |
| `/r/{id}` | anyone | Read-only receipt with a QR code |
| `/demo` | judges | 4 phone-frame (`mockup-phone`) iframes: host plus 3 friends, each loading `/s/{slug}?d=<name>` |

**Simulated devices:** iframes from the same origin share cookies and `localStorage`. The participant token is therefore stored under the key `ts:{slug}:{d}`, using the `?d=` query parameter, so each iframe acts as a separate phone.

## 12. Demo script (3 minutes)

1. **Story (20s):** "Eight of us, one bill, three days of WhatsApp reminders."
2. **Snap (30s):** photograph a real Lusaka restaurant bill. Gemini's extraction appears and the totals check shows ✅.
3. **Split live (60s):** the `/demo` page shows 4 phones. Tap items on different phones, and the claims and shares update on all of them at once. Show a shared plate of chips split ½ and ½.
4. **Pay (30s):** one participant pays **for real** in live mode with a few cents. The webhook arrives and their row turns green on every phone. Then the host payout approval modal appears, showing the human-approval rule in action.
5. **Track (30s):** in shop mode, photograph 3 drinks on the counter. They match the catalogue, stock drops from 12 to 9, and a receipt is sent.
6. **Close (10s):** open-source on GitHub, built on Gemini, running on DigitalOcean, paid through DevDraft.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Gemini misreads the bill | Totals validator, then `ModelRetry`, then the host edit screen |
| Model tool calling is unreliable | `PromptedOutput` for extraction; `AGENT_MODEL` can point the tool agent at a different model |
| Payment-link response shape is unknown | Log the raw response, try several candidate keys, check at kickoff |
| Webhook can't reach the app or isn't delivered | Poll the payment-link status every 5 seconds |
| Venue Wi-Fi drops | Mock mode, a recorded backup video, and a hotspot |
| Spending real money by accident | `MAX_TXN_USD`, `MAX_TEAM_USD`, `CHARGE_SCALE`, refunds before 3:30 PM |

## 14. Roadmap (not today)

WhatsApp bot entry point, Redis hub, mobile-money payout to the host, receipt PDFs, multi-currency, per-person tips, offline queue.
