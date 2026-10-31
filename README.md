# TrackSplit

Snap a bill → share a link → everyone taps what they ordered → each person pays their exact share via DevDraft, live on every phone.
Snap the shop counter → items matched to the product DB → stock tracked → receipt sent.

Gemma 4 (vision) · Pydantic AI · FastAPI + WebSockets · daisyUI · DevDraft · DigitalOcean. MIT.

- Spec & architecture: [docs/TRACKSPLIT.md](docs/TRACKSPLIT.md)
- Build prompt & step-by-step plan: [docs/BUILD_PROMPT.md](docs/BUILD_PROMPT.md)

## Run it locally

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 for you). From the repo root:

```bash
uv sync                                   # install dependencies
cp .env.example .env                      # then edit .env (see below)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The demo shop (Kaizen Café, 15 products) is seeded automatically on startup into `tracksplit.db`.

Open:

| URL | What |
|---|---|
| http://localhost:8000 | Home |
| http://localhost:8000/demo | Sample bill on 4 simulated phones (host + Alice, Bwalya, Chanda). Fastest way to see everything working. |
| http://localhost:8000/new | Split a real bill: take a photo, check the items, create the split, share the link/QR |
| http://localhost:8000/shop | Shop mode: snap the counter or tap + on products, then Charge or Split |

### Minimum `.env`

Payments run in mock mode by default, so you only need a model key for photo reading:

```dotenv
LLM_MODEL=deepseek:deepseek-chat   # or a Gemma 4 id like gemma-4-..., which uses GEMINI_API_KEY
DEEPSEEK_API_KEY=...               # or GEMINI_API_KEY=... for Gemma / Gemini
DEVDRAFT_MODE=mock
PUBLIC_BASE_URL=                   # leave blank locally
```

Without a key, everything except reading photos still works: use "or type it in" on `/new`, or tap products on `/shop`.

### Use your phone

1. Put your phone on the same Wi-Fi as the laptop.
2. Find the laptop's IP: `ip -4 addr` on Linux, `ipconfig getifaddr en0` on macOS.
3. On the phone, open `http://<laptop-ip>:8000/new` and tap **Take photo**. The camera opens directly.
4. Create the split. Send the link (or show the QR code) to friends on the same Wi-Fi.

For phones on other networks, deploy it (below) or tunnel it, e.g. `cloudflared tunnel --url http://localhost:8000`.

### Sample bills to photograph

```bash
uv run python -m samples.make_bills       # writes samples/bill-*.pdf
```

Open one on the laptop screen and photograph it with the phone.

### Mock payments

With `DEVDRAFT_MODE=mock`, the Pay button opens a fake DevDraft checkout (`/mock-pay/{id}`). Pressing Pay there marks the person paid exactly the way the real webhook does: their row turns green on every phone, and when everyone has paid the host gets the payout approval prompt. Every receipt can be downloaded as a PDF from `/r/{id}`.

### Tests

```bash
uv run pytest
```

### Run with Docker

```bash
docker build -t tracksplit .
docker run --rm -p 8000:8080 --env-file .env tracksplit
```

## Deploy (DigitalOcean App Platform)

1. Push to GitHub.
2. In the DigitalOcean dashboard, go to Apps → Create App → pick this repo and branch `master`. It builds the `Dockerfile`.
3. Set the HTTP port to `8080` and the instance count to **1**. The live-update hub lives in memory, so it must stay a single instance.
4. Add the environment variables from [.do/app.yaml](.do/app.yaml) and put keys in as encrypted values.
5. Open `https://<your-app>.ondigitalocean.app/new` on any phone.

You can also run `doctl apps create --spec .do/app.yaml`. The SQLite database is reset on every redeploy, and the demo shop is re-seeded.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `LLM_MODEL` | none | Model that reads photos. A bare id (e.g. a Gemma 4 id) uses the Gemini API; `provider:model` (e.g. `deepseek:deepseek-chat`) uses that provider |
| `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` | none | Key for that provider |
| `DEVDRAFT_MODE` | `mock` | `mock` or `live` |
| `DEVDRAFT_CLIENT_KEY`, `DEVDRAFT_CLIENT_SECRET`, `DEVDRAFT_WEBHOOK_SECRET` | none | Live DevDraft only. Webhook URL: `{PUBLIC_BASE_URL}/webhooks/devdraft` |
| `PUBLIC_BASE_URL` | blank = the URL the page was opened on | Public app URL, used in share links and payment links |
| `FX_ZMW_PER_USD` | `26.5` | Kwacha per US dollar |
| `CHARGE_SCALE` | `1` | Multiplies what is charged in USDC, e.g. `0.01` for cent-sized live demos |
| `MAX_TXN_USD` / `MAX_TEAM_USD` | `5` / `50` | Live payment caps, checked before calling DevDraft |
| `DATABASE_URL` | `sqlite:///tracksplit.db` | SQLite file |

## License

MIT, see [LICENSE](LICENSE).
