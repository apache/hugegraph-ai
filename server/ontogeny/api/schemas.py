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
"""Request bodies for the REST surface. Module-level on purpose: FastAPI
resolves handler annotations against the module namespace -- a model class
nested inside a function silently degrades the parameter to a query param."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# ------------------------------------------------------------------ schemas


class QueryBody(BaseModel):
    filter: Any = None
    sort: Any = None
    limit: int = 100
    offset: int = 0
    links: list[str] | None = None
    via: str | None = None


class AggregateBody(BaseModel):
    fn: str
    field: str | None = None
    filter: Any = None


class RejectBody(BaseModel):
    """Human rejection of an evolution proposal -- the reason becomes the
    loop's memory (fed to the proposer's prompt on later rounds)."""
    reason: str = ""


class GraduationBody(BaseModel):
    """T3 ticket: request a mutation class be moved toward T0."""
    mutation: str


class ActionBody(BaseModel):
    parameters: dict[str, Any] = {}
    target_id: str | None = None
    expected_revision: int | None = None
    idempotency_key: str | None = None


class FunctionBody(BaseModel):
    parameters: dict[str, Any] = {}
    version: str | None = None  # pin the expected function content version


class TraverseBody(BaseModel):
    start_type: str
    start_ids: list[str]
    path: list[dict[str, Any]]
    max_depth: int = 3


class EvolveProposalBody(BaseModel):
    gap: dict[str, Any]


class PublishBody(BaseModel):
    path: str | None = None


class DomainCreateBody(BaseModel):
    """Scaffold a new (empty) ontology package under the domains root."""

    name: str
    display: str | None = None
    description: str | None = None
    activate: bool = True


class DomainActivateBody(BaseModel):
    name: str


# ------------------------------------------------------------------ accounts


class LoginBody(BaseModel):
    username: str
    password: str


class UserCreateBody(BaseModel):
    username: str
    password: str
    display: str = ""
    roles: list[str] = []
    site: str | None = None
    markings: list[str] = []
    is_admin: bool = False


class UserUpdateBody(BaseModel):
    """Every field optional: a PATCH touches only what it names."""
    display: str | None = None
    password: str | None = None
    roles: list[str] | None = None
    site: str | None = None
    markings: list[str] | None = None
    status: str | None = None
    is_admin: bool | None = None


class RoleBody(BaseModel):
    """A role's grant set: the actions it may perform.

    ``site`` optionally scopes every grant to one site, which is the one
    constraint the matrix can express without becoming a policy editor.
    """
    name: str
    actions: list[str] = []
    site: str | None = None


class RoleDeleteBody(BaseModel):
    name: str
    # roles are referenced by accounts; deleting one that is still held would
    # silently strip access, so the caller must say what to do about it
    reassign_to: str | None = None


class RuntimeConfigBody(BaseModel):
    """LLM and storage provider selection for the operations console."""
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    storage_provider: str | None = None
    storage_url: str | None = None
    # Graph-server credentials: needed by any HugeGraph in auth mode, which is
    # also the only kind of 1.7 server where the platform may create a graph.
    storage_user: str | None = None
    storage_password: str | None = None


class FunctionSourceBody(BaseModel):
    """A function's code, as typed in the console.

    Saving never executes the body — trying it first is the separate
    ``POST /functions/{name}/test`` endpoint, so a save's side effects stay
    exactly the file, the version and the revision row.
    """
    source: str


class FunctionTestBody(BaseModel):
    """Editor text to run once without saving anything."""
    source: str


class ProjectionScaffoldBody(BaseModel):
    """Optional naming for an auto-derived whole-ontology projection.

    The graph name is NOT settable: it is the domain's own name, so a domain
    cannot be pointed at another model's graph.
    """
    name: str | None = None
    graphspace: str = "DEFAULT"


class BuilderSaveBody(BaseModel):
    """Full or partial ontology resources as JSON (builder output).

    Module-level on purpose: FastAPI resolves handler annotations against the
    module namespace -- a model class nested inside ``build_app`` silently
    degrades the parameter to a query param.
    """
    resources: list[dict[str, Any]]  # each = {apiVersion, kind, metadata, spec}
    story: list[dict[str, Any]] | None = None  # optional demo-story steps
    # "Kind/name" entries to remove from the package before writing
    # (builder-tracked deletions/renames; keeps disk == canvas)
    deletes: list[str] | None = None
    # Canvas node positions, committed alongside the model on save (stored as
    # the package's layout.yaml sidecar). None = leave the stored layout
    # untouched; {} = clear it (the canvas falls back to automatic layout).
    layout: dict[str, Any] | None = None


class MountSource(BaseModel):
    """Where the data lives. CSV carries its content inline (uploaded file or
    pasted text -- the server materializes it into the package's data/ dir);
    SQL sources carry a DSN and table name."""

    kind: Literal["csv", "sqlite", "postgres", 'mysql']
    filename: str | None = None       # csv only
    content: str | None = None        # csv only: the file text
    dsn: str | None = None            # sqlite/postgres only
    table: str | None = None          # sql only (csv uses the filename stem)


class MountBody(BaseModel):
    """Data mounting for the scenario builder: attach a store to the package,
    bind an object type's backing to it, publish, and pull the rows in."""

    object: str
    store: str = ""                   # store resource name; defaults to csv-<object>
    source: MountSource
    # prop -> source column overrides; same-name columns map implicitly
    mapping: dict[str, str] | None = None



class AssistantBody(BaseModel):
    messages: list[dict[str, str]]
    propose: bool = False


class SessionBudgetBody(BaseModel):
    """Per-session budget overrides; 0 = unlimited, omitted = plugin default."""
    steps: int | None = None
    wall_ms: int | None = None
    writes_per_session: int | None = None


class AgentSessionBody(BaseModel):
    plugin: str
    task: str = ""
    budget: SessionBudgetBody | None = None
    expires_at: str | None = None  # ISO instant; past that the session refuses calls


class AgentRunBody(BaseModel):
    """THIS drive's instruction. Optional: omitted -> the session keeps its
    current task (a plain re-drive of the same assignment)."""
    task: str | None = None


class AgentToolBody(BaseModel):
    # tool input; act_* may carry `rationale` for the approval queue
    filter: dict | None = None
    limit: int | None = None
    parameters: dict | None = None
    target_id: str | None = None
    expected_revision: int | None = None
    start_type: str | None = None
    start_ids: list[str] | None = None
    path: list[dict] | None = None
    rationale: str | None = None
    # the driving agent's own reasoning for this call; recorded on the step and
    # shown in the console's timeline (it is NOT a tool argument)
    thought: str | None = None


class AgentFinishBody(BaseModel):
    result: dict | None = None


class AgentDecisionBody(BaseModel):
    decision: Literal["approved", "rejected"]


class ExploreBody(BaseModel):
    start_type: str | None = None
    start_id: str | None = None
    n: int = 12
    max_depth: int = 3
    seed: int | None = None
