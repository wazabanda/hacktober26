"""Render compose.html frame by frame with headless Chrome (CDP on :9333).

uv run python demo/film/render.py --stills 1 5.5 ...   -> demo/work/stills/t*.jpg (review)
uv run python demo/film/render.py                      -> demo/work/frames/%05d.jpg (all frames)
"""

import argparse
import asyncio
import json
from pathlib import Path

from cdp import Page

HERE = Path(__file__).resolve().parent
WORK = HERE.parent / "work"
TL = json.loads((HERE / "timeline.json").read_text())


async def main(stills: list[float]):
    p = await Page.open()
    await p.viewport(1920, 1080, dpr=1)
    await p.send("Page.addScriptToEvaluateOnNewDocument", source=f"window.TL = {json.dumps(TL)};")
    await p.goto((HERE / "compose.html").as_uri(), wait=1)
    await p.eval("window.ready")
    if stills:
        out = WORK / "stills"
        out.mkdir(parents=True, exist_ok=True)
        for t in stills:
            await p.eval(f"render({t})")
            await p.shot(out / f"t{t:05.2f}.jpg", fmt="jpeg", quality=88)
        return
    out = WORK / "frames"
    out.mkdir(parents=True, exist_ok=True)
    n = int(TL["duration"] * TL["fps"])
    for f in range(n):
        await p.eval(f"render({f / TL['fps']})")
        await p.shot(out / f"{f:05d}.jpg", fmt="jpeg", quality=92)
        if f % 150 == 0:
            print(f"frame {f}/{n}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", type=float, nargs="*", default=[])
    asyncio.run(main(ap.parse_args().stills))
