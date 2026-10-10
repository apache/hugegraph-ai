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
/** API client: single typed door to the backend.
 *
 * - baseURL from VITE_API_BASE (defaults to '' -- dev proxy)
 * - injects the dev principal (X-Ontogeny-Principal) chosen in the PrincipalBar
 * - unwraps the backend error model {code, message, details} into ApiError
 */
import type {
  ActionMeta,
  AgentApproval,
  AgentPluginInfo,
  AgentSession,
  AssistantReply,
  DataPreview,
  FunctionMeta,
  OntologyMeta,
  OntologyResource,
  Principal,
  ProjectionEdges,
  ProjectionSummary,
  ProjectionVertices,
  ProposalDetail,
  ProposalSummary,
  QueryResult,
  RevisionRow,
  SignalRow,
  TraverseResult,
  ExploreResult,
  ExtensionsInventory,
} from './types'

export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, unknown>

  constructor(code: string, message: string, status: number, details?: Record<string, unknown>) {
    super(message)
    this.code = code
    this.status = status
    this.details = details
  }
}

/** One switchable ontology (a package directory on disk). */
export interface DomainInfo {
  name: string
  display?: string | null
  description?: string | null
  path: string
  objects: number
  links: number
  actions: number
  /** Live health check: the package on disk loads and validates (see
   *  `ServiceContext.list_domains`). Errors cap at the first few. */
  check: { ok: boolean; errors: string[] }
  active: boolean
}

export const PRESET_PRINCIPALS: Record<string, Principal> = {
  planner: { id: 'u-planner', Role: ['planner'], site: 'plant-north' },
  planner_marked: { id: 'u-planner-m', Role: ['planner'], site: 'plant-north', markings: ['internal'] },
  operator: { id: 'u-operator', Role: ['operator'], site: 'plant-north' },
  quality: { id: 'u-quality', Role: ['quality'], site: 'plant-north' },
  visitor: { id: 'visitor', Role: ['visitor'] },
  agent: { id: 'mcp-agent', Role: ['service'] },
}

const PRINCIPAL_KEY = 'ontogeny.principal'

/** The explicit development override, or null when there is none.
 *
 * This is deliberately separate from `getPrincipal()`: the header may only be
 * sent when someone actually chose an override. Sending a *default* preset on
 * every request used to be harmless, but now that accounts exist it would
 * shadow the session for any caller that has one — and a principal carrying a
 * non-ASCII display name is not even a legal HTTP header value.
 */
export function getDevPrincipal(): Principal | null {
  const raw = localStorage.getItem(PRINCIPAL_KEY)
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (p && typeof p.id === 'string') return p
  } catch {
    /* corrupt override: ignore it rather than break every request */
  }
  return null
}

/** The principal to *display* (settings dialog): the override, else the default
 *  preset that a fresh dev session would act as. */
export function getPrincipal(): Principal {
  return getDevPrincipal() ?? PRESET_PRINCIPALS.planner
}

export function setPrincipal(p: Principal | null): void {
  if (p === null) {
    localStorage.removeItem(PRINCIPAL_KEY)
    return
  }
  localStorage.setItem(PRINCIPAL_KEY, JSON.stringify(p))
}

/** HTTP header values are ISO-8859-1; a principal with a Chinese display name
 *  would throw inside `fetch` rather than fail politely. Exported for the
 *  Access page's identity tab, which validates custom JSON before applying it. */
export function headerSafe(p: Principal): boolean {
  try {
    return /^[\x20-\x7e]*$/.test(JSON.stringify(p))
  } catch {
    return false
  }
}

