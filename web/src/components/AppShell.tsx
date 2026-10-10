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
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useAuth } from '../api/auth'
import { keys, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { useTheme } from '../theme'
import { useFocusTrap, useMediaQuery } from '../lib/focus'
import { Badge, Button, Panel } from './ui'
import { DomainSwitcher } from './DomainSwitcher'
import { AgentDock } from './AgentDock'
import {
  IconBook, IconChevron, IconCog, IconCube, IconGlobe, IconGrid, IconLayers, IconList,
  IconMoon, IconNetwork, IconRoute, IconSearch, IconShield, IconSpark, IconSun, IconUser, IconX,
  
} from './icons'

/** Routes that own the whole viewport (edge-to-edge canvases). They render
 *  their own chrome, so the shell drops its padding, max-width and scrolling. */
/* Canvas pages: the page itself does not scroll — a canvas inside it fills the
 * remaining height instead. They keep the same page padding, header position and
 * max width as every other page, so only the canvas is special. */
const FULL_BLEED_ROUTES = ['/ontology', '/graph', '/knowledge', '/action']

const NAV_GROUPS: Array<{
  key: string
  items: Array<{
    to: string
    key: string
    icon: (p: React.SVGProps<SVGSVGElement>) => React.ReactElement
  }>
}> = [
  {
    key: 'nav.group.overview',
    items: [
      { to: '/', key: 'nav.dashboard', icon: IconGrid },
    ],
  },
  {
    key: 'nav.group.model',
    items: [
      { to: '/ontology', key: 'nav.ontology', icon: IconCube },
      { to: '/graph', key: 'nav.graph', icon: IconNetwork },
      // the ontology's two halves, each editable: Knowledge = what exists
      // (objects · links · projection), Action = what may happen (actions ·
      // functions · policies). The old single "data preview" is the Knowledge
      // page's first tab; /data still resolves there.
      { to: '/knowledge', key: 'nav.knowledge', icon: IconBook },
      { to: '/action', key: 'nav.action', icon: IconRoute },
    ],
  },
  {
    key: 'nav.group.operate',
    items: [
      // The agent's conversation is a floating dock (bottom-right, ⌘J) rather
      // than a route: it is something you keep beside your work, not a place
      // you navigate to. What remains here manages runs: sessions, pending
      // writes and plugins, one surface with a tab bar.
      { to: '/agent/manage', key: 'nav.agentManage', icon: IconLayers },
      { to: '/audit', key: 'nav.audit', icon: IconShield },
      // self-improvement anchors the governance tail: it consumes what audit
      // produces (signals from real runs) and sits directly above operations
      { to: '/evolve', key: 'nav.evolve', icon: IconSpark },
      // extensions and operations are one module now (capabilities, registry,
      // projection, demo environment); /extensions deep-links into its tab
      { to: '/admin', key: 'nav.admin', icon: IconCog },
      // accounts & the role/permission matrix (administrators only)
      { to: '/access', key: 'nav.access', icon: IconUser },
    ],
  },
]

/** Fixed-English provenance line. Deliberately not i18n'd: upstream branding
 *  reads the same in every locale, and the footer stays a single short line. */
const APP_PROVENANCE = 'A subproject of Apache HugeGraph · v0.3'

/** Command-palette style search over the loaded ontology + navigation.
 *  Resting state is one icon in the one-line footer; activating swaps the row
 *  for the input, with results opening *upwards*. ⌘K activates from anywhere. */
function GlobalSearch({ collapsed, segmented = false, open, onOpen, onClose, onExpandRail }: {
  collapsed: boolean
  /** resting icon renders as a cell of the sunken footer toolbar (expanded rail) */
  segmented?: boolean
  open: boolean
  onOpen: () => void
  onClose: () => void
  onExpandRail: () => void
}) {
  const { t } = useI18n()
  const meta = useMeta()
  const [query, setQuery] = useState('')
  const [listOpen, setListOpen] = useState(false)
  const [wantsFocus, setWantsFocus] = useState(false)
  // which option the arrow keys are on; -1 = the input itself
  const [cursor, setCursor] = useState(-1)
  const nav = useNavigate()
  const boxRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // ⌘K works whether the search is open or not, collapsed rail included
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setWantsFocus(true)
        if (collapsed) onExpandRail()
        onOpen()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [collapsed, onExpandRail, onOpen])

  // while the input row is open: Escape or an outside click folds it back
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setListOpen(false)
        setQuery('')
        onClose()
      }
    }
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setListOpen(false)
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open, onClose])

  useEffect(() => {
    if (!open || !wantsFocus) return
    inputRef.current?.focus()
    setWantsFocus(false)
  }, [open, wantsFocus])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q || !meta.data) return []
    const out: Array<{ kind: string; label: string; to: string; hint?: string }> = []
    for (const [name, obj] of Object.entries(meta.data.objects)) {
      if (name.includes(q) || (obj.display ?? '').toLowerCase().includes(q)) {
        out.push({ kind: 'objectType', label: name, to: `/ontology/${name}`, hint: obj.display })
      }
    }
    for (const [name, action] of Object.entries(meta.data.actions)) {
      if (name.includes(q)) out.push({ kind: 'action', label: name, to: `/actions/${name}`, hint: action.target })
    }
    for (const name of Object.keys(meta.data.functions)) {
      if (name.includes(q)) out.push({ kind: 'function', label: name, to: `/functions/${name}` })
    }
    for (const g of NAV_GROUPS) {
      for (const item of g.items) {
        const label = t(item.key).toLowerCase()
        if (label.includes(q)) out.push({ kind: 'page', label: t(item.key), to: item.to })
      }
    }
    return out.slice(0, 9)
  }, [query, meta.data, t])

  // a new query invalidates the highlighted row
  useEffect(() => setCursor(-1), [query])

  const go = (to: string) => {
    nav(to)
    setListOpen(false)
    setQuery('')
    onClose()
  }

  if (!open) {
    return (
      <button
        type="button"
        data-testid="global-search-open"
        className={segmented ? 'ontogeny-seg-btn flex-1' : 'ontogeny-nav-item flex-1 justify-center px-0'}
        title={t('topbar.search')}
        onClick={() => {
          setWantsFocus(true)
          if (collapsed) onExpandRail()
          onOpen()
        }}
      >
        <IconSearch width={15} height={15} />
      </button>
    )
  }

  return (
    <div ref={boxRef} className="relative min-w-0 flex-1">
      <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 muted">
        <IconSearch width={14} height={14} />
      </span>
      <input
        ref={inputRef}
        className="ontogeny-input pl-8 pr-12 text-[12.5px]"
        placeholder={t('topbar.search')}
        value={query}
        data-testid="global-search"
        onFocus={() => setListOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value)
          setListOpen(true)
        }}
        role="combobox"
        aria-expanded={listOpen && Boolean(query.trim())}
        aria-controls="ontogeny-search-results"
        aria-activedescendant={cursor >= 0 ? `ontogeny-search-option-${cursor}` : undefined}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            // clamp rather than wrap: the list opens upward, so wrapping from
            // the top row to the bottom one reads as a jump away from the input
            e.preventDefault()
            if (!results.length) return
            setListOpen(true)
            setCursor((i) => {
              const next = e.key === 'ArrowDown' ? i + 1 : i - 1
              if (next < 0) return i
              return Math.min(next, results.length - 1)
            })
          } else if (e.key === 'Enter') {
            // Enter with nothing highlighted takes the first result (the old
            // behaviour), so the keyboard-only flow stays a single keystroke
            const pick = results[cursor >= 0 ? cursor : 0]
            if (pick) go(pick.to)
          }
        }}
      />
      <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2">
        <span className="ontogeny-kbd">⌘K</span>
      </span>
      {listOpen && query.trim() ? (
        <Panel
          role="listbox"
          ariaLabel={t('topbar.search')}
          floating
          className="absolute bottom-full left-0 z-50 mb-1.5 w-[344px] py-1"
          style={{ background: 'var(--surface-card)' }}
        >
          {meta.error ? (
            <div className="px-3.5 py-2.5 text-[12.5px]" style={{ color: 'var(--tone-danger-fg)' }}>
              {t('topbar.searchUnavailable')}
            </div>
          ) : results.length === 0 ? (
            <div className="px-3.5 py-2.5 text-[12.5px] muted">{t('topbar.searchEmpty')}</div>
          ) : (
            results.map((r, i) => (
              <button
                key={`${r.kind}-${r.label}-${i}`}
                id={`ontogeny-search-option-${i}`}
                role="option"
                aria-selected={i === cursor}
                data-testid={`search-option-${i}`}
                // the input keeps DOM focus, so the highlight is driven by state
                // rather than :hover / :focus
                onMouseEnter={() => setCursor(i)}
                className="flex w-full items-center gap-3 px-3.5 py-2 text-left text-[13px] transition-colors"
                style={{ background: i === cursor ? 'var(--surface-hover)' : undefined }}
                onClick={() => go(r.to)}
              >
                <Badge tone={r.kind === 'action' ? 'violet' : r.kind === 'function' ? 'info' : r.kind === 'page' ? 'neutral' : 'brand'}>
                  {t(`search.kind.${r.kind}`)}
                </Badge>
                <span className="font-mono text-[12.5px]">{r.label}</span>
                {r.hint ? <span className="ml-auto truncate text-[12px] muted">{r.hint}</span> : null}
              </button>
            ))
          )}
        </Panel>
      ) : null}
    </div>
  )
}

