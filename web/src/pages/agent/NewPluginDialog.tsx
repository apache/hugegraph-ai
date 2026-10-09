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
 * NewPluginDialog — declare an agent plugin from the console.
 *
 * The form is a thin editor over the AgentPlugin DSL resource; everything it
 * offers is bounded by what the platform already enforces:
 *
 *  - roles are picked from `meta.roles` (the vocabulary the Cedar policies
 *    actually reference — a role outside it silently grants nothing and the
 *    validator refuses the package);
 *  - tools are picked from the compiled catalog (`search_<object>`,
 *    `call_<function>`, `act_<action>`, plus the two fixed meta tools), with
 *    write tools marked — and `approval.writes: never` + any act_* is a
 *    validator warning, surfaced as such in the UI;
 *  - the principal id follows the `agent:<name>` convention.
 *
 * Layout: the dialog sits dead-center on a transparent backdrop (no dark
 * veil), wide enough for two columns — the form on the left, an inspector on
 * the right that shows whatever role/tool was clicked last (what it reads
 * from the snapshot, which parameters an action takes, whether it is already
 * on the allow-list).
 *
 * Saving goes through the same builder door as every other resource
 * (partial-save: only the new plugin is written).
 */
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useFocusTrap } from '../../lib/focus'
import { useI18n } from '../../i18n'
import { apiClient, ApiError } from '../../api/client'
import { keys, useMeta } from '../../api/queries'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Badge, Button, KeyValue } from '../../components/ui'
import { IconCog, IconX } from '../../components/icons'
import type { ActionMeta, FunctionMeta, ObjectMeta, ParamMeta } from '../../api/types'

/** Same normalization as the backend's tool catalog (_snake). */
export const toSnake = (name: string): string =>
  name.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')

type ApprovalWrites = 'confirm' | 'never' | 'auto'

type Inspection =
  | { kind: 'role'; name: string }
  | { kind: 'tool'; name: string }

type Detail =
  | { type: 'role'; name: string }
  | { type: 'fixed'; name: string }
  | { type: 'object'; name: string; key: string; def: ObjectMeta }
  | { type: 'function'; name: string; key: string; def: FunctionMeta }
  | { type: 'action'; name: string; key: string; def: ActionMeta }
  | { type: 'unknown'; name: string }

