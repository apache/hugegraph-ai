/*
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and
limitations under the License.
*/
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
/**
 * The ontology editing session shared by the Knowledge and Action pages.
 *
 * One draft for both pages, held above the router: Knowledge edits the semantic
 * layer (object types, links, projections) and Action the kinetic layer
 * (actions, functions, policy sets), but they reference each other — a link
 * points at object types, an action targets one, a projection includes them —
 * so two independent copies would let a link select a type the other page just
 * renamed. One store also means ONE save bar for whatever is dirty.
 *
 * The store holds the resources *verbatim* (see api/resources.ts) and only ever
 * sends what the user touched, so untouched YAML on disk is never rewritten —
 * the same data-loss-safe partial save the Scenario Builder uses. Edits survive
 * a refresh through localStorage, like the builder's draft.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, ApiError } from '../../api/client'
import { domainsQuery, invalidateMeta } from '../../api/queries'
import { rkey, type ResourceKind } from '../../api/resources'
import type { OntologyResource } from '../../api/types'

const DRAFT_KEY = 'ontogeny.ontology.draft'
/** A draft older than this is stale enough to drop without asking: the published
 *  package has almost certainly moved on. */
const DRAFT_TTL_MS = 14 * 24 * 60 * 60 * 1000

interface PersistedDraft {
  savedAt: number
  resources: OntologyResource[]
  touched: string[]
  removed: string[]
  layout: Layout
  stores?: string[]
  /** Which package this draft belongs to. A deployment serves ONE active
   *  ontology, so a draft carrying a different domain's name is another model's
   *  work: restoring it onto this canvas showed the previous domain's types
   *  (and saving would have written them into the new package). */
  domain?: string
}

/** Graph node id -> position, as arranged by hand on the ontology canvas.
 *  Committed positions live WITH the package on the server (its `layout.yaml`
 *  sidecar, saved by `save()` alongside the model); only the unsaved editing
 *  draft touches localStorage. */
export type Layout = Record<string, { x: number; y: number }>

/** The stored draft, or null when there is nothing valid to restore.
 *
 * Deliberately *not* domain-filtered here: at mount the active domain is still
 * unknown (it arrives with the domains query), so the decision of whether this
 * draft may be restored is made once that answer lands — see `adopt`. */
function forgetDraft(key: string) {
  try { localStorage.removeItem(key) } catch { /* storage may be disabled */ }
}

function readDraft(key: string): PersistedDraft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as PersistedDraft
    if (!Array.isArray(parsed?.resources) || typeof parsed.savedAt !== 'number') return null
    if (!parsed.resources.every((r) => r && typeof r.kind === 'string' && typeof r.metadata?.name === 'string' && r.spec && typeof r.spec === 'object') ||
        !Array.isArray(parsed.touched) || !parsed.touched.every((k) => typeof k === 'string') ||
        !Array.isArray(parsed.removed) || !parsed.removed.every((k) => typeof k === 'string')) return null
    parsed.layout = parsed.layout ?? {}
    if (typeof parsed.layout !== 'object' || Array.isArray(parsed.layout) ||
        !Object.values(parsed.layout).every((point) => point && Number.isFinite(point.x) && Number.isFinite(point.y))) return null
    if (Date.now() - parsed.savedAt > DRAFT_TTL_MS) {
      forgetDraft(key)
      return null
    }
    return parsed
  } catch {
    forgetDraft(key)
    return null
  }
}

/** Forget every trace of the ontology editing session.
 *
 * Called on a domain switch: the resources and the persisted draft both
 * describe the package that is no longer active. Also clears the legacy
 * localStorage layout keys, which moved server-side (the package's
 * `layout.yaml`); old browsers' copies are simply discarded. */
export function clearOntologyDraftStorage() {
  try {
    localStorage.removeItem(DRAFT_KEY)
    localStorage.removeItem('ontogeny.ontology.layout')
  } catch {
    /* storage unavailable: nothing was persisted anyway */
  }
}

export interface SaveResult {
  content_hash: string
  written: string[]
  removed: string[]
  issues: Array<{ code: string; severity: string; message: string }>
}

