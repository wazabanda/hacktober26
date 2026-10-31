"""Minimal Chrome DevTools Protocol client (headless Chrome started with --remote-debugging-port)."""

import asyncio
import base64
import itertools
import json

import httpx
import websockets


class Page:
    @classmethod
    async def open(cls, port: int = 9333) -> "Page":
        target = httpx.put(f"http://127.0.0.1:{port}/json/new?about:blank").json()
        p = cls()
        p.ws = await websockets.connect(target["webSocketDebuggerUrl"], max_size=2**30)
        p.ids, p.pending = itertools.count(1), {}
        p.reader = asyncio.create_task(p._read())
        await p.send("Page.enable")
        return p

    async def _read(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if msg.get("id") in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)

    async def send(self, method: str, **params):
        i = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        msg = await fut
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def eval(self, expr: str):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"]))
        return r.get("result", {}).get("value")

    async def viewport(self, w: int, h: int, dpr: float = 1, mobile: bool = False):
        await self.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=dpr, mobile=mobile)

    async def goto(self, url: str, wait: float = 1.5):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(wait)

    async def shot(self, path: str, fmt: str = "png", quality: int | None = None):
        params = {"format": fmt, **({"quality": quality} if quality else {})}
        data = (await self.send("Page.captureScreenshot", **params))["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
