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
"""HugeGraph adapter: schema bootstrap, incremental upserts, vertex deletion.

Implements the core ``ontogeny.projection.GraphStore`` contract. The endpoint is
engine-internal and NEVER exposed to consumers; graph queries return IDs +
whitelisted properties which the engine re-assembles through the normal policy
path (authorization is not implemented twice).

Two REST dialects are supported, selected by ``api`` (``auto`` probes once):

``1.7``  graphspace-scoped: ``/graphspaces/{space}/graphs/{graph}/...``
         upserts go through the *batch* endpoints (the single-edge POST rejects
         composite ids), composite primary-key ids must be double-quoted in URL
         segments, and writes need an explicit ``update_strategies`` map
         (we use OVERRIDE = last write wins, the only sane projection semantic).
``1.5``  the historical ``/apis/...?graph=`` shape, kept for the compose
         profile that pins ``hugegraph/hugegraph:1.5.0``.
"""
from __future__ import annotations

import json

import datetime as _dt
import logging
from typing import Any, Iterable
from urllib.parse import quote

import httpx

from ontogeny.errors import StoreError

log = logging.getLogger("ontogeny.projection")

#: HugeGraph rejects an empty ``update_strategies`` map, and projected edges
#: carry no properties (the compiler emits none), so batch edge writes need an
#: inert entry. ``OVERRIDE`` is the projection semantic anyway.
_NOOP_STRATEGY = {"_ignore": "OVERRIDE"}

#: numeric/date property types get a RANGE index (which also serves equality);
#: everything else gets SECONDARY. HugeGraph allows one index per (label, field)
#: -- a redundant second index is rejected outright.
_RANGE_TYPES = {"INT", "LONG", "FLOAT", "DOUBLE", "DATE"}

_SCHEMA_EXISTS_MARKERS = ("has existed", "already exist", "existed")


