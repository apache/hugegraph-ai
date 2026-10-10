/*
 * Copyright 2026 Apache HugeGraph Authors
 * 
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * 
 *     http://www.apache.org/licenses/LICENSE-2.0
 * 
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
/** Backend payload types (mirrors server/ontogeny/api/app.py + registry compiled.to_meta). */

/** How a property gets its value, when it is not stored directly. */
export interface PropertyDerivation {
  kind: 'expr' | 'function'
  /** The read-time expression — set when `kind === 'expr'`. */
  expr?: string | null
  /** Function entry point — set when `kind === 'function'`. */
  entry?: string | null
  /** Other object types whose changes also recompute this property. */
  triggers?: string[]
}

export interface PropertyMeta {
  type: string
  required: boolean
  marking: string | null
  /** Human name for the field, so panels never have to show only the machine name. */
  display?: string | null
  /** Business meaning of the field (DSL `description:`). */
  description?: string | null
  /** `source` = maintained by sync; `ontology` = action-layer owned. */
  owner?: 'source' | 'ontology' | null
  derived?: PropertyDerivation | null
}

export interface ObjectMeta {
  display?: string
  primaryKey: string[]
  properties: Record<string, PropertyMeta>
  links: string[]
  actions: string[]
}

export interface ParamMeta {
  type: string
  required: boolean
  default?: string | number | boolean | null
}

export interface ActionMeta {
  display?: string
  target: string
  parameters: Record<string, ParamMeta>
}

export interface FunctionMeta {
  entry: string
  parameters: Record<string, ParamMeta>
  /** declared capabilities, e.g. read-objects: [..] -- used by the dashboard
   *  constellation to link a function to the object types it reads */
  capabilities?: Array<Record<string, unknown>>
}

export type Cardinality = 'ONE_TO_ONE' | 'ONE_TO_MANY' | 'MANY_TO_MANY'

/** A declared LinkType with its direction. `ObjectMeta.links` only says "this
 *  type is an endpoint", so consumers need this map to know which end is the
 *  source — older snapshots omit it. */
export interface LinkTypeMeta {
  display?: string
  source: string
  target: string
  cardinality: Cardinality
}

export interface OntologyMeta {
  package: string
  content_hash: string
  objects: Record<string, ObjectMeta>
  actions: Record<string, ActionMeta>
  functions: Record<string, FunctionMeta>
  projections: Record<string, { engine: string; graph: string; objects?: string[]; links?: string[] }>
  policies?: Record<string, { display?: string; source: string; rules: number }>
  /** The role vocabulary the Cedar policies reference — the only roles an
   *  agent-plugin principal may declare (anything else is AGENT-ROLE-UNKNOWN). */
  roles?: string[]
  linkTypes?: Record<string, LinkTypeMeta>
}

/** One DSL resource exactly as it is compiled and as `/admin/builder/save`
 *  accepts it. The Knowledge / Action editors hold these verbatim (see
 *  `api/resources.ts` for why the meta snapshot is not enough to edit from). */
export interface OntologyResource {
  apiVersion: string
  kind: 'ObjectType' | 'LinkType' | 'Projection' | 'Action' | 'Function' | 'PolicySet'
  metadata: { name: string; display?: string | null; description?: string | null }
  spec: Record<string, unknown>
}

export interface QueryResult {
  objects: Record<string, unknown>[]
  total: number
  latency_ms: number
  links?: Record<string, Record<string, Record<string, unknown>[]>>
}

export interface LinkEdge {
  src: string
  dst: string
  edge_type: string
}

export interface RevisionRow {
  id: number
  action: string
  object_type: string
  object_id: string
  principal: string
  outcome: string
  message: string | null
  created_at: string | null
}

export interface SignalRow {
  id: number
  kind: string
  evidence: Record<string, unknown>
}

export interface ProposalSummary {
  id: number
  status: string
  tier: string | null
  gap_kind: string
  /** Who decided the mutation: the LLM (when a provider is configured) or the
   *  deterministic heuristic fallback. */
  origin?: 'llm' | 'heuristic' | 'human'
  /** The model's own reasoning, kept even when it DECLINED the mutation. */
  llm_analysis?: string | null
  superseded_by?: number | null
}

export interface ProposalDetail extends ProposalSummary {
  diff: Array<Record<string, string>>
  rationale: string
  eval_report: { passed?: boolean; suites?: Record<string, unknown> } | null
  rejected_reason?: string | null
  signal_id?: number | null
}

export interface AssistantReply {
  content: string
  thinking?: string | null
  proposals?: Array<Record<string, string>> | null
  rationale?: string | null
}

export interface Mutation {
  mutation: string
  object?: string
  prop?: string
  type?: string
  value?: string
  [k: string]: unknown
}

export interface Principal {
  id: string
  Role?: string[]
  roles?: string[]
  site?: string
  markings?: string[]
  /** UI-only facts the server attaches; the engine ignores unknown keys. */
  display?: string
  is_admin?: boolean
  authenticated?: boolean
  /** Which resolution won: session cookie, bearer token, the dev header, none. */
  via?: 'session' | 'bearer' | 'dev-header' | 'anonymous'
}

export interface TraverseStep {
  type: string
  ids: string[]
  objects: Record<string, unknown>[]
}

export interface TraverseEdge {
  link: string
  source: { type: string; id: string }
  target: { type: string; id: string }
}

export interface TraverseResult {
  steps: TraverseStep[]
  edges?: TraverseEdge[]
  final_ids: string[]
}

