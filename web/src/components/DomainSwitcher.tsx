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
 * Domain switcher: which ontology package the console is serving.
 *
 * A deployment serves exactly ONE active ontology (domain); switching
 * republishes another package server-side and retires the previous snapshot.
 * Everything on every page derives from that snapshot, so a successful switch
 * invalidates the whole React Query cache -- and every localStorage artifact
 * that belongs to the package being left behind: the ontology session's draft
 * and its hand-arranged layout (see `clearOntologyDraftStorage`).
 *
 * Three placements, one component:
 *   - `rail` (the sidebar foot) — the console's home for it. Which package is
 *     active is *navigation* state: it changes what every route shows, so it
 *     belongs with the nav rather than floating over the page, and the canvas
 *     keeps its full height. Collapses to a single icon in the 64px rail.
 *   - the dashboard's context bar — the page where "what is in this package"
 *     is the first question, so it gets the full bar with the description.
 *
 * It steps aside when there is nothing to switch between: a one-domain
 * deployment does not need a picker, so it renders nothing at all.
 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, type DomainInfo } from '../api/client'
import { domainsQuery, invalidateOnDomainSwitch } from '../api/queries'
import { clearOntologyDraftStorage } from '../pages/ontology/draft'
import { useI18n } from '../i18n'
import { ApiError } from '../api/client'
import { buildZip, folderEntries, type ZipEntry } from '../lib/zip'
import { useFocusTrap } from '../lib/focus'
import { Alert, Badge, Button, Panel } from './ui'
import { IconCheck, IconChevron, IconCube, IconPlus } from './icons'

export function DomainSwitcher({ collapsed = false }: {
  /** The sidebar is in its 64px rail: the trigger shrinks to its icon. */
  collapsed?: boolean
}) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const domains = useQuery(domainsQuery())

  // the dropdown closes on Escape or an outside click, like every popover here
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const afterSwitch = () => {
    // the snapshot, the object tables, audit, signals, sessions -- a domain
    // switch moves all of them; the ontology session's draft and layout belong
    // to the old package and must not be restored onto the new canvas
    invalidateOnDomainSwitch(qc)
    clearOntologyDraftStorage()
  }
  const activate = useMutation({
    mutationFn: (name: string) => apiClient.activateDomain(name),
    onSuccess: afterSwitch,
  })

  const list = domains.data?.domains ?? []
  const active = list.find((d) => d.active)

  // Drawn from the FIRST domain on: the menu is not only a switcher, it is
  // also the only entry point for "New domain" (scaffold or import) -- hiding
  // it on a single-domain deployment made creating the second domain
  // impossible (chicken-and-egg).
  if (!domains.isLoading && list.length < 1) return null

  const activeName = active ? (active.display || active.name) : '…'

  return (
    <div className="relative" ref={boxRef} data-testid="domain-bar">
      <button
        type="button"
        data-testid="domain-switcher"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`${t('domain.label')}: ${activeName}`}
        aria-label={`${t('domain.label')}: ${activeName}`}
        onClick={() => setOpen((o) => !o)}
        data-active={open}
        className={collapsed
          ? 'ontogeny-nav-item w-full justify-center px-0'
          : 'ontogeny-nav-item w-full'}
      >
        <span
          className="grid size-[22px] shrink-0 place-items-center rounded-md"
          style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}
        >
          <IconCube width={13} height={13} />
        </span>
        {collapsed ? null : (
          <>
            <span className="min-w-0 flex-1 truncate">{activeName}</span>
            <IconChevron
              width={13}
              height={13}
              className="shrink-0 muted"
              style={{ transform: open ? 'rotate(90deg)' : undefined, transition: 'transform .15s' }}
            />
          </>
        )}
      </button>

      {open ? (
        <Panel
          role="listbox"
          ariaLabel={t('domain.switch')}
          floating
          // Opens *upward* out of the sidebar foot — there is nothing below it —
          // and to the side of the 64px rail, where it would otherwise be
          // clipped by the rail's own width.
          className={[
            'absolute z-50 w-[340px] py-1',
            collapsed ? 'bottom-0 left-full ml-2' : 'bottom-full left-0 mb-1.5',
          ].join(' ')}
          style={{ background: 'var(--surface-card)' }}
          testId="domain-menu"
        >
          {list.length === 0 ? (
            <div className="px-3.5 py-2.5 text-[12.5px] muted">{t('domain.empty')}</div>
          ) : list.map((d) => (
            <DomainOption
              key={d.name}
              domain={d}
              switching={activate.isPending && activate.variables === d.name}
              onPick={() => {
                setOpen(false)
                if (!d.active) activate.mutate(d.name)
              }}
            />
          ))}
          <div className="mt-1 px-1.5 pt-1" style={{ borderTop: '1px solid var(--border-subtle)' }}>
            <button
              type="button"
              data-testid="domain-create"
              onClick={() => { setOpen(false); setCreateOpen(true) }}
              className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-[12.5px] transition-colors hover:bg-[var(--surface-hover)]"
            >
              <span
                className="grid size-6 shrink-0 place-items-center rounded-md"
                style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}
              >
                <IconPlus width={13} height={13} />
              </span>
              {t('domain.create')}
            </button>
          </div>
        </Panel>
      ) : null}

      {/* The switch is a server round-trip that republishes a package: a
          failure has to be visible, and the footer is where the control is. */}
      {activate.error ? (
        <div
          className="absolute bottom-full left-0 z-50 mb-1.5 w-[280px]"
          data-testid="domain-switch-error"
        >
          <Alert tone="danger">
            {t('domain.switchFailed')}: {String((activate.error as { message?: string }).message ?? activate.error)}
          </Alert>
        </div>
      ) : null}

      <CreateDomainDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        existingNames={list.map((d) => d.name)}
        onCreated={afterSwitch}
      />
    </div>
  )
}