function LanguageSwitch() {
  const { lang, setLang, t } = useI18n()

  return (
    <div className="flex items-center rounded-lg p-0.5" style={{ background: 'var(--surface-sunken)' }} title={t('topbar.language')}>
      <IconGlobe width={13} height={13} className="mx-1.5 muted" />
      {(['zh', 'en'] as const).map((code) => (
        <button
          key={code}
          data-testid={`lang-${code}`}
          onClick={() => setLang(code)}
          className="rounded-md px-2 py-[3px] text-[12px] font-medium transition-colors"
          style={{
            background: lang === code ? 'var(--surface-card)' : 'transparent',
            color: lang === code ? 'var(--text-primary)' : 'var(--text-muted)',
            boxShadow: lang === code ? 'var(--shadow-card)' : 'none',
          }}
        >
          {code === 'zh' ? '中文' : 'EN'}
        </button>
      ))}
    </div>
  )
}

/** Theme toggle, one click, right on the footer dock: sun in light mode,
 *  moon in dark. Detailed settings live in the dialog; this one is frequent
 *  enough to earn a permanent slot. */
function ThemeToggle({ className }: { className: string }) {
  const [theme, toggle] = useTheme()
  const { t } = useI18n()

  return (
    <button
      type="button"
      className={className}
      onClick={toggle}
      data-testid="theme-toggle"
      title={`${t('topbar.theme')}: ${theme === 'dark' ? t('topbar.theme.dark') : t('topbar.theme.light')}`}
    >
      {theme === 'dark' ? <IconMoon width={15} height={15} /> : <IconSun width={15} height={15} />}
    </button>
  )
}

