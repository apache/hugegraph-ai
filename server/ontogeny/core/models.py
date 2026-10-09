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
"""Pydantic models for the nine DSL resource kinds (dsl-spec).

Strict by design: ``extra='forbid'`` everywhere so typos fail at load, not at
runtime. Environment references (``${VAR}``) are carried unresolved; the
runtime resolves them via Settings.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .types import PropertyType

API_VERSION = "ontogeny/v1"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ResourceMeta(_Model):
    name: str
    display: str | None = None
    description: str | None = None
    version: str | None = None

    @field_validator("name")
    @classmethod
    def _kebab(cls, v: str) -> str:
        if not NAME_RE.fullmatch(v):
            raise ValueError(f"name must be kebab-case, got {v!r}")
        return v


# ---------------------------------------------------------------- store


class StoreSpec(_Model):
    type: Literal["postgres", "sqlite", "duckdb", "csv", "parquet", "iceberg"]
    connection: str
    access: Literal["read-only", "read-write"] = "read-only"


# ---------------------------------------------------------------- object


class PropertyDef(_Model):
    type: str
    display: str | None = None
    description: str | None = None
    required: bool = False
    owner: Literal["source", "ontology"] | None = None
    marking: str | None = None
    # expression (read-time) or {"kind": "function", "entry": ..., "object_param": ...,
    # "triggers": [other, object, types]} (write-time, materialized by the
    # derivation worker; `triggers` extends recompute events beyond the owning
    # type -- a cross-object count must refresh when the OTHER table moves)
    derived: str | dict[str, Any] | None = None

    def derived_kind(self) -> str | None:
        if isinstance(self.derived, str):
            return "expr"
        if isinstance(self.derived, dict):
            return "function"
        return None

    def derived_entry(self) -> str | None:
        return str(self.derived.get("entry")) if self.derived_kind() == "function" else None

    def derived_object_param(self) -> str:
        return str((self.derived or {}).get("object_param") or "obj")

    def derived_triggers(self) -> list[str]:
        """Extra object types whose changes must recompute this property."""
        if self.derived_kind() != "function":
            return []
        triggers = (self.derived or {}).get("triggers") or []
        return [str(t) for t in triggers]

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        PropertyType.parse(v)  # raises ValueError with details
        return v

    def ptype(self) -> PropertyType:
        return PropertyType.parse(self.type)


class WatermarkCfg(_Model):
    column: str


class SyncCfg(_Model):
    strategy: Literal["snapshot", "watermark", "changelog"]
    watermark: WatermarkCfg | None = None
    schedule: str | None = None
    deletes: Literal["none", "absent-means-archive"] | None = None


class SourceRef(_Model):
    schema_: str | None = Field(default=None, alias="schema")
    table: str


class BackingSpec(_Model):
    store: str
    mode: Literal["materialized", "virtual"] = "materialized"
    """materialized = rows are pulled into the platform's relational tables;
    virtual = the source is declared but never synced (query push-down target)."""
    source: SourceRef
    mapping: dict[str, str] = Field(default_factory=dict)  # prop -> column (overrides; same-name implied)
    sync: SyncCfg | None = None


class ObjectTypeSpec(_Model):
    primaryKey: list[str] = Field(min_length=1)
    properties: dict[str, PropertyDef] = Field(min_length=1)
    backing: BackingSpec | None = None


# ---------------------------------------------------------------- link


class ForeignKeyJoin(_Model):
    kind: Literal["foreign-key"]
    keys: dict[str, str]  # "target-side.prop" -> "source-side.prop"


class JoinTableSide(_Model):
    model_config = ConfigDict(extra="allow")
    # {prop: column}


class JoinTableJoin(_Model):
    kind: Literal["join-table"]
    store: str
    relation: SourceRef
    keys: dict[str, dict[str, str]]  # {"source": {...}, "target": {...}}


JoinSpec = Annotated[Union[ForeignKeyJoin, JoinTableJoin], Field(discriminator="kind")]


class LinkSpec(_Model):
    source: str
    target: str
    cardinality: Literal["ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_MANY"]
    join: JoinSpec


# ---------------------------------------------------------------- action


class ParamDef(_Model):
    type: str
    required: bool = False
    default: Any = None
    display: str | None = None
    unit: str | None = None  # documentation metadata for return types

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        PropertyType.parse(v)
        return v

    def ptype(self) -> PropertyType:
        return PropertyType.parse(self.type)


class Rule(_Model):
    expr: str
    message: str | None = None


class _EffectBase(_Model):
    when: str | None = None


class ModifyTargetEffect(_EffectBase):
    kind: Literal["modify-target"]
    set: dict[str, str]


class ModifyLinkedEffect(_EffectBase):
    kind: Literal["modify-linked"]
    link: str
    set: dict[str, str]


class CreateObjectEffect(_EffectBase):
    kind: Literal["create-object"]
    properties: dict[str, str]


class ArchiveObjectEffect(_EffectBase):
    kind: Literal["archive-object"]


class LinkEntry(_Model):
    model_config = ConfigDict(extra="allow")


class SetLinkEffect(_EffectBase):
    kind: Literal["set-link"]
    link: str
    add: list[LinkEntry] = Field(default_factory=list)
    remove: list[LinkEntry] = Field(default_factory=list)


class WebhookEffect(_EffectBase):
    kind: Literal["webhook"]
    url: str


class EmitEventEffect(_EffectBase):
    kind: Literal["emit-event"]
    payload: dict[str, Any] = Field(default_factory=dict)


Effect = Annotated[
    Union[
        ModifyTargetEffect,
        ModifyLinkedEffect,
        CreateObjectEffect,
        ArchiveObjectEffect,
        SetLinkEffect,
        WebhookEffect,
        EmitEventEffect,
    ],
    Field(discriminator="kind"),
]


class FunctionExecution(_Model):
    kind: Literal["function"]
    entry: str  # "file.py:function"


class ApprovalCfg(_Model):
    approvers: int = 1
    exclude_submitter: bool = True


class AuditCfg(_Model):
    fields: list[str] | None = None


class ActionSpec(_Model):
    target: str
    parameters: dict[str, ParamDef] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)
    policy: str | None = None  # PolicySet name; None -> package default ("default")
    effects: list[Effect] = Field(default_factory=list)
    execution: FunctionExecution | None = None
    approval: ApprovalCfg | None = None
    scheduled: bool = False
    revertible: bool = False
    audit: AuditCfg = Field(default_factory=AuditCfg)


# ---------------------------------------------------------------- function


class Capability(_Model):
    model_config = ConfigDict(extra="allow")  # read-objects: [..] / llm: true / http: {allow: [..]}


class FunctionStep(_Model):
    """One step of a declarative function's pipeline.

    Deliberately a small, linear vocabulary — read an object type, ask a model,
    call an endpoint — because that is what a prompt-shaped function actually is.
    Anything needing a loop or a branch belongs in a code function; keeping the
    declarative side narrow is what stops it becoming a bad programming language
    with no debugger.
    """
    id: str
    kind: Literal["read", "llm", "http"]
    # read
    object: str | None = None
    filter: dict[str, Any] | None = None
    limit: int | None = None
    # llm
    prompt: str | None = None
    system: str | None = None
    # http
    method: str | None = None
    url: str | None = None
    body: Any = None
    headers: dict[str, str] | None = None


class FunctionSpec(_Model):
    """A function body: either code (``python``) or a declared pipeline.

    ``python`` keeps the sandbox: the entry names a real file in the package and
    a child process runs it. ``declarative`` has no file at all — the body IS the
    DSL, which is what makes a prompt editable, versionable and reviewable
    without editing Python.
    """
    runtime: Literal["python", "declarative"] = "python"
    # required for python; meaningless for declarative
    entry: str = ""
    parameters: dict[str, ParamDef] = Field(default_factory=dict)
    returns: ParamDef | None = None
    steps: list[FunctionStep] = Field(default_factory=list)
    # declarative only: which step's value IS the function's result. Omitted, the
    # function returns every step keyed by id — explicit, so adding a step can
    # never silently change what a caller receives.
    returns_step: str | None = None
    capabilities: list[Capability] = Field(default_factory=list)


# ---------------------------------------------------------------- policy


class PolicySetSpec(_Model):
    language: Literal["cedar"] = "cedar"
    source: str


# ---------------------------------------------------------------- projection


class ProjectionObjectCfg(_Model):
    properties: list[str] = Field(default_factory=list)


class ProjectionInclude(_Model):
    objects: dict[str, ProjectionObjectCfg]
    links: list[str] = Field(default_factory=list)


class ProjectionIndex(_Model):
    object: str
    property: str


class ProjectionSpec(_Model):
    engine: Literal["hugegraph"] = "hugegraph"
    endpoint: str
    graph: str
    # HugeGraph 1.7 namespaces every graph under a graphspace; 1.5 has no such
    # concept and ignores this.
    graphspace: str = "DEFAULT"
    # REST dialect: auto probes the endpoint once (/graphspaces => 1.7).
    api: Literal["auto", "1.5", "1.7"] = "auto"
    include: ProjectionInclude
    deletion: Literal["remove", "keep-flagged"] = "remove"
    indexes: list[ProjectionIndex] = Field(default_factory=list)


# ---------------------------------------------------------------- agent plugin


class AgentPluginPrincipal(_Model):
    """The plugin's own identity: this IS its permission surface (I1).

    Roles/site/markings resolve against the same Cedar policies a human
    principal would -- a plugin can never exceed what its declared identity
    is permitted, no matter what its tool list promises.
    """
    id: str
    Role: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)  # lowercase alias, OIDC style
    site: str | None = None
    markings: list[str] = Field(default_factory=list)

    def as_principal(self) -> dict:
        out: dict = {"id": self.id}
        roles = sorted(set(self.Role) | set(self.roles))
        if roles:
            out["Role"] = roles
        if self.site is not None:
            out["site"] = self.site
        if self.markings:
            out["markings"] = list(self.markings)
        return out


class AgentPluginTransport(_Model):
    # how the external agent reaches the platform; the platform NEVER calls
    # out to the agent -- every transport is the agent calling IN through the
    # session protocol (http: plain REST, mcp: MCP client, webhook: scripted
    # callbacks, local: in-process driver used by tests/evals).
    kind: Literal["http", "mcp", "webhook", "local"] = "http"
    endpoint: str | None = None


class AgentPluginTools(_Model):
    allow: list[str] = Field(default_factory=list)   # subset of the compiled catalog
    deny: list[str] = Field(default_factory=list)    # explicit narrowing on top


class AgentPluginApproval(_Model):
    # writes: confirm (human gate, default) | never (read-only plugin) | auto
    #         (auto-approve ONLY the actions listed in auto_actions; M3)
    writes: Literal["confirm", "never", "auto"] = "confirm"
    auto_actions: list[str] = Field(default_factory=list)


class AgentPluginBudget(_Model):
    steps: int = 40
    wall_ms: int = 120_000
    writes_per_session: int = 3


class AgentEngineSpec(_Model):
    """Who drives this plugin's sessions (agent-paradigm.md §3).

    builtin-llm: the platform's in-process LLM tool loop (needs ONTOGENY_LLM_BASE_URL
    at runtime -- keys never live in Git). external-pull: a third-party runtime
    drives the session over the session protocol. external-push: the platform
    delegates to the engine's HTTP endpoint (fields reserved; not implemented).
    """
    kind: Literal["builtin-llm", "external-pull", "external-push"] = "external-pull"
    endpoint: str | None = None


class AgentPluginSpec(_Model):
    engine: AgentEngineSpec = Field(default_factory=AgentEngineSpec)
    principal: AgentPluginPrincipal
    transport: AgentPluginTransport = Field(default_factory=AgentPluginTransport)
    tools: AgentPluginTools = Field(default_factory=AgentPluginTools)
    approval: AgentPluginApproval = Field(default_factory=AgentPluginApproval)
    budget: AgentPluginBudget = Field(default_factory=AgentPluginBudget)


# ---------------------------------------------------------------- eval suite


class AgentCaseExpect(_Model):
    """Agent eval expectations (deterministic selection, no LLM judge).

    ``outcomes`` compares per-step outcome classes (mapped through the same
    ok/denied/rejected classifier the demo story uses). ``idempotent`` replays
    the whole script in a fresh session and requires every write step to be
    refused by rules/policy the second time -- a double-apply is a red.
    """
    outcomes: list[str] = Field(default_factory=list)
    idempotent: bool = False


class AgentCase(_Model):
    name: str
    plugin: str
    # scripted trajectory: [{tool, args}] -- real LLM is NOT reproducible, so
    # evals replay recorded/scripted tool sequences through the real broker.
    script: list[dict[str, Any]] = Field(default_factory=list)
    expect: AgentCaseExpect = Field(default_factory=AgentCaseExpect)


class QueryExpectation(_Model):
    columns: list[str] | None = None
    max_latency_ms: int | None = Field(default=None, alias="max-latency-ms")
    row_count_max: int | None = Field(default=None, alias="row-count-max")
    min_rows: int | None = Field(default=None, alias="min-rows")


class QueryCase(_Model):
    name: str
    query: dict[str, Any]  # {object, filter?, sort?, limit?}
    expect: QueryExpectation = Field(default_factory=QueryExpectation)


class ReplayExpectation(_Model):
    no_double_close: bool = Field(default=True, alias="no-double-close")
    effects_idempotent: bool = Field(default=True, alias="effects-idempotent")
    outcomes_match: float | None = Field(default=None, alias="outcomes-match")  # min fraction of replays whose outcome class matches history


class ReplayCase(_Model):
    action: str
    cases: Literal["from-revisions"]
    since: str  # e.g. "90d"
    expect: ReplayExpectation = Field(default_factory=ReplayExpectation)


class CoverageCfg(_Model):
    objects: list[str]
    expect: dict[str, Any] = Field(default_factory=dict)  # {"quarantine-rate": "<1%"} kept symbolic


class EvalSuiteSpec(_Model):
    queries: list[QueryCase] = Field(default_factory=list)
    replays: list[ReplayCase] = Field(default_factory=list)
    agents: list[AgentCase] = Field(default_factory=list)
    coverage: CoverageCfg | None = None


# ---------------------------------------------------------------- evolution policy


class ObservabilityCfg(_Model):
    collect: list[str] = Field(default_factory=list)
    marking_aware: bool = Field(default=True, alias="marking-aware")
    #: per-detector sensitivity, keyed like {"unmapped_filter_min": 2,
    #: "slow_query_p95_ms": 1500, ...} -- unset keys keep the built-in defaults
    thresholds: dict[str, float] = Field(default_factory=dict)


class BudgetCfg(_Model):
    per_week: int = Field(alias="per-week")
    blast_radius: str = Field(default="single-namespace", alias="blast-radius")


class TierCfg(_Model):
    mutations: list[str] = Field(default_factory=list)
    budget: BudgetCfg | None = None
    requires: list[str] = Field(default_factory=list)


class GraduationCfg(_Model):
    rule: str


class EvolutionPolicySpec(_Model):
    loop: bool = True
    #: direction F: how often the scheduled observe+diagnose beat runs; 0 = the
    #: loop only moves when someone clicks (promotion stays human-gated either way)
    interval_minutes: int = Field(default=0, alias="interval-minutes")
    observability: ObservabilityCfg = Field(default_factory=ObservabilityCfg)
    tiers: dict[str, TierCfg] = Field(default_factory=dict)
    graduation: GraduationCfg | None = None


# ---------------------------------------------------------------- ontology manifest


class OntologySpec(_Model):
    imports: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- resource wrappers


class _Resource(_Model):
    model_config = ConfigDict(extra="forbid")
    apiVersion: Literal["ontogeny/v1"]
    metadata: ResourceMeta



class StoreResource(_Resource):
    kind: Literal["Store"]
    spec: StoreSpec


class ObjectTypeResource(_Resource):
    kind: Literal["ObjectType"]
    spec: ObjectTypeSpec


class LinkTypeResource(_Resource):
    kind: Literal["LinkType"]
    spec: LinkSpec


class ActionResource(_Resource):
    kind: Literal["Action"]
    spec: ActionSpec


class FunctionResource(_Resource):
    kind: Literal["Function"]
    spec: FunctionSpec


class PolicySetResource(_Resource):
    kind: Literal["PolicySet"]
    spec: PolicySetSpec


class ProjectionResource(_Resource):
    kind: Literal["Projection"]
    spec: ProjectionSpec


class AgentPluginResource(_Resource):
    kind: Literal["AgentPlugin"]
    spec: AgentPluginSpec


class EvalSuiteResource(_Resource):
    kind: Literal["EvalSuite"]
    spec: EvalSuiteSpec


class EvolutionPolicyResource(_Resource):
    kind: Literal["EvolutionPolicy"]
    spec: EvolutionPolicySpec


class OntologyResource(_Resource):
    kind: Literal["Ontology"]
    spec: OntologySpec


RESOURCE_BY_KIND = {
    "Store": StoreResource,
    "ObjectType": ObjectTypeResource,
    "LinkType": LinkTypeResource,
    "Action": ActionResource,
    "Function": FunctionResource,
    "PolicySet": PolicySetResource,
    "Projection": ProjectionResource,
    "AgentPlugin": AgentPluginResource,
    "EvalSuite": EvalSuiteResource,
    "EvolutionPolicy": EvolutionPolicyResource,
    "Ontology": OntologyResource,
}

AnyResource = (
    StoreResource | ObjectTypeResource | LinkTypeResource | ActionResource
    | FunctionResource | PolicySetResource | ProjectionResource | EvalSuiteResource
    | EvolutionPolicyResource | OntologyResource
)