/** One object type with its row count and a few sample rows (/data/preview). */
export interface DataPreviewType {
  type: string
  display?: string
  primary_key: string
  total: number | null
  rows: Record<string, unknown>[]
  error?: string
}

export interface DataPreview {
  objects: DataPreviewType[]
  total: number
}

export interface ProjectionLabel {
  name: string
  primary_keys?: string[]
  source_label?: string
  target_label?: string
}

export interface ProjectionSummary {
  /** Does the package DECLARE a Projection resource? (independent of whether a
   *  graph client is wired — conflating the two is what made the console offer
   *  "create a projection" for a package that already had one) */
  declared?: boolean
  declared_name?: string | null
  /** Why the layer is not wired, when it is not: each cause has its own fix. */
  blocked_by?: 'not-declared' | 'provider-sqlite' | 'endpoint-unresolved' | 'extension-missing' | null
  /** A probe we were not allowed to make (e.g. credentials refused). */
  probe_error?: string
  auth_rejected?: boolean
  configured: boolean
  ok: boolean
  /** Effective storage provider ('hugegraph' | 'sqlite') — lets the console tell
   *  "sqlite by design" apart from "HugeGraph selected but nothing projected". */
  storage_provider?: 'hugegraph' | 'sqlite'
  /** The one graph a domain owns: its own English name, snake-cased. */
  graph_name?: string
  /** Whether that graph exists on the server yet. `null` = could not be probed
   *  (no endpoint / no graph extension / unreachable) — an answer the console
   *  must never round to "absent". */
  graph_exists?: boolean | null
  reason?: string
  error?: string
  code?: string
  name?: string
  engine?: string
  graph?: string
  graphspace?: string
  dialect?: string
  objects?: string[]
  links?: string[]
  labels?: { vertices: ProjectionLabel[]; edges: ProjectionLabel[] }
  counts?: { vertices: Record<string, number>; edges: Record<string, number> }
}

/** Graph rows come back re-assembled by the engine (same shape as object reads). */
export interface ProjectionVertices {
  label: string
  rows: Record<string, unknown>[]
  hidden: number
  sampled: number
}

export interface ProjectionEdgeEnd {
  type: string
  id: string
  display: string
}

export interface ProjectionEdge {
  id: string
  link: string
  source: ProjectionEdgeEnd
  target: ProjectionEdgeEnd
}

export interface ProjectionEdges {
  label: string
  rows: ProjectionEdge[]
  hidden: number
  sampled: number
}

export interface ExploreNode extends Record<string, unknown> {
  _type: string
  _id: string
}

export interface ExploreEdge {
  link: string
  source: { type: string; id: string }
  target: { type: string; id: string }
}

export interface ExploreResult {
  start: { type: string; id: string }
  n_requested: number
  depth: number
  nodes: ExploreNode[]
  edges: ExploreEdge[]
  truncated: boolean
}

/* ---------------------------------------------------------------- agent */

export interface AgentToolDef {
  name: string
  kind: 'meta' | 'search' | 'call' | 'traverse' | 'act'
  target?: string | null
  description: string
  writes: boolean
  input_schema: Record<string, unknown>
}

export interface AgentPluginInfo {
  name: string
  display?: string
  description?: string
  transport: string
  engine: { kind: 'builtin-llm' | 'external-pull' | 'external-push'; endpoint?: string | null }
  principal: Record<string, unknown>
  approval: string
  budget: { steps: number; wall_ms: number; writes_per_session: number }
  tools: Record<string, AgentToolDef>
}

export interface AgentStep {
  seq: number
  tool: string
  args: string
  /** The driver's own reasoning for this call (engine or external agent).
   *  Empty when the driver did not supply one. */
  thought?: string
  outcome: string
  detail?: Record<string, unknown> | null
  latency_ms: number
  revision_id?: number | null
  approval_id?: number | null
  /** which drive of the session produced this step (1-based; 0 = legacy) */
  run_no?: number
}

export interface AgentSession {
  id: number
  plugin: string
  principal: string
  task: string
  status: string
  budget: { steps: number; wall_ms: number; writes: number; writes_used: number; steps_used: number }
  /** how many times this session has been driven (steps are tagged per run) */
  run_count?: number
  /** past this instant the session refuses calls and runs */
  expires_at?: string | null
  catalog_hash: string
  created_at?: string | null
  tools?: Record<string, AgentToolDef>
  steps?: AgentStep[]
  result?: { final?: string; thought?: string; error?: string; blocked_on?: number } | null
}

export interface AgentApproval {
  id: number
  session_id: number
  plugin: string
  tool: string
  action: string
  parameters: Record<string, unknown>
  target_id?: string | null
  rationale: string
  status: string
  requested_at?: string | null
  /** set once the gate has decided (and, on executed, the revision id) */
  decided_by?: string | null
  decided_at?: string | null
}

export interface AgentToolCallResult {
  outcome: string
  error?: string
  detail?: unknown
  approval_id?: number
  revision_id?: number
  object_id?: string
  step?: number
  latency_ms?: number
}

export interface ExtensionInfo {
  name: string
  kind: string
  display: string
  description: string
  provides: string[]
  requires: string[]
  entry: string
  status: 'discovered' | 'disabled' | 'loaded' | 'error' | 'skipped'
  error?: string | null
  path: string
}

export interface ExtensionsInventory {
  extensions: ExtensionInfo[]
  capabilities: Record<string, { extension: string } & Record<string, unknown>>
  dirs: string[]
}

