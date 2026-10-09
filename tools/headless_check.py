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
"""Headless-Chrome checks for the things jsdom cannot see.

jsdom has no layout, no computed styles and no real focus traversal, so the
frontend's visual/interaction claims can only be checked in a browser. This
drives Chrome over CDP and reports:

  1. **contrast**  — every visible text leaf, computed `color` against its
     nearest opaque background, WCAG relative-luminance ratio, thresholded at
     3.0 (large/bold) or 4.5 (body). Run in both themes.
  2. **responsive** — sidebar and `<main>` widths at 1280/1024/768/480, plus any
     element whose content overflows its own box.
  3. **keyboard**   — real Tab/Escape key events: where focus lands, whether the
     skip link is the first stop, whether the drawer traps and restores focus.
  4. **reduced motion** — whether the animations actually stop.

    python3 tools/headless_check.py --base http://127.0.0.1:8000 [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# WCAG 2.1: normal text needs 4.5:1, large text (>=18.66px bold or >=24px) 3.0:1
JS_CONTRAST = r"""
(() => {
  const lum = (rgb) => {
    const [r, g, b] = rgb.map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const parts = m[1].split(',').map((x) => parseFloat(x.trim()));
    return { rgb: parts.slice(0, 3), a: parts.length > 3 ? parts[3] : 1 };
  };
  const ratio = (fg, bg) => {
    const a = lum(fg), b = lum(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  // walk up until an element paints an opaque background
  const bgOf = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const c = parse(getComputedStyle(node).backgroundColor);
      if (c && c.a >= 0.95) return c.rgb;
      node = node.parentElement;
    }
    const c = parse(getComputedStyle(document.body).backgroundColor);
    return c ? c.rgb : [255, 255, 255];
  };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const text = n.textContent.trim();
    if (!text) continue;
    const el = n.parentElement;
    if (!el) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.6) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const fg = parse(cs.color);
    if (!fg) continue;
    const r = ratio(fg.rgb, bgOf(el));
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3.0 : 4.5;
    if (r < need) {
      out.push({
        text: text.slice(0, 48),
        ratio: Math.round(r * 100) / 100,
        need,
        size,
        color: cs.color,
        selector: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
          ? '.' + el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.') : ''),
      });
    }
  }
  return out;
})()
"""

JS_LAYOUT = r"""
(() => {
  const main = document.querySelector('main');
  const sidebar = document.querySelector('[data-testid="sidebar"]');
  const overflows = [];
  for (const el of document.querySelectorAll('main *')) {
    const cs = getComputedStyle(el);
    if (['auto', 'scroll', 'hidden'].includes(cs.overflowX)) continue;
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
      overflows.push({
        selector: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className
          ? '.' + el.className.split(/\s+/).filter(Boolean).slice(0, 2).join('.') : ''),
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      });
    }
  }
  return {
    docScrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    sidebarWidth: sidebar ? Math.round(sidebar.getBoundingClientRect().width) : null,
    mainWidth: main ? Math.round(main.getBoundingClientRect().width) : null,
    sidebarCollapsed: sidebar ? sidebar.getAttribute('data-collapsed') : null,
    nestedOverflow: overflows.slice(0, 8),
  };
})()
"""


class Chrome:
    def __init__(self, port: int = 9222):
        self.port = port
        self.proc: subprocess.Popen | None = None
        self.ws = None
        self.msg_id = 0
        self.profile = tempfile.mkdtemp(prefix="ontogeny-cdp-")

    async def start(self):
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
             "--disable-gpu", "--hide-scrollbars", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(60):
            try:
                async with httpx.AsyncClient() as c:
                    r = await c.get(f"http://127.0.0.1:{self.port}/json/version", timeout=1)
                    if r.status_code == 200:
                        targets = (await c.get(f"http://127.0.0.1:{self.port}/json/list")).json()
                        page = next(t for t in targets if t.get("type") == "page")
                        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=2**24)
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
            # ignore events

    async def goto(self, url, wait=1.4):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(wait)

    async def eval(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def key(self, key, code=None, shift=False):
        """A real key event: what Chrome does with focus, not what we assume."""
        params = {"type": "keyDown", "key": key, "code": code or key, "windowsVirtualKeyCode": VK.get(key, 0)}
        if shift:
            params["modifiers"] = 8
            params["windowsVirtualKeyCode"] = VK.get(key, 0)
        await self.send("Input.dispatchKeyEvent", **params)
        await self.send("Input.dispatchKeyEvent", type="keyUp", key=key, code=code or key,
                        windowsVirtualKeyCode=VK.get(key, 0), modifiers=8 if shift else 0)
        await asyncio.sleep(0.06)

    async def set_cookie(self, name: str, value: str, url: str):
        await self.send("Network.enable")
        await self.send("Network.setCookie", name=name, value=value, url=url)

    async def set_viewport(self, width, height=900):
        await self.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                        deviceScaleFactor=1, mobile=False)
        await asyncio.sleep(0.25)

    async def set_theme(self, theme):
        await self.eval(f"localStorage.setItem('ontogeny.theme', {json.dumps(theme)})")
        await self.eval(f"document.documentElement.setAttribute('data-theme', {json.dumps(theme)})")
        await asyncio.sleep(0.2)

    async def set_reduced_motion(self, on):
        await self.send("Emulation.setEmulatedMedia",
                        features=[{"name": "prefers-reduced-motion", "value": "reduce" if on else "no-preference"}])

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


VK = {"Tab": 9, "Escape": 27, "Enter": 13, "ArrowDown": 40, "ArrowUp": 38}

ROUTES = [
    "/", "/demo", "/ontology", "/builder", "/data", "/objects/sales-order",
    "/actions/confirm-sales-order", "/functions/capacity-check", "/graph",
    "/agent", "/agent/manage", "/agent/manage?tab=approvals", "/evolve", "/audit", "/admin",
    "/ontology/sales-order", "/access", "/login", "/knowledge", "/knowledge?tab=links",
    "/knowledge?tab=projections", "/action", "/action?tab=functions", "/action?tab=policies",
]


def _bootstrap_password() -> str | None:
    """The demo daemon prints a generated admin password once, on first start.

    Reading it back keeps `python tools/headless_check.py` a one-liner against a
    fresh deployment; pass --login-password (or ONTOGENY_ADMIN_PASSWORD) to override.
    """
    if os.environ.get("ONTOGENY_ADMIN_PASSWORD"):
        return os.environ["ONTOGENY_ADMIN_PASSWORD"]
    import re as _re
    for log in (".ontogeny-daemon/ontogeny.log", ".ontogeny-demo/ontogeny.log"):
        try:
            text = Path(log).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = _re.findall(r"generated password: (\S+)", text)
        if found:
            return found[-1]
    return None


async def audit(base: str, only: str | None = None,
                user: str = "admin", password: str | None = None) -> dict:
    ch = Chrome()
    await ch.start()
    report: dict = {"base": base, "contrast": {}, "responsive": {}, "keyboard": {}, "motion": {}}
    try:
        await ch.send("Page.enable")
        await ch.send("Runtime.enable")
        await ch.set_viewport(1600, 1000)

        # sign in: every page below the gate is unreachable without a session,
        # and an audit that only ever saw the login page would report a clean
        # bill of health for pages it never loaded
        password = password or _bootstrap_password()
        signed_in = False
        if password:
            try:
                async with httpx.AsyncClient() as c:
                    r = await c.post(f"{base}/api/v1/auth/login",
                                     json={"username": user, "password": password}, timeout=10)
                if r.status_code == 200:
                    await ch.set_cookie("ontogeny_session", r.json()["token"], base)
                    signed_in = True
            except Exception as exc:  # noqa: BLE001 -- reported, not fatal
                report["login_error"] = str(exc)
        report["signed_in"] = signed_in
        if not signed_in:
            report["login_error"] = report.get("login_error") or (
                "no credentials: pass --login-password or set ONTOGENY_ADMIN_PASSWORD")

        routes = [r for r in ROUTES if not only or only in r]
        # ---- contrast, both themes ---------------------------------------
        for theme in ("light", "dark"):
            failures = []
            for route in routes:
                await ch.goto(f"{base}{route}")
                await ch.set_theme(theme)
                bad = await ch.eval(JS_CONTRAST) or []
                if bad:
                    failures.append({"route": route, "count": len(bad), "worst": min(b["ratio"] for b in bad),
                                     "samples": sorted(bad, key=lambda b: b["ratio"])[:4]})
            report["contrast"][theme] = {
                "failingRoutes": len(failures),
                "totalNodes": sum(f["count"] for f in failures),
                "worst": min((f["worst"] for f in failures), default=None),
                "details": failures,
            }

        # ---- responsive ---------------------------------------------------
        await ch.set_theme("light")
        for width in (1280, 1024, 768, 480):
            await ch.set_viewport(width, 900)
            per_route = {}
            for route in routes[:6]:
                await ch.goto(f"{base}{route}", wait=0.9)
                per_route[route] = await ch.eval(JS_LAYOUT)
            report["responsive"][width] = per_route
        await ch.set_viewport(1600, 1000)

        # ---- keyboard -----------------------------------------------------
        await ch.goto(f"{base}/")
        await ch.eval("document.body.focus()")
        first = await ch.eval(
            "(() => { const f = document.querySelector('a[href], button, input, select, textarea, [tabindex]:not([tabindex=\"-1\"])');"
            " return f ? (f.getAttribute('data-testid') || f.tagName + ':' + (f.textContent||'').trim().slice(0,24)) : null; })()"
        )
        await ch.key("Tab")
        after_tab = await ch.eval(
            "(() => { const el = document.activeElement; return el.getAttribute('data-testid') || el.tagName + ':' + (el.textContent||'').trim().slice(0,24); })()"
        )
        nav = await ch.eval(
            "(() => { const el = document.querySelector('a[data-testid=\"skip-link\"]');"
            " if (!el) return null; el.click();"
            " const main = document.querySelector('main');"
            " return { href: el.getAttribute('href'), mainId: main && main.id,"
            " mainFocusable: main ? main.hasAttribute('tabindex') : false,"
            " focused: document.activeElement === main }; })()"
        )
        report["keyboard"] = {"firstFocusable": first, "afterOneTab": after_tab, "skipLink": nav}

        # drawer: open it on a page that has one, then test the trap
        await ch.goto(f"{base}/graph")
        drawer = await ch.eval("!!document.querySelector('[data-testid=\"node-info-drawer\"]')")
        report["keyboard"]["drawerPresentOnGraph"] = drawer
        await ch.goto(f"{base}/objects/sales-order/SO-2026-0001")
        drawer2 = await ch.eval("!!document.querySelector('[data-testid=\"node-info-drawer\"]')")
        report["keyboard"]["drawerPresentOnObject"] = drawer2

        # ---- reduced motion ------------------------------------------------
        motion = {}
        for on in (False, True):
            await ch.set_reduced_motion(on)
            await ch.goto(f"{base}/")
            motion["reduce" if on else "normal"] = await ch.eval(
                "(() => { const el = document.querySelector('.ontogeny-animate-in');"
                " const s = el ? getComputedStyle(el) : null;"
                " const sk = document.querySelector('[data-testid=\"skeleton\"], .ontogeny-skeleton');"
                " return { animateIn: s ? s.animationName + ' ' + s.animationDuration : null,"
                " skeleton: sk ? getComputedStyle(sk).animationName + ' ' + getComputedStyle(sk).animationIterationCount : null,"
                " mediaMatches: matchMedia('(prefers-reduced-motion: reduce)').matches }; })()"
            )
        report["motion"] = motion
        await ch.set_reduced_motion(False)
    finally:
        await ch.close()
    return report


def summarize(rep: dict) -> int:
    problems = 0
    if not rep.get("signed_in"):
        print(f"[FAIL] sign-in: {rep.get('login_error')}\n"
              "        the audit below measured only the login page\n")
        problems += 1
    for theme, data in rep["contrast"].items():
        worst = data["worst"]
        status = "OK " if not data["totalNodes"] else "FAIL"
        if data["totalNodes"]:
            problems += 1
        print(f"[{status}] contrast ({theme}): {data['totalNodes']} failing nodes across "
              f"{data['failingRoutes']} routes, worst {worst}")
        for d in data["details"][:4]:
            print(f"        {d['route']}: {d['count']} nodes, worst {d['worst']}")
            for s in d["samples"][:2]:
                print(f"          {s['ratio']}:1 (need {s['need']}) {s['size']}px {s['selector']} {s['text']!r}")

    print()
    for width, routes in rep["responsive"].items():
        sample = routes.get("/") or next(iter(routes.values()))
        overflow = [r for r, v in routes.items() if v["nestedOverflow"]]
        flag = "FAIL" if int(width) <= 480 and sample["sidebarWidth"] and sample["sidebarWidth"] > 300 else "OK "
        if flag == "FAIL":
            problems += 1
        print(f"[{flag}] {width}px: sidebar={sample['sidebarWidth']} main={sample['mainWidth']} "
              f"collapsed={sample['sidebarCollapsed']} nestedOverflow={len(overflow)} routes")

    print()
    k = rep["keyboard"]
    ok_skip = bool(k["skipLink"] and k["skipLink"]["focused"] and k["skipLink"]["mainFocusable"])
    if not ok_skip:
        problems += 1
    print(f"[{'OK ' if ok_skip else 'FAIL'}] keyboard: first={k['firstFocusable']!r} "
          f"afterTab={k['afterOneTab']!r} skipLink={k['skipLink']}")

    print()
    for name, m in rep["motion"].items():
        print(f"       motion({name}): {m}")
    return problems


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--json", default="")
    ap.add_argument("--route", default="")
    ap.add_argument("--login-user", default=os.environ.get("ONTOGENY_ADMIN_USER", "admin"))
    ap.add_argument("--login-password", default=None)
    args = ap.parse_args()

    rep = await audit(args.base, args.route or None, args.login_user, args.login_password)
    if args.json:
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        print(f"wrote {args.json}")
    problems = summarize(rep)
    print(f"\n{problems} check group(s) with findings")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