export interface OntologyDraft {
  resources: OntologyResource[]
  /** The active package these resources were loaded from (null before the
   *  domain answer lands). */
  domain: string | null
  /** Resources of one kind, in the order the server returned them. */
  ofKind: (kind: ResourceKind) => OntologyResource[]
  get: (kind: ResourceKind, name: string) => OntologyResource | undefined
  /** The object-type names, for every select that points at one. */
  objectNames: string[]
  /** Store names declared by the active package (mount-mode editor options). */
  stores: string[]
  loading: boolean
  loadError: string | null
  saving: boolean
  saveError: string | null
  saveResult: SaveResult | null
  dirty: boolean
  /** Hand-arranged node positions, pending until saved (see `moveNode`). */
  layout: Layout
  /** Move one graph node. Like every other edit this only takes effect on save. */
  moveNode: (id: string, x: number, y: number) => void
  /** Forget the hand-arranged layout and fall back to the automatic one. */
  resetLayout: () => void
  touched: Set<string>
  /** Keys queued for deletion on the next save ("Kind/name"). */
  removed: Set<string>
  restoredAt: number | null
  /** Arm the store. The first active-domain answer does the loading; both
   *  editing pages call this, and calling it twice is a no-op. */
  ensureLoaded: () => void
  /** Drop the local copy and re-read the active package from the server. */
  reload: () => Promise<void>
  /** Forget every unsaved edit on this canvas and start over from the published
   *  package — the "clear the canvas" of the old Scenario Builder. */
  reloadFromServer: () => void
  /** Replace one resource, marking it dirty. */
  update: (kind: ResourceKind, name: string, next: (res: OntologyResource) => OntologyResource) => void
  /** Add a brand-new resource (already named and unique). */
  create: (res: OntologyResource) => void
  /** Rename, cascading the references an ObjectType rename implies. */
  rename: (kind: ResourceKind, from: string, to: string) => void
  remove: (kind: ResourceKind, name: string) => void
  save: () => Promise<void>
  discard: () => void
  dismissSaveResult: () => void
}

const Ctx = createContext<OntologyDraft | null>(null)

/** Every place a spec references an object type, rewritten on rename.
 *  Kept as one function: missing a field here is how a rename silently orphans
 *  a link or a projection include. Returns the SAME object when nothing
 *  matched, so the caller can tell "changed" from "untouched" by identity. */
function renameObjectRefs(res: OntologyResource, from: string, to: string): OntologyResource {
  const spec = { ...res.spec }
  let hit = false
  if (res.kind === 'LinkType') {
    if (spec.source === from) { spec.source = to; hit = true }
    if (spec.target === from) { spec.target = to; hit = true }
  }
  if (res.kind === 'Action' && spec.target === from) { spec.target = to; hit = true }
  if (res.kind === 'Projection') {
    const include = { ...(spec.include as Record<string, unknown> | undefined) }
    const objects = { ...(include.objects as Record<string, unknown> | undefined) }
    if (objects[from]) {
      objects[to] = objects[from]
      delete objects[from]
      include.objects = objects
      spec.include = include
      hit = true
    }
    if (Array.isArray(spec.indexes)) {
      const indexes = (spec.indexes as Array<Record<string, unknown>>).map((ix) => {
        if (ix.object !== from) return ix
        hit = true
        return { ...ix, object: to }
      })
      spec.indexes = indexes
    }
  }
  return hit ? { ...res, spec } : res
}