/** Who is signed in, and the way out. The session is a cookie the page cannot
 *  read, so this is the server's answer (from `useAuth`), not localStorage.
 *  A `via: 'dev-header'` principal is the acting-as simulation from the Access
 *  page's identity tab, not an account — labeled as such. */
function SignedInAccount({ onSignedOut }: { onSignedOut: () => void }) {
  const { t } = useI18n()
  const { principal, isAdmin, signOut } = useAuth()
  const [busy, setBusy] = useState(false)
  const roles = (principal?.Role ?? principal?.roles ?? []) as string[]

  return (
    <div data-testid="signed-in-account" className="rounded-lg px-2.5 py-2.5" style={{ background: 'var(--surface-sunken)' }}>
      <div className="flex items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg" style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}>
          <IconUser width={15} height={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-mono text-[12.5px]">{principal?.id ?? '—'}</span>
            {principal?.via === 'dev-header' ? (
              <span data-testid="simulated-badge">
                <Badge tone="warning">{t('access.simulated')}</Badge>
              </span>
            ) : null}
          </div>
          <div className="truncate text-[11px] muted">
            {String((principal as { display?: string } | null)?.display ?? '')}
          </div>
        </div>
        {isAdmin ? <span className="ontogeny-nav-tag" data-tone="extension">{t('access.admin')}</span> : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {roles.length === 0 ? <span className="text-[11px] muted">{t('access.noRoles')}</span> : null}
        {roles.map((r) => <span key={r} className="ontogeny-code">{r}</span>)}
      </div>
      <div className="mt-2.5 flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[11px] muted">
          {t('topbar.site')}: <span className="font-mono">{(principal as { site?: string } | null)?.site ?? '—'}</span>
        </span>
        <Button
          size="sm"
          data-testid="sign-out"
          disabled={busy}
          onClick={() => { setBusy(true); void signOut().finally(() => { setBusy(false); onSignedOut() }) }}
        >
          {t('access.signOut')}
        </Button>
      </div>
    </div>
  )
}

/** Everything that used to crowd the sidebar foot — language, theme, version,
 *  plus the signed-in account — editable here, so the rail itself stays one
 *  line. The dev acting-as picker lives on Access control → identity simulation, next to the
 *  roles it simulates. */
function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const meta = useMeta()
  const ref = useFocusTrap<HTMLDivElement>(open)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'rgba(0,0,0,.45)' }}
      onClick={onClose}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.title')}
        data-testid="settings-dialog"
        className="ontogeny-card ontogeny-modal max-h-[85vh] w-full max-w-lg overflow-y-auto p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-[14px] font-semibold">{t('settings.title')}</h2>
          <button
            type="button"
            data-testid="settings-close"
            aria-label={t('common.cancel')}
            onClick={onClose}
            className="grid size-7 place-items-center rounded-lg muted transition-colors"
            style={{ background: 'var(--surface-sunken)' }}
          >
            <IconX width={14} height={14} />
          </button>
        </div>

        <div className="mt-4">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('topbar.language')}</div>
          <LanguageSwitch />
        </div>

        <div className="mt-4">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('access.account')}</div>
          <SignedInAccount onSignedOut={onClose} />
        </div>

        <div className="mt-4 ontogeny-divider" />
        <div className="flex items-center justify-between gap-3">
          <span
            className="truncate font-mono text-[11px] muted"
            data-testid="settings-version"
            title={meta.error ? t('app.metaUnreadable') : meta.data?.content_hash}
          >
            RSI v0.3 · {meta.error ? t('common.unknown') : (meta.data?.content_hash.slice(0, 8) ?? '—')}
          </span>
          <Button variant="primary" data-testid="settings-done" onClick={onClose}>{t('settings.done')}</Button>
        </div>
      </div>
    </div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { t } = useI18n()
  const location = useLocation()
  const meta = useMeta()
  // The human write gate is a governance signal, not a page-local detail: the
  // count rides on the sidebar's agent module so a pending write is visible
  // from anywhere. Polled slowly (it changes only when an agent writes).
  const pendingApprovals = useQuery({
    queryKey: keys.agentApprovals('pending'),
    queryFn: () => apiClient.agentApprovals('pending'),
    refetchInterval: 30000,
  })
  const pendingCount = pendingApprovals.data?.approvals?.length ?? 0
  // `null` = the user has never chosen, so the viewport decides. The sidebar
  // used to be a fixed 236px at every width: at 480px that left <main> 244px
  // wide, and its inner containers overflowed into a nested horizontal scroll.
  const [preference, setPreference] = useState<boolean | null>(() => {
    const saved = localStorage.getItem('ontogeny.sidebar')
    return saved === 'collapsed' ? true : saved === 'expanded' ? false : null
  })
  const isNarrow = useMediaQuery('(max-width: 1023px)')
  const isMobile = useMediaQuery('(max-width: 767px)')
  const railCollapsed = preference ?? isNarrow
  // inside the drawer there is no rail: labels are always shown
  const collapsed = isMobile ? false : railCollapsed

  // below `md` the rail is too narrow to read, so the sidebar becomes an
  // off-canvas drawer and the page gets the full width back
  const [drawerOpen, setDrawerOpen] = useState(false)
  const drawerRef = useFocusTrap<HTMLElement>(isMobile && drawerOpen)

  // one-line footer state: search swaps the row for its input; everything
  // detailed (language/theme/identity/version) lives in the settings dialog
  const [searchOpen, setSearchOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const setSidebar = (next: boolean) => {
    localStorage.setItem('ontogeny.sidebar', next ? 'collapsed' : 'expanded')
    setPreference(next)
  }

  // navigating closes the mobile drawer; a route change should never leave it open
  useEffect(() => setDrawerOpen(false), [location.pathname, location.search])

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrawerOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  // Exactly ONE nav row may be active. Plain `startsWith` lit up /agent while
  // /agent/sessions was open, and exact-match-only dropped the highlight on
  // detail routes (/ontology/sales-order, /evolve/12). So: the active row is the
  // longest nav target that the current path is (or is nested under).
  const activeTo = useMemo(() => {
    if (location.pathname === '/') return '/'
    let best = ''
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        if (item.to === '/') continue
        const hit = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)
        if (hit && item.to.length > best.length) best = item.to
      }
    }
    return best
  }, [location.pathname])
  const isActive = (to: string) => to === activeTo

  const bleed = FULL_BLEED_ROUTES.includes(location.pathname)

  return (
    <div className="flex h-full">
      {/* The first stop in the tab order. Without it a keyboard user tabbed
          through all 16 sidebar controls before reaching the page (measured);
          visible only while focused, which is the convention. */}
      <a
        href="#ontogeny-main"
        data-testid="skip-link"
        className="sr-only focus:not-sr-only fixed left-3 top-3 z-50 rounded-lg px-3.5 py-2 text-[13px] font-medium"
        style={{ background: 'var(--color-brand-500)', color: '#fff', boxShadow: 'var(--shadow-float)' }}
      >
        {t('nav.skipToContent')}
      </a>

      {/* mobile: the rail is unreadable, so the sidebar slides in over the page */}
      {isMobile && drawerOpen ? (
        <div
          className="fixed inset-0 z-40"
          style={{ background: 'rgba(0,0,0,.45)' }}
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      <aside
        ref={drawerRef}
        className="flex shrink-0 flex-col transition-[width] duration-200 md:relative"
        style={isMobile ? {
          position: 'fixed',
          insetBlock: 0,
          left: 0,
          zIndex: 41,
          width: 260,
          transform: drawerOpen ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform .2s ease-out',
          background: 'var(--sidebar-bg)',
          borderRight: '1px solid var(--sidebar-border)',
        } : {
          position: 'relative',
          width: collapsed ? 64 : 236,
          background: 'var(--sidebar-bg)',
          borderRight: '1px solid var(--sidebar-border)',
        }}
        data-collapsed={collapsed}
        data-mobile={isMobile}
        data-drawer-open={isMobile ? drawerOpen : undefined}
        data-testid="sidebar"
      >
        {/* collapse toggle: floating on the sidebar edge. Not in drawer mode --
            there the sidebar is either fully open or off-canvas. */}
        {isMobile ? null : (
        <button
          onClick={() => setSidebar(!collapsed)}
          data-testid="sidebar-toggle"
          title={collapsed ? t('nav.expand') : t('nav.collapse')}
          aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
          className="absolute -right-3 top-16 z-10 grid size-6 place-items-center rounded-full"
          style={{
            background: 'var(--surface-card)', border: '1px solid var(--border-subtle)',
            color: 'var(--text-muted)', boxShadow: 'var(--shadow-edge)',
          }}
        >
          <IconChevron
            width={13} height={13}
            style={{ transform: collapsed ? 'rotate(0deg)' : 'rotate(180deg)', transition: 'transform .2s' }}
          />
        </button>
        )}

        <Link
          to="/"
          className={collapsed ? 'flex justify-center pb-4 pt-5' : 'flex items-center gap-2.5 px-5 pb-4 pt-5'}
          title={APP_PROVENANCE}
        >
          <img src="/icon.png" alt="" width={32} height={32} className="size-8 shrink-0" />
          {collapsed ? null : (
            <span className="min-w-0">
              <span className="ontogeny-wordmark block truncate text-[16px]" style={{ color: 'var(--sidebar-fg-active)' }}>
                {t('app.name')}
              </span>
              <span
                className="mt-[3px] block whitespace-nowrap text-[7.5px]"
                style={{ color: 'var(--sidebar-muted)', letterSpacing: '0.05em' }}
              >
                {t('app.tagline')}
              </span>
            </span>
          )}
        </Link>

        <nav className="flex-1 overflow-y-auto px-2.5 pb-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.key}>
              {collapsed ? (
                group.key === 'nav.group.overview' ? null : (
                  <div className="mx-auto my-2 h-px w-6" style={{ background: 'var(--sidebar-border)' }} />
                )
              ) : group.key === 'nav.group.overview' ? null : (
                <div className="ontogeny-nav-group">{t(group.key)}</div>
              )}
              {group.items.map((item) => {
                const Icon = item.icon
                // the write gate is a governance signal: its queue rides on the
                // module's nav row so a pending write is visible from anywhere
                const count = item.to === '/agent/manage' ? pendingCount : 0
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    data-active={isActive(item.to)}
                    data-testid={`nav-${item.to.replace(/\//g, '') || 'dashboard'}`}
                    title={collapsed ? t(item.key) : undefined}
                    className={collapsed ? 'ontogeny-nav-item justify-center px-0' : 'ontogeny-nav-item'}
                  >
                    <Icon width={15} height={15} />
                    {collapsed ? null : <span className="min-w-0 flex-1">{t(item.key)}</span>}
                    {count && !collapsed ? (
                      <span className="ontogeny-nav-count" data-testid="nav-approvals-count">{count}</span>
                    ) : null}
                  </Link>
                )
              })}
            </div>
          ))}
        </nav>

        {/* The ontology context bar lives at the foot of the rail, not over the
            page: which package the console serves is *navigation* state (it
            changes what every route shows), so it belongs with the nav, and the
            page keeps its full height for the canvas. Draws nothing while the
            deployment has a single domain. */}
        <div className="shrink-0 px-2.5 pb-2">
          <DomainSwitcher collapsed={collapsed} />
        </div>

        {/* app controls live at the foot of the sidebar — one tactile dock:
            search · docs · theme · settings (rail: stacked icons). Language
            and identity live in the settings dialog. */}
        <div className="shrink-0 px-2.5 pb-3">
          {collapsed ? (
            <div className="flex flex-col items-stretch gap-1 pt-2.5">
              <GlobalSearch
                collapsed
                open={searchOpen}
                onOpen={() => setSearchOpen(true)}
                onClose={() => setSearchOpen(false)}
                onExpandRail={() => setSidebar(false)}
              />
              {searchOpen ? null : (
                <>
                  <ThemeToggle className="ontogeny-nav-item flex-1 justify-center px-0" />
                  <button
                    type="button"
                    className="ontogeny-nav-item flex-1 justify-center px-0"
                    data-testid="settings-open"
                    title={t('settings.title')}
                    onClick={() => setSettingsOpen(true)}
                  >
                    <IconCog width={15} height={15} />
                  </button>
                </>
              )}
            </div>
          ) : searchOpen ? (
            <div className="pt-2.5">
              <GlobalSearch
                collapsed={false}
                open
                onOpen={() => setSearchOpen(true)}
                onClose={() => setSearchOpen(false)}
                onExpandRail={() => setSidebar(false)}
              />
            </div>
          ) : (
            <div className="pt-2.5">
              <div className="ontogeny-dock">
                <GlobalSearch
                  collapsed={false}
                  segmented
                  open={false}
                  onOpen={() => setSearchOpen(true)}
                  onClose={() => setSearchOpen(false)}
                  onExpandRail={() => setSidebar(false)}
                />
                <ThemeToggle className="ontogeny-seg-btn flex-1" />
                <button
                  type="button"
                  className="ontogeny-seg-btn flex-1"
                  data-testid="settings-open"
                  title={t('settings.title')}
                  onClick={() => setSettingsOpen(true)}
                >
                  <IconCog width={15} height={15} />
                </button>
              </div>
            </div>
          )}

          <div
            className={(collapsed
              ? 'mt-1.5 text-center text-[9.5px]'
              : 'mt-2 truncate px-1 text-[10px] leading-relaxed')}
            style={{ color: 'var(--sidebar-muted)' }}
            data-testid="sidebar-footer"
            title={meta.error ? t('app.metaUnreadable') : meta.data?.content_hash}
          >
            {collapsed ? 'v0.3' : APP_PROVENANCE}
          </div>
        </div>
      </aside>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* the agent conversation: one dock for the whole console, on every page */}
      <AgentDock />

      <div className="flex min-w-0 flex-1 flex-col">
        {isMobile ? (
          <div className="flex shrink-0 items-center gap-2 px-4 pt-3">
            <button
              onClick={() => setDrawerOpen(true)}
              data-testid="sidebar-open"
              aria-label={t('nav.openMenu')}
              aria-expanded={drawerOpen}
              className="grid size-8 shrink-0 place-items-center rounded-lg"
              style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}
            >
              <IconList width={16} height={16} />
            </button>
            <span className="ontogeny-wordmark truncate text-[13px]" style={{ color: 'var(--text-primary)' }}>
              {t('app.name')}
            </span>
          </div>
        ) : null}
        <main
          id="ontogeny-main"
          // `tabIndex={-1}` lets the skip link's `#ontogeny-main` actually move focus
          // (a fragment jump alone moves the scroll position, not the caret)
          tabIndex={-1}
          data-bleed={bleed}
          className={(bleed
            ? 'min-h-0 flex-1 overflow-hidden focus:outline-none'
            : 'min-h-0 flex-1 overflow-auto focus:outline-none') + ' px-4 py-4 md:px-6 md:py-6'}
        >
          <div className={bleed ? 'ontogeny-animate-in mx-auto h-full max-w-[1400px]' : 'ontogeny-animate-in mx-auto max-w-[1400px]'}>{children}</div>
        </main>
      </div>
    </div>
  )
}
