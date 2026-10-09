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
"""A tiny query benchmark over a real ServiceContext -- the missing baseline.

Not part of the test suite (numbers are environmental); run it before/after
query-engine changes and compare like with like:

    python tools/bench_query.py                      # demo package, 200 iters
    python tools/bench_query.py --iters 1000
    ONTOGENY_BENCH_DSN=sqlite+aiosqlite:////tmp/b.db \\
        ONTOGENY_BENCH_PACKAGE=/path/to/pkg python tools/bench_query.py

Measures per object type: search-all, filtered search, and (for the golden
package) a 2-hop traversal. Reports p50/p95 in milliseconds.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRINCIPAL = {"id": "bench", "Role": ["auditor"]}


def pct(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return ordered[idx]


async def bench(sc, iters: int) -> None:
    from ontogeny.agent.catalog import build_catalog

    catalog = build_catalog(sc.compiled)
    searches = sorted(n for n, t in catalog.items() if t.kind == "search")
    traverses = [n for n, t in catalog.items() if t.kind == "traverse"]

    print(f"{'probe':<44} {'p50 ms':>8} {'p95 ms':>8} {'n':>5}")
    print("-" * 70)
    for name in searches:
        target = catalog[name].target
        # a real field to filter on, so the filter path is exercised too
        field = next(iter(sc.compiled.objects[target].spec.properties))
        async def _run(s, filt=None):
            return await sc.query.query(s, target, PRINCIPAL, filt=filt, limit=20)
        for label, filt in (("all", None),
                            (f"filter:{field}", {"field": field, "op": "contains", "value": ""})):
            samples = []
            for _ in range(iters):
                async with sc.sessionmaker() as s:
                    t0 = time.perf_counter()
                    await _run(s, filt)
                    samples.append((time.perf_counter() - t0) * 1000)
            print(f"{name} [{label}]".ljust(44)
                  + f" {pct(samples, .5):8.1f} {pct(samples, .95):8.1f} {iters:5d}")
    for name in traverses:
        # a cheap deterministic traversal: first object of the first type
        first_type = sorted(sc.compiled.objects)[0]
        async with sc.sessionmaker() as s:
            page = await sc.query.query(s, first_type, PRINCIPAL, limit=1)
        rows = page.get("rows") or []
        if not rows:
            continue
        start_id = rows[0].get("id") or rows[0].get(next(iter(rows[0])))
        links = sorted(sc.compiled.links)
        if not links:
            continue
        path = [{"link": links[0], "direction": "out"}]
        samples = []
        for _ in range(iters):
            async with sc.sessionmaker() as s:
                t0 = time.perf_counter()
                await sc.query.traverse(s, first_type, [start_id], PRINCIPAL, path)
                samples.append((time.perf_counter() - t0) * 1000)
        print(f"traverse[{links[0]},1hop]:".ljust(44)
              + f" {pct(samples, .5):8.1f} {pct(samples, .95):8.1f} {iters:5d}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=200)
    args = ap.parse_args()

    from ontogeny.config import Settings
    from ontogeny.demo import seed_from_package
    from ontogeny.service import ServiceContext

    tmp = Path(tempfile.mkdtemp(prefix="ontogeny-bench-"))
    try:
        pkg_src = Path(os.environ.get("ONTOGENY_BENCH_PACKAGE")
                       or REPO / "domains" / "product-manufacturing")
        pkg = tmp / "pkg"
        shutil.copytree(pkg_src, pkg)
        src = tmp / "src.db"
        seed_from_package(pkg_src, src, force=True)
        dsn = os.environ.get("ONTOGENY_BENCH_DSN") or f"sqlite+aiosqlite:///{tmp/'main.db'}"
        sc = ServiceContext(Settings(db_dsn=dsn,
                                     env={"ERP_DSN": f"sqlite+aiosqlite:///{src}"}), str(pkg))
        await sc.initialize()
        for t in sc.compiled.objects:
            await sc.sync(t)
        await bench(sc, args.iters)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
