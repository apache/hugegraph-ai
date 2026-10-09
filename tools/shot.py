#!/usr/bin/env python3
# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Screenshot helper over CDP (dev tool, not a test).

    python3 tools/shot.py --base http://127.0.0.1:8000 --out /tmp/shots \
        --routes /:/graph:/agent --width 1600 --height 1000
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
VK = {"Tab": 9, "Escape": 27, "Enter": 13}


class Chrome:
    def __init__(self, port: int = 9333):
        self.port = port
        self.proc = None
        self.ws = None
        self.msg_id = 0
        self.profile = tempfile.mkdtemp(prefix="ontogeny-shot-")

    async def start(self):
        import httpx
        import websockets

        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
             "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(80):
            try:
                async with httpx.AsyncClient() as c:
                    r = await c.get(f"http://127.0.0.1:{self.port}/json/version", timeout=1)
                    if r.status_code == 200:
                        targets = (await c.get(f"http://127.0.0.1:{self.port}/json/list")).json()
                        page = next(t for t in targets if t.get("type") == "page")
                        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=2 ** 26)
                        return
            except Exception:
                pass
            await asyncio.sleep(0.25)
        raise RuntimeError("chrome did not come up")

    async def send(self, method, **params):
        self.msg_id += 1
        mid = self.msg_id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            raw = json.loads(await self.ws.recv())
            if raw.get("id") == mid:
                if "error" in raw:
                    raise RuntimeError(f"{method}: {raw['error']}")
                return raw.get("result", {})

    async def goto(self, url, wait=2.0):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(wait)

    async def eval(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def set_viewport(self, width, height):
        await self.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                        deviceScaleFactor=1, mobile=False)
        await asyncio.sleep(0.3)

    async def shot(self, path: Path):
        res = await self.send("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        path.write_bytes(base64.b64decode(res["data"]))

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default="/tmp/ontogeny-shots")
    ap.add_argument("--routes", default="/")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--theme", default="light")
    ap.add_argument("--script", default="", help="JS evaluated after load, per route")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ch = Chrome()
    await ch.start()
    try:
        await ch.send("Page.enable")
        await ch.send("Runtime.enable")
        await ch.set_viewport(args.width, args.height)
        await ch.goto(f"{args.base}/", wait=2.5)
        await ch.eval(f"localStorage.setItem('ontogeny.theme', {json.dumps(args.theme)})")
        for route in args.routes.split(":"):
            if not route.strip():
                continue
            await ch.goto(f"{args.base}{route}", wait=2.2)
            await ch.eval(f"document.documentElement.setAttribute('data-theme', {json.dumps(args.theme)})")
            if args.script:
                result = await ch.eval(args.script)
                print("script ->", result)
                await asyncio.sleep(2.0)
            name = (route.strip("/").replace("/", "_") or "root") + f"_{args.theme}.png"
            await ch.shot(out / name)
            print("wrote", out / name)
    finally:
        await ch.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
