# TrackSplit — Build Prompt & Step-by-Step Spec

Paste the **Prompt** section into Claude Code or Codex at the repo root. The **Steps** are the build order. Each step has an acceptance check, and you should not start the next step until the current check passes. The product and design reference is [TRACKSPLIT.md](TRACKSPLIT.md). Read it first.

Deadlines today (31 Oct 2026, CAT): **refund live test payments by 15:30**, **submit by 16:30**.

---

## Prompt

```text
You are building TrackSplit, a hackathon web app, in this repo. Read docs/TRACKSPLIT.md fully first; it is the spec.
Build it in the order of docs/BUILD_PROMPT.md "Steps", verifying each step's acceptance check before moving on.

Product in one line: photo of a bill -> Gemma 4 extracts typed line items -> shareable live receipt where each person
taps what they ordered -> each person gets a DevDraft payment link for their exact share -> webhooks mark them paid
live on every phone. Second mode: shop owner photographs items on the counter -> matched against the product DB for
prices -> stock is decremented on payment and a receipt is issued.

Stack (do not substitute):
- Python 3.13, uv, FastAPI, uvicorn (ONE worker), Jinja2 templates, SQLModel on SQLite, httpx.
- pydantic-ai-slim[google] for all LLM work. Model ids come from env: LLM_MODEL (vision extraction, Gemma 4),
  AGENT_MODEL (tool-using agent, defaults to LLM_MODEL). Provider: GoogleModel + GoogleProvider(api_key=GEMINI_API_KEY).
- UI: Tailwind browser CDN + daisyUI 5 CDN + Alpine.js CDN. No JS build step. Mobile-first. Theme "emerald" light,
  "dim" dark. Use daisyUI components (card, btn, badge, avatar-group, modal, drawer, stat, radial-progress,
  file-input, mockup-phone, toast). Read the daisyUI skill before writing templates if available.
- Real time: FastAPI WebSocket, in-memory hub (dict slug -> set[WebSocket]). Mutations go via HTTP POST; after every
  mutation broadcast a full state snapshot. Clients render only from snapshots.

Hard rules:
1. The LLM only extracts. All money math, rounding, tax/service allocation, currency conversion and stock changes
   are pure Python in app/split.py and app/shop.py with tests. Prices in shop mode come from the DB, never the model.
2. Money is integer minor units (ngwee). Shares must sum exactly to the receipt total (largest-remainder rounding).
3. Every LLM output is a Pydantic model via output_type. Use PromptedOutput for the extraction agents (Gemma may
   lack native tool calling) and put instructions in the user message, not only the system prompt.
4. Any tool that moves money out or changes stock is requires_approval=True; the UI shows an approve modal.
5. DevDraft: base https://api.devdraft.ai, headers x-client-key / x-client-secret, Idempotency-Key uuid4 on POST.
   DEVDRAFT_MODE=mock|live. Mock returns /mock-pay/{payment_id} links whose Pay button calls the same internal
   "mark paid" function the webhook uses. Refuse any link > MAX_TXN_USD (5) or team total > MAX_TEAM_USD (50)
   before calling the API. Log raw DevDraft responses. Read the pay URL from the first present key of
   url|paymentUrl|link|checkoutUrl. Verify webhook x-webhook-signature = hex HMAC-SHA256(raw body, DEVDRAFT_WEBHOOK_SECRET).
   Also poll GET /api/v0/payment-links/{id} every 5 s for splits in "settling" as a fallback.
6. Secrets only from env (.env, gitignored). Never print or commit keys.
7. Keep it small: no auth system, no ORM migrations tool, no frontend framework, no abstractions with one impl.
   Fewest files that stay readable. Each non-trivial pure function gets a test in tests/.

Reuse ideas from ~/Dev/django_web_agent (read, don't import):
- backend/django_agent/attachments.py: VISION_PROMPT wording, upload size/type limits (8 MB, jpeg/png/webp).
- backend/django_agent/agent.py: requires_approval tools + DeferredToolRequests flow for the approve modal.
- backend/django_agent/llm.py: single cached get_model() reading env.

When done with each step, run its acceptance check and tell me the result in one line. If something in the spec is
impossible (e.g. DevDraft returns an unexpected shape), stop and show me the raw response instead of guessing.
```

