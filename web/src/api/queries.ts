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
/** Every React Query key in the app, in one place.
 *
 * The point is not tidiness: keys that name the *same server resource* must be
 * identical, or the cache silently splits and one screen shows stale data while
 * another shows fresh. That had happened four times over:
 *
 *  - `/graph/projection`  → `['projection']` (ProjectionView) and
 *                           `['projection-summary']` (Admin, Extensions): two
 *                           caches, so "rebuild projection" refreshed one of them
 *  - `/agent/approvals?status=pending` → `['agent-approvals','pending']` and
 *                           `['agent-approvals']`: the approvals badge and the
 *                           approvals table disagreed
 *  - `/agent/sessions/{id}` → `['agent-session', id]` and `['ext-scenario', id]`,
 *                           polled at 4s and 1.2s respectively: one session, two
 *                           pollers, two answers
 *  - `/audit/revisions`   → `['revisions','latest']` and `['revisions', applied]`
 *                           (the same empty filter written two ways)
 *
 * `meta()` additionally pins `staleTime: Infinity`. The compiled snapshot is
 * immutable ("publish, then never change"), so the 5s default only caused
 * refetches; worse, the shell's two observers passed 60s while the 13 page
 * observers took the 5s global, so whichever mounted last won and the sidebar's
 * `content_hash` could disagree with a just-published one.
 */
import { queryOptions, useQuery, type QueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'

/** Compile-and-publish is the only way the snapshot changes, so it never goes
 *  stale on its own — only an explicit invalidation moves it. */
export const metaQuery = () =>
  queryOptions({ queryKey: ['meta'] as const, queryFn: apiClient.meta, staleTime: Infinity })

/** Where materialized object data physically lives (db, tables, sources, rows).
 *  Refetches on the same invalidations as meta: a republish can re-back types,
 *  and rows move on every sync. */
export const storageQuery = () =>
  queryOptions({ queryKey: ['storage'] as const, queryFn: apiClient.metaStorage })

/** Call after anything that republishes the package (publish, builder save). */
export function invalidateMeta(qc: QueryClient) {
  // a republish moves every function's file story too — a function published
  // for the first time now HAS a source answer (until then the endpoint 404s
  // and the query would otherwise keep that error cached forever), and its
  // revision list may have grown — so the code editors must re-ask
  void qc.invalidateQueries({ queryKey: ['function-source'] })
  // a republish can re-back object types, so the storage summary must re-ask
  void qc.invalidateQueries({ queryKey: ['storage'] })
  return qc.invalidateQueries({ queryKey: ['meta'] })
}

/** The switchable domains and which one is active.
 *
 * A domain switch republishes server-side, so this answer moves then — and the
 * ontology editing session hangs off it: its resources, its layout and its
 * persisted draft all belong to ONE package. Sharing the key means the switcher
 * and that session can never disagree about which package is active. */
export const domainsQuery = () =>
  queryOptions({ queryKey: ['domains'] as const, queryFn: apiClient.domains })

/** Call ONLY after a domain switch (or a create-domain-with-activation).
 *
 * Every other mutation must invalidate its own key family — a bare
 * `invalidateQueries()` throws away meta, extensions and the projection on
 * unrelated successes, which the query-keys contract test forbids. A domain
 * switch is the one event that genuinely replaces ALL of it: the snapshot, the
 * object tables, the audit trail, signals and agent sessions. */
export function invalidateOnDomainSwitch(qc: QueryClient) {
  return qc.invalidateQueries({ predicate: () => true })
}

export const keys = {
  meta: ['meta'] as const,

  // ---- objects ----------------------------------------------------------
  // `sortKey` is the serialized server-side sort (or null): it belongs in the
  // key because the queryFn reads it -- a key that omits it serves a cached
  // page in the wrong order (sorting on page 0 used to do exactly that).
  objects: (type: string, filter: unknown, page: number, sortKey: string | null = null) =>
    ['objects', type, filter, page, sortKey] as const,
  object: (type: string, id: string) => ['object', type, id] as const,
  objectLinks: (type: string, id: string, link: string | null) => ['linked', type, id, link] as const,
  objectHistory: (type: string, id: string) => ['history', type, id] as const,

  // ---- data preview / projection ---------------------------------------
  dataPreview: (limit: number) => ['data-preview', limit] as const,
  /** One key for `/graph/projection`, wherever it is read. */
  projection: ['projection'] as const,
  projectionVertices: (label: string) => ['projection-vertices', label] as const,
  projectionEdges: (label: string) => ['projection-edges', label] as const,
  /** Prefixes, for invalidating every sampled label at once after a rebuild. */
  projectionVerticesPrefix: ['projection-vertices'] as const,
  projectionEdgesPrefix: ['projection-edges'] as const,

  // ---- functions --------------------------------------------------------
  /** The source file a function executes — one key, read-only. */
  functionSource: (name: string) => ['function-source', name] as const,

  // ---- audit / evolve ---------------------------------------------------
  revisions: (params: { object_type?: string; object_id?: string; action?: string }) =>
    ['revisions', params.object_type ?? '', params.object_id ?? '', params.action ?? ''] as const,
  signals: ['signals'] as const,
  proposals: ['proposals'] as const,
  proposal: (id: number | string) => ['proposal', String(id)] as const,

  // ---- agent ------------------------------------------------------------
  agentPlugins: ['agent-plugins'] as const,
  agentApprovals: (status = 'pending') => ['agent-approvals', status] as const,
  agentSessions: (plugin?: string) => ['agent-sessions', plugin ?? ''] as const,
  /** One key for `/agent/sessions/{id}`, whichever page polls it. */
  agentSession: (id: number | string | null) => ['agent-session', String(id)] as const,

  // ---- admin ------------------------------------------------------------
  extensions: ['extensions'] as const,
  llmStatus: ['llm-status'] as const,
  runtimeConfig: ['runtime-config'] as const,
}

/** Convenience wrappers so the `staleTime: Infinity` invariant cannot be
 *  forgotten at a call site. */
export function useMeta() {
  return useQuery(metaQuery())
}