export function NewPluginDialog({
  open, onClose, existingNames, onCreated, editing = null,
}: {
  open: boolean
  onClose: () => void
  existingNames: string[]
  onCreated?: (name: string) => void
  /** When set, the dialog edits an EXISTING plugin: fields prefill from its raw
   *  DSL resource and saving rewrites that same resource (partial-save). */
  editing?: { name: string; resource: Record<string, any> } | null
}) {
  const { t } = useI18n()
  const meta = useMeta()
  const qc = useQueryClient()
  const trapRef = useFocusTrap<HTMLDivElement>(open)

  const [name, setName] = useState('')
  const [display, setDisplay] = useState('')
  const [description, setDescription] = useState('')
  const [roles, setRoles] = useState<string[]>([])
  const [site, setSite] = useState('')
  const [writes, setWrites] = useState<ApprovalWrites>('confirm')
  const [steps, setSteps] = useState(40)
  const [writesPerSession, setWritesPerSession] = useState(3)
  const [tools, setTools] = useState<string[]>([])
  const [inspect, setInspect] = useState<Inspection | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [doneName, setDoneName] = useState<string | null>(null)

  // direction 3: editing prefills from the plugin's raw resource; a plain
  // "new" open resets everything back to the create defaults
  useEffect(() => {
    if (open && !editing) {
      setName(''); setDisplay(''); setDescription(''); setRoles([]); setSite('')
      setWrites('confirm'); setSteps(40); setWritesPerSession(3); setTools([]); setDoneName(null)
      return
    }
    if (!open || !editing) return
    const r = editing.resource
    const spec = (r.spec ?? {}) as Record<string, any>
    const principal = (spec.principal ?? {}) as Record<string, any>
    setName(editing.name)
    setDisplay((r.metadata as any)?.display ?? '')
    setDescription((r.metadata as any)?.description ?? '')
    setRoles((principal.Role ?? principal.roles ?? []) as string[])
    setSite(principal.site ?? '')
    setWrites((spec.approval?.writes ?? 'confirm') as ApprovalWrites)
    setSteps(spec.budget?.steps ?? 40)
    setWritesPerSession(spec.budget?.writes_per_session ?? 3)
    setTools((spec.tools?.allow ?? []) as string[])
    setDoneName(null)
  }, [open, editing])

  const nameOk = /^[a-z][a-z0-9-]*$/.test(name)
  // after a successful create the name IS in the list — that is not a conflict
  const nameFree = doneName !== null || !existingNames.includes(name)
  const rolesOk = roles.length > 0

  const groups = useMemo(() => {
    const m = meta.data
    return [
      {
        key: 'meta', label: t('agent.new.group.meta'), writes: false,
        tools: ['describe_ontology', 'traverse_graph'],
      },
      {
        key: 'search', label: t('agent.new.group.search'), writes: false,
        tools: Object.keys(m?.objects ?? {}).map((o) => `search_${toSnake(o)}`),
      },
      {
        key: 'call', label: t('agent.new.group.call'), writes: false,
        tools: Object.keys(m?.functions ?? {}).map((f) => `call_${toSnake(f)}`),
      },
      {
        key: 'act', label: t('agent.new.group.act'), writes: true,
        tools: Object.keys(m?.actions ?? {}).map((a) => `act_${toSnake(a)}`),
      },
    ]
  }, [meta.data, t])

  /** Resolve the inspected chip against the meta snapshot — the right pane's
   *  whole content. Tool names are `search_<snake>` over possibly
   *  underscored source names, so match by normalization, not by prefix split. */
  const detail = useMemo<Detail | null>(() => {
    if (!inspect) return null
    if (inspect.kind === 'role') return { type: 'role', name: inspect.name }
    const n = inspect.name
    const m = meta.data
    if (n === 'describe_ontology' || n === 'traverse_graph') return { type: 'fixed', name: n }
    const obj = Object.entries(m?.objects ?? {}).find(([k]) => `search_${toSnake(k)}` === n)
    if (obj) return { type: 'object', name: n, key: obj[0], def: obj[1] }
    const fn = Object.entries(m?.functions ?? {}).find(([k]) => `call_${toSnake(k)}` === n)
    if (fn) return { type: 'function', name: n, key: fn[0], def: fn[1] }
    const act = Object.entries(m?.actions ?? {}).find(([k]) => `act_${toSnake(k)}` === n)
    if (act) return { type: 'action', name: n, key: act[0], def: act[1] }
    return { type: 'unknown', name: n }
  }, [inspect, meta.data])

  const canSubmit = nameOk && nameFree && rolesOk && !busy

  const toggleTool = (tool: string) => {
    setTools((prev) => (prev.includes(tool) ? prev.filter((x) => x !== tool) : [...prev, tool]))
    setInspect({ kind: 'tool', name: tool })
  }
  const toggleRole = (role: string) => {
    setRoles((prev) => (prev.includes(role) ? prev.filter((x) => x !== role) : [...prev, role]))
    setInspect({ kind: 'role', name: role })
  }

  const submit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    try {
      const orig = (editing?.resource ?? {}) as Record<string, any>
      const origSpec = (orig.spec ?? {}) as Record<string, any>
      const resource = {
        apiVersion: 'ontogeny/v1',
        kind: 'AgentPlugin',
        metadata: { name, ...(display ? { display } : {}), ...(description ? { description } : {}) },
        spec: {
          engine: origSpec.engine ?? { kind: 'builtin-llm' },
          ...(origSpec.transport ? { transport: origSpec.transport } : {}),
          principal: { id: `agent:${name}`, Role: roles, ...(site ? { site } : {}) },
          tools: { allow: tools, ...(origSpec.tools?.deny ? { deny: origSpec.tools.deny } : {}) },
          approval: { writes, ...(origSpec.approval?.auto_actions ? { auto_actions: origSpec.approval.auto_actions } : {}) },
          budget: { steps, wall_ms: origSpec.budget?.wall_ms ?? 120_000, writes_per_session: writesPerSession },
        },
      }
      await apiClient.builderSave([resource], [])
      qc.invalidateQueries({ queryKey: keys.agentPlugins })
      setDoneName(name)
      onCreated?.(name)
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const warns: string[] = []
  if (writes === 'never' && tools.some((tool) => tool.startsWith('act_'))) {
    warns.push(t('agent.new.warn.neverWithAct'))
  }
  if (tools.length === 0) warns.push(t('agent.new.warn.noTools'))

  const groupOf = (tool: string) =>
    tool.startsWith('act_') ? t('agent.new.group.act')
      : tool.startsWith('call_') ? t('agent.new.group.call')
        : tool.startsWith('search_') ? t('agent.new.group.search')
          : t('agent.new.group.meta')

  // Portaled to <body> like every other modal: rendered inline, an ancestor of
  // the panel tree can become the containing block for `position: fixed`, and
  // the overlay then centers against that box instead of the viewport — which
  // is exactly the "dialog stuck to the top" bug.
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(15, 23, 42, .45)' }}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('agent.new.title')}
        data-testid="new-plugin-dialog"
        className="ontogeny-card ontogeny-modal flex max-h-[86vh] w-full max-w-5xl flex-col overflow-hidden"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-4" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{editing ? t('agent.new.editTitle') : t('agent.new.title')}</h2>
            <p className="mt-0.5 text-[12px] muted">{t('agent.new.subtitle')}</p>
          </div>
          <button onClick={onClose} data-testid="new-plugin-close" aria-label={t('common.close')}
            className="grid size-7 shrink-0 place-items-center rounded-lg hover:bg-[var(--surface-hover)]" style={{ color: 'var(--text-muted)' }}>
            <IconX width={14} height={14} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:grid-rows-[minmax(0,1fr)]">
          {/* ------------------------------------------------ left: the form */}
          <div className="flex min-h-0 flex-col gap-4 overflow-y-auto px-5 py-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="ontogeny-label">{t('agent.new.name')}</span>
                <input className="ontogeny-input font-mono text-[12.5px]" data-testid="new-plugin-name"
                  placeholder="ops-copilot" value={name} disabled={!!editing}
                  title={editing ? t('agent.new.nameLocked') : undefined}
                  onChange={(e) => { setName(e.target.value); setDoneName(null) }} />
                {name && !nameOk ? <span className="mt-1 block text-[11px]" style={{ color: 'var(--tone-danger-fg)' }}>{t('agent.new.nameHint')}</span> : null}
                {name && nameOk && !nameFree ? <span className="mt-1 block text-[11px]" style={{ color: 'var(--tone-warning-fg)' }}>{t('agent.new.nameTaken')}</span> : null}
              </label>
              <label className="block">
                <span className="ontogeny-label">{t('agent.new.display')}</span>
                <input className="ontogeny-input" data-testid="new-plugin-display"
                  value={display} onChange={(e) => setDisplay(e.target.value)} />
              </label>
            </div>

            <label className="block">
              <span className="ontogeny-label">{t('agent.new.description')}</span>
              <input className="ontogeny-input" data-testid="new-plugin-description"
                value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>

            {/* identity: id is derived, roles come from the Cedar vocabulary */}
            <div className="rounded-lg p-3" style={{ background: 'var(--surface-sunken)' }}>
              <span className="ontogeny-label">{t('agent.new.roles')}</span>
              <div className="flex flex-wrap gap-1.5" data-testid="new-plugin-roles">
                {(meta.data?.roles ?? []).map((role) => (
                  <button key={role} data-testid={`new-plugin-role-${role}`} onClick={() => toggleRole(role)}
                    className="rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors"
                    style={{
                      background: roles.includes(role) ? 'var(--brand-tint)' : 'var(--surface-card)',
                      color: roles.includes(role) ? 'var(--brand-fg)' : 'var(--text-secondary)',
                      boxShadow: roles.includes(role) ? 'inset 0 0 0 1px var(--brand-tint-ring)' : '1px solid var(--border-subtle)',
                    }}>
                    {role}
                  </button>
                ))}
                {!(meta.data?.roles ?? []).length ? <span className="text-[12px] muted">{t('common.loading')}</span> : null}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className="text-[11.5px] muted">{t('agent.new.principalId')}</span>
                <code className="ontogeny-code">{name ? `agent:${name}` : 'agent:…'}</code>
                <input className="ontogeny-input ml-auto h-7 w-28 text-[12px]" placeholder={t('agent.new.site')}
                  value={site} onChange={(e) => setSite(e.target.value)} />
                <p className="mt-1.5 w-full text-[11px] leading-relaxed muted" data-testid="new-plugin-site-hint">
                  {t('agent.new.siteHint')}
                </p>
              </div>
            </div>

            {/* tools */}
            <div>
              <span className="ontogeny-label">{t('agent.new.tools')}</span>
              <div className="flex flex-col gap-2.5">
                {groups.map((g) => (
                  <div key={g.key}>
                    <div className="mb-1 flex items-center gap-2">
                      <span className="text-[11px] font-semibold uppercase tracking-[0.06em] muted">{g.label}</span>
                      {g.writes ? <Badge tone="warning">{t('agent.new.writes')}</Badge> : null}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {g.tools.map((tool) => (
                        <button key={tool} onClick={() => toggleTool(tool)}
                          data-testid={`new-plugin-tool-${tool}`}
                          className="rounded-lg px-2 py-1 font-mono text-[11px] transition-colors"
                          style={{
                            background: tools.includes(tool) ? 'var(--brand-tint)' : 'var(--surface-sunken)',
                            color: tools.includes(tool) ? 'var(--brand-fg)' : 'var(--text-secondary)',
                            boxShadow: tools.includes(tool) ? 'inset 0 0 0 1px var(--brand-tint-ring)' : 'none',
                          }}>
                          {tool}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* approval + budget */}
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <span className="ontogeny-label">{t('agent.new.approval')}</span>
                <div className="flex gap-1.5">
                  {(['confirm', 'never', 'auto'] as ApprovalWrites[]).map((w) => (
                    <button key={w} onClick={() => setWrites(w)}
                      className="rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition-colors"
                      style={{
                        background: writes === w ? 'var(--brand-tint)' : 'var(--surface-sunken)',
                        color: writes === w ? 'var(--brand-fg)' : 'var(--text-secondary)',
                        boxShadow: writes === w ? 'inset 0 0 0 1px var(--brand-tint-ring)' : 'none',
                      }}>
                      {t(`agent.new.writes.${w}`)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="ontogeny-label">{t('agent.new.steps')}</span>
                  <input type="number" min={1} className="ontogeny-input tnum" value={steps}
                    onChange={(e) => setSteps(Math.max(1, Number(e.target.value) || 1))} />
                </label>
                <label className="block">
                  <span className="ontogeny-label">{t('agent.new.writesBudget')}</span>
                  <input type="number" min={0} className="ontogeny-input tnum" value={writesPerSession}
                    onChange={(e) => setWritesPerSession(Math.max(0, Number(e.target.value) || 0))} />
                </label>
              </div>
            </div>

            {warns.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
            {error ? <Alert tone="danger" testId="new-plugin-error">{error}</Alert> : null}
            {doneName ? (
              <Alert tone="success" testId="new-plugin-done">{t('agent.new.done', { name: doneName })}</Alert>
            ) : null}
          </div>

          {/* --------------------------------------------- right: the inspector */}
          <aside
            data-testid="new-plugin-detail"
            className="min-h-0 overflow-y-auto border-t px-4 py-4 lg:border-t-0"
            style={{ borderLeft: '1px solid var(--border-subtle)', background: 'var(--surface-sunken)' }}
          >
            <div className="ontogeny-label mb-2">{t('agent.new.detail.heading')}</div>
            <DetailPane detail={detail} tools={tools} roles={roles} groupOf={groupOf} t={t} />
          </aside>
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-3 px-5 py-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <span className="text-[11px] muted">{t('agent.new.publishNote')}</span>
          <div className="flex gap-2">
            <Button onClick={onClose} data-testid="new-plugin-cancel">{t('common.close')}</Button>
            <Button variant="primary" disabled={!canSubmit} onClick={submit} data-testid="new-plugin-submit">
              {busy ? t('common.loading') : editing ? t('common.save') : t('agent.new.create')}
            </Button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}

/* ----------------------------------------------------------- inspector pane */

type TFn = (key: string, params?: Record<string, string | number>) => string

function DetailPane({ detail, tools, roles, groupOf, t }: {
  detail: Detail | null
  tools: string[]
  roles: string[]
  groupOf: (tool: string) => string
  t: TFn
}) {
  if (!detail) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
        <span className="grid size-9 place-items-center rounded-xl" style={{ background: 'var(--surface-card)', color: 'var(--text-muted)' }}>
          <IconCog width={16} height={16} />
        </span>
        <p className="max-w-[220px] text-[12px] leading-relaxed muted">{t('agent.new.detail.placeholder')}</p>
      </div>
    )
  }

  const allowBadge = detail.type !== 'role' ? (() => {
    const on = tools.includes(detail.name)
    return <Badge tone={on ? 'success' : 'neutral'}>{t(on ? 'agent.new.detail.inAllow' : 'agent.new.detail.notInAllow')}</Badge>
  })() : null

  const header = (
    <div className="flex flex-wrap items-center gap-1.5">
      <code className="ontogeny-code">{detail.name}</code>
      {detail.type === 'role'
        ? <Badge tone="brand">{t('agent.new.detail.roleBadge')}</Badge>
        : detail.type === 'action'
          ? <Badge tone="warning">{groupOf(detail.name)}</Badge>
          : detail.type !== 'unknown'
            ? <Badge tone="info">{groupOf(detail.name)}</Badge>
            : null}
      {allowBadge}
    </div>
  )

  if (detail.type === 'role') {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <p className="text-[12px] leading-relaxed secondary-text">{t('agent.new.detail.roleBody')}</p>
        <div>
          <div className="ontogeny-label mb-1">{t('agent.new.roles')}</div>
          <div className="flex flex-wrap gap-1">
            {roles.map((r) => <Badge key={r} tone={r === detail.name ? 'brand' : 'neutral'}>{r}</Badge>)}
          </div>
        </div>
      </div>
    )
  }

  if (detail.type === 'fixed') {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <p className="text-[12px] leading-relaxed secondary-text">{t(`agent.new.detail.${detail.name}`)}</p>
      </div>
    )
  }

  if (detail.type === 'unknown') {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <p className="text-[12px] muted">{t('agent.new.detail.placeholder')}</p>
      </div>
    )
  }

  if (detail.type === 'object') {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <KeyValue items={[
          { key: t('agent.new.detail.object'), value: detail.def.display ? `${detail.def.display} (${detail.key})` : detail.key },
          { key: t('agent.new.detail.pk'), value: detail.def.primaryKey.join(', '), mono: true },
        ]} />
        <div>
          <div className="ontogeny-label mb-1">{t('agent.new.detail.properties')} · {Object.keys(detail.def.properties).length}</div>
          <FieldRows rows={Object.entries(detail.def.properties).map(([k, p]) => ({
            name: k, type: p.type, required: p.required, desc: p.description ?? null,
          }))} />
        </div>
      </div>
    )
  }

  if (detail.type === 'function') {
    return (
      <div className="flex flex-col gap-3">
        {header}
        <KeyValue items={[{ key: t('agent.new.detail.entry'), value: detail.def.entry, mono: true }]} />
        <ParamBlock label={t('agent.new.detail.params')} params={detail.def.parameters} />
      </div>
    )
  }

  // action (write)
  return (
    <div className="flex flex-col gap-3">
      {header}
      <KeyValue items={[
        ...(detail.def.display ? [{ key: t('agent.new.detail.actionName'), value: detail.def.display }] : []),
        { key: t('agent.new.detail.target'), value: detail.def.target, mono: true },
      ]} />
      <ParamBlock label={t('agent.new.detail.params')} params={detail.def.parameters} />
      <Alert tone="warning">{t('agent.new.detail.writeNote')}</Alert>
    </div>
  )
}

function ParamBlock({ label, params }: { label: string; params: Record<string, ParamMeta> }) {
  const rows = Object.entries(params)
  return (
    <div>
      <div className="ontogeny-label mb-1">{label} · {rows.length}</div>
      <FieldRows rows={rows.map(([k, p]) => ({ name: k, type: p.type, required: p.required, desc: null }))} />
    </div>
  )
}

function FieldRows({ rows }: { rows: { name: string; type: string; required?: boolean; desc?: string | null }[] }) {
  const { t } = useI18n()
  if (rows.length === 0) return <p className="text-[12px] muted">—</p>
  return (
    <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
      {rows.map((r) => (
        <div key={r.name} className="flex items-center gap-2 py-1.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <code className="ontogeny-code shrink-0">{r.name}</code>
          <span className="shrink-0 font-mono text-[10.5px] muted">{r.type}</span>
          {r.required != null ? (
            <span className="shrink-0 text-[10.5px]" style={{ color: r.required ? 'var(--tone-warning-fg)' : 'var(--text-muted)' }}>
              {r.required ? t('agent.new.detail.required') : t('agent.new.detail.optional')}
            </span>
          ) : null}
          {r.desc ? (
            <span className="ml-auto min-w-0 flex-1 truncate text-right text-[11px] muted" title={r.desc}>{r.desc}</span>
          ) : null}
        </div>
      ))}
    </div>
  )
}
