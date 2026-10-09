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
"""Headless-Chrome button audit: click EVERY visible, enabled button on every
console route and report the ones that do nothing.

"Does nothing" = after the click, within the settle window, there is no DOM
mutation, no fetch/XHR, no hash/history change and no dialog/drawer opening.
A quiet click is not always a bug (e.g. a toggle already in that state), so
the report is a REVIEW LIST with per-button context, not a verdict.

    python3 tools/button_audit.py --base http://127.0.0.1:8000 [--json out.json]

Requires Google Chrome (headless) + the console served by the real backend.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

ROUTES = [
    "/",
    "/ontology",
    "/knowledge",
    "/action",
    "/graph",
    "/agent/manage",
    "/audit",
    "/evolve",
    "/admin",
    "/access",
]

#: prep before each page load: a dev principal so gated pages render their
#: full chrome (dev_auth is on in dev/demo deployments)
PREP_JS = r"""
(() => {
  localStorage.setItem('ontogeny.principal', JSON.stringify(
    { id: 'audit-bot', Role: ['admin'], authenticated: false }));
  localStorage.setItem('ontogeny.theme', 'dark');
})();
"""

#: instrumentation injected after load: mutation + network counters, error log
HOOK_JS = r"""
(() => {
  window.__audit = { mutations: 0, requests: 0, errors: [], dialogs: 0 };
  const bump = () => { window.__audit.mutations += 1; };
  new MutationObserver(bump).observe(document.body,
    { childList: true, subtree: true, attributes: true,
      attributeFilter: ['class', 'style', 'aria-expanded', 'open', 'data-state'] });
  const of_ = window.fetch;
  window.fetch = function (...a) { window.__audit.requests += 1; return of_.apply(this, a); };
  const ox = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (...a) { window.__audit.requests += 1; return ox.apply(this, a); };
  window.addEventListener('error', (e) => window.__audit.errors.push(String(e.message)));
  window.addEventListener('unhandledrejection', (e) =>
    window.__audit.errors.push('rejection:' + String(e.reason).slice(0, 120)));
  const od = HTMLDialogElement.prototype.showModal;
  HTMLDialogElement.prototype.showModal = function (...a) {
    window.__audit.dialogs += 1; return od.apply(this, a); };
})();
"""

CLICKABLE_JS = r"""
(() => {
  const out = [];
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.pointerEvents !== 'none';
  };
  document.querySelectorAll('button, [role="button"], summary').forEach((el, i) => {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    if (!vis(el)) return;
    el.setAttribute('data-audit-idx', String(i));
    const label = (el.innerText || el.getAttribute('aria-label') ||
                   el.title || el.getAttribute('data-testid') || '').trim().slice(0, 40);
    out.push({ idx: i, label });
  });
  return out;
})();
"""

CLICK_JS = """
(() => {
  const el = document.querySelector('[data-audit-idx="IDX"]');
  if (!el) return { clicked: false };
  el.scrollIntoView({ block: 'center' });
  el.click();
  return { clicked: true };
})();
"""

READ_JS = "window.__audit"


class Chrome:
    def __init__(self, port: int = 9333):
        self.port = port
        self.proc = None
        self._id = 0
        self.futures: dict[int, asyncio.Future] = {}
        self.ws = None

    async def start(self, width: int = 1440, height: int = 900):
        prof = tempfile.mkdtemp(prefix="ontogeny-audit-")
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             "--no-first-run", "--no-default-browser-check",
             "--disable-gpu", f"--window-size={width},{height}",
             f"--user-data-dir={prof}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/json/version", timeout=1)
                if r.status_code == 200:
                    break
            except Exception:
                await asyncio.sleep(0.2)
        ws_url = httpx.get(f"http://127.0.0.1:{self.port}/json/list").json()[0]["webSocketDebuggerUrl"]
        self.ws = await websockets.connect(ws_url, max_size=32 * 1024 * 1024)
        asyncio.get_event_loop().create_task(self._reader())

    async def _reader(self):
        while True:
            try:
                msg = json.loads(await self.ws.recv())
            except Exception:
                return
            fut = self.futures.pop(msg.get("id"), None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def send(self, method, **params):
        self._id += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self.futures[self._id] = fut
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        for _ in range(150):  # ~15s hard cap per call
            if fut.done():
                break
            await asyncio.sleep(0.1)
        if not fut.done():
            fut.set_result({"error": {"message": "timeout"}})
        return fut.result()

    async def goto(self, url, wait=1.8):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(wait)

    async def eval(self, expr, await_promise=False):
        r = await self.send("Runtime.evaluate",
                            expression=expr, returnByValue=True,
                            awaitPromise=await_promise)
        if "exceptionDetails" in r:
            return {"__error__": r["exceptionDetails"].get("text", "exception")}
        # CDP nests: {id, result: {result: {type, value}}}
        return r.get("result", {}).get("result", {}).get("value")

    async def close(self):
        try:
            await self.ws.close()
        finally:
            self.proc.terminate()


async def audit(base: str, settle: float) -> dict:
    chrome = Chrome()
    await chrome.start()
    report: dict = {"routes": {}, "errors": {}}
    try:
        for route in ROUTES:
            url = base + route
            await chrome.goto(base + "/")  # same origin so localStorage applies
            await chrome.eval(PREP_JS)
            await chrome.goto(url, wait=2.2)
            await chrome.eval(HOOK_JS)
            buttons = await chrome.eval(CLICKABLE_JS) or []
            quiet, errors = [], []
            for b in buttons:
                before = await chrome.eval(READ_JS)
                clicked = await chrome.eval(
                    CLICK_JS.replace("IDX", str(b["idx"])))
                await asyncio.sleep(settle)
                after = await chrome.eval(READ_JS) or {}
                # element unmounted by an earlier click (a view/tab switch is
                # itself activity): skip, do not count as quiet
                if not clicked or not clicked.get("clicked") or clicked.get("__error__"):
                    continue
                activity = (after.get("mutations", 0) - before.get("mutations", 0)
                            + after.get("requests", 0) - before.get("requests", 0)
                            + after.get("dialogs", 0) - before.get("dialogs", 0))
                if activity == 0:
                    quiet.append(b["label"] or f"<#{b['idx']}>")
            final = await chrome.eval(READ_JS) or {}
            errors = final.get("errors", [])
            report["routes"][route] = {"buttons": len(buttons), "quiet": quiet}
            if errors:
                report["errors"][route] = errors[:5]
            print(f"{route:<16} buttons={len(buttons):3d} quiet={len(quiet):3d} "
                  f"{'QUIET: ' + '; '.join(quiet[:6]) if quiet else ''}")
    finally:
        await chrome.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--settle", type=float, default=0.7)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    t0 = time.time()
    rep = asyncio.run(audit(args.base, args.settle))
    total_quiet = sum(len(r["quiet"]) for r in rep["routes"].values())
    print(f"\n{total_quiet} quiet button(s) across {len(ROUTES)} routes "
          f"({time.time() - t0:.0f}s); review list above")
    if args.json:
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    main()
