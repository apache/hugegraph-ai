# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and
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
        return (
            f"WEB_CONCURRENCY={workers}: ontogeny is a single-process kernel "
            "(registry + outbox + workers in-process); run exactly one "
            "worker per database, or split the database by domain"
        )
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
        import asyncio
        import logging

        # uvicorn's own logger is configured to INFO by default (the "ontogeny"
        # logger is not), so the deployment contract is actually visible
        log = logging.getLogger("uvicorn.error")
        log.info(
            "ontogeny single-process kernel up (registry + outbox + "
            "derivation + evolve + projection workers all in-process; "
            "do NOT scale with uvicorn workers)"
        )
        suspicion = multiprocess_suspected()
        if suspicion:
            log.error("MULTIPROCESS DEPLOYMENT SUSPECTED: %s", suspicion)
        try:
            await sc.initialize()
            if os.environ.get("ONTOGENY_DEMO_POPULATE") == "1" and sc.package_root:
                total = 0
                for object_type in sc.compiled.objects if sc.compiled else {}:
                    async with sc.sessionmaker() as s:
                        summary = await sc.sync_engine.sync(s, object_type)
                        await s.commit()
                    total += int(summary.get("inserted", 0))
                logging.getLogger("ontogeny.demo").info(
                    "demo data synced: %d rows across %d object types", total, len(sc.compiled.objects)
                )

            async def _evolve_worker():
                from .evolve.ops import run_diagnose

                while True:
                    await asyncio.sleep(minutes * 60)
                    try:
                        async with sc.sessionmaker() as s:
                            evo = getattr(sc.compiled, "evolution", None)
                            obs = getattr(getattr(evo, "spec", None), "observability", None) if evo else None
                            await sc.telemetry.aggregate_signals(s, thresholds=getattr(obs, "thresholds", None) or None)
                            await s.commit()
                        await run_diagnose(sc)
                        logging.getLogger("ontogeny.evolve").info("evolve cycle ok")
                    except Exception as exc:
                        logging.getLogger("ontogeny.evolve").warning("evolve cycle failed: %s", exc)

            async def _outbox_worker():
                while True:
                    try:
                        # Publish/domain switches replace the runtime. Resolve
                        # its dispatcher on every tick, never retain an old one.
                        await sc.outbox.dispatch_pending()
                    except Exception as exc:
                        logging.getLogger("ontogeny.outbox").warning("outbox tick failed: %s", exc)
                    await asyncio.sleep(1.0)

            evo = getattr(sc.compiled, "evolution", None)
            spec = getattr(evo, "spec", None)
            minutes = int(getattr(spec, "interval_minutes", 0) or 0) if spec else 0
            async with base_lifespan(app):

                def log_task_failure(task):
                    if not task.cancelled() and task.exception() is not None:
                        exc = task.exception()
                        log.error(
                            "background task %s failed", task.get_name(), exc_info=(type(exc), exc, exc.__traceback__)
                        )

                tasks = []
                try:
                    tasks.append(asyncio.create_task(_outbox_worker(), name="ontogeny-outbox"))
                    app.state.outbox_task = tasks[0]
                    if getattr(spec, "loop", False) and minutes > 0:
                        app.state.evolve_task = asyncio.create_task(_evolve_worker(), name="ontogeny-evolve")
                        tasks.append(app.state.evolve_task)
                    for task in tasks:
                        task.add_done_callback(log_task_failure)
                    yield
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Initialization can fail partway through; close only resources
            # that were actually created, after background tasks have stopped.
            resources = [getattr(sc, "functions", None), getattr(sc, "projection_client", None), sc.llm]
            resources.extend(outbox.http for outbox in sc._outbox_instances)
            closed = set()
            for resource in resources:
                if resource is None or id(resource) in closed:
                    continue
                closed.add(id(resource))
                close = getattr(resource, "aclose", None)
                if close is not None:
                    try:
                        await close()
                    except Exception:
                        log.exception("resource shutdown failed")
            if sc.engine is not None:
                await sc.engine.dispose()

    app.router.lifespan_context = lifespan
    return app