function DomainOption({ domain: d, switching, onPick }: {
  domain: DomainInfo
  switching: boolean
  onPick: () => void
}) {
  const { t } = useI18n()
  return (
    <button
      type="button"
      role="option"
      aria-selected={d.active}
      data-testid={`domain-option-${d.name}`}
      onClick={onPick}
      className="flex w-full items-start gap-2.5 px-3.5 py-2 text-left transition-colors hover:bg-[var(--surface-hover)]"
      style={{ background: d.active ? 'var(--surface-sunken)' : undefined }}
    >
      <span
        className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg"
        style={d.active
          ? { background: 'var(--brand-tint)', color: 'var(--brand-fg)' }
          : { background: 'var(--surface-sunken)', color: 'var(--text-muted)' }}
      >
        <IconCube width={14} height={14} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="min-w-0 truncate font-mono text-[12.5px] font-medium">{d.name}</span>
          {d.active ? <Badge tone="brand">{t('domain.active')}</Badge> : null}
          {switching ? <span className="text-[11px] muted">{t('domain.switching')}</span> : null}
        </span>
        {d.display && d.display !== d.name ? (
          <span className="block truncate text-[11.5px] secondary-text">{d.display}</span>
        ) : null}
        <span className="mt-0.5 block truncate text-[11px] muted tnum">
          {t('domain.typesCount', { objects: d.objects, links: d.links, actions: d.actions })}
        </span>
        {!d.check?.ok && d.check?.errors?.length ? (
          <span
            className="mt-0.5 block truncate text-[11px]"
            style={{ color: 'var(--tone-danger-fg)' }}
            title={d.check.errors.join('\n')}
          >
            {t('domain.checkFailed', { error: d.check.errors[0] })}
          </span>
        ) : null}
      </span>
      {d.active && !switching ? (
        <IconCheck width={14} height={14} className="mt-1 shrink-0" style={{ color: 'var(--tone-success-fg)' }} />
      ) : null}
    </button>
  )
}

/** "New domain" dialog: scaffold + activate in one step, so creating a domain
 *  lands you inside it (the builder is the very next stop for modelling). */
