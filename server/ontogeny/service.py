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
"""ServiceContext: the single composition root.

REST API, MCP server, CLI and background workers are thin shells over this
object -- governance (transactions, policy, audit) has exactly one path.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from .action import ActionRuntime, OutboxDispatcher, SseBroker
from .auth import AuthService
from .agent.broker import AgentBroker
from .config import Settings
from .core.loader import load_package
from .db import init_schema, make_engine, make_sessionmaker
from .engine import QueryService
from .errors import DSLValidationError, NotFoundError, OOError, StoreError
from .evolve import Promoter
from .evolve.evalrunner import EvalRunner
from .ext_host import ExtensionHost
from .functions import DeclarativeRuntime, DerivationWorker, FunctionRuntime, FunctionSandbox
from .policy import PolicyEngine
from .projection import ProjectionWorker, compile_projection
from .registry import RegistryService
from .registry.compiled import CompiledOntology, domain_graph_name
from .stores import ObjectRepository, SyncEngine
from .stores.sources import make_source
from .telemetry import TelemetryService

log = logging.getLogger("ontogeny.service")

_DOMAIN_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,62}")
# resource directories a scaffolded (empty) domain ships with, so the builder
# and hand-editing both have the conventional layout to write into
_DOMAIN_DIRS = ("objects", "links", "actions", "functions", "policies", "stores", "evals")


class DomainError(OOError):
    """Bad domain name or the domain already exists."""

    code = "DOMAIN_INVALID"
    http_status = 400


def _read_manifest(path: Path) -> dict[str, Any]:
    """ontology.yaml of the package at ``path`` as a plain dict ({} on any
    failure -- listing must survive a half-written domain directory)."""
    try:
        import yaml

        doc = yaml.safe_load((Path(path) / "ontology.yaml").read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001 -- listing is best-effort by design
        return {}


def _manifest_name(path: Path) -> str | None:
    meta = _read_manifest(path).get("metadata") or {}
    name = meta.get("name")
    return str(name) if isinstance(name, str) else None


def _count_yaml(path: Path) -> int:
    return len(list(path.glob("*.yaml"))) if path.is_dir() else 0


def _check_package(path: Path) -> dict[str, Any]:
    """Dynamic health check for one domain: load the package from disk and run
    the semantic validator, the same bar activation will apply. Listing stays
    best-effort: a package that fails to parse reports ``ok: false`` with the
    first errors instead of breaking the switcher."""
    try:
        from .core import load_package, validate

        rep = validate(load_package(str(path)))
        if rep.ok:
            return {"ok": True, "errors": []}
        return {"ok": False,
                "errors": [f"{i.resource}: {i.message}" for i in rep.issues if i.severity == "error"][:5]}
    except Exception as exc:  # noqa: BLE001 -- any failure is the check's answer
        return {"ok": False, "errors": [str(exc)[:300]]}


def _pk_from_graph_id(graph_id: Any) -> str | None:
    """HugeGraph stores a projected object as ``<labelId>:<primaryKey>``."""
    if graph_id is None:
        return None
    text = str(graph_id)
    key = text.split(":", 1)[1] if ":" in text else text
    return key or None


#: Why the projection layer is not wired, in one sentence each. The console
#: shows these instead of a generic failure, because each one has a DIFFERENT
#: fix and none of them is "declare a projection".
_PROJECTION_BLOCK_REASONS = {
    "not-declared": "no projection declared",
    "provider-sqlite": "storage provider is {provider}, not 'hugegraph', so nothing is projected",
    "endpoint-unresolved": "the projection endpoint ${HUGEGRAPH_URL} cannot be resolved "
                           "(set the HugeGraph address in the storage configuration)",
    "extension-missing": "the graph-hugegraph extension is not loaded, so there is no "
                         "graph client to wire",
}


def _display_of(obj: dict, compiled: CompiledOntology, object_type: str) -> str:
    """Best human label for a preview row (name-like field, else the key)."""
    for candidate in ("name", "display", "title"):
        if obj.get(candidate):
            return str(obj[candidate])
    pk = compiled.objects[object_type].spec.primaryKey[0]
    return str(obj.get(pk, ""))


def _mask_dsn(dsn: str) -> str:
    """A DSN with the password removed and the noise trimmed, so the console
    can show WHERE data lives without leaking credentials."""
    import re as _re

    if not dsn:
        return ""
    if dsn.startswith(("sqlite", "csv")) or dsn.startswith("/"):
        tail = dsn.split("///", 1)[-1]
        return f"file: {tail}" if not dsn.startswith("csv") else f"file: {dsn}"
    m = _re.match(r"(\w+\+?\w*)://([^:/@]+)(?::[^@]*)?@([^/]+)/(\S+)", dsn)
    if m:
        return f"{m.group(1)}://{m.group(2)}@{m.group(3)}/{m.group(4)}"
    m = _re.match(r"(\w+\+?\w*)://([^/@]+)?@?([^/]+)/(\S+)", dsn)
    if m:
        user = f"{m.group(2)}@" if m.group(2) else ""
        return f"{m.group(1)}://{user}{m.group(3)}/{m.group(4)}"
    return dsn[:80]


class ServiceContext:
    def __init__(self, settings: Settings, package_root: str | None = None,
                 *, projection_http: httpx.AsyncClient | None = None,
                 llm_http: httpx.AsyncClient | None = None,
                 ui_dir: str | None = None,
                 package_root_override: str | None = None) -> None:
        self.settings = settings
        self.package_root = package_root
        # The package this process booted from (ONTOGENY_PACKAGE_ROOT). Domain
        # activation moves `package_root`, but the boot package stays listed
        # and switchable -- it is the deployment's default domain.
        self.boot_package_root = package_root
        # On DB-only boots the snapshot has no directory to point at; if the
        # caller knows where the package lives on disk, use it for sidecars
        # (function sources, reprojection of policy text).
        self.package_root_override = package_root_override
        self.ui_dir = ui_dir  # built SPA directory served same-origin (optional)
        from .layout import LayoutStore
        self._layout = LayoutStore(package_root)
        self.registry = RegistryService()
        self.engine = None
        self.sessionmaker = None
        self.compiled: CompiledOntology | None = None
        self.sse = SseBroker()
        self.projection_http = projection_http
        self.llm_http = llm_http
        # extension-pluggable surfaces (populated by extensions/ at boot):
        # sc.llm (capability:llm), sc.graph_store_factory (capability:graph-store),
        # sc.agent_engines (engine factories). The core only defines contracts.
        self.llm = None
        self.graph_store_factory = None
        self.agent_engines: dict[str, Any] = {}
        self.ext: ExtensionHost | None = None

    # ------------------------------------------------------------- lifecycle

    async def initialize(self) -> "ServiceContext":
        self.engine = make_engine(self.settings.db_dsn)
        await init_schema(self.engine)
        self.sessionmaker = make_sessionmaker(self.engine)
        # Persisted console configuration is applied BEFORE extensions load, so
        # a saved LLM/HugeGraph endpoint wins over the process environment.
        await self._load_runtime_settings()
        self.ext = ExtensionHost(self)
        self.ext.discover()
        self.ext.load()  # providers set sc.llm / sc.graph_store_factory; engines register factories
        # A deployment with no administrator is unreachable -- nobody could
        # create the first account -- so bootstrap runs once, on an empty table,
        # right after the schema exists.
        self.auth = AuthService(self)
        await self.auth.ensure_admin()
        async with self.sessionmaker() as session:
            compiled = await self.registry.load_latest(session)
        if compiled is None:
            if self.package_root is None:
                raise StoreError("registry is empty and no ONTOGENY_PACKAGE_ROOT configured to publish from")
            compiled = await self.publish(self.package_root)
        else:
            self._rebuild_services(compiled)
            async with self.sessionmaker() as session:
                await self.repo.ensure(session)
        return self

    async def _load_runtime_settings(self) -> None:
        """Apply the console-saved configuration row over the process environment.

        "Over" is precise: the row wins where it says something, and stays out of
        the way where it does not. A row with no HugeGraph URL is NOT an
        instruction to forget ``HUGEGRAPH_URL`` — that variable is usually the
        deployment's own (daemon.sh, compose.yaml), and every
        ``${HUGEGRAPH_URL}`` in the DSL resolves against it. Deleting it here
        turned "the console never stored a URL" into "this deployment has no
        graph endpoint", which silently disabled a working projection. Only an
        explicit console choice of ``sqlite`` withdraws the endpoint.
        """
        from .runtime_config import load_runtime_config

        async with self.sessionmaker() as session:
            row = await load_runtime_config(session)
        if row is None:
            return
        env = dict(self.settings.env)
        storage_provider = row.storage_provider or ("hugegraph" if row.hugegraph_url else self.settings.storage_provider)
        if storage_provider == "hugegraph":
            # the row's endpoint, else whatever the process was started with
            url = row.hugegraph_url or os.environ.get("HUGEGRAPH_URL")
            if url:
                env["HUGEGRAPH_URL"] = url
        elif row.storage_provider == "sqlite":
            env.pop("HUGEGRAPH_URL", None)
            os.environ.pop("HUGEGRAPH_URL", None)
        self.settings = replace(
            self.settings,
            llm_provider=row.llm_provider or self.settings.llm_provider or "ollama",
            llm_base_url=row.llm_base_url or None,
            llm_model=row.llm_model or None,
            llm_api_key=row.llm_api_key or None,
            storage_provider=storage_provider,
            # Credentials follow the same rule as the URL: the row wins where it
            # says something, the deployment's own environment otherwise. They
            # are deliberately NOT exported into os.environ — an env var is
            # world-readable through /proc, and nothing outside this process
            # needs them (the graph client is constructed here).
            hugegraph_user=row.hugegraph_user or self.settings.hugegraph_user,
            hugegraph_password=row.hugegraph_password or self.settings.hugegraph_password,
            env=env,
        )
        if env.get("HUGEGRAPH_URL"):
            os.environ["HUGEGRAPH_URL"] = env["HUGEGRAPH_URL"]

    async def runtime_config(self) -> dict[str, Any]:
        """The LLM + storage configuration exposed to the operations console."""
        return {
            "llm": {
                "provider": self.settings.llm_provider or "ollama",
                "base_url": self.settings.llm_base_url,
                "model": self.settings.llm_model,
                "api_key_set": bool(self.settings.llm_api_key),
            },
            "storage": {
                "provider": self._storage_provider(),
                "url": self.settings.env.get("HUGEGRAPH_URL") or os.environ.get("HUGEGRAPH_URL"),
                "user": self.settings.hugegraph_user,
                # the password itself never leaves the server, exactly like the
                # LLM api key: the console learns only whether one is set
                "password_set": bool(self.settings.hugegraph_password),
            },
        }

    async def configure_runtime(
        self, *,
        llm_provider: str | None = None,
        llm_base_url: str | None = None,
        llm_model: str | None = None,
        llm_api_key: str | None = None,
        storage_provider: str | None = None,
        storage_url: str | None = None,
        storage_user: str | None = None,
        storage_password: str | None = None,
    ) -> dict[str, Any]:
        """Persist + hot-apply the LLM and storage provider selections."""
        from .runtime_config import save_runtime_config

        provider = (llm_provider or self.settings.llm_provider or "ollama").lower()
        storage = (storage_provider or self.settings.storage_provider or "sqlite").lower()
        env = dict(self.settings.env)
        # A blank URL field means "keep whatever endpoint is in effect" — the
        # deployment's own HUGEGRAPH_URL when the console has none — exactly as a
        # blank API key means "keep the secret". It must NOT mean "erase it":
        # that silently dropped a working graph endpoint and, because the
        # resolution scope is also exported into the process environment, took
        # the deployment's own variable down with it.
        if storage == "hugegraph":
            url = (storage_url or self.settings.env.get("HUGEGRAPH_URL")
                   or os.environ.get("HUGEGRAPH_URL"))
            if url:
                env["HUGEGRAPH_URL"] = url
        else:
            env.pop("HUGEGRAPH_URL", None)
        # A blank API key from the form means "keep the existing secret"; the UI
        # never receives the key back after it has been saved.
        api_key = llm_api_key if llm_api_key is not None else self.settings.llm_api_key
        if provider == "disabled":
            base_url = None
            model = None
            api_key = None
        else:
            base_url = llm_base_url if llm_base_url is not None else self.settings.llm_base_url
            model = llm_model if llm_model is not None else self.settings.llm_model
            if provider != "external":
                api_key = None
        # Same convention for the graph credentials: a blank password keeps the
        # stored one (the console never receives it back), a blank user clears
        # the pair so an operator can drop credentials when a server stops
        # enforcing auth.
        hg_user = storage_user if storage_user is not None else self.settings.hugegraph_user
        if not hg_user:
            hg_password = None
            hg_user = None
        else:
            hg_password = (storage_password if storage_password
                           else self.settings.hugegraph_password)
        self.settings = replace(
            self.settings,
            llm_provider=provider,
            llm_base_url=base_url or None,
            llm_model=model or None,
            llm_api_key=api_key or None,
            storage_provider=storage,
            hugegraph_user=hg_user or None,
            hugegraph_password=hg_password or None,
            env=env,
        )
        if env.get("HUGEGRAPH_URL"):
            os.environ["HUGEGRAPH_URL"] = env["HUGEGRAPH_URL"]
        elif storage != "hugegraph":
            # only an explicit switch away from HugeGraph withdraws the endpoint
            os.environ.pop("HUGEGRAPH_URL", None)

        async with self.sessionmaker() as session:
            await save_runtime_config(
                session,
                llm_provider=provider,
                llm_base_url=base_url or None,
                llm_model=model or None,
                llm_api_key=api_key or None,
                storage_provider=storage,
                # persist what the CONSOLE was told, not the resolved endpoint:
                # a NULL here means "inherit HUGEGRAPH_URL from the deployment",
                # which stays true even if the deployment later moves the graph
                storage_url=storage_url or None,
                storage_user=hg_user or None,
                storage_password=hg_password or None,
            )
            await session.commit()

        # Re-run provider registrations against the new settings, then rebuild
        # the service objects that captured the old clients/endpoints.
        old_llm = self.llm
        if old_llm is not None and hasattr(old_llm, "aclose"):
            try:
                await old_llm.aclose()
            except Exception:  # noqa: BLE001 -- old client teardown is best-effort
                pass
        self.llm = None
        self.graph_store_factory = None
        if self.ext is not None:
            self.ext.reload_providers()
        if self.compiled is not None:
            self._rebuild_services(self.compiled)
        return await self.runtime_config()

    def _storage_provider(self) -> str:
        """Effective storage provider, inferring HugeGraph from a configured URL.

        Tests and older deployments pass ``Settings(env={"HUGEGRAPH_URL": ...})``
        directly; those must keep working without an explicit storage-provider row.
        """
        configured = self.settings.storage_provider or "sqlite"
        if configured == "hugegraph":
            return "hugegraph"
        if self.settings.env.get("HUGEGRAPH_URL") or os.environ.get("HUGEGRAPH_URL"):
            return "hugegraph"
        return "sqlite"

    # ------------------------------------------------------- graph addressing

    def _graph_endpoint(self) -> str | None:
        """The HugeGraph endpoint, whether or not a projection is declared.

        A declared projection names it as a DSL reference (``${HUGEGRAPH_URL}``);
        without one the same variable is read straight from the resolution
        scope. The console needs this to answer "does this domain already have a
        graph?" *before* anything is declared — that answer is what decides
        whether the graph is loaded or built.
        """
        if self.compiled is not None and self.compiled.projections:
            declared = next(iter(self.compiled.projections.values()))
            try:
                return self.settings.resolve_env_ref(declared.spec.endpoint)
            except KeyError:
                return None
        return self.settings.env.get("HUGEGRAPH_URL") or os.environ.get("HUGEGRAPH_URL") or None

    def graph_name(self) -> str | None:
        """This domain's one graph name (``None``: no package loaded yet)."""
        if self.compiled is None:
            return None
        return domain_graph_name(self.compiled.package_name)

    async def graph_state(self) -> dict[str, Any]:
        """Whether the domain's graph exists on the server: ``True``/``False``/``None``.

        The three-valued answer is the point. ``True`` means the graph is there
        and its contents should be *loaded*; ``False`` means there is nothing to
        load and building is the only way forward; ``None`` means we could not
        find out (no endpoint, no graph extension, unreachable server) and the
        caller must not pretend otherwise.
        """
        name = self.graph_name()
        if name is None:
            return {"graph_name": None, "graphspace": None, "graph_exists": None}
        graphspace = "DEFAULT"
        if self.compiled is not None and self.compiled.projections:
            graphspace = next(iter(self.compiled.projections.values())).spec.graphspace
        if self._storage_provider() != "hugegraph" or self.graph_store_factory is None:
            return {"graph_name": name, "graphspace": graphspace, "graph_exists": None}
        endpoint = self._graph_endpoint()
        if not endpoint:
            return {"graph_name": name, "graphspace": graphspace, "graph_exists": None}
        probe = self.graph_store_factory(endpoint, name, graphspace=graphspace,
                                         http=self.projection_http,
                                         user=self.settings.hugegraph_user,
                                         password=self.settings.hugegraph_password,
                                         data_dir=self.settings.hugegraph_data_dir)
        try:
            exists = await probe.exists()
        except OOError as exc:
            # a probe we were not allowed to make must not read as "absent": the
            # console would offer a destructive build on a graph it cannot see
            return {"graph_name": name, "graphspace": graphspace, "graph_exists": None,
                    "probe_error": exc.message}
        return {"graph_name": name, "graphspace": graphspace, "graph_exists": exists,
                "auth_rejected": bool(getattr(probe, "auth_rejected", False))}

    def _apply_package_root_override(self, compiled: CompiledOntology) -> CompiledOntology:
        """Point a DB-loaded snapshot at the on-disk package when available."""
        candidate = self.package_root_override or self.package_root
        if candidate and Path(candidate).is_dir() \
                and Path(compiled.package_root).resolve() != Path(candidate).resolve() \
                and _manifest_name(candidate) == compiled.package_name:
            # only when the on-disk package IS the same package: a different
            # domain activated from domains/ must keep its own root, or builder
            # saves and promotions would land in the boot package's directory
            compiled = replace(compiled, package_root=str(candidate))
        if not Path(compiled.package_root).is_dir():
            # a snapshot rebuilt from the registry has no directory; a domain
            # activated from the domains root is deterministic to re-derive
            dom = self.domains_root() / compiled.package_name
            if dom.is_dir():
                compiled = replace(compiled, package_root=str(dom))
        return compiled

    async def publish(self, package_root: str, *, created_by: str | None = None) -> CompiledOntology:
        self.package_root = package_root
        pkg = load_package(package_root)
        async with self.sessionmaker() as session:
            compiled = await self.registry.publish(session, pkg, created_by=created_by or "ontogeny")
            await session.commit()
        self._rebuild_services(compiled)
        async with self.sessionmaker() as session:
            await self.repo.ensure(session)
        return compiled

    async def reload(self) -> CompiledOntology:
        """Refresh services from the registry (e.g. after an evolve promotion)."""
        async with self.sessionmaker() as session:
            compiled = await self.registry.load_latest(session)
        if compiled is not None and (
            self.compiled is None or compiled.content_hash != self.compiled.content_hash
        ):
            self._rebuild_services(compiled)
            async with self.sessionmaker() as session:
                await self.repo.ensure(session)
        return self.compiled  # type: ignore[return-value]

    def _rebuild_services(self, compiled: CompiledOntology) -> None:
        compiled = self._apply_package_root_override(compiled)
        if not Path(compiled.package_root).is_dir() and compiled.functions:
            log.warning(
                "packages loaded from the registry have no directory on disk; "
                "set ONTOGENY_PACKAGE_ROOT so function sources in %s can be resolved",
                sorted(compiled.functions),
            )
        self.compiled = compiled
        # the MCP tool list is a compiled artifact: a promote that changes the
        # ontology must be reflected at the next list_tools, not after a restart
        surface = getattr(self, "mcp_surface", None)
        if surface is not None:
            surface.refresh()
        self.repo = ObjectRepository(compiled)
        self.sync_engine = SyncEngine(
            compiled, self.settings, self.repo,
            lambda store: make_source(store, self.settings.resolve_env_ref(store.spec.connection)),
        )
        self.policy = PolicyEngine(compiled)
        # sc.llm comes from an llm-provider extension (llm-ollama ships with the
        # repo); None means "capability absent" and every LLM consumer degrades.
        # The sandbox shares the platform LLM gateway: ontogeny.llm() inside a
        # function is budgeted + routed here, never called from the child
        self.sandbox = FunctionSandbox(compiled, self.repo, llm=self.llm,
                                       llm_call_timeout_s=self.settings.llm_call_timeout_s)
        # Both ways of having a body, behind one door: code runs in the sandbox,
        # a declarative pipeline runs here through the same engine and gateway
        # the sandbox reaches over RPC. Every caller uses `self.functions`, so
        # the two cannot drift in budgeting, masking or error reporting.
        self.functions = FunctionRuntime(self.sandbox, DeclarativeRuntime(
            llm=self.llm, repo=self.repo, compiled=compiled,
            http_allowlist=list(self.settings.function_http_allowlist or ()),
            resolve_ref=self.settings.resolve_env_ref,
            llm_call_timeout_s=self.settings.llm_call_timeout_s,
        ))
        self.derivation = DerivationWorker(compiled, self.repo, self.functions, self.sessionmaker)
        self.runtime = ActionRuntime(
            compiled, self.repo, self.policy, self.settings,
            function_runner=self._function_runner,
        )
        self.query = QueryService(compiled, self.repo, self.policy)
        self.telemetry = TelemetryService(compiled)
        self.eval_runner = EvalRunner(self.repo, self.query)
        self.promoter = Promoter(self.settings, self.registry)
        # evolution proposer: the LLM decides by default when a provider is
        # configured (bounded by the mutation catalog + schema validation --
        # see ontogeny.evolve.proposer.DecidingProposer); without one the loop runs
        # the deterministic heuristic proposer unchanged
        from .evolve.proposer import DecidingProposer
        self.proposer = DecidingProposer(self.llm)

        # optional projection layer (zero dependency unless declared AND configured;
        # the graph store comes from a graph extension -- without one, or with an
        # unresolvable endpoint, the platform degrades gracefully to SQL-only)
        self.projection_worker = None
        self.projection_client = None
        self.projection_decl = None
        # WHY the layer is not wired, as a stable code. "Declared" and "wired"
        # are different questions, and a console that conflates them offers
        # "create a projection" for a package that already has one -- an action
        # the backend then refuses. Recording the blocking cause here is what
        # lets the console show the fix instead of a dead end.
        self.projection_blocked_by: str | None = None
        provider = self._storage_provider()
        if compiled.projections and provider != "hugegraph":
            self.projection_blocked_by = "provider-sqlite"
            log.info("projection %s declared but storage provider is %s; running SQL-only",
                     next(iter(compiled.projections.values())).metadata.name, provider)
        if compiled.projections and provider == "hugegraph":
            first = next(iter(compiled.projections.values()))
            try:
                endpoint = self.settings.resolve_env_ref(first.spec.endpoint)
            except KeyError as exc:
                self.projection_blocked_by = "endpoint-unresolved"
                log.warning("projection %s declared but endpoint unresolved (%s); "
                            "running SQL-only, graph APIs disabled", first.metadata.name, exc)
            else:
                if self.graph_store_factory is None:
                    self.projection_blocked_by = "extension-missing"
                    log.warning("projection %s declared but no graph extension is loaded "
                                "(extensions/graph-hugegraph); running SQL-only",
                                first.metadata.name)
                else:
                    self.projection_client = self.graph_store_factory(
                        endpoint, first.spec.graph,
                        graphspace=first.spec.graphspace, api=first.spec.api,
                        http=self.projection_http,
                        user=self.settings.hugegraph_user,
                        password=self.settings.hugegraph_password,
                        data_dir=self.settings.hugegraph_data_dir,
                    )
                    self.projection_worker = ProjectionWorker(compiled, first, self.projection_client)
                    self.projection_decl = first


        async def _projection_hook(event) -> bool:
            if self.projection_worker is None:
                return True
            async with self.sessionmaker() as session:
                return await self.projection_worker.handle_event(self.repo, session, event)

        async def _derivation_hook(event) -> bool:
            return await self.derivation.handle_event(event)

        async def _derivation_drain() -> dict[str, int]:
            return await self.derivation.drain()

        self.outbox = OutboxDispatcher(
            self.sessionmaker, self.settings, sse=self.sse, projection_hook=_projection_hook,
            derivation_hook=_derivation_hook, derivation_drain=_derivation_drain,
        )
        self.agents = AgentBroker(self)
        self.eval_runner.agent_broker = self.agents  # agent eval cases use the same gates
        # accounts & sessions: identity only -- authorization stays in the policy
        # plane, which is why AuthService never decides anything about resources
        self.auth = AuthService(self)
        # agent engines come from extensions (agent-paradigm §3.1): sc.agent_engines
        # maps engine kind -> factory(sc) -> engine, registered by the extension host
        # at boot; dispatch in the /run endpoint stays untouched by new engines.

    async def _function_runner(self, session, entry: str, params: dict, ctx) -> list[dict]:
        if self.compiled is None:
            raise StoreError("service not initialized")
        for fn in self.compiled.functions.values():
            if fn.spec.entry == entry:
                return await self.sandbox.run(session, fn, params)
        raise StoreError(f"function entry {entry!r} not found")

    # --------------------------------------------------------------- domains

    def domains_root(self) -> Path:
        """Directory holding switchable domains.

        ``ONTOGENY_DOMAINS_ROOT`` wins; the default is a ``domains/`` sibling of the
        *boot* package, which in the demo layout is ``<data-dir>/domains`` --
        next to ``pkg/`` (the boot copy) and ``pkg.pristine/``. Derived from the
        boot package, never the current one: after activating a domain the
        current package root lives INSIDE this directory.
        """
        env = os.environ.get("ONTOGENY_DOMAINS_ROOT")
        if env:
            return Path(env)
        base = Path(self.boot_package_root or self.package_root or ".").resolve().parent
        if base.name == "domains":
            # source-checkout layout: the boot package itself lives at
            # <repo>/domains/<name>, so parent IS the domains root -- appending
            # another "domains" produced <repo>/domains/domains/<name>
            return base
        return base / "domains"

    def list_domains(self) -> list[dict[str, Any]]:
        """Every activatable domain: each domains-root subdirectory carrying an
        ontology.yaml, plus the active package itself when it lives elsewhere
        (the boot copy). The active domain sorts first."""
        active_name = self.compiled.package_name if self.compiled else None
        candidates: list[Path] = []
        root = self.domains_root()
        if root.is_dir():
            candidates.extend(
                p for p in sorted(root.iterdir()) if (p / "ontology.yaml").is_file()
            )
        for pkg_root in (self.boot_package_root, self.package_root):
            path = Path(pkg_root) if pkg_root else None
            if path is not None and (path / "ontology.yaml").is_file():
                candidates.append(path)

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in candidates:
            manifest = _read_manifest(path)
            meta = manifest.get("metadata") or {}
            name = meta.get("name") or path.name
            if name in seen:
                continue
            seen.add(name)
            out.append({
                "name": name,
                "display": meta.get("display"),
                "description": meta.get("description"),
                "path": str(path.resolve()),
                "objects": _count_yaml(path / "objects"),
                "links": _count_yaml(path / "links"),
                "actions": _count_yaml(path / "actions"),
                "check": _check_package(path),
                "active": name == active_name,
            })
        out.sort(key=lambda d: (not d["active"], d["name"]))
        return out

    # ---- canvas layout sidecar ------------------------------------------
    #
    # The ontology canvas' hand-arranged node positions used to live in the
    # browser's localStorage; now they live WITH the package, as a `layout.yaml`
    # sidecar next to ontology.yaml. Same trade as the resources themselves:
    # per-domain by construction, it travels with zip import/export and Git,
    # and it survives browsers and machines. The loader only scans the known
    # resource directories, so the sidecar is invisible to the DSL.

    def storage_summary(self) -> dict[str, Any]:
        """Where materialized object data physically lives, spelled out.

        The DSL declares a backing STORE (the external source of record, e.g.
        the ERP/MES database); syncing PULLS rows from that source into the
        platform's own object tables (``ontogeny_obj_<type>``) inside THIS
        deployment's database (SQLite file in demos, Postgres in production).
        Queries, actions, versions and audit all read those object tables —
        never the source directly. This summary names the concrete target so
        consoles can say exactly where the data landed."""
        dsn = self.settings.db_dsn or ""
        if "sqlite" in dsn:
            raw = dsn.split("///", 1)[-1] or "(in-memory)"
            target = {"kind": "sqlite", "target": str(Path(raw).resolve()) if not raw.startswith(":") else raw}
        elif dsn.startswith(("postgres", "postgresql")):
            m = re.match(r"(?:postgresql?[+a-z]*://)([^:/@]+)(?::[^@]*)?@([^/]+)/([^?]+)", dsn)
            shown = f"postgres://{m.group(1)}@{m.group(2)}/{m.group(3)}" if m else "(configured DSN)"
            target = {"kind": "postgres", "target": shown}  # password never leaves the process
        else:
            target = {"kind": "unknown", "target": "(unrecognized DSN)"}

        objects: dict[str, Any] = {}
        if self.compiled is not None:
            for name, obj in self.compiled.objects.items():
                backing = getattr(obj.spec, "backing", None)
                sync = getattr(backing, "sync", None) if backing else None
                store_res = self.compiled.stores.get(backing.store) if backing else None
                desc: dict[str, Any] = {
                    "table": self.compiled.table_name(name),
                    "store": backing.store if backing else None,
                    "mode": backing.mode if backing else None,
                    "source_table": backing.source.table if backing and backing.source else None,
                    "store_type": store_res.spec.type if store_res else None,
                }
                if sync is not None:
                    desc["sync"] = sync.strategy
                    if sync.schedule:
                        desc["sync_schedule"] = sync.schedule
                    if sync.watermark is not None and sync.watermark.column:
                        desc["sync_watermark"] = sync.watermark.column
                objects[name] = desc

        # declared sources with their RESOLVED, credential-free targets: the
        # console can then say "sqlite · /path/erp.db" instead of a bare store
        # name, which reads like a placeholder
        stores: dict[str, dict[str, str]] = {}
        for name, store in (self.compiled.stores.items() if self.compiled else []):
            conn = store.spec.connection or ""
            try:
                conn = self.settings.resolve_env_ref(conn)
            except Exception:  # noqa: BLE001 -- an unresolved ${VAR} stays symbolic
                pass
            stores[name] = {"type": store.spec.type, "target": _mask_dsn(conn)}

        return {"target": target, "object_table_prefix": "ontogeny_obj_", "objects": objects,
                "stores": stores}

    # canvas layout: a front-end concern, kept in its own module (ontogeny.layout)
    def layout_path(self) -> Path | None:
        return self._layout.path()

    def read_layout(self) -> dict[str, Any]:
        return self._layout.read()

    def write_layout(self, layout: dict[str, Any]) -> None:
        self._layout.write(layout)

    def create_domain(self, name: str, *, display: str | None = None,
                      description: str | None = None) -> dict[str, Any]:
        """Scaffold a minimal, valid package under the domains root: manifest +
        empty resource directories. Activation is the caller's decision."""
        if not _DOMAIN_NAME_RE.fullmatch(name):
            raise DomainError(f"domain name must be kebab-case [a-z][a-z0-9-], got {name!r}")
        if name.lower() in ("domains", "pkg", "pkg.pristine"):
            raise DomainError(f"domain name {name!r} is reserved")
        dom = self.domains_root() / name
        if dom.exists():
            raise DomainError(f"domain {name!r} already exists", details={"path": str(dom)})
        for sub in _DOMAIN_DIRS:
            (dom / sub).mkdir(parents=True, exist_ok=True)
        import yaml

        manifest = {
            "apiVersion": "ontogeny/v1",
            "kind": "Ontology",
            "metadata": {
                "name": name,
                "display": display or name,
                "description": description,
                "version": "0.1.0",
            },
            "spec": {"imports": []},
        }
        (dom / "ontology.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        return {
            "name": name,
            "display": display or name,
            "description": description,
            "path": str(dom.resolve()),
            "objects": 0, "links": 0, "actions": 0,
            "active": False,
        }

    async def import_domain(self, data: bytes, *, activate: bool = True) -> dict[str, Any]:
        """Turn an uploaded domain-package zip into a switchable domain.

        The zip is treated as untrusted input end to end: entries must stay
        inside the extraction directory (no absolute paths, no ``..``), the
        archive is bounded (entry count + uncompressed size), and the package
        must VALIDATE before anything is moved into the domains root -- a
        rejected import leaves no residue. On success the folder lands at
        ``<domains root>/<manifest name>`` and can be activated like any
        scaffolded domain.
        """
        import io
        import shutil
        import tempfile
        import zipfile

        from .core.loader import load_package
        from .core.validator import validate

        MAX_ENTRIES = 2000
        MAX_UNCOMPRESSED = 256 * 1024 * 1024  # 256 MB across all entries

        root = self.domains_root()
        root.mkdir(parents=True, exist_ok=True)

        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise DomainError(f"not a zip archive: {exc}") from exc

        names = zf.namelist()
        if not names:
            raise DomainError("the archive is empty")
        if len(names) > MAX_ENTRIES:
            raise DomainError(f"too many entries (>{MAX_ENTRIES})")

        # every member must resolve INSIDE the extraction dir; a leading
        # single folder is the normal "zip of the domain directory" shape and
        # is unwrapped so the manifest sits at the extraction root
        def _strip_root(ns: list[str]) -> tuple[str, int] | None:
            first = ns[0].split("/")[0]
            if first and all(n == first or n.startswith(first + "/") for n in ns):
                return first + "/", len(first) + 1
            return None

        prefix, plen = _strip_root(names) or ("", 0)
        rel_names = [n[plen:].rstrip("/") for n in names if n[plen:].rstrip("/")]
        if "ontology.yaml" not in rel_names:
            raise DomainError(
                "no ontology.yaml found: the archive must contain a domain package "
                "(a folder with ontology.yaml, or the package files at the zip root)"
            )

        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=root))
        try:
            total = 0
            for info in zf.infolist():
                member = info.filename[plen:]
                if not member or member.endswith("/"):
                    continue
                target = (staging / member).resolve()
                if staging.resolve() not in target.parents:
                    raise DomainError(f"unsafe archive member: {info.filename!r}")
                total += info.file_size
                if total > MAX_UNCOMPRESSED:
                    raise DomainError("archive too large when extracted")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

            # a package that does not validate can never become a domain: the
            # switcher would list something activate_domain must then refuse
            report = validate(load_package(str(staging)))
            if not report.ok:
                errs = "; ".join(f"{i.code}@{i.resource}: {i.message}"
                                 for i in report.issues if i.severity == "error")
                raise DomainError(f"package rejected by validator: {errs}",
                                  details={"issues": [
                                      {"code": i.code, "resource": i.resource,
                                       "message": i.message} for i in report.issues
                                  ]})

            name = (_read_manifest(staging).get("metadata") or {}).get("name") or ""
            if not _DOMAIN_NAME_RE.fullmatch(name):
                raise DomainError(
                    f"package name must be kebab-case [a-z][a-z0-9-], got {name!r}")
            if name.lower() in ("domains", "pkg", "pkg.pristine"):
                raise DomainError(f"domain name {name!r} is reserved")
            final = root / name
            if final.exists():
                raise DomainError(f"domain {name!r} already exists",
                                  details={"path": str(final)})

            staging.rename(final)
        finally:
            # staging was renamed on success; on any failure nothing remains
            shutil.rmtree(staging, ignore_errors=True)

        if activate:
            compiled = await self.activate_domain(final)
            out = self._domain_entry(final, active=True)
            out["content_hash"] = compiled.content_hash
            return out
        return self._domain_entry(final, active=False)

    def _domain_entry(self, path: Path, *, active: bool) -> dict[str, Any]:
        """One list_domains-shaped record for a freshly imported domain."""
        meta = _read_manifest(path).get("metadata") or {}
        return {
            "name": meta.get("name") or path.name,
            "display": meta.get("display"),
            "description": meta.get("description"),
            "path": str(path.resolve()),
            "objects": _count_yaml(path / "objects"),
            "links": _count_yaml(path / "links"),
            "actions": _count_yaml(path / "actions"),
            "active": active,
        }

    def resolve_domain(self, name: str) -> Path:
        """Directory of a named domain: the active or boot package when the
        name matches one of them, else ``<domains root>/<name>``."""
        for pkg_root in (self.package_root, self.boot_package_root):
            path = Path(pkg_root) if pkg_root else None
            if path is not None and (path / "ontology.yaml").is_file() \
                    and _manifest_name(path) == name:
                return path
        dom = self.domains_root() / name
        if (dom / "ontology.yaml").is_file():
            return dom
        raise NotFoundError(f"unknown domain: {name}")

    @staticmethod
    def _validate_package_for_switch(package_root: str | Path, label: str) -> None:
        """Fail a switch *before* anything is retired if a package is invalid.

        The target package is checked so a bad target can never deactivate the
        current domain. The current package is checked too: switching away from
        a package that can no longer be loaded would strand the operator in the
        next domain with no way back.
        """
        from .core.validator import validate as _validate

        pkg = load_package(str(package_root))
        report = _validate(pkg)
        if report.ok:
            return
        errors = "; ".join(
            f"{i.code}@{i.resource}: {i.message}"
            for i in report.issues if i.severity == "error"
        )
        raise DSLValidationError(
            f"{label} package rejected by validator: {errors}",
            details={"issues": [
                {"code": i.code, "resource": i.resource, "message": i.message}
                for i in report.issues
            ]},
        )

    async def activate_domain(self, package_root: str | Path) -> CompiledOntology:
        """Switch the active domain with a hard preflight on both sides.

        The requirement is asymmetric on purpose: a broken *target* must never
        delete the current rows, and a broken *current* package must block the
        switch rather than becoming a one-way door.
        """
        target = Path(package_root)
        current = Path(self.package_root) if self.package_root else None
        if current is not None and current.is_dir() and current.resolve() != target.resolve():
            try:
                self._validate_package_for_switch(current, "current domain")
            except DSLValidationError:
                raise
            except Exception as exc:  # noqa: BLE001 -- report as a switch guard
                raise DSLValidationError(f"current domain cannot be validated: {exc}") from exc
        self._validate_package_for_switch(target, "target domain")
        pkg = load_package(str(target))
        async with self.sessionmaker() as session:
            compiled = await self.registry.activate(session, pkg, created_by="console")
            await session.commit()
        self.package_root = str(target.resolve())
        self._rebuild_services(compiled)
        async with self.sessionmaker() as session:
            await self.repo.ensure(session)
        return compiled

    # ------------------------------------------------------------ operations

    async def function_source_revisions(self, name: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Audit rows for one function's code edits, newest first.

        Read from the same ``ontogeny_revision`` table the Audit page renders, so
        "who changed this code, and when" has one answer rather than two.
        """
        from sqlalchemy import select

        from .action.models import RevisionRow

        async with self.sessionmaker() as session:
            rows = (await session.execute(
                select(RevisionRow)
                .where(RevisionRow.object_type == "Function",
                       RevisionRow.object_id == name,
                       RevisionRow.action == "edit-function-source")
                .order_by(RevisionRow.id.desc())
                .limit(limit)
            )).scalars().all()
        return [
            {"id": r.id, "principal": r.principal, "at": r.created_at.isoformat(),
             "version": (r.after or {}).get("version"),
             "bytes": (r.after or {}).get("bytes"),
             "message": r.message}
            for r in rows
        ]

    async def save_function_source(
        self, name: str, source: str, *, principal: dict,
    ) -> dict[str, Any]:
        """Write a function's code, publish it, and record who did it.

        The console's code editor exists because the alternative — hand-editing a
        file on the server — is worse: no syntax check before it lands, no audit
        trail, no immediate feedback. What it does NOT change is the sandbox: the
        code still runs in a child process with rlimits and the capabilities the
        DSL declares. Editing the code is a privilege; the capability list is
        still what bounds it.

        Saving never RUNS the code — trying it before committing is what
        ``test_function_source`` is for, and keeping the two apart is what makes
        a save's side effects (file, version, revision row) exactly predictable.
        """
        import ast as _ast
        import hashlib

        from .action.models import RevisionRow
        from .errors import DSLValidationError, NotFoundError
        from .functions.sandbox import function_source_path

        if self.compiled is None or self.package_root is None:
            raise StoreError("no working package to write into")
        fn = self.compiled.functions.get(name)
        if fn is None:
            raise NotFoundError(f"unknown function {name!r}")
        if fn.spec.runtime != "python":
            raise DSLValidationError(
                f"function {name!r} is runtime={fn.spec.runtime}: its body IS the DSL, "
                "edit the steps instead"
            )
        # Same entry guard as the test path: a malformed entry is authoring
        # input, which deserves a 400, not the SandboxError (a 500) that
        # ``function_source_path`` would raise for it.
        _file, _, func = (fn.spec.entry or "").partition(":")
        if not func:
            raise DSLValidationError(
                f"entry must be 'file.py:function', got {fn.spec.entry!r}",
                details={"entry": fn.spec.entry},
            )
        path = function_source_path(self.compiled, fn)

        # Syntax first: nothing is written until the text at least parses, so a
        # half-typed save cannot leave the package un-importable.
        try:
            _ast.parse(source)
        except SyntaxError as exc:
            raise DSLValidationError(
                f"python syntax error on line {exc.lineno}: {exc.msg}",
                details={"line": exc.lineno, "offset": exc.offset, "text": (exc.text or "").rstrip()},
            ) from exc

        before = path.read_text(encoding="utf-8") if path.is_file() else None
        if before == source:
            # nothing changed: report success without a publish or a revision row,
            # so the history stays a record of actual changes
            return {"ok": True, "changed": False, "path": str(path),
                    "version": self.compiled.function_versions.get(name)}

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        try:
            compiled = await self.publish(str(self.package_root), created_by=f"console:{principal.get('id')}")
        except Exception:
            # the package no longer validates: put the old text back so the
            # working copy stays publishable, and let the caller see why
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(before, encoding="utf-8")
            raise

        version = compiled.function_versions.get(name)
        async with self.sessionmaker() as session:
            session.add(RevisionRow(
                action="edit-function-source",
                object_type="Function",
                object_id=name,
                principal=str(principal.get("id") or "?"),
                params={"path": str(path)},
                before={"source": before, "bytes": len(before or "")},
                after={"source": source, "bytes": len(source),
                       "version": version,
                       "sha256": hashlib.sha256(source.encode()).hexdigest()[:12]},
                outcome="executed",
                message=f"source edited in the console ({len(source)} bytes)",
            ))
            await session.commit()

        out: dict[str, Any] = {
            "ok": True, "changed": True, "path": str(path), "version": version,
            "content_hash": compiled.content_hash, "bytes": len(source),
        }
        return out

    async def test_function_source(self, name: str, source: str) -> dict[str, Any]:
        """Run the editor's buffer ONCE, persisting nothing.

        The counterpart to ``save_function_source``: a syntax error here is a
        returned failure rather than a refused save, a run that calls out really
        calls out — but no file is written, nothing is published, and no
        revision row exists afterwards. Inputs are derived the same way the old
        opt-in smoke run derived them (``_smoke_params``), because a test with
        invented-but-plausible inputs is the only kind worth reading.
        """
        import ast as _ast

        from .errors import DSLValidationError, NotFoundError

        if self.compiled is None:
            raise StoreError("no working package to test against")
        fn = self.compiled.functions.get(name)
        if fn is None:
            raise NotFoundError(f"unknown function {name!r}")
        if fn.spec.runtime != "python":
            raise DSLValidationError(
                f"function {name!r} is runtime={fn.spec.runtime}: its body IS the DSL, "
                "edit the steps instead"
            )
        # A malformed entry would only explode later, inside the sandbox spawn
        # (``entry.split(":")``), surfacing as an opaque 500. Validate it here
        # so the editor gets a readable 400 — mirroring exactly what
        # ``function_source_path`` enforces on the save path, no stricter.
        entry = fn.spec.entry or ""
        _file, _, func = entry.partition(":")
        if not func:
            raise DSLValidationError(
                f"entry must be 'file.py:function', got {entry!r}",
                details={"entry": entry},
            )
        # Report a syntax error before spawning anything: the child would only
        # fail to import the module, and the traceback says less than ast does.
        try:
            _ast.parse(source)
        except SyntaxError as exc:
            raise DSLValidationError(
                f"python syntax error on line {exc.lineno}: {exc.msg}",
                details={"line": exc.lineno, "offset": exc.offset, "text": (exc.text or "").rstrip()},
            ) from exc

        async with self.sessionmaker() as session:
            params, sources = await self._smoke_params(session, fn)
            try:
                value = await self.functions.run_source(session, fn, source, params)
                # the child answers over a JSON line, so the value is already
                # wire-safe (dates arrived as strings, tensors do not exist here)
                return {"ok": True, "value": value,
                        "params": params, "param_sources": sources}
            except OOError as exc:
                return {"ok": False, "code": exc.code, "message": exc.message,
                        "params": params, "param_sources": sources}

    async def _smoke_params(self, session, fn) -> tuple[dict[str, Any], dict[str, str]]:
        """Parameter values for a smoke run, and where each came from.

        Invoking with ``{}`` was a design mistake: every function that HAS
        required parameters — precisely the ones worth smoke-testing — failed
        instantly with "missing 1 required positional argument", which says
        nothing about the code. So values are derived instead, in the order that
        makes the run most meaningful:

        1. the declared ``default`` (the author already said what is sensible);
        2. **a real primary key** when the parameter names one (``equipment_id``
           → an actual row's id), so the function reads real data and its own
           logic executes instead of bailing out on "not found";
        3. a type-shaped sample (first enum value, 1, true, now, "sample").

        The sources travel back to the editor: a smoke run is only trustworthy if
        whoever reads it knows which inputs were invented.
        """
        from .core.types import PropertyType

        params: dict[str, Any] = {}
        sources: dict[str, str] = {}
        # primary keys by property name, so a `*_id` parameter can be answered
        # with a row that actually exists
        pk_index: dict[str, str] = {}
        for obj_name, obj in self.compiled.objects.items():
            pk_index.setdefault(obj.spec.primaryKey[0], obj_name)

        for name, pdef in fn.spec.parameters.items():
            if pdef.default is not None:
                params[name] = pdef.default
                sources[name] = "declared default"
                continue
            obj_type = pk_index.get(name)
            if obj_type is not None:
                rows, _total = await self.repo.query(session, obj_type, limit=1)
                if rows:
                    params[name] = rows[0].get(name)
                    sources[name] = f"real id from {obj_type}"
                    continue
            kind = PropertyType.parse(pdef.type)
            if kind.kind == "enum" and kind.enum_values:
                params[name], sources[name] = kind.enum_values[0], "first enum value"
            elif kind.kind in ("integer", "decimal"):
                params[name], sources[name] = 1, f"sample {kind.kind}"
            elif kind.kind == "boolean":
                params[name], sources[name] = True, "sample boolean"
            elif kind.kind in ("date", "timestamp"):
                import datetime as _dt

                params[name] = _dt.datetime.now(_dt.timezone.utc).isoformat()
                sources[name] = "now"
            else:
                params[name], sources[name] = "sample", "sample text"
        return params, sources

    async def sync(self, object_type: str) -> dict[str, Any]:
        try:
            async with self.sessionmaker() as session:
                summary = await self.sync_engine.sync(session, object_type)
                await session.commit()
            return summary
        except Exception as exc:
            # The failed run's audit must outlive the rollback above: without
            # this, ontogeny_sync_run only ever recorded successes and the failure
            # half of the quarantine/fitness signal did not exist.
            import datetime as _dt

            from .stores.sync import SyncRunRow
            try:
                strategy = self.sync_engine.strategy_for(object_type)
            except Exception:  # noqa: BLE001 -- label only, best effort
                strategy = "snapshot"
            async with self.sessionmaker() as s2:
                s2.add(SyncRunRow(
                    object_type=object_type, strategy=strategy, status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    finished_at=_dt.datetime.now(_dt.timezone.utc),
                ))
                await s2.commit()
            raise

    async def evolve_promote(self, proposal_id: int) -> dict[str, Any]:
        """The one promote implementation shared by REST and the CLI.

        Carries the full safety net: the post-merge hot-swap of the compiled
        snapshot and the direction-F verification (a merge that was green
        before and goes red after is rolled back without a human). The CLI
        used to call promoter.promote() directly, promoting with none of it."""
        from sqlalchemy import select as _select

        if self.package_root is None:
            raise DSLValidationError("promotion requires ONTOGENY_PACKAGE_ROOT (git working copy)")
        async with self.sessionmaker() as s:
            from .evolve.models import ProposalRow

            p = (await s.execute(_select(ProposalRow).where(ProposalRow.id == proposal_id))).scalar_one_or_none()
            if p is None:
                raise NotFoundError(f"proposal {proposal_id} not found")
            pre_green = bool(p.eval_report and p.eval_report.get("passed"))
            result = await self.promoter.promote(s, p, self.package_root, eval_report=p.eval_report)
            await s.commit()
        if result.get("status") == "promoted":
            await self.reload()  # hot-swap the compiled snapshot (new schema is live)
            if pre_green and result.get("rollback_dir"):
                red = False
                async with self.sessionmaker() as s2:
                    for suite in (self.compiled.eval_suites or {}).values():
                        rep = await self.eval_runner.run(s2, suite)
                        red = red or not rep["passed"]
                if red:
                    async with self.sessionmaker() as s3:
                        rb = await self.promoter.rollback(s3, result["rollback_dir"])
                    await self.reload()
                    result = {"status": "promoted_then_rolled_back",
                              "reason": "post-merge eval went red -- auto-reverted",
                              "rollback": rb, "original": result}
        return result

    async def projection_rebuild(self) -> dict[str, int]:
        """Drop the graph's data, re-apply its schema, backfill from the tables.

        The drop is not optional: a backfill alone only ever adds, so rows the
        previous package projected (or rows deleted while the graph was
        unreachable) stay in the graph and it goes on answering with objects the
        platform no longer has.
        """
        if self.projection_worker is None or self.compiled is None:
            raise StoreError("no projection declared")
        prj = next(iter(self.compiled.projections.values()))
        # create-then-wipe-then-fill: the graph may not exist at all (a first
        # build), and every step after this one needs it to.
        await self.projection_client.ensure_graph()
        await self.projection_client.clear()
        schema = compile_projection(self.compiled, prj)
        await self.projection_client.ensure_schema(schema)
        async with self.sessionmaker() as session:
            return await self.projection_worker.rebuild(self.repo, session)

    def _derive_projection(self, *, name: str, graph: str, graphspace: str,
                           engine: str = "hugegraph") -> dict[str, Any]:
        """A whole-ontology projection: every object type and every link.

        The obvious projection is also the only one that can be derived without
        asking questions: all object types, each with its non-marked and
        non-derived properties (marked properties are refused by the validator,
        and a derived one is computed at read time so it has no stored column to
        project), plus every link whose two endpoints are both included.

        Deterministic: same ontology in, same YAML out.
        """
        if self.compiled is None:
            raise StoreError("service not initialized")

        objects: dict[str, dict[str, Any]] = {}
        for obj_name, obj in sorted(self.compiled.objects.items()):
            props = [
                pname for pname, pdef in sorted(obj.spec.properties.items())
                if pdef.marking is None and pdef.derived is None
            ]
            objects[obj_name] = {"properties": props}

        links = sorted(
            lname for lname, lnk in self.compiled.links.items()
            if lnk.spec.source in objects and lnk.spec.target in objects
        )

        # index the primary key of every included type: it is what a lookup by
        # natural key (a filter on the graph) resolves against
        indexes = [
            {"object": obj_name, "property": self.compiled.objects[obj_name].spec.primaryKey[0]}
            for obj_name in sorted(objects)
        ]
        return {
            "apiVersion": "ontogeny/v1",
            "kind": "Projection",
            "metadata": {
                "name": name,
                "display": "全量图谱投影",
                "description": "由运维台自动生成：包含本体全部对象类型与联系，"
                               "支撑多跳追溯与图算法",
            },
            "spec": {
                "engine": engine,
                "endpoint": "${HUGEGRAPH_URL}",
                "graph": graph,
                "graphspace": graphspace,
                "include": {"objects": objects, "links": links},
                "deletion": "remove",
                "indexes": indexes,
            },
        }

    async def scaffold_projection(
        self, *, name: str | None = None, graphspace: str = "DEFAULT",
    ) -> dict[str, Any]:
        """Declare this domain's projection, then LOAD or BUILD its graph.

        The step that turns a configured HugeGraph endpoint into a working
        graph. Without a Projection resource there is nothing to build and the
        console can only report "no projection declared", so the storage card
        offers this as one action. What it does next depends on the server,
        which is the point:

        * the domain's graph already exists -> **load it**: declare, publish,
          attach, and leave the contents alone. They are the answer to "what is
          in my graph?", and wiping them to re-derive the same rows would be
          work with a destructive failure mode;
        * no such graph -> **build it**: create the schema and backfill.

        The graph name is not a parameter: it is the domain's own name, so a
        domain cannot point at another model's graph.
        """
        from .core.models import ProjectionResource
        from .errors import AlreadyDeclaredError
        from .registry.compiled import domain_graph_name

        if self.compiled is None or self.package_root is None:
            raise StoreError("no working package to write a projection into")
        pkg_dir = Path(self.package_root)
        if not pkg_dir.is_dir():
            raise StoreError(f"package dir {pkg_dir} does not exist")

        # Never clobber a declared projection. A hand-written one carries
        # choices this derivation cannot recover -- a curated property
        # whitelist, deliberately omitted links -- and silently replacing it
        # with "everything" would be a data-model decision made by a button.
        # An existing projection means the caller wants `rebuild`.
        if self.compiled.projections:
            existing = next(iter(self.compiled.projections))
            raise AlreadyDeclaredError(
                f"package already declares projection {existing!r}; "
                "rebuild it instead, or delete the resource to re-derive",
                details={"projection": existing},
            )

        pkg_name = self.compiled.package_name
        name = name or f"{pkg_name}-graph"
        graph = domain_graph_name(pkg_name)
        payload = self._derive_projection(name=name, graph=graph, graphspace=graphspace)
        resource = ProjectionResource.model_validate(payload)

        target = pkg_dir / "projections" / f"{name}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        import yaml as _yaml
        target.write_text(
            _yaml.safe_dump(resource.model_dump(mode="json", by_alias=True, exclude_none=True),
                            allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        compiled = await self.publish(str(pkg_dir), created_by="console")
        if self.projection_worker is None:
            # published but unusable: the endpoint is unset/unresolvable or the
            # graph extension never loaded -- surface WHY instead of a bare 500
            raise StoreError(
                "projection written and published, but no graph client was wired: "
                "check the HugeGraph URL and that the graph-hugegraph extension loaded"
            )
        prj = next(iter(compiled.projections.values()))
        state = await self.graph_state()
        if state.get("graph_exists") is True:
            # loaded, not rebuilt: the graph is already there
            summary = await self.projection_summary()
            counts = summary.get("counts") or {}
            return {
                "action": "loaded",
                "name": name,
                "graph": graph,
                "path": str(target),
                "vertices": sum((counts.get("vertices") or {}).values()),
                "edges": sum((counts.get("edges") or {}).values()),
            }
        # Built from scratch: a graph appearing under this domain's name starts
        # empty, and both it and its schema have to exist before rows can go in.
        await self.projection_client.ensure_graph()
        await self.projection_client.clear()
        await self.projection_client.ensure_schema(compile_projection(compiled, prj))
        async with self.sessionmaker() as session:
            counts = await self.projection_worker.rebuild(self.repo, session)
        return {
            "action": "built",
            "name": name,
            "graph": graph,
            "path": str(target),
            "vertices": counts.get("vertices", 0),
            "edges": counts.get("edges", 0),
        }

    # ---------------------------------------------------------- data preview

    async def data_preview(self, principal: dict, *, limit: int = 3) -> dict[str, Any]:
        """Every declared object type with its row count and first ``limit`` rows.

        Rows come from the query engine, so derived properties and marking masks
        are exactly what any other read would return.
        """
        if self.compiled is None:
            raise StoreError("service not initialized")
        out: list[dict[str, Any]] = []
        total = 0
        async with self.sessionmaker() as session:
            for name, resource in self.compiled.objects.items():
                entry: dict[str, Any] = {
                    "type": name,
                    "display": resource.metadata.display,
                    "primary_key": resource.spec.primaryKey[0],
                    "total": None,
                    "rows": [],
                }
                try:
                    res = await self.query.query(session, name, principal, limit=limit, offset=0)
                    entry["total"] = res["total"]
                    entry["rows"] = res["objects"]
                    total += res["total"]
                except OOError as exc:
                    # one unreadable type must not blank the whole preview
                    entry["error"] = exc.code
                out.append(entry)
        return {"objects": out, "total": total}

    async def projection_summary(self) -> dict[str, Any]:
        """Declared projection + live label inventory of the graph.

        Two independent questions, answered separately because conflating them
        produced the worst state this console can be in: reporting "no projection
        declared" for a package that HAS one, which then offered a "create
        projection" button whose only possible outcome was a refusal.

        * ``declared`` — does the package declare a Projection resource?
        * ``configured`` — is a graph client actually wired (declared AND the
          provider is HugeGraph AND the endpoint resolves AND the extension
          loaded)? ``blocked_by`` says which of those is missing.
        """
        declared = None
        if self.compiled is not None and self.compiled.projections:
            declared = next(iter(self.compiled.projections.values()))
        base: dict[str, Any] = {
            "declared": declared is not None,
            "declared_name": declared.metadata.name if declared is not None else None,
            "storage_provider": self._storage_provider(),
            "blocked_by": None if declared is not None else "not-declared",
            **(await self.graph_state()),
        }
        if self.projection_client is None or self.projection_decl is None:
            blocked = self.projection_blocked_by or "not-declared"
            return {
                **base,
                "configured": False,
                "ok": False,
                "blocked_by": blocked,
                # literal substitution, not str.format: these strings contain
                # ``${HUGEGRAPH_URL}`` and format() would read it as a field
                "reason": _PROJECTION_BLOCK_REASONS.get(
                    blocked, "projection is not wired"
                ).replace("{provider}", repr(self._storage_provider())),
            }
        spec = self.projection_decl.spec
        out: dict[str, Any] = {
            **base,
            "configured": True,
            "ok": True,
            "name": self.projection_decl.metadata.name,
            "engine": spec.engine,
            "graph": spec.graph,
            "graphspace": spec.graphspace,
            "objects": sorted(spec.include.objects),
            "links": list(spec.include.links),
            "dialect": await self.projection_client.dialect(),
        }
        # A declared projection whose graph is not on the server yet is a
        # "schema without a graph": readable metadata, nothing to read. Saying
        # ok=true would report a working graph that holds no data at all.
        if out.get("graph_exists") is False:
            out["ok"] = False
            out["reason"] = "graph not built on the server yet"
            return out
        try:
            out["labels"] = await self.projection_client.labels()
            out["counts"] = await self.projection_client.counts()
        except OOError as exc:
            out.update({"ok": False, "error": exc.message, "code": exc.code,
                        "auth_rejected": bool(getattr(self.projection_client, "auth_rejected", False))})
        return out

    async def projection_vertices(self, label: str, principal: dict, *, limit: int = 20) -> dict[str, Any]:
        """Sample graph vertices for a label, re-assembled through the engine.

        The graph only ever returns ids + whitelisted properties; whatever we
        hand to a consumer is re-read through the normal query path so masking
        (and any future row-level rule) is applied in exactly one place.
        """
        if self.compiled is None or self.projection_client is None:
            raise StoreError("no projection declared")
        if label not in self.compiled.objects:
            raise NotFoundError(f"unknown object type {label!r}")
        vertices = await self.projection_client.sample_vertices(label, limit=limit)
        rows: list[dict[str, Any]] = []
        hidden = 0
        async with self.sessionmaker() as session:
            for vertex in vertices:
                key = _pk_from_graph_id(vertex.get("id"))
                if key is None:
                    continue
                try:
                    rows.append(await self.query.get(session, label, key, principal))
                except OOError:
                    hidden += 1  # not readable (deleted, or not authorised)
        return {"label": label, "rows": rows, "hidden": hidden,
                "sampled": len(vertices)}

    async def projection_edges(self, label: str, principal: dict, *, limit: int = 20) -> dict[str, Any]:
        """Sample graph edges; an edge surfaces only when both ends are readable."""
        if self.compiled is None or self.projection_client is None:
            raise StoreError("no projection declared")
        if label not in self.compiled.links:
            raise NotFoundError(f"unknown link {label!r}")
        lnk = self.compiled.links[label]
        edges = await self.projection_client.sample_edges(label, limit=limit)
        rows: list[dict[str, Any]] = []
        hidden = 0
        async with self.sessionmaker() as session:
            for edge in edges:
                src, dst = _pk_from_graph_id(edge.get("outV")), _pk_from_graph_id(edge.get("inV"))
                if src is None or dst is None:
                    continue
                try:
                    out_obj = await self.query.get(session, lnk.spec.source, src, principal)
                    in_obj = await self.query.get(session, lnk.spec.target, dst, principal)
                except OOError:
                    hidden += 1
                    continue
                rows.append({
                    "id": edge.get("id"),
                    "link": label,
                    "source": {"type": lnk.spec.source, "id": src,
                               "display": _display_of(out_obj, self.compiled, lnk.spec.source)},
                    "target": {"type": lnk.spec.target, "id": dst,
                               "display": _display_of(in_obj, self.compiled, lnk.spec.target)},
                })
        return {"label": label, "rows": rows, "hidden": hidden, "sampled": len(edges)}


    def snapshot(self) -> SimpleNamespace:
        """Convenience view for API/MCP shells."""
        return SimpleNamespace(
            compiled=self.compiled, repo=self.repo, runtime=self.runtime,
            query=self.query, sync_engine=self.sync_engine, telemetry=self.telemetry,
            eval_runner=self.eval_runner, promoter=self.promoter, proposer=self.proposer,
            registry=self.registry, outbox=self.outbox, sandbox=self.sandbox,
            derivation=self.derivation,
        )
