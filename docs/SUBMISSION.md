# TrackSplit

**Snap the bill and everyone pays their exact share from their own phone, live.**

Splitting a bill in a group usually means one person pays, someone works it out on a calculator, and the payback gets chased over WhatsApp for days. With TrackSplit, the host photographs the bill and AI reads every line item, the tax and the service charge. The host checks it, then shares a link or QR code. Friends tap what they ate, and shared plates split automatically. Each person pays their exact share by mobile money (MTN, Airtel, Zamtel), card or USDC through DevDraft. Every phone updates live, and everyone gets a PDF receipt.

The same engine runs a shop counter for small businesses. Photograph the items, and TrackSplit matches them to the product catalogue, takes payment and updates the stock. Restocking works the same way: photograph the delivery note.

We developed on DeepSeek and Gemma; production runs Google Gemini 2.5 Flash through Pydantic AI, and switching model is one setting. The model only reads the photo. Tested code does all the money maths, so shares always add up to the bill exactly. Spending caps limit every payment, and payouts and stock changes need a human to approve them. DevDraft's sandbox went down during the hackathon, so we built a full mock checkout, and the real integration switches back on with one setting.

Built with FastAPI + WebSockets, hosted on DigitalOcean. Open source (MIT).