---

## Target layout

```
pyproject.toml            # uv; deps: fastapi uvicorn[standard] jinja2 sqlmodel httpx python-multipart
                          #       pydantic-ai-slim[google] python-dotenv qrcode[pil]
.env.example
app/
  main.py                 # FastAPI app, page routes, API routes, ws route, webhook, mock-pay
  db.py                   # engine, SQLModel tables (TRACKSPLIT.md §6), get_session
  schemas.py              # LLM IO + SplitState models
  llm.py                  # get_model(), receipt_reader, counter_reader, restock_reader, counter_agent
  split.py                # pure money math (+ snapshot builder)
  shop.py                 # product matching, cart pricing, stock moves
  devdraft.py             # live/mock client, caps, webhook verify
  hub.py                  # websocket rooms + broadcast
  templates/  base.html index.html new.html split.html host.html shop.html receipt.html demo.html mock_pay.html
  static/app.js           # tiny: ws connect + reconnect, token per ?d=
skills/receipt-reader/SKILL.md  # open-source agent skill + CLI usage
tests/test_split.py tests/test_shop.py tests/test_devdraft.py
seed.py                   # demo business + 15 Lusaka products
LICENSE (MIT)  README.md
```

## Env

```dotenv
GEMINI_API_KEY=
LLM_MODEL=gemma-4-...            # exact Gemma 4 id from models.list; fallback gemini-2.5-flash
AGENT_MODEL=                      # empty = LLM_MODEL
DEVDRAFT_MODE=mock                # mock | live
DEVDRAFT_CLIENT_KEY=
DEVDRAFT_CLIENT_SECRET=
DEVDRAFT_WEBHOOK_SECRET=
PUBLIC_BASE_URL=http://localhost:8000
FX_ZMW_PER_USD=26.5               # set the real rate on the day
CHARGE_SCALE=1                    # 0.01 for live demo so a K450 bill charges cents
MAX_TXN_USD=5
MAX_TEAM_USD=50
DATABASE_URL=sqlite:///tracksplit.db
```

---

## Steps

Times are targets from a 12:15 start. If you fall behind, cut the steps marked *(cut-able)*.

### Step 0: Scaffold (12:15–12:30)
- `uv init`, add deps, `.env.example`, `.gitignore` (`.env`, `*.db`, `uploads/`), MIT `LICENSE`.
- `app/main.py` serves `/` from `base.html` + `index.html` (daisyUI hero, two buttons). `GET /health` returns ok.
- **Accept:** `uv run uvicorn app.main:app` works, and `/` renders with daisyUI styling on a phone-width viewport.

### Step 1: Money math, test-first (12:30–12:55)
`app/split.py`, pure functions with no DB:
- `allocate(total: int, weights: list[int]) -> list[int]`: largest remainder. The result sums to `total`, and all-zero weights split evenly.
- `unit_costs(line_total: int, qty: int) -> list[int]`
- `shares(items, claims, extras_minor) -> dict[participant_id, int]`: a unit claimed by k people is split with `allocate`, and extras are allocated in proportion to each person's item subtotal.
- `to_usdc(minor: int) -> Decimal` using `FX_ZMW_PER_USD` and `CHARGE_SCALE`, rounded to 2 places, minimum 0.01.
- **Accept:** `uv run pytest tests/test_split.py` passes. Required cases:
  - 3 people with uneven items and 16% VAT plus 10% service: the shares sum to the total exactly.
  - One shared unit claimed by 3 people.
  - Leftover units.
  - Rounding with a total of K100.01.

