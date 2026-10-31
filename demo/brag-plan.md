# TrackSplit demo film — plan

**Angle:** the whole product in one dinner: one bill, three phones, everyone pays their exact share, then the same engine runs a shop counter.
**Hook (0–4s):** "8 friends. 1 bill." and the actual receipt drops in: "Who had the T-bone?"
**Tone:** default (punchy, clean) in the app's own theme: teal / orange / warm yellow on mint, Plus Jakarta Sans.
**Format:** 1920×1080, 30 fps, 40 s (asked for 30–45 s). 120 BPM, every cut on a bar.
**Data:** fictional restaurant (Mwezi Grill House), fictional people (Mwila, Alice, Bwalya, Chanda), mock DevDraft checkout. No real keys, URLs or customers.

Every phone screen is a real screenshot of the running app (`film/capture.py` drives the real flow against a throwaway DB).
One exception: the "after Gemini read the photo" screen is the real edit screen filled with the sample bill's lines, because no Gemini key was set when filming.

| Time | Scene | On screen |
|---|---|---|
| 0–4 | Hook | "8 friends." / "1 bill." / receipt drops in / "Who had the T-bone?" |
| 4–10 | Snap | Tap Take photo, shutter flash, scan line over the bill; phone fills with items; "Gemini reads every line."; "Lines match the total" |
| 10–14 | Share | Host page with QR; "Share one link." / "Friends scan the QR. No app, no sign-up." |
| 14–22 | Live | Alice, Bwalya, Chanda's phones; taps on each; all three update on the beat; "Tap what you had." → "Every phone updates live." |
| 22–28 | Pay | Mobile money (PIN prompt → success), card, USDC; Paid badges; "Everyone pays their exact share." |
| 28–32 | Settled | Paid bill + host's payout approval; "Everyone's paid." / "Money only leaves after the host taps Approve." |
| 32–36 | Shop | Cart of 3 Cokes → payment QR → paid; receipt printer; stock 12 → 9 |
| 36–40 | Outro | TrackSplit wordmark, tagline, Gemini · DevDraft · DigitalOcean · MIT |

**Sound:** synthesized in C at 120 BPM (pads, bass, kick from the first cut, hats from Share, claps from Live). Tap ticks (C6), live-update blips (E6→G6), payment bells (C-E-G-C), whooshes into cuts, shutter click, stock ticks. Mixed under the music, -14 LUFS.