function CreateDomainDialog({ open, onClose, existingNames, onCreated }: {
  open: boolean
  onClose: () => void
  existingNames: string[]
  onCreated: () => void
}) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const ref = useFocusTrap<HTMLDivElement>(open)
  const [name, setName] = useState('')
  const [display, setDisplay] = useState('')
  const [description, setDescription] = useState('')
  // "scaffold" = create an empty package here; "import" = upload a domain zip
  // or a whole package FOLDER (zipped client-side before upload)
  const [mode, setMode] = useState<'scaffold' | 'import'>('scaffold')
  const [file, setFile] = useState<File | null>(null)
  const [folder, setFolder] = useState<{ name: string; entries: ZipEntry[] } | null>(null)
  // problems that make the CURRENT selection unuploadable, shown as a list
  // (client-side preflight); server-side refusals arrive via create.error
  const [problems, setProblems] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // re-open with a clean form
  useEffect(() => {
    if (open) {
      setName(''); setDisplay(''); setDescription(''); setFile(null)
      setFolder(null); setProblems([]); setMode('scaffold')
    }
  }, [open])

  const MAX_FILES = 2000
  const MAX_BYTES = 256 * 1024 * 1024

  /** Read a picked folder into zip entries, refusing selections that cannot
   *  be a domain package BEFORE any upload, with the exact reasons listed. */
  const pickFolder = async (files: FileList | null) => {
    setFile(null)
    setProblems([])
    if (!files || !files.length) { setFolder(null); return }
    const { entries, root } = await folderEntries(files)
    const found: string[] = []
    if (!entries.some(e => e.path === 'ontology.yaml')) {
      found.push(t('domain.errNoManifest', { root: root || '…' }))
      found.push(t('domain.errFoundInstead', {
        roots: [...new Set(entries.map(e => e.path.split('/')[0]))].slice(0, 8).join(', '),
      }))
    }
    if (entries.length > MAX_FILES) found.push(t('domain.errTooManyFiles', { count: entries.length }))
    const bytes = entries.reduce((n, e) => n + e.data.length, 0)
    if (bytes > MAX_BYTES) found.push(t('domain.errTooBig', { mb: Math.round(bytes / 1048576) }))
    setProblems(found)
    setFolder(found.length ? null : { name: root || 'package', entries })
  }

  const pickZip = (f: File | null) => {
    setFolder(null)
    setProblems([])
    setFile(f)
  }

  const NAME_RE = /^[a-z][a-z0-9-]{0,62}$/
  const nameTaken = existingNames.includes(name.trim())
  const nameOk = NAME_RE.test(name.trim()) && !nameTaken

  const create = useMutation({
    mutationFn: async () => {
      if (mode === 'import') {
        const payload = folder
          ? new File([buildZip(folder.entries)], `${folder.name}.zip`, { type: 'application/zip' })
          : (file as File)
        return apiClient.importDomain(payload, true)
      }
      return apiClient.createDomain({
        name: name.trim(),
        display: display.trim() || undefined,
        description: description.trim() || undefined,
        activate: true,
      })
    },
    onSuccess: () => {
      // the new domain is now live server-side: move the whole cache to it
      invalidateOnDomainSwitch(qc)
      localStorage.removeItem('ontogeny.builder.draft')
      onCreated()
      onClose()
    },
  })

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'rgba(0,0,0,.45)' }}
      onClick={onClose}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t('domain.createTitle')}
        data-testid="domain-create-dialog"
        className="ontogeny-card ontogeny-modal w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-[14px] font-semibold">{t('domain.createTitle')}</h2>

        <div className="mt-3 flex gap-1 rounded-lg p-1"
             style={{ background: 'var(--surface-sunken)' }} role="tablist">
          {(['scaffold', 'import'] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              data-testid={`domain-mode-${m}`}
              onClick={() => setMode(m)}
              className={`flex-1 rounded-md px-3 py-1.5 text-[12.5px] font-semibold transition-colors ${
                mode === m ? 'ontogeny-btn-primary' : 'muted hover:text-[var(--text-primary)]'
              }`}
            >
              {t(m === 'scaffold' ? 'domain.tab.create' : 'domain.tab.import')}
            </button>
          ))}
        </div>

        {mode === 'import' ? (
          <>
            <p className="mt-3 text-[12.5px] secondary-text">{t('domain.importHint')}</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <div>
                <label className="ontogeny-label" htmlFor="domain-zip">{t('domain.importPick')}</label>
                <input
                  id="domain-zip"
                  type="file"
                  accept=".zip,application/zip"
                  data-testid="domain-zip-input"
                  className="ontogeny-input mt-1 text-[12px]"
                  onChange={(e) => pickZip(e.target.files?.[0] ?? null)}
                />
              </div>
              <div>
                <label className="ontogeny-label" htmlFor="domain-folder">{t('domain.importFolder')}</label>
                <input
                  id="domain-folder"
                  type="file"
                  multiple
                  data-testid="domain-folder-input"
                  className="ontogeny-input mt-1 text-[12px]"
                  ref={(el) => { if (el) el.setAttribute('webkitdirectory', '') }}
                  onChange={(e) => { void pickFolder(e.target.files) }}
                />
              </div>
            </div>
            <p className="mt-1 text-[11px] muted">{t('domain.importPickHint')}</p>
            {file ? (
              <p className="mt-1.5 font-mono text-[11.5px]" data-testid="domain-zip-name">
                {file.name} · {(file.size / 1024).toFixed(1)} KB
              </p>
            ) : null}
            {folder ? (
              <p className="mt-1.5 font-mono text-[11.5px]" data-testid="domain-zip-name">
                {t('domain.folderSummary', { name: folder.name, count: folder.entries.length })}
              </p>
            ) : null}
            {problems.length ? (
              <ul className="mt-2 flex flex-col gap-1" data-testid="domain-import-problems">
                {problems.map((msg) => (
                  <li key={msg} className="text-[11.5px]" style={{ color: 'var(--tone-danger-fg)' }}>
                    · {msg}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : (
          <p className="mt-3 text-[12.5px] secondary-text">{t('domain.createHint')}</p>
        )}

        <div className="mt-4 flex flex-col gap-3">
          {mode === 'scaffold' ? (<>
          <div>
            <label className="ontogeny-label" htmlFor="domain-name">{t('domain.name')}</label>
            <input
              id="domain-name"
              className="ontogeny-input mt-1 font-mono"
              placeholder={t('domain.namePlaceholder')}
              value={name}
              data-testid="domain-name-input"
              onChange={(e) => setName(e.target.value)}
            />
            {name.trim() && !NAME_RE.test(name.trim()) ? (
              <p className="mt-1 text-[11.5px]" style={{ color: 'var(--tone-danger-fg)' }}>
                {t('domain.namePlaceholder')}
              </p>
            ) : nameTaken ? (
              <p className="mt-1 text-[11.5px]" style={{ color: 'var(--tone-danger-fg)' }}>
                {t('domain.nameTaken')}
              </p>
            ) : null}
          </div>
          <div>
            <label className="ontogeny-label" htmlFor="domain-display">{t('domain.display')}</label>
            <input
              id="domain-display"
              className="ontogeny-input mt-1"
              placeholder={t('domain.displayPlaceholder')}
              value={display}
              data-testid="domain-display-input"
              onChange={(e) => setDisplay(e.target.value)}
            />
          </div>
          <div>
            <label className="ontogeny-label" htmlFor="domain-desc">{t('domain.description')}</label>
            <input
              id="domain-desc"
              className="ontogeny-input mt-1"
              value={description}
              data-testid="domain-desc-input"
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          </>) : null}
        </div>

        {create.error ? (
          /* The specific problems, not just "it failed": the server refuses
             imports with the validator's issue list (details.issues), so the
             operator sees exactly what to fix in the package. */
          <div className="mt-3" data-testid="domain-import-error">
            <Alert tone="danger" title={t('domain.importFailed')}>
              {String((create.error as { message?: string }).message ?? create.error)}
              {create.error instanceof ApiError && Array.isArray(create.error.details?.issues) ? (
                <ul className="mt-1.5 flex flex-col gap-0.5">
                  {(create.error.details.issues as Array<{ code?: string; resource?: string; message?: string }>)
                    .slice(0, 20)
                    .map((issue, i) => (
                      <li key={i} className="font-mono text-[11px]">
                        · {issue.code ?? 'ERROR'}@{issue.resource ?? '?'}: {issue.message ?? ''}
                      </li>
                    ))}
                </ul>
              ) : null}
              {create.error instanceof ApiError && Array.isArray(create.error.details?.issues)
                && (create.error.details.issues as unknown[]).length > 20 ? (
                  <p className="mt-1 text-[11px]">
                    {t('domain.moreIssues', { count: (create.error.details.issues as unknown[]).length - 20 })}
                  </p>
                ) : null}
            </Alert>
          </div>
        ) : null}

        <div className="mt-5 flex justify-end gap-2">
          <Button data-testid="domain-create-cancel" onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            data-testid="domain-create-confirm"
            disabled={create.isPending || (mode === 'scaffold'
              ? !nameOk
              : !(file || (folder && !problems.length)))}
            onClick={() => create.mutate()}
          >
            {create.isPending
              ? t(mode === 'scaffold' ? 'domain.creating' : 'domain.importing')
              : t(mode === 'scaffold' ? 'domain.create' : 'domain.importAction')}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