### Step 2: DB + seed (12:55–13:05)
- `app/db.py` holds the tables from TRACKSPLIT.md §6. `create_all` runs on startup.
- `seed.py` creates the business "Kaizen Café". Products (name, aliases, price in ngwee, stock): Mosi 375ml, Castle Lite, Coke 500ml, Fanta, Maheu, Nshima & chicken, Nshima & beef, Chips, Village chicken, T-bone, Kapenta, Samoosa, Bottled water, Rolls, Tea.
- **Accept:** `uv run python seed.py` creates the products, and running it twice does not create duplicates.

### Step 3: Gemma extraction (13:05–13:35)
- `app/llm.py`:
  - `get_model(env_key)`, cached.
  - `receipt_reader = Agent(model, output_type=PromptedOutput(ReceiptExtract))`.
  - The instruction prompt goes in the user message together with `BinaryContent(data, media_type)`. Adapt `VISION_PROMPT` from django_web_agent: copy numbers exactly, put unclear text in `unreadable`, and never invent items.
  - `@receipt_reader.output_validator` checks that the line totals sum to the subtotal and that subtotal + tax + service ≈ total (±1% or ±K1). If not, raise `ModelRetry("lines sum to X but subtotal is Y; re-read the line items")`.
  - Define `counter_reader` the same way with `CounterExtract` (no prices).
- `POST /api/extract/receipt` (multipart image, max 8 MB, jpeg/png/webp) returns `ReceiptExtract` JSON.
- **Accept:** with a real bill photo, curl returns valid JSON and the totals check passes. Write down which model id worked. If Gemma fails on the API, set `LLM_MODEL` to the fallback and note it.

### Step 4: Create split + host review page (13:35–13:55)
- `/new` has a camera `file-input` (`accept="image/*" capture="environment"`). On upload it calls the extract endpoint and shows a loading state ("Gemma is reading your bill…"). It then shows an editable item table (name/qty/line total) and editable extras, plus a live "lines vs total" check badge and a **payee** toggle (`My wallet` / `Business wallet`).
- `POST /api/splits` saves the Receipt, its items and the Split, and returns the slug (8 random URL-safe characters). The host is added automatically as a participant.
- It then redirects to `/s/{slug}/host`, which shows a QR code (`qrcode` generates a PNG served at `/s/{slug}/qr.png`) and the share link.
- **Accept:** photo, edit screen and created split all work, and the QR code opens `/s/{slug}` on a phone that is on the same LAN.

### Step 5: Live split (13:55–14:35), the core of the demo
- `app/hub.py`: `join(slug, ws, participant_id)`, `leave`, `broadcast_state(slug)` (builds `SplitState` from the DB and sends it to everyone), `send_to(participant_id, msg)`.
- The API routes from TRACKSPLIT.md §10 each check the token, change the DB, then call `broadcast_state`.
  - `claim` toggles a claim.
  - A confirmed participant cannot change their claims until they unconfirm.
- `split.html` (Alpine):
  - Name modal on first visit. The token is stored in `localStorage` under `ts:{slug}:{d}`, where `d` is the `?d=` query value or `"me"`.
  - Item cards each have one pill per unit. Tapping a pill toggles the claim, and an `avatar-group` shows everyone who claimed it.
  - Sticky bottom bar with "My share K…" and a Confirm button. After confirming it shows "Pay K… ($…)", and after paying a ✅ and a receipt link.
  - The WebSocket reconnects every 2 seconds after a drop.
- `/s/{slug}/host` shows the live participant table, a `radial-progress` for amount claimed and amount paid, and buttons to assign the leftovers.
- `/demo?slug=` shows 4 `mockup-phone` iframes: host, then `?d=alice`, `?d=bwalya`, `?d=chanda`.
- **Accept:** on `/demo`, claims made on one phone appear on all the others in under 1 second. All shares add up to the total. Two different names in two iframes count as separate people.

### Step 6: DevDraft payments (14:35–15:05)
- `app/devdraft.py`:
  - `create_payment_link(payment) -> (link_id, url)`: checks the caps, then makes the live or mock call. The live body is in TRACKSPLIT.md §9, with `url` slug `ts-{slug}-{payment_id}` and `customFields.payment_id`.
  - `verify_signature(raw, header)`.
  - `mark_paid(payment_id)`: idempotent. It updates the Payment and Participant, broadcasts, and when everyone has paid it sets the split to `paid` and creates a `Payout(proposed)` if the payee is the host.
  - `list_wallets()`.