export function OntologyDraftProvider({ children, storageScope }: { children: ReactNode; storageScope?: string }) {
  const storageKey = storageScope === undefined ? DRAFT_KEY : `${DRAFT_KEY}:${encodeURIComponent(storageScope)}`
  const loadedScope = useRef(storageKey)
  const editVersion = useRef(0)
  const loadRequest = useRef(0)
  const saveInFlight = useRef(false)
  const qc = useQueryClient()
  // Which ontology this editing session belongs to. The deployment serves ONE
  // active domain, and "which one" is a server answer -- so the page's load
  // waits for it instead of guessing from whatever the canvas happens to hold.
  // `['domains']` is shared with the DomainSwitcher, so this costs no extra
  // request while that bar is on screen and one request per session otherwise.
  const domains = useQuery(domainsQuery())
  const activeDomain = domains.data?.active ?? null
  /** The domain whose resources are currently loaded. */
  const [domain, setDomain] = useState<string | null>(null)

  const [resources, setResources] = useState<OntologyResource[]>([])
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [removed, setRemoved] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveResult, setSaveResult] = useState<SaveResult | null>(null)
  const [restoredAt, setRestoredAt] = useState<number | null>(null)
  const [layout, setLayout] = useState<Layout>({})
  /** Store names declared by the active package (the mount-mode editor's
   *  options — a typo here is a BACKING-STORE validation error). */
  const [stores, setStores] = useState<string[]>([])
  const [savedLayout, setSavedLayout] = useState<Layout>({})
  /** Mounted: the first domain answer may load the canvas. */
  const [ready, setReady] = useState(false)
  /** The domain the current state was loaded for; guards against a late answer
   *  from a superseded request overwriting the newer domain's resources. */
  const loadedFor = useRef<string | null>(null)

  const layoutDirty = useMemo(
    () => JSON.stringify(layout) !== JSON.stringify(savedLayout),
    [layout, savedLayout],
  )
  const dirty = touched.size > 0 || removed.size > 0 || layoutDirty

  // persist on every change; a clean session leaves no draft behind
  useEffect(() => {
    // Do not erase a persisted draft before the domain answer lets us adopt it.
    if (domain === null || loadedFor.current !== domain || loadedScope.current !== storageKey) return
    if (!dirty) {
      forgetDraft(storageKey)
      return
    }
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        savedAt: Date.now(), resources, touched: [...touched], removed: [...removed], layout, domain, stores,
      } satisfies PersistedDraft))
    } catch {
      // quota exceeded: editing keeps working, it just cannot be restored
    }
  }, [resources, touched, removed, layout, dirty, domain, storageKey, stores])

  const load = useCallback(async (forDomain: string | null, keepSaveResult = false) => {
    if (forDomain === null) return
    const request = ++loadRequest.current
    const version = editVersion.current
    setLoading(true)
    try {
      const res = await apiClient.builderResources()
      if (loadedFor.current !== forDomain || request !== loadRequest.current || version !== editVersion.current) return
      setResources(res.resources)
      setStores(res.stores ?? [])
      setTouched(new Set())
      setRemoved(new Set())
      // the published package is the source of truth for committed positions
      const serverLayout = res.layout ?? {}
      setLayout(serverLayout)
      setSavedLayout(serverLayout)
      setLoadError(null)
      if (!keepSaveResult) setSaveResult(null)
      forgetDraft(storageKey)
      setRestoredAt(null)
    } catch (e) {
      if (loadedFor.current !== forDomain || request !== loadRequest.current) return
      setLoadError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
    } finally {
      if (loadedFor.current === forDomain && request === loadRequest.current) setLoading(false)
    }
  }, [storageKey])

  /** Take ownership of one active domain: restore that domain's own draft when
   *  there is one, otherwise load what is published under it.
   *
   * This is the fix for the empty / stale canvas: the page used to seed itself
   * once, at mount, and never again -- so after a switch it either kept drawing
   * the previous package or (with nothing loaded) drew nothing at all. */
  useEffect(() => {
    if (!ready || domains.data === undefined) return
    if (domain === activeDomain && loadedScope.current === storageKey) return
    ++editVersion.current
    ++loadRequest.current
    loadedScope.current = storageKey
    const draft = readDraft(storageKey)
    const restorable = draft && (draft.domain ?? activeDomain) === activeDomain ? draft : null
    loadedFor.current = activeDomain
    setDomain(activeDomain)
    setStores(restorable?.stores ?? [])
    setSaveError(null)
    // a restored draft carries its own WIP positions; otherwise start clean and
    // let the server answer fill in the package's committed layout (see `load`)
    setLayout(restorable?.layout ?? {})
    setSavedLayout({})
    if (restorable) {
      // a restored draft is the user's own work: never overwrite it with the server
      setResources(restorable.resources)
      setTouched(new Set(restorable.touched))
      setRemoved(new Set(restorable.removed))
      setRestoredAt(restorable.savedAt)
      setLoadError(null)
      setSaveResult(null)
      setLoading(false)
    } else {
      if (draft) forgetDraft(storageKey)
      setResources([])
      setTouched(new Set())
      setRemoved(new Set())
      setRestoredAt(null)
      setSaveResult(null)
      void load(activeDomain)
    }
  }, [ready, domains.data, activeDomain, domain, load, storageKey])

  const ensureLoaded = useCallback(() => setReady(true), [])

  const update = useCallback<OntologyDraft['update']>((kind, name, next) => {
    ++editVersion.current
    setResources((prev) => prev.map((r) => (r.kind === kind && r.metadata.name === name ? next(r) : r)))
    setTouched((prev) => new Set(prev).add(rkey(kind, name)))
    setSaveResult(null)
  }, [])

  const create = useCallback<OntologyDraft['create']>((res) => {
    ++editVersion.current
    setResources((prev) => [...prev, res])
    setTouched((prev) => new Set(prev).add(rkey(res.kind, res.metadata.name)))
    setSaveResult(null)
  }, [])

  const rename = useCallback<OntologyDraft['rename']>((kind, from, to) => {
    if (!to || to === from) return
    ++editVersion.current
    // resources whose spec pointed at the old name become dirty as well
    const affected = new Set<string>()
    setResources((prev) => prev.map((r) => {
      if (r.kind === kind && r.metadata.name === from) {
        return { ...r, metadata: { ...r.metadata, name: to } }
      }
      if (kind !== 'ObjectType') return r
      const next = renameObjectRefs(r, from, to)
      if (next !== r) affected.add(rkey(r.kind, r.metadata.name))
      return next
    }))
    setTouched((prev) => {
      const next = new Set(prev)
      next.delete(rkey(kind, from))
      next.add(rkey(kind, to))
      for (const k of affected) next.add(k)
      return next
    })
    setRemoved((prev) => new Set(prev).add(rkey(kind, from)))
    setSaveResult(null)
  }, [])

  const remove = useCallback<OntologyDraft['remove']>((kind, name) => {
    ++editVersion.current
    setResources((prev) => prev.filter((r) => !(r.kind === kind && r.metadata.name === name)))
    setTouched((prev) => {
      const next = new Set(prev)
      next.delete(rkey(kind, name))
      return next
    })
    setRemoved((prev) => new Set(prev).add(rkey(kind, name)))
    setSaveResult(null)
  }, [])

  const save = useCallback(async () => {
    if (saveInFlight.current || domain === null) return
    saveInFlight.current = true
    const version = editVersion.current
    setSaving(true)
    setSaveError(null)
    try {
      const changed = resources.filter((r) => touched.has(rkey(r.kind, r.metadata.name)))
      const res = await apiClient.builderSave(
        changed as unknown as Array<Record<string, unknown>>,
        [...removed],
        layout,
      )
      if (loadedFor.current !== domain || loadedScope.current !== storageKey) return
      setSaveResult({
        content_hash: res.content_hash,
        written: res.written,
        removed: res.removed,
        issues: res.issues ?? [],
      })
      const unchanged = editVersion.current === version
      if (unchanged) {
        setTouched(new Set())
        setRemoved(new Set())
      }
      // the layout is committed alongside the model (the server stores it as
      // the package's layout.yaml): a drag is an edit like any other, so it
      // takes effect when the user says so and not before
      setSavedLayout(layout)
      if (unchanged) forgetDraft(storageKey)
      setRestoredAt(null)
      // a save IS a publish: the compiled snapshot moved, so every page reading
      // it (object tables, the shell's content hash, this canvas) must re-read
      void invalidateMeta(qc)
      // re-seed from what is now published, so ids/versions match the server
      if (unchanged) void load(domain, true)
    } catch (e) {
      if (loadedFor.current !== domain || loadedScope.current !== storageKey) return
      if (e instanceof ApiError) {
        const errs = (e.details?.errors ?? []) as Array<{ resource: string; message: string }>
        setSaveError(errs.length ? errs.map((x) => `${x.resource}: ${x.message}`).join('\n') : `${e.code}: ${e.message}`)
      } else {
        setSaveError(String(e))
      }
    } finally {
      saveInFlight.current = false
      setSaving(false)
    }
  }, [resources, touched, removed, layout, domain, load, qc, storageKey])

  const discard = useCallback(() => {
    ++editVersion.current
    forgetDraft(storageKey)
    setRestoredAt(null)
    setTouched(new Set())
    setRemoved(new Set())
    setLayout(savedLayout) // unsaved drags go back to where they were
    void load(domain)
  }, [load, savedLayout, domain, storageKey])

  const moveNode = useCallback<OntologyDraft['moveNode']>((id, x, y) => {
    ++editVersion.current
    setLayout((prev) => ({ ...prev, [id]: { x, y } }))
  }, [])

  const resetLayout = useCallback(() => { ++editVersion.current; setLayout({}) }, [])

  /** Empty the canvas and discard the draft, then re-read the package. Used by
   *  "clear canvas": the model on disk is untouched until a save. */
  const reloadFromServer = useCallback(() => {
    ++editVersion.current
    forgetDraft(storageKey)
    setSavedLayout({})
    setLayout({})
    setTouched(new Set())
    setRemoved(new Set())
    setRestoredAt(null)
    setSaveResult(null)
    setResources([])
    void load(domain)
  }, [load, domain, storageKey])

  const value = useMemo<OntologyDraft>(() => ({
    resources,
    domain,
    ofKind: (kind) => resources.filter((r) => r.kind === kind),
    get: (kind, name) => resources.find((r) => r.kind === kind && r.metadata.name === name),
    objectNames: resources.filter((r) => r.kind === 'ObjectType').map((r) => r.metadata.name),
    loading, loadError, saving, saveError, saveResult,
    dirty, touched, removed, restoredAt, layout, moveNode, resetLayout, stores,
    ensureLoaded, reload: () => load(domain), reloadFromServer,
    update, create, rename, remove, save, discard,
    dismissSaveResult: () => setSaveResult(null),
  }), [
    resources, domain, loading, loadError, saving, saveError, saveResult, dirty, touched, removed,
    restoredAt, layout, moveNode, resetLayout, stores,
    ensureLoaded, load, reloadFromServer, update, create, rename, remove, save, discard,
  ])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useOntologyDraft(): OntologyDraft {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useOntologyDraft must be used inside OntologyDraftProvider')
  return ctx
}
