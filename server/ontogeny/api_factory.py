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
"""ASGI entrypoint for ``uvicorn ontogeny.api_factory --factory``."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager


def multiprocess_suspected() -> str | None:
    """Why we think this process is part of a multi-worker deployment, if we do.

    ontogeny is a SINGLE-PROCESS kernel: the registry, the outbox dispatcher, the
    derivation drain, the evolve worker and the projection worker all live in
    this one process, and the demo's SQLite file cannot arbitrate writers.
    uvicorn honours WEB_CONCURRENCY for its worker count, so that env var is
    our one reliable early signal -- checked at lifespan startup, before the
    duplicate workers have stepped on each other.
    """
    try:
        workers = int(os.environ.get("WEB_CONCURRENCY", "1") or "1")
    except ValueError:
        return None
    if workers > 1:
        return (f"WEB_CONCURRENCY={workers}: ontogeny is a single-process kernel "
                "(registry + outbox + workers in-process); run exactly one "
                "worker per database, or split the database by domain")
    return None


def create_app_factory():
    from .api import build_app
    from .config import load_settings
    from .service import ServiceContext

    settings = load_settings()
    sc = ServiceContext(
        settings,
        os.environ.get("ONTOGENY_PACKAGE_ROOT") or None,
        ui_dir=os.environ.get("ONTOGENY_UI_DIR") or None,
    )
    app = build_app(sc)
    # build_app's lifespan mounts the MCP surface once the compiled snapshot
    # exists -- which is only true AFTER initialize(), so it runs inside.
    base_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        import logging

        # uvicorn's own logger is configured to INFO by default (the "ontogeny"
        # logger is not), so the deployment contract is actually visible
        log = logging.getLogger("uvicorn.error")
        log.info("ontogeny single-process kernel up (registry + outbox + "
                 "derivation + evolve + projection workers all in-process; "
                 "do NOT scale with uvicorn workers)")
        suspicion = multiprocess_suspected()
        if suspicion:
            log.error("MULTIPROCESS DEPLOYMENT SUSPECTED: %s", suspicion)
        await sc.initialize()
        if os.environ.get("ONTOGENY_DEMO_POPULATE") == "1" and sc.package_root:
            # `ontogeny serve --demo`: a fresh demo boots with its source data
            # already synced (no guided story -- the console is the interface)
            import logging

            log = logging.getLogger("ontogeny.demo")
            total = 0
            for object_type in (sc.compiled.objects if sc.compiled else {}):
                async with sc.sessionmaker() as s:
                    summary = await sc.sync_engine.sync(s, object_type)
                    await s.commit()
                total += int(summary.get("inserted", 0))
            log.info("demo data synced: %d rows across %d object types", total,
                     len(sc.compiled.objects))
        # direction F: the observe+diagnose beats on the domain's cadence.
        # Promotion is NEVER automatic from here -- the ladder keeps its gates.
        import asyncio
        import logging

        log = logging.getLogger("ontogeny.evolve")

        async def _evolve_worker():
            from .evolve.ops import run_diagnose

            while True:
                await asyncio.sleep(minutes * 60)
                try:
                    async with sc.sessionmaker() as s:
                        evo = getattr(sc.compiled, "evolution", None)
                        obs = getattr(getattr(evo, "spec", None), "observability", None) if evo else None
                        await sc.telemetry.aggregate_signals(
                            s, thresholds=getattr(obs, "thresholds", None) or None)
                        await s.commit()
                    await run_diagnose(sc)
                    log.info("evolve cycle ok")
                except Exception as exc:  # noqa: BLE001 -- a failed beat must not kill the loop
                    log.warning("evolve cycle failed: %s", exc)

        evo = getattr(sc.compiled, "evolution", None)
        spec = getattr(evo, "spec", None)
        minutes = int(getattr(spec, "interval_minutes", 0) or 0) if spec else 0
        if getattr(spec, "loop", False) and minutes > 0:
            app.state.evolve_task = asyncio.get_running_loop().create_task(_evolve_worker())
        async with base_lifespan(app):
            yield
        task = getattr(app.state, "evolve_task", None)
        if task is not None:
            task.cancel()

    app.router.lifespan_context = lifespan
    return app