- `confirm` creates the Payment and the link, then sends `pay_link` only to that participant.
- `POST /webhooks/devdraft` verifies the signature, finds the Payment (by custom field, link id or slug, whichever the payload has; log the payload), then calls `mark_paid`.
- Background task: while any split is `settling`, poll the status of each pending link every 5 seconds.
- `/mock-pay/{id}`: a daisyUI card with a "Pay $x" button that calls `mark_paid`.
- The host payout modal on the host page is the "agent wants to send $x to your wallet — Approve / Decline" step, using the approval pattern from `requires_approval`. Approve sets `Payout.approved` (plus the live transfer call, if DevDraft confirmed the endpoint).
- **Accept:**
  - Mock mode: all 4 phones pay, everything turns green live, and the payout modal appears.
  - Live mode: **one** real link for $0.01–$0.50 is paid from a phone, and the webhook or the poller marks it paid.
  - Refund it before 15:30 and write down the refund time.

### Step 7: Shop mode (15:05–15:35) *(trim if late: drop restock and the agent chat)*
- `app/shop.py`:
  - `match(label) -> Product | None`: lowercase, then `difflib.get_close_matches` over name plus aliases with cutoff 0.6.
  - `price_cart(lines) -> Cart` (DB prices).
  - `commit_sale(cart, receipt_id)`: in one transaction, inserts `StockMove(-qty)` rows and refuses to go below 0.
- `/shop` has a products table with stock badges (`badge-error` at or below the threshold), a "Snap counter" button that calls `counter_reader` then `match` and opens the cart drawer, and editable quantities with unmatched items highlighted. "Charge" creates one payment link (with a QR code); "Split this" creates a split from the cart.
- When the payment completes, call `commit_sale` and render the receipt at `/r/{id}`.
- *(cut-able)* `counter_agent` chat with the tools `search_products`, `get_stock`, `adjust_stock` (approval).
- *(cut-able)* Restock by photographing a delivery note.
- **Accept:** a photo of 3 Cokes produces a cart of 3 Cokes at the DB price. After payment, stock drops by 3 and the receipt page shows it.

### Step 8: Deploy + skill + submit (15:35–16:20)
- DigitalOcean App Platform, Python buildpack. Run command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`. Instance count **1**. Set env vars in the dashboard and set `PUBLIC_BASE_URL` to the app URL.
- Register the DevDraft webhook to `{PUBLIC_BASE_URL}/webhooks/devdraft`.
- SQLite on App Platform is temporary and gets wiped on redeploy, which is fine for a demo. Run `seed.py` on startup if the DB is empty.
- `skills/receipt-reader/SKILL.md` covers what the skill does, its input and output (the `ReceiptExtract` schema), and the CLI `uv run python -m app.llm receipt photo.jpg`.
- README with a pitch paragraph, a screenshot or GIF, how to run, the env table, the 3 challenges it targets, and the MIT license. Add the GitHub topic `hacktoberfest`.
- **Accept:** a phone on mobile data opens the deployed split link and claims live. The MLH submission is in **before 16:30**, entered in all 3 categories.

---

## Definition of done (judge checklist)

- [ ] Bill photo becomes extracted items through **Gemma 4** (DeepMind track)
- [ ] Open-source repo with an MIT license, the open-weight model, and the `receipt-reader` skill (DigitalOcean track)
- [ ] A working DevDraft payment flow, at least 1 real paid link, the webhook or poller marks it paid, and human approval is shown for the payout (DevDraft track, 30% of its score)
- [ ] Live multi-device split working over the deployed URL
- [ ] Stock decrements on a shop sale
- [ ] All live payments refunded before 15:30, and the team total stayed ≤ $50
- [ ] No keys in git (`git log -p | grep -i secret` is clean)