const BASE = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE ?? ''

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // The dev override, and only when one was actually chosen: a signed-in caller
  // is identified by the session cookie, which the browser attaches itself.
  const dev = getDevPrincipal()
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (dev && headerSafe(dev)) headers['X-Ontogeny-Principal'] = JSON.stringify(dev)

  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, {
      ...init,
      // the session is an HttpOnly cookie: same-origin keeps it out of script's
      // reach while still sending it on every API call
      credentials: 'same-origin',
      headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
    })
  } catch (e) {
    // an aborted long-running call (diagnose modal's 中断) is a normal state,
    // not a network failure — give it its own code so callers can branch
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError('ABORTED', 'request aborted', 0)
    }
    throw new ApiError('NETWORK', `backend unreachable: ${String(e)}`, 0)
  }
  if (!resp.ok) {
    let code = `HTTP_${resp.status}`
    let message = resp.statusText || 'request failed'
    let details: Record<string, unknown> | undefined
    try {
      const body = await resp.json()
      code = body.code ?? code
      message = body.message ?? body.error ?? message
      // builder/save validation reports {code, errors: [{resource, message}]}
      details = body.details ?? (body.errors ? { errors: body.errors } : undefined)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(code, message, resp.status, details)
  }
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

interface QueryBody {
  filter?: unknown
  sort?: unknown
  limit?: number
  offset?: number
  links?: string[]
}

export const apiClient = {
  // ---- meta
  meta: () => api<OntologyMeta>('/api/v1/meta/ontology'),
  /** Where materialized object data physically lives: the platform database
   *  (kind + file/DSN, credentials redacted), each object's ontogeny_obj_<type>
   *  table, backing store / source table / sync strategy, live row counts. */
  metaStorage: () =>
    api<{
      target: { kind: string; target: string }
      object_table_prefix: string
      objects: Record<string, {
        table: string
        store: string | null
        mode: string | null
        source_table: string | null
        store_type: string | null
        sync?: string
        sync_schedule?: string
        sync_watermark?: string
        rows?: number | null
      }>
      stores?: Record<string, { type: string; target: string }>
      graph?: {
        declared: boolean
        wired: boolean
        engine: string | null
        graph: string | null
        endpoint_configured: boolean
        endpoint?: string | null
        provider?: string
        blocked_by?: string | null
      }
    }>('/api/v1/meta/storage'),

  // ---- objects
  queryObjects: (type: string, body: QueryBody) =>
    api<QueryResult>(`/api/v1/objects/${encodeURIComponent(type)}/query`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getObject: (type: string, id: string) =>
    api<Record<string, unknown>>(`/api/v1/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}`),
  getLinks: (type: string, id: string, link: string) =>
    api<Record<string, unknown>[]>(
      `/api/v1/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}/links/${encodeURIComponent(link)}`,
    ),
  getHistory: (type: string, id: string) =>
    api<{ versions: Record<string, unknown>[] }>(
      `/api/v1/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}/history`,
    ),
  aggregate: (type: string, fn: string, field?: string | null) =>
    api<{ value: number }>(`/api/v1/objects/${encodeURIComponent(type)}/aggregate`, {
      method: 'POST',
      body: JSON.stringify({ fn, field: field ?? null }),
    }),

  // ---- actions
  validateAction: (name: string, body: { parameters: Record<string, unknown>; target_id?: string | null }) =>
    api<{
      parameters: Record<string, unknown>
      rules: Array<{ expr: string; ok: boolean; message: string | null }>
      policy: { allow: boolean; reason: string }
    }>(`/api/v1/actions/${encodeURIComponent(name)}/validate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  executeAction: (
    name: string,
    body: {
      parameters: Record<string, unknown>
      target_id?: string | null
      expected_revision?: number | null
      idempotency_key?: string | null
    },
  ) =>
    api<{ revision_id: number; outcome: string; object_id: string; after: Record<string, unknown> | null }>(
      `/api/v1/actions/${encodeURIComponent(name)}/execute`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  // ---- functions
  invokeFunction: (name: string, parameters: Record<string, unknown>) =>
    api<{ value: unknown }>(`/api/v1/functions/${encodeURIComponent(name)}/invoke`, {
      method: 'POST',
      body: JSON.stringify({ parameters }),
    }),
  /** The file the sandbox actually executes for this function. */
  functionSource: (name: string) =>
    api<{
      name: string
      runtime: string
      entry: string
      path: string | null
      exists: boolean
      source: string | null
      capabilities: Array<Record<string, unknown>>
      revisions?: Array<{ id: number; principal: string; at: string; version: string | null; bytes: number }>
    }>(`/api/v1/functions/${encodeURIComponent(name)}/source`),
  /** Write a function's code from the console (administrator only). Saving
   *  never executes the body — that is what testFunctionSource is for. */
  saveFunctionSource: (name: string, source: string) =>
    api<{
      ok: boolean
      changed?: boolean
      path?: string
      version?: string
      bytes?: number
    }>(`/api/v1/functions/${encodeURIComponent(name)}/source`, {
      method: 'PUT',
      body: JSON.stringify({ source }),
    }),
  /** Run the editor's code once (administrator only): no file write, no
   *  publish, no revision record. Errors come back in-band, not as HTTP. */
  testFunctionSource: (name: string, source: string) =>
    api<{
      ok: boolean
      value?: unknown
      code?: string
      message?: string
      /** The values the run invented, and where each came from. */
      params?: Record<string, unknown>
      param_sources?: Record<string, string>
    }>(`/api/v1/functions/${encodeURIComponent(name)}/test`, {
      method: 'POST',
      body: JSON.stringify({ source }),
    }),

  // ---- graph
  traverse: (body: { start_type: string; start_ids: string[]; path: Array<{ link: string; direction: string }> }) =>
    api<TraverseResult>('/api/v1/graph/traverse', { method: 'POST', body: JSON.stringify(body) }),
  explore: (body: { start_type?: string; start_id?: string; n?: number; max_depth?: number; seed?: number | null }) =>
    api<ExploreResult>('/api/v1/graph/explore', { method: 'POST', body: JSON.stringify(body) }),

  // ---- agent plugins (external agents, same governance)
  agentPlugins: () => api<{ plugins: AgentPluginInfo[] }>('/api/v1/agent/plugins'),
  agentSessions: (plugin?: string) =>
    api<{ sessions: AgentSession[] }>(
      `/api/v1/agent/sessions${plugin ? `?plugin=${encodeURIComponent(plugin)}` : ''}`,
    ),
  agentSession: (id: number) => api<AgentSession>(`/api/v1/agent/sessions/${id}`),
  agentOpenSession: (plugin: string, task: string,
                     config?: { budget?: { steps?: number; wall_ms?: number; writes_per_session?: number }; expires_at?: string | null }) =>
    api<AgentSession>('/api/v1/agent/sessions', {
      method: 'POST',
      body: JSON.stringify({ plugin, task, ...(config ?? {}) }),
    }),
  agentRun: (sessionId: number, task?: string) =>
    api<{ id: number; status: string }>(`/api/v1/agent/sessions/${sessionId}/run`, {
      method: 'POST',
      body: JSON.stringify(task ? { task } : {}),
    }),
  agentFinish: (sessionId: number, result: Record<string, unknown> | null) =>
    api<{ id: number; status: string }>(`/api/v1/agent/sessions/${sessionId}/finish`, {
      method: 'POST',
      body: JSON.stringify({ result }),
    }),
  agentDeleteSession: (sessionId: number) =>
    api<{ deleted: number }>(`/api/v1/agent/sessions/${sessionId}`, { method: 'DELETE' }),
  agentApprovals: (status = 'pending') =>
    api<{ approvals: AgentApproval[] }>(`/api/v1/agent/approvals?status=${encodeURIComponent(status)}`),
  agentDecide: (approvalId: number, decision: 'approved' | 'rejected') =>
    api<{ id: number; status: string; revision_id?: number }>(
      `/api/v1/agent/approvals/${approvalId}/decision`,
      { method: 'POST', body: JSON.stringify({ decision }) },
    ),
  agentDeleteApproval: (approvalId: number) =>
    api<{ deleted: number }>(`/api/v1/agent/approvals/${approvalId}`, { method: 'DELETE' }),

  // ---- data preview (every object type + the graph projection)
  dataPreview: (limit = 3) => api<DataPreview>(`/api/v1/data/preview?limit=${limit}`),
  projectionSummary: () => api<ProjectionSummary>('/api/v1/graph/projection'),
  projectionVertices: (label: string, limit = 20) =>
    api<ProjectionVertices>(
      `/api/v1/graph/projection/vertices?label=${encodeURIComponent(label)}&limit=${limit}`,
    ),
  projectionEdges: (label: string, limit = 20) =>
    api<ProjectionEdges>(
      `/api/v1/graph/projection/edges?label=${encodeURIComponent(label)}&limit=${limit}`,
    ),

  // ---- audit
  revisions: (params: { object_type?: string; object_id?: string; action?: string }) => {
    const q = new URLSearchParams()
    if (params.object_type) q.set('object_type', params.object_type)
    if (params.object_id) q.set('object_id', params.object_id)
    if (params.action) q.set('action', params.action)
    return api<{ revisions: RevisionRow[] }>(`/api/v1/audit/revisions?${q.toString()}`)
  },

  // ---- evolve
  signals: (init?: RequestInit) => api<{ signals: SignalRow[] }>('/api/v1/evolve/signals', init),
  aggregateSignals: () => api<{ created: SignalRow[] }>('/api/v1/evolve/aggregate', { method: 'POST' }),
  /** One decision per gap the diagnoser produced, so the console can show the
   *  round's thinking (analysis text, declines, skips) — not just the output. */
  diagnose: (init?: RequestInit) =>
    api<{
      proposals: Array<ProposalSummary & { diff: Mutation2[]; rationale: string; analysis?: string | null }>
      /** Provenance of the round: the model's decisions vs declines vs
       *  rule-rejections vs heuristic fallbacks. */
      decided_by?: { llm_decided?: number; llm_declined?: number; llm_rejected?: number; fallback?: number }
      decisions?: Array<{
        signal_id: number | null
        kind: string
        outcome: 'llm' | 'heuristic' | 'human' | 'declined' | 'informational' | 'skipped'
        analysis: string | null
        rationale: string | null
      }>
    }>('/api/v1/evolve/diagnose', { method: 'POST', ...init }),
  proposals: () => api<{ proposals: ProposalSummary[] }>('/api/v1/evolve/proposals'),
  /** Raw AgentPlugin DSL resource for the editor (lossless round-trip). */
  agentPluginResource: (name: string) =>
    api<{ resource: Record<string, unknown> }>(`/api/v1/agent/plugins/${encodeURIComponent(name)}/resource`),
  proposal: (id: number) => api<ProposalDetail>(`/api/v1/evolve/proposals/${id}`),
  deleteSignal: (id: number) => api<{ deleted: number }>(`/api/v1/evolve/signals/${id}`, { method: 'DELETE' }),
  deleteProposal: (id: number) => api<{ deleted: number }>(`/api/v1/evolve/proposals/${id}`, { method: 'DELETE' }),
  rejectProposal: (id: number, reason: string) =>
    api<{ id: number; status: string }>(`/api/v1/evolve/proposals/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  evalProposal: (id: number) => api<{ passed: boolean; candidate_evaluated?: boolean }>(`/api/v1/evolve/proposals/${id}/eval`, { method: 'POST' }),
  promoteProposal: (id: number) =>
    api<{ status: string; tier?: string; branch?: string; budget_used?: number; budget_cap?: number; content_hash?: string; reason?: string }>(
      `/api/v1/evolve/proposals/${id}/promote`,
      { method: 'POST' },
    ),

  // ---- admin
  sync: (type: string) => api<Record<string, number>>(`/api/v1/admin/sync/${encodeURIComponent(type)}`, { method: 'POST' }),

  // ---- domains (switchable ontologies; exactly one is active server-side)
  domains: () => api<{ domains: DomainInfo[]; active: string | null }>('/api/v1/admin/domains'),
  createDomain: (body: { name: string; display?: string; description?: string; activate?: boolean }) =>
    api<DomainInfo & { content_hash?: string }>('/api/v1/admin/domains', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  /** Import a domain-package zip (administrator only): raw zip as the body,
   *  no multipart. The server validates before installing; on success the
   *  domain can be activated immediately. */
  importDomain: (file: File, activate = true) =>
    api<DomainInfo & { content_hash?: string }>(
      `/api/v1/admin/domains/import?activate=${activate}`,
      { method: 'POST', body: file, headers: { 'content-type': 'application/zip' } },
    ),
  activateDomain: (name: string) =>
    api<{ activated: boolean; name: string; content_hash: string }>('/api/v1/admin/domains/activate', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  /** Recompile + republish the package (`path` defaults to the server's root).
   *  Goes through `api()` like everything else, so the principal header, the
   *  `resp.ok` check and `ApiError` classification all apply. */
  publish: (path?: string) =>
    api<{ content_hash: string }>('/api/v1/admin/publish', {
      method: 'POST',
      body: JSON.stringify(path ? { path } : {}),
    }),
  dispatchOutbox: () => api<Record<string, number>>('/api/v1/admin/outbox/dispatch', { method: 'POST' }),
  rebuildProjection: () => api<Record<string, number>>('/api/v1/admin/projection/rebuild', { method: 'POST' }),
  /** Derive + write + publish this domain's projection, then LOAD its graph if
   *  the graph already exists on the server, or BUILD it if it does not. */
  scaffoldProjection: (body: { name?: string; graphspace?: string } = {}) =>
    api<{ action: 'loaded' | 'built'; name: string; graph: string; path: string; vertices: number; edges: number }>(
      '/api/v1/admin/projection/scaffold',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  llmStatus: () =>
    api<{ configured: boolean; base_url?: string; model?: string; ok?: boolean; models?: string[]; error?: string }>(
      '/api/v1/admin/llm/status',
    ),
  extensions: () => api<ExtensionsInventory>('/api/v1/admin/extensions'),
  runtimeConfig: () => api<RuntimeConfig>('/api/v1/admin/runtime-config'),
  saveRuntimeConfig: (body: {
    llm_provider?: string
    llm_base_url?: string | null
    llm_model?: string | null
    llm_api_key?: string | null
    storage_provider?: string
    storage_url?: string | null
    storage_user?: string | null
    storage_password?: string | null
  }) => api<RuntimeConfig>('/api/v1/admin/runtime-config', { method: 'PUT', body: JSON.stringify(body) }),

  // ---- assistant (Ollama)
  assistantChat: (messages: Array<{ role: string; content: string }>, propose: boolean) =>
    api<AssistantReply>('/api/v1/assistant/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, propose }),
    }),

  // ---- scenario builder data mounting ------------------------------------
  /** Attach a data source to an object type: store resource + backing binding
   *  + publish + sync, with the quarantine report back. See the mount dialog. */
  mountData: (body: {
    object: string
    store?: string
    source: { kind: 'csv'; filename?: string; content: string }
          | { kind: 'sqlite' | 'postgres' | 'mysql'; dsn: string; table: string }
    mapping?: Record<string, string>
  }) =>
    api<{
      published: boolean
      store: string
      object: string
      mapping: Record<string, string>
      sync: { inserted: number; updated: number; noop: number; quarantined: number }
      quarantine: Array<{ pk: string | null; code: string; reason: string }>
    }>('/api/v1/admin/builder/mount', { method: 'POST', body: JSON.stringify(body) }),

  // ---- scenario builder (touched resources -> YAML on disk -> publish)
  builderSave: (resources: Array<Record<string, unknown>>, deletes: string[],
                layout?: Record<string, { x: number; y: number }>) =>
    api<{ published: boolean; content_hash: string; written: string[]; removed: string[]; issues: Array<{ code: string; severity: string; message: string }> }>(
      '/api/v1/admin/builder/save',
      { method: 'POST', body: JSON.stringify({ resources, deletes, layout }) },
    ),
  /** Lossless seed for the Knowledge / Action editors: the compiled resources
   *  as `{apiVersion, kind, metadata, spec}` (see api/resources.ts), plus the
   *  package's saved canvas layout. */
  builderResources: () =>
    api<{ resources: OntologyResource[]; content_hash: string | null; layout: Record<string, { x: number; y: number }>; stores?: string[] }>('/api/v1/admin/builder/resources'),

  // ---- accounts & sessions ------------------------------------------------
  login: (username: string, password: string) =>
    api<{ token: string; principal: Principal }>('/api/v1/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    }),
  logout: () => api<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' }),
  /** 401 when nobody is signed in — the app's gate reads that, not a flag. */
  me: () => api<{ principal: Principal; dev_auth?: boolean }>('/api/v1/auth/me'),
  sessions: () => api<{ sessions: Array<{ token: string; user: string; created_at: string | null; expires_at: string | null; last_seen: string | null }> }>('/api/v1/auth/sessions'),

  // ---- account & role administration -------------------------------------
  users: () => api<{ users: AccountUser[] }>('/api/v1/admin/users'),
  createUser: (body: {
    username: string; password: string; display?: string; roles?: string[];
    site?: string | null; markings?: string[]; is_admin?: boolean
  }) => api<AccountUser>('/api/v1/admin/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (username: string, patch: Partial<{
    display: string; password: string; roles: string[]; site: string | null;
    markings: string[]; status: string; is_admin: boolean
  }>) => api<AccountUser>(`/api/v1/admin/users/${encodeURIComponent(username)}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  }),
  deleteUser: (username: string) =>
    api<{ deleted: string }>(`/api/v1/admin/users/${encodeURIComponent(username)}`, { method: 'DELETE' }),

  /** The role x action matrix, read out of the compiled Cedar. */
  roles: () => api<RolesPayload>('/api/v1/admin/roles'),
  saveRole: (name: string, actions: string[], site?: string | null) =>
    api<{ saved: string; actions: string[] }>(`/api/v1/admin/roles/${encodeURIComponent(name)}`, {
      method: 'PUT', body: JSON.stringify({ name, actions, site: site ?? null }),
    }),
  deleteRole: (name: string, reassignTo?: string | null) =>
    api<{ deleted: string; reassigned: string[] }>(`/api/v1/admin/roles/${encodeURIComponent(name)}`, {
      method: 'DELETE', body: JSON.stringify({ name, reassign_to: reassignTo ?? null }),
    }),
}

export interface RuntimeConfig {
  llm: {
    provider: 'ollama' | 'external' | 'disabled' | string
    base_url: string | null
    model: string | null
    api_key_set: boolean
  }
  storage: {
    provider: 'hugegraph' | 'sqlite' | string
    url: string | null
    /** HugeGraph credentials — needed by a server in auth mode. */
    user: string | null
    /** The password itself never leaves the server; this only says one is set. */
    password_set: boolean
  }
}

/** An account as the administration API returns it (never the password hash). */
export interface AccountUser {
  id: number
  username: string
  display: string
  roles: string[]
  site: string | null
  markings: string[]
  status: 'active' | 'disabled'
  is_admin: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface RoleGrant {
  policy: string
  roles: string[]
  actions: string[]
  conditional: boolean
  managed: boolean
}

export interface RoleInfo {
  name: string
  sources: string[]
  managedPolicy: string
  hasManagedPolicy: boolean
  members: string[]
  /** Role is carried by the signed-in principal. */
  current?: boolean
  /** The role can be safely deleted from the permission matrix. */
  deletable?: boolean
}

/** role -> action -> cell */
export type PermissionMatrix = Record<string, Record<string, {
  granted: boolean
  source?: string
  managed?: boolean
  conditional?: boolean
  anyPrincipal?: boolean
}>>

export interface RolesPayload {
  roles: RoleInfo[]
  actions: string[]
  matrix: PermissionMatrix
  grants: RoleGrant[]
}

type Mutation2 = Record<string, string>
export type { ActionMeta, FunctionMeta }