class HugeGraphClient:
    def __init__(self, endpoint: str, graph: str, *, graphspace: str = "DEFAULT",
                 api: str = "auto", http: httpx.AsyncClient | None = None,
                 timeout: float = 15.0, batch_size: int = 500,
                 user: str | None = None, password: str | None = None,
                 data_dir: str | None = None) -> None:
        self.base = endpoint.rstrip("/")
        self.graph = graph
        self.graphspace = graphspace or "DEFAULT"
        self.api = api or "auto"
        self._dialect: str | None = None if self.api == "auto" else self.api
        self._http = http
        self._timeout = timeout
        self.batch_size = batch_size
        # A HugeGraph in auth mode answers 401 to every anonymous request, so
        # these travel on each call. Absent credentials are legitimate (a
        # non-auth server); the server's own 401 is then the honest answer.
        self._user = user
        self._password = password
        # Where a graph CREATED by the platform keeps its RocksDB files. Left to
        # the server's default this is one shared directory for every graph, and
        # the second graph can never open its store (see ensure_graph).
        self._data_dir = data_dir
        self._label_ids: dict[str, int] = {}
        self._edge_props: dict[str, list[str]] = {}
        #: Set once the server has refused our credentials. Sticky, so a caller
        #: can label the connection "credentials refused" rather than parse text.
        self.auth_rejected = False

    def _auth(self) -> dict[str, str]:
        if not self._user:
            return {}
        import base64

        raw = f"{self._user}:{self._password or ''}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    @property
    def authenticated(self) -> bool:
        return bool(self._user)

    async def client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------- transport

    async def _request(self, method: str, path: str, *, json_body: Any = None,
                       params: dict | None = None, ok: Iterable[int] = (200, 201, 202, 204),
                       tolerate_schema_exists: bool = False) -> httpx.Response:
        c = await self.client()
        resp = await c.request(method, f"{self.base}{path}", json=json_body, params=params,
                               headers=self._auth())
        if resp.status_code in set(ok):
            return resp
        if tolerate_schema_exists and resp.status_code == 400:
            text = resp.text
            if any(marker in text for marker in _SCHEMA_EXISTS_MARKERS):
                return resp
        if resp.status_code in (401, 403):
            # the one failure an operator can act on without reading Java: say
            # which side is missing credentials rather than echoing the server.
            # `auth_rejected` is sticky on the client so a caller can label the
            # whole connection state "credentials refused" instead of guessing
            # from an error string.
            self.auth_rejected = True
            raise StoreError(
                f"hugegraph refused {method} {path}: {resp.status_code} "
                f"({'credentials were sent' if self.authenticated else 'no credentials configured'}). "
                "This graph server enforces auth (auth.authenticator is set); set the "
                "HugeGraph user/password in the console's storage configuration."
            )
        raise StoreError(f"hugegraph {method} {path} failed: {resp.status_code} {resp.text[:200]}")

    async def dialect(self) -> str:
        """``1.7`` when the endpoint exposes graphspaces, else the legacy shape."""
        if self._dialect is None:
            c = await self.client()
            try:
                resp = await c.get(f"{self.base}/graphspaces", headers=self._auth())
                self._dialect = "1.7" if resp.status_code == 200 else "1.5"
            except httpx.HTTPError:
                self._dialect = "1.5"
            log.info("hugegraph dialect at %s: %s", self.base, self._dialect)
        return self._dialect

    def _g(self, path: str) -> str:
        """Graph-scoped path for the active dialect.

        Every public method resolves the dialect first; failing loudly here is
        deliberate, because an unresolved dialect would silently address a
        1.5-shaped path on a 1.7 server.
        """
        if self._dialect is None:
            raise StoreError("hugegraph dialect not resolved yet; await dialect() first")
        if self._dialect == "1.7":
            return f"/graphspaces/{self.graphspace}/graphs/{self.graph}{path}"
        return path

    # ------------------------------------------------------------ addressing

    async def exists(self) -> bool:
        """Does this domain's graph exist on the server yet?

        The console's load-vs-build decision. Listing the graphspace's graphs is
        the one call that answers it without noise: asking for a graph by name
        answers 500 for "absent" on 1.7, which is indistinguishable from a real
        failure. Anything we cannot interpret counts as *unknown* (``None``)
        rather than absent — never tell an operator their graph is gone when the
        truth is that we could not look.
        """
        await self.dialect()
        try:
            if self._dialect == "1.7":
                resp = await self._request("GET", f"/graphspaces/{self.graphspace}/graphs")
            else:
                resp = await self._request("GET", "/graphs")
        except StoreError:
            return None  # type: ignore[return-value]
        try:
            names = resp.json().get("graphs")
        except Exception:  # noqa: BLE001 -- an unparseable answer is not "absent"
            return None  # type: ignore[return-value]
        if not isinstance(names, list):
            return None  # type: ignore[return-value]
        return self.graph in names

    async def ensure_graph(self) -> bool:
        """Create this domain's graph if it is not there yet. True = created.

        HugeGraph does not create a graph on first write: posting schema to an
        absent graph answers ``500 NullPointerException`` from GraphManager, so a
        build had no way to start. Creation is its own call, and the name goes in
        the PATH (a POST to the collection with a body is a 405).

        The body must carry a complete graph config:

        * ``gremlin.graph`` — the auth proxy; the server refuses a config without
          a valid factory;
        * ``backend``/``serializer`` — inherited from the deployment, so a server
          that standardised on hstore keeps creating hstore graphs;
        * ``store`` — the graph name;
        * ``rocksdb.data_path``/``rocksdb.wal_path`` — **per graph**, and this is
          the one that bites. Left to the server's default, every dynamically
          created graph points at the SAME directory, so the second graph fails to
          open its store with ``lock hold by current process``: one deployment
          could only ever have one created graph. The path is derived from the
          graph name (unique by construction) under ``data_dir`` when the
          operator configured one, else under the server's working directory.

        Since HugeGraph 1.7 dynamic creation requires auth mode, a non-auth server
        still refuses this; that refusal is reported as what the operator has to
        do instead of as an opaque server error.
        """
        await self.dialect()
        if await self.exists() is True:
            return False
        backend = await self._default_backend()
        body = {
            "gremlin.graph": "org.apache.hugegraph.auth.HugeFactoryAuthProxy",
            "backend": backend,
            "serializer": "binary",
            # the store defaults to the graph name per the REST docs; naming it
            # keeps the created config self-describing
            "store": self.graph,
        }
        if backend == "rocksdb":
            base = self._data_dir or "rocksdb-data"
            body["rocksdb.data_path"] = f"{base}/{self.graph}/data"
            body["rocksdb.wal_path"] = f"{base}/{self.graph}/wal"
        if self._dialect == "1.7":
            path = f"/graphspaces/{self.graphspace}/graphs/{self.graph}"
        else:
            path = f"/graphs/{self.graph}"
        try:
            await self._request("POST", path, json_body=body)
        except StoreError as exc:
            raise StoreError(
                f"graph {self.graph!r} does not exist and this HugeGraph server "
                f"refused to create it. Since HugeGraph 1.7 dynamic graph "
                f"creation requires the server to run in auth mode; on a "
                f"non-auth deployment add the graph to the server's graphs.yaml "
                f"instead, then build again. Server said: {exc}",
                details={"graph": self.graph, "graphspace": self.graphspace,
                         "create_path": path, "body": body},
            ) from exc
        log.info("hugegraph graph %r created in graphspace %r (backend=%s)",
                 self.graph, self.graphspace, body["backend"])
        return True

    async def _default_backend(self) -> str:
        """The backend new graphs should use: whatever this deployment already runs.

        Read from any graph the server already has (the built-in ``hugegraph``
        one is always there), so the platform inherits the deployment's choice
        instead of imposing one. Falls back to ``rocksdb``, the server default.
        """
        try:
            if self._dialect == "1.7":
                resp = await self._request("GET", f"/graphspaces/{self.graphspace}/graphs/hugegraph")
            else:
                resp = await self._request("GET", "/graphs/hugegraph")
            backend = resp.json().get("backend")
            if isinstance(backend, str) and backend:
                return backend
        except (StoreError, ValueError, AttributeError):
            pass
        return "rocksdb"

    # ---------------------------------------------------------------- schema

    async def clear(self) -> None:
        """Delete every vertex and edge, keeping the schema (rebuild step 1).

        HugeGraph requires the confirmation phrase as a query parameter, which is
        the honest guard here: this wipes the graph, and the only reason it is
        safe is that a projection is a *derived* index -- everything it holds can
        be re-projected from the authoritative object tables.

        A graph that does not exist yet has nothing to clear: this is the first
        step of a first build, so a missing graph is a no-op rather than a
        failure (1.7 answers 500 to /clear on an absent graph, which would
        otherwise block the only path that could create it).
        """
        await self.dialect()
        if await self.exists() is False:
            return
        await self._request(
            "DELETE", self._g("/clear"),
            params={"confirm_message": "I'm sure to delete all data"},
        )

    async def ensure_schema(self, schema: dict[str, Any]) -> None:
        if await self.dialect() == "1.7":
            await self._ensure_schema_v17(schema)
        else:
            await self._ensure_schema_v15(schema)

    async def _ensure_schema_v17(self, schema: dict[str, Any]) -> None:
        dtypes = {p["name"]: p["data_type"] for p in schema["propertykeys"]}
        for pk in schema["propertykeys"]:
            await self._request(
                "POST", self._g("/schema/propertykeys"),
                json_body={"name": pk["name"], "data_type": pk["data_type"]},
                tolerate_schema_exists=True,
            )
        for vl in schema["vertexlabels"]:
            props = list(vl["properties"])
            keys = list(vl.get("primary_keys") or [props[0]])
            await self._request(
                "POST", self._g("/schema/vertexlabels"),
                json_body={
                    "name": vl["label"],
                    "id_strategy": "PRIMARY_KEY",
                    "primary_keys": keys,
                    "properties": props,
                    "nullable_keys": [p for p in props if p not in keys],
                    "enable_label_index": True,
                },
                tolerate_schema_exists=True,
            )
        for el in schema["edgelabels"]:
            props = list(el.get("properties") or [])
            # HugeGraph rejects MULTIPLE without sort_keys; a projected edge
            # carries no properties, so there is nothing to sort on and SINGLE
            # is both legal and the intended dedup semantic.
            await self._request(
                "POST", self._g("/schema/edgelabels"),
                json_body={
                    "name": el["name"],
                    "source_label": el["source_label"],
                    "target_label": el["target_label"],
                    "frequency": "SINGLE",
                    "properties": props,
                    "nullable_keys": props,
                },
                tolerate_schema_exists=True,
            )
            self._edge_props[el["name"]] = props
        for ix in schema["indexes"]:
            dtypes.setdefault(ix["property"], "TEXT")
            await self._request(
                "POST", self._g("/schema/indexlabels"),
                json_body={
                    "name": f"{ix['label']}_by_{ix['property']}",
                    "base_type": "VERTEX_LABEL",
                    "base_value": ix["label"],
                    "index_type": "RANGE" if dtypes[ix["property"]] in _RANGE_TYPES else "SECONDARY",
                    "fields": [ix["property"]],
                },
                tolerate_schema_exists=True,
            )
        self._label_ids = {}

    async def _ensure_schema_v15(self, schema: dict[str, Any]) -> None:
        """Historical 1.5 payloads (kept as-is: the compose profile pins 1.5.0)."""
        g = {"graph": self.graph}
        for pk in schema["propertykeys"]:
            await self._request("POST", "/apis/schema/propertykeys",
                                json_body={"name": pk["name"], "data_type": pk["data_type"]}, params=g)
        for vl in schema["vertexlabels"]:
            await self._request("POST", "/apis/schema/vertexlabels", json_body=vl, params=g)
        for el in schema["edgelabels"]:
            await self._request("POST", "/apis/schema/edgelabels", json_body=el, params=g)
        for ix in schema["indexes"]:
            await self._request(
                "POST", "/apis/graph/indexes/secondary",
                json_body={"name": f"{ix['label']}_by_{ix['property']}", "base_value_type": "VERTEX",
                           "index_label": ix["property"], "label": ix["label"]},
                params=g,
            )

    async def _label_id(self, label: str) -> int | None:
        """Vertex label id, needed to build composite PRIMARY_KEY ids."""
        if not self._label_ids:
            resp = await self._request("GET", self._g("/schema/vertexlabels"))
            self._label_ids = {v["name"]: int(v["id"]) for v in resp.json().get("vertexlabels", [])}
        return self._label_ids.get(label)

    async def vertex_id(self, label: str, key: Any) -> str | None:
        """HugeGraph's stored id for a projected object (``<labelId>:<pk>``)."""
        lid = await self._label_id(label)
        return None if lid is None else f"{lid}:{key}"

    # ---------------------------------------------------------------- writes

    async def upsert_vertices(self, label: str, pk_prop: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        if await self.dialect() == "1.7":
            await self._upsert_vertices_v17(label, pk_prop, items)
        else:
            await self._upsert_vertices_v15(label, pk_prop, items)

    async def _upsert_vertices_v17(self, label: str, pk_prop: str, items: list[dict[str, Any]]) -> None:
        body: list[dict[str, Any]] = []
        props: set[str] = set()
        for item in items:
            values = {k: _plain(v) for k, v in item.items() if v is not None}
            if pk_prop not in values:
                # PRIMARY_KEY ids derive from the key properties, so a row
                # without them cannot be addressed at all.
                log.warning("skipping %s row without primary key %r", label, pk_prop)
                continue
            props.update(values)
            body.append({"label": label, "properties": values})
        if not body:
            return
        strategies = {p: "OVERRIDE" for p in sorted(props)} or dict(_NOOP_STRATEGY)
        for chunk in _chunks(body, self.batch_size):
            await self._request("PUT", self._g("/graph/vertices/batch"),
                                json_body={"vertices": chunk, "update_strategies": strategies})

    async def _upsert_vertices_v15(self, label: str, pk_prop: str, items: list[dict[str, Any]]) -> None:
        body = [
            {"label": label, "id": str(item.get(pk_prop)), "properties": {
                k: _plain(v) for k, v in item.items() if v is not None and k != pk_prop
            }}
            for item in items
        ]
        await self._request("POST", "/apis/graph/vertices/batch-upsert", json_body=body,
                            params={"graph": self.graph})

    async def upsert_edges(self, link_name: str, src_label: str, dst_label: str,
                           pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        if await self.dialect() == "1.7":
            await self._upsert_edges_v17(link_name, src_label, dst_label, pairs)
        else:
            await self._upsert_edges_v15(link_name, src_label, dst_label, pairs)

    async def _upsert_edges_v17(self, link_name: str, src_label: str, dst_label: str,
                                pairs: list[tuple[str, str]]) -> None:
        src_lid, dst_lid = await self._label_id(src_label), await self._label_id(dst_label)
        if src_lid is None or dst_lid is None:
            log.warning("skipping %s: unknown endpoint label %r/%r", link_name, src_label, dst_label)
            return
        body = [
            {"label": link_name, "outV": f"{src_lid}:{s}", "inV": f"{dst_lid}:{d}",
             "outVLabel": src_label, "inVLabel": dst_label, "properties": {}}
            for s, d in pairs
        ]
        props = self._edge_props.get(link_name) or []
        strategies = {p: "OVERRIDE" for p in props} or dict(_NOOP_STRATEGY)
        for chunk in _chunks(body, self.batch_size):
            await self._request("PUT", self._g("/graph/edges/batch"),
                                json_body={"edges": chunk, "update_strategies": strategies})

    async def _upsert_edges_v15(self, link_name: str, src_label: str, dst_label: str,
                                pairs: list[tuple[str, str]]) -> None:
        body = [
            {"label": link_name, "outV": s, "outV_label": src_label, "inV": d, "inV_label": dst_label}
            for s, d in pairs
        ]
        await self._request("POST", "/apis/graph/edges/batch-upsert", json_body=body,
                            params={"graph": self.graph})

    async def query_vertices(self, label: str, *, properties: dict[str, Any] | None = None,
                             limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Vertices of one label, optionally exact-match filtered on properties.

        HugeGraph's vertex list API supports equality filters only; the caller
        falls back to Gremlin (or in-memory filtering) for range/like queries.
        Returns raw HugeGraph vertex dicts ({id, label, properties}).
        """
        params: dict[str, Any] = {"label": label, "limit": limit, "offset": offset}
        if properties:
            params["properties"] = json.dumps(
                {k: _plain(v) for k, v in properties.items()}, separators=(",", ":")
            )
        if await self.dialect() == "1.7":
            resp = await self._request("GET", self._g("/graph/vertices"), params=params)
        else:
            resp = await self._request("GET", "/apis/graph/vertices",
                                       params={**params, "graph": self.graph})
        return resp.json().get("vertices", [])

    async def get_vertex(self, label: str, key: Any) -> dict[str, Any] | None:
        """One vertex by (label, pk value), or None when absent."""
        if await self.dialect() == "1.7":
            full = await self.vertex_id(label, key)
            if full is None:
                return None
            quoted = quote(f'"{full}"', safe="")
            resp = await self._request("GET", self._g(f"/graph/vertices/{quoted}"), ok=(200, 404))
            return resp.json() if resp.status_code == 200 else None
        resp = await self._request("GET", f"/apis/graph/vertices/{quote(str(key), safe='')}",
                                   params={"graph": self.graph}, ok=(200, 404))
        return resp.json() if resp.status_code == 200 else None

    async def delete_vertex(self, label: str, vertex_id: str) -> None:
        if await self.dialect() == "1.7":
            full = await self.vertex_id(label, vertex_id)
            if full is None:
                return
            # 1.7 only parses a string id when it is double-quoted in the path;
            # a missing vertex is the desired end state, so 404 counts as success.
            quoted = quote(f'"{full}"', safe="")
            await self._request("DELETE", self._g(f"/graph/vertices/{quoted}"),
                                ok=(200, 204, 404))
        else:
            await self._request("DELETE", "/apis/graph/vertices",
                                params={"graph": self.graph, "label": label, "id": vertex_id})

    # --------------------------------------------------------------- preview

    async def labels(self) -> dict[str, list[dict[str, Any]]]:
        """Declared vertex/edge labels of the graph (schema view)."""
        await self.dialect()
        v = await self._request("GET", self._g("/schema/vertexlabels"))
        e = await self._request("GET", self._g("/schema/edgelabels"))
        return {
            "vertices": [{"name": x["name"], "primary_keys": x.get("primary_keys", [])}
                         for x in v.json().get("vertexlabels", [])],
            "edges": [{"name": x["name"], "source_label": x.get("source_label"),
                       "target_label": x.get("target_label")}
                      for x in e.json().get("edgelabels", [])],
        }

    async def gremlin(self, query: str, *, timeout: float = 30.0, interval: float = 0.4) -> Any:
        """Run Gremlin through the async job API and return the parsed result.

        1.7 standalone has no *synchronous* Gremlin: the embedded Gremlin Server
        carries no graph/traversal-source binding (dynamic binding is a PD-mode
        feature), so ``POST /gremlin`` always fails. The job API binds per task
        and is the supported path.
        """
        import asyncio

        await self.dialect()
        resp = await self._request("POST", self._g("/jobs/gremlin"),
                                   json_body={"gremlin": query}, ok=(200, 201, 202))
        task_id = resp.json().get("task_id")
        if task_id is None:
            raise StoreError(f"hugegraph gremlin job returned no task id: {resp.text[:200]}")
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            task = (await self._request("GET", self._g(f"/tasks/{task_id}"))).json()
            status = task.get("task_status")
            if status == "success":
                return _parse_result(task.get("task_result"))
            if status in ("failed", "cancelled"):
                raise StoreError(f"hugegraph gremlin job {task_id} {status}: {task.get('task_result')}")
        raise StoreError(f"hugegraph gremlin job {task_id} timed out after {timeout}s")

    async def counts(self) -> dict[str, dict[str, int]]:
        """Vertices/edges per label -- two group-by jobs, no row transfer."""
        v = await self.gremlin("g.V().group().by(label).by(count())")
        e = await self.gremlin("g.E().group().by(label).by(count())")
        return {"vertices": _as_counts(v), "edges": _as_counts(e)}

    async def sample_vertices(self, label: str, limit: int = 20) -> list[dict[str, Any]]:
        await self.dialect()
        resp = await self._request("GET", self._g("/graph/vertices"),
                                   params={"label": label, "limit": limit})
        return resp.json().get("vertices", [])

    async def sample_edges(self, label: str, limit: int = 20) -> list[dict[str, Any]]:
        await self.dialect()
        resp = await self._request("GET", self._g("/graph/edges"),
                                   params={"label": label, "limit": limit})
        return resp.json().get("edges", [])


def _chunks(seq: list[Any], size: int):
    step = max(1, size)
    for i in range(0, len(seq), step):
        yield seq[i:i + step]


def _as_counts(raw: Any) -> dict[str, int]:
    """``group().by(label).by(count())`` -> ``{"label": n}`` (the job result is a
    JSON string holding a one-element list)."""
    if isinstance(raw, str):
        raw = _parse_result(raw)
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    return {str(k): int(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _parse_result(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _plain(v: Any) -> Any:
    # HugeGraph DATE expects "yyyy-MM-dd HH:mm:ss.SSS" (an ISO "T" separator is
    # rejected), so datetimes are rendered explicitly rather than via isoformat.
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S.") + f"{v.microsecond // 1000:03d}"
    if isinstance(v, _dt.date):
        return v.strftime("%Y-%m-%d")
    return v
