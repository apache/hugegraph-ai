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
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useFocusTrap } from '../../lib/focus'
import { IconWarning } from '../icons'

/* ------------------------------------------------------------------ Button */

type ButtonVariant = 'primary' | 'ghost' | 'subtle' | 'danger'

export function Button({
  children,
  variant = 'ghost',
  size,
  icon,
  /** Icon-only: squares the button off. The label then lives in `title` +
   *  `aria-label`, which every call site must supply — a button whose only
   *  content is a glyph is unreadable to a screen reader otherwise. */
  square = false,
  ...rest
}: {
  children?: ReactNode
  variant?: ButtonVariant
  size?: 'sm' | 'lg'
  icon?: ReactNode
  square?: boolean
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = [
    `ontogeny-btn-${variant}`,
    size ? `ontogeny-btn-${size}` : '',
    square ? (size === 'sm' ? 'ontogeny-icon-btn-sm' : 'ontogeny-icon-btn') : '',
  ].filter(Boolean).join(' ')
  return (
    <button {...rest} className={[cls, rest.className].filter(Boolean).join(' ')}>
      {icon}
      {children}
    </button>
  )
}

/* -------------------------------------------------------------------- Card */

export function Card({
  title, description, actions, toolbar, children, padded = true, className, bodyClassName, testId, bare = false,
}: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  /** Control row that belongs to this surface (filters, palette, view
   *  switches). It lives *inside* the card, separated by a hairline, so a page
   *  reads as one panel instead of a floating toolbar stacked on a box. */
  toolbar?: ReactNode
  children?: ReactNode
  padded?: boolean
  className?: string
  /** Extra classes for the body wrapper — e.g. `flex min-h-0 flex-1 flex-col`
   *  so a canvas inside can fill the card instead of falling back to a fixed
   *  height. */
  bodyClassName?: string
  testId?: string
  /** Draw behind an existing surface: no card frame of its own (used by the
   *  agent dock, whose dialog already draws the one frame). */
  bare?: boolean
}) {
  const hasHeader = Boolean(title || description || actions)
  const hairline = '1px solid var(--border-subtle)'
  return (
    <section
      className={[bare ? '' : 'ontogeny-card overflow-hidden', className].filter(Boolean).join(' ')}
      data-testid={testId}
    >
      {hasHeader && (
        <header className="flex shrink-0 flex-wrap items-start justify-between gap-x-4 gap-y-2 px-5 pt-4 pb-3">
          <div className="min-w-0">
            {title ? <h2 className="text-[13px] font-semibold tracking-wide">{title}</h2> : null}
            {description ? <p className="mt-0.5 text-[12.5px] muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      )}
      {toolbar ? (
        <div
          className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-5 py-2.5"
          style={{
            borderTop: hasHeader ? hairline : undefined,
            borderBottom: hairline,
            background: 'var(--surface-sunken)',
          }}
        >
          {toolbar}
        </div>
      ) : null}
      <div className={[padded ? 'px-5 pb-5' : '', padded && !hasHeader && !toolbar ? 'pt-5' : '', bodyClassName].filter(Boolean).join(' ')}>
        {children}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------- Badge */

const BADGE_TONES: Record<string, { bg: string; fg: string; ring: string }> = {
  neutral: { bg: 'var(--tone-neutral-bg)', fg: 'var(--tone-neutral-fg)', ring: 'var(--tone-neutral-ring)' },
  brand: { bg: 'var(--tone-brand-bg)', fg: 'var(--tone-brand-fg)', ring: 'var(--tone-brand-ring)' },
  success: { bg: 'var(--tone-success-bg)', fg: 'var(--tone-success-fg)', ring: 'var(--tone-success-ring)' },
  warning: { bg: 'var(--tone-warning-bg)', fg: 'var(--tone-warning-fg)', ring: 'var(--tone-warning-ring)' },
  danger: { bg: 'var(--tone-danger-bg)', fg: 'var(--tone-danger-fg)', ring: 'var(--tone-danger-ring)' },
  info: { bg: 'var(--tone-info-bg)', fg: 'var(--tone-info-fg)', ring: 'var(--tone-info-ring)' },
  violet: { bg: 'var(--tone-violet-bg)', fg: 'var(--tone-violet-fg)', ring: 'var(--tone-violet-ring)' },
}

export type BadgeTone = keyof typeof BADGE_TONES

export function Badge({
  children, tone = 'neutral', mono, title,
}: {
  children: ReactNode
  tone?: BadgeTone
  mono?: boolean
  title?: string
}) {
  const t = BADGE_TONES[tone] ?? BADGE_TONES.neutral
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-[2px] text-[11px] font-medium ${mono ? 'font-mono' : ''}`}
      style={{ background: t.bg, color: t.fg, boxShadow: `inset 0 0 0 1px ${t.ring}` }}
    >
      {children}
    </span>
  )
}

/** Maps engine states/outcomes to a consistent tone across all pages. */
export function toneForStatus(value: string | null | undefined): BadgeTone {
  if (!value) return 'neutral'
  const v = value.toLowerCase()
  if (['executed', 'promoted', 'ok', 'pass', 'approved', 'running', 'completed', 'closed', 'available', 'shipped'].includes(v)) return 'success'
  if (['proposed', 'evaluated', 'pending', 'planned', 'draft', 'open', 'idle'].includes(v)) return 'info'
  if (['awaiting_human', 'in_progress', 'busy', 'swing', 'normal'].includes(v)) return 'warning'
  if (['rejected', 'rejected_rule', 'denied_policy', 'error', 'fail', 'cancelled', 'down', 'urgent', 'maintenance'].includes(v)) return 'danger'
  if (['t0-auto-merge', 't0_auto_merge', 'released', 'high'].includes(v)) return 'violet'
  if (['t1-pr', 't2-canary', 'low'].includes(v)) return 'brand'
  if (['t3-human-only'].includes(v)) return 'danger'
  return 'neutral'
}

/* --------------------------------------------------------------- Sparkline */

function Sparkline({
  data, width = 72, height = 22, className, tone = 'var(--color-brand-500)',
}: {
  data: number[]
  width?: number
  height?: number
  className?: string
  tone?: string
}) {
  if (data.length < 2) return null
  const max = Math.max(...data)
  const min = Math.min(...data)
  const span = max - min || 1
  const step = width / (data.length - 1)
  const points = data.map((v, i) => `${i * step},${height - ((v - min) / span) * height}`).join(' ')
  return (
    <svg width={width} height={height} className={className} aria-hidden="true">
      <polyline points={points} fill="none" stroke={tone} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

/* --------------------------------------------------------------- Page shell */

/** Every page's root. One source of truth for the vertical rhythm between a
 *  header, its metric strips, toolbars and cards — pages used to pick their own
 *  gap-3/gap-4/gap-5 or forget a wrapper entirely, which is what made the app
 *  feel assembled from different products.
 *
 *  `fill` is for canvas pages (ontology, graph, builder): they own the whole
 *  viewport and need a bounded height for their canvas to fill. */
export function Page({
  children, fill = false, className, testId,
}: {
  children: ReactNode
  fill?: boolean
  className?: string
  testId?: string
}) {
  return (
    <div
      className={['flex flex-col gap-5', fill ? 'h-full min-h-0' : '', className].filter(Boolean).join(' ')}
      data-testid={testId}
    >
      {children}
    </div>
  )
}

/* --------------------------------------------------------------- Tone tokens */

/** Tone palettes. `BADGE_TONES` and `TONES` are the same table: components ask
 *  for a semantic tone (`success`, `warning`…) and never hand-pick a hex, so
 *  light/dark and future re-themes stay in one place. */
export const TONES = BADGE_TONES

/** Tinted *panel* style for a tone (status callouts, awaiting-approval blocks,
 *  scope bars). Keeps call sites free of rgba() literals. */
export function toneSurface(tone: BadgeTone = 'neutral'): React.CSSProperties {
  const t = TONES[tone] ?? TONES.neutral
  return { background: t.bg, border: `1px solid ${t.ring}`, color: t.fg }
}

/* ---------------------------------------------------------------- Stat */

/** A metric cell. Never rendered on its own — `StatBar` packs several into one
 *  surface so a status strip is a single panel instead of four little cards. */
function Stat({
  label, value, hint, tone, icon, trend, size = 'md',
}: {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  tone?: BadgeTone
  icon?: ReactNode
  trend?: number[]
  size?: 'md' | 'sm'
}) {
  const toneVar = tone === 'danger' ? 'var(--tone-danger-fg)'
    : tone === 'success' ? 'var(--tone-success-fg)'
    : tone === 'warning' ? 'var(--tone-warning-fg)'
    : tone === 'violet' ? 'var(--tone-violet-fg)'
    : tone === 'brand' ? 'var(--tone-brand-fg)' : undefined
  return (
    <div className={['flex min-w-0 items-center gap-3', size === 'sm' ? 'px-4 py-3' : 'px-5 py-4'].join(' ')}>
      {icon ? <span className="shrink-0 muted" aria-hidden="true">{icon}</span> : null}
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11px] font-medium uppercase tracking-wide muted">{label}</div>
        <div
          className={['font-mono tabular-nums', size === 'sm' ? 'text-[15px]' : 'text-[18px] font-semibold'].join(' ')}
          style={toneVar ? { color: toneVar } : undefined}
        >
          {value}
        </div>
        {hint ? <div className="mt-0.5 truncate text-[11.5px] muted">{hint}</div> : null}
      </div>
      {trend && trend.length > 1 ? (
        <Sparkline data={trend} className="shrink-0" tone={toneVar ?? 'var(--color-brand-500)'} />
      ) : null}
    </div>
  )
}

/** Metrics for a whole region as ONE surface. Cells are separated by hairlines
 *  and the grid wraps on its own, so the outer edge never shows a seam (the
 *  -1px offset is clipped by the card's overflow). */
export function StatBar({
  items, size = 'md', className,
}: {
  items: Array<{
    label: ReactNode
    value: ReactNode
    hint?: ReactNode
    tone?: BadgeTone
    icon?: ReactNode
    trend?: number[]
  }>
  size?: 'md' | 'sm'
  className?: string
}) {
  const hairline = '1px solid var(--border-subtle)'
  return (
    <div className={['ontogeny-card overflow-hidden', className].filter(Boolean).join(' ')}>
      <div
        className="grid"
        style={{
          gridTemplateColumns: 'repeat(auto-fit, minmax(188px, 1fr))',
          margin: '-1px 0 0 -1px',
        }}
      >
        {items.map((it, i) => (
          <div key={i} style={{ borderTop: hairline, borderLeft: hairline }}>
            <Stat {...it} size={size} />
          </div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ Strip */

/** A tinted, borderless band for grouping a few related values inside a
 *  surface. Used instead of a nested bordered box so panels stay flat. */
export function Strip({
  children, label, className, testId,
}: {
  children: ReactNode
  label?: ReactNode
  className?: string
  testId?: string
}) {
  return (
    <div
      className={['flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg px-3.5 py-2.5', className].filter(Boolean).join(' ')}
      style={{ background: 'var(--surface-sunken)' }}
      data-testid={testId}
    >
      {label ? (
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.07em] muted">{label}</span>
      ) : null}
      {children}
    </div>
  )
}

/** Divided row of small specs (caps, limits): one tinted band, hairline
 *  separators, no inner boxes. */
export function SpecRow({
  items, className,
}: {
  items: Array<{ label: ReactNode; value: ReactNode }>
  className?: string
}) {
  const hairline = '1px solid var(--border-subtle)'
  return (
    <div
      className={['grid overflow-hidden rounded-lg', className].filter(Boolean).join(' ')}
      style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`, background: 'var(--surface-sunken)' }}
    >
      {items.map((it, i) => (
        <div key={i} className="px-3 py-2 text-center" style={i ? { borderLeft: hairline } : undefined}>
          <div className="truncate text-[10px] font-semibold uppercase tracking-[0.06em] muted">{it.label}</div>
          <div className="mt-0.5 truncate font-mono text-[13px] font-semibold tnum">{it.value}</div>
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ Split */

/** Regions that belong to one surface, separated by a hairline instead of each
 *  getting its own card. Use inside a `padded={false}` Card. */
export function Split({
  children, cols = 'lg:grid-cols-2', className,
}: {
  children: ReactNode
  cols?: string
  className?: string
}) {
  return <div className={['grid', cols, className].filter(Boolean).join(' ')}>{children}</div>
}

/** One region of a `Split`: hairline on top when stacked, on the left when the
 *  columns sit side by side. */

/* ------------------------------------------------------------- ProgressBar */

export function ProgressBar({ value, max = 100, tone = 'var(--color-brand-500)', label }: {
  value: number
  max?: number
  tone?: string
  label?: ReactNode
}) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100))
  return (
    <div>
      {label ? <div className="mb-1 flex justify-between text-[11.5px] muted">{label}</div> : null}
      <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'var(--surface-sunken)' }}>
        <div className="h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, background: tone }} />
      </div>
    </div>
  )
}

/* -------------------------------------------------------------- EmptyState */

/** The one empty state. Three placements, one look:
 *  - default  → sits in a card body (dashed outline, generous padding);
 *  - `compact`→ sits in a table cell or a narrow column;
 *  - `floating`→ overlays a canvas, so it needs a solid surface and a float
 *    shadow instead of a dashed outline. */
export function EmptyState({
  title, description, action, icon, compact = false, floating = false, bare = false,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  icon?: ReactNode
  compact?: boolean
  /** Overlays a canvas: needs its own surface and a float shadow. */
  floating?: boolean
  /** Sits inside a panel that already draws the frame — draws nothing itself,
   *  so a card never contains a second dashed box. */
  bare?: boolean
}) {
  return (
    <div
      className={[
        'flex flex-col items-center justify-center gap-2 text-center',
        bare ? '' : 'rounded-xl',
        compact ? 'px-4 py-6' : bare ? 'px-4 py-8' : 'px-6 py-10',
        floating || bare ? '' : 'border border-dashed',
      ].join(' ')}
      style={{
        background: floating ? 'var(--surface-card)' : 'transparent',
        borderColor: floating || bare ? undefined : 'var(--border-strong)',
        boxShadow: floating ? 'var(--shadow-float)' : undefined,
      }}
    >
      {icon ? (
        <div
          className={['mb-1 grid place-items-center rounded-xl', compact ? 'size-9' : 'size-10'].join(' ')}
          style={{ background: 'var(--surface-sunken)', color: 'var(--text-muted)' }}
        >
          {icon}
        </div>
      ) : null}
      <div className={compact ? 'text-[12.5px] font-medium' : 'text-[13.5px] font-medium'}>{title}</div>
      {description ? (
        <div className={['max-w-md muted', compact ? 'text-[11.5px]' : 'text-[12.5px]'].join(' ')}>{description}</div>
      ) : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  )
}

/* ---------------------------------------------------------------- Skeleton */

export function Skeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={['space-y-2', className].filter(Boolean).join(' ')} data-testid="skeleton">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="ontogeny-skeleton h-9" style={{ width: `${100 - i * 6}%` }} />
      ))}
    </div>
  )
}

/* --------------------------------------------------------------- CodeBlock */

export function CodeBlock({ code, language, maxHeight = 320 }: { code: string; language?: string; maxHeight?: number }) {
  const html = highlight(code)
  return (
    <div className="relative overflow-hidden rounded-lg" style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}>
      {language ? (
        <div className="flex items-center justify-between px-3 py-1.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] muted" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          {language}
        </div>
      ) : null}
      <pre
        className="overflow-auto px-3.5 py-3 font-mono text-[12px] leading-[1.65]"
        style={{ maxHeight }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  )
}

/** Minimal, dependency-free JSON/YAML highlighter (escapes first, then colours). */
function highlight(code: string): string {
  const escaped = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // tone tokens, so the JSON/YAML colours follow the theme too (they sit on
  // --surface-sunken, which is dark in the dark theme)
  return escaped
    .replace(/(&quot;|")([^"\\]|\\.)*?\1(?=\s*:)/g, (m) => `<span style="color:var(--tone-violet-fg)">${m}</span>`)
    .replace(/:\s(&quot;|")([^"\\]|\\.)*?\1/g, (m) => `:<span style="color:var(--tone-success-fg)">${m.slice(1)}</span>`)
    .replace(/\b(true|false|null)\b/g, '<span style="color:var(--tone-warning-fg)">$1</span>')
    .replace(/(?<![\w"])(-?\d+(\.\d+)?)(?![\w"])/g, '<span style="color:var(--tone-info-fg)">$1</span>')
}

/* --------------------------------------------------------------------- Tabs */

export function Tabs<T extends string>({
  tabs, value, onChange,
}: {
  tabs: Array<{ id: T; label: ReactNode; count?: number; icon?: ReactNode; badge?: ReactNode; hint?: string }>
  value: T
  onChange: (id: T) => void
}) {
  return (
    <div
      className="flex gap-1 overflow-x-auto rounded-xl p-1"
      role="tablist"
      style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
    >
      {tabs.map((tab) => {
        const active = tab.id === value
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active}
            data-testid={`tab-${tab.id}`}
            title={tab.hint}
            onClick={() => onChange(tab.id)}
            className="relative flex shrink-0 items-center gap-2 whitespace-nowrap rounded-lg px-3.5 py-2 text-[13px] transition-colors"
            style={{
              background: active ? 'var(--surface-card)' : 'transparent',
              color: active ? 'var(--text-primary)' : 'var(--text-muted)',
              fontWeight: active ? 600 : 500,
              boxShadow: active ? 'var(--shadow-card)' : 'none',
            }}
          >
            {tab.icon ? (
              <span style={{ color: active ? 'var(--brand-fg)' : 'var(--text-muted)' }}>{tab.icon}</span>
            ) : null}
            {tab.label}
            {tab.count !== undefined ? (
              <span
                className="rounded-full px-1.5 py-px font-mono text-[10.5px] font-semibold tnum"
                style={{
                  background: active ? 'var(--brand-tint)' : 'var(--surface-card)',
                  color: active ? 'var(--brand-fg)' : 'var(--text-muted)',
                }}
              >
                {tab.count}
              </span>
            ) : null}
            {tab.badge}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------- Alert */

const ALERT_TONES = {
  info: { bg: 'var(--tone-info-bg)', border: 'var(--tone-info-ring)', fg: 'var(--tone-info-fg)' },
  success: { bg: 'var(--tone-success-bg)', border: 'var(--tone-success-ring)', fg: 'var(--tone-success-fg)' },
  warning: { bg: 'var(--tone-warning-bg)', border: 'var(--tone-warning-ring)', fg: 'var(--tone-warning-fg)' },
  danger: { bg: 'var(--tone-danger-bg)', border: 'var(--tone-danger-ring)', fg: 'var(--tone-danger-fg)' },
  brand: { bg: 'var(--tone-brand-bg)', border: 'var(--tone-brand-ring)', fg: 'var(--tone-brand-fg)' },
}

export function Alert({ tone = 'info', title, children, action, testId = 'alert' }: {
  tone?: keyof typeof ALERT_TONES
  title?: ReactNode
  children?: ReactNode
  action?: ReactNode
  /** Several alerts can coexist on a page; tests target a specific one. */
  testId?: string
}) {
  const t = ALERT_TONES[tone]
  return (
    <div
      className="flex items-start gap-3 rounded-lg px-3.5 py-3 text-[12.5px]"
      style={{ background: t.bg, border: `1px solid ${t.border}` }}
      data-testid={testId}
    >
      <span className="mt-[3px] size-1.5 shrink-0 rounded-full" style={{ background: t.fg }} />
      <div className="min-w-0 flex-1">
        {title ? <div className="font-semibold" style={{ color: t.fg }}>{title}</div> : null}
        {children ? <div className="mt-0.5 secondary-text">{children}</div> : null}
      </div>
      {action}
    </div>
  )
}

/* ------------------------------------------------------------------ Mapper */

/** Renders a definition list of key/value pairs (object detail, config views). */
export function KeyValue({ items, labelWidth = 'w-44' }: {
  items: Array<{ key: ReactNode; value: ReactNode; mono?: boolean }>
  /** Every field list shares one label column; only a dense drawer narrows it. */
  labelWidth?: 'w-44' | 'w-32'
}) {
  return (
    <dl className="min-w-0 divide-subtle">
      {items.map((item, i) => (
        <div key={i} className="flex min-w-0 items-start gap-4 py-2" style={{ borderColor: 'var(--border-subtle)' }}>
          <dt className={`${labelWidth} shrink-0 text-[12.5px] muted`}>{item.key}</dt>
          {/* break-all keeps long mono tokens (hashes, JSON, URLs) inside the
              container instead of stretching the page horizontally */}
          <dd className={`min-w-0 flex-1 text-[13px] ${item.mono ? 'break-all font-mono text-[12px]' : 'break-words'}`}>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/* ------------------------------------------------------------------- Panel */

/** A surface that is *not* a card: an overlay (search results, popovers), a
 *  element floating over a canvas, or a tile inside a larger panel.
 *
 * `Card` is for a page's content blocks — it owns a header, a toolbar and
 * padding. These surfaces want the same background/border/radius without any of
 * that, and the triple used to be spelled out by hand in a dozen places, which
 * is how some landed on `--shadow-card` and others on `--shadow-float` with no
 * reason behind the split. */
export function Panel({
  children, className, style, floating = false, testId, role, ariaLabel,
}: {
  children?: ReactNode
  className?: string
  style?: React.CSSProperties
  /** Floating over content (canvas, page): stronger shadow. */
  floating?: boolean
  testId?: string
  role?: string
  ariaLabel?: string
}) {
  return (
    <div
      className={['ontogeny-card overflow-hidden', className].filter(Boolean).join(' ')}
      style={{ boxShadow: floating ? 'var(--shadow-float)' : 'var(--shadow-card)', ...style }}
      data-testid={testId}
      role={role}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  )
}

/* ------------------------------------------------------------- MenuButton */

/** One entry in a `MenuButton`'s dropdown. */
export interface MenuItem {
  id: string
  label: string
  icon?: ReactNode
  /** Optional one-line explanation, shown under the label. */
  hint?: string
  onSelect: () => void
  disabled?: boolean
}

/** An icon-only button that opens a menu of labelled actions.
 *
 * The design rule this exists for: a toolbar shows *glyphs*, and the words
 * appear when you go looking for them. Five "New …" buttons with five words
 * each is a paragraph where one `+` will do — but a `+` with no menu is a
 * riddle, so the menu is where the labels live, next to an icon each.
 *
 * Closes on Escape, on an outside click, and on selection; the trigger carries
 * `title` + `aria-label` so the glyph is never the only name for it. */
export function MenuButton({
  items, label, icon, testId, menuTestId, align = 'left', direction = 'down', variant = 'ghost', size = 'sm',
}: {
  items: MenuItem[]
  /** Name of the trigger, for the tooltip and assistive tech. */
  label: string
  icon: ReactNode
  testId?: string
  menuTestId?: string
  align?: 'left' | 'right'
  /** `up` when the trigger sits near the bottom of its container. */
  direction?: 'down' | 'up'
  variant?: ButtonVariant
  size?: 'sm' | 'lg'
}) {
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

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

  return (
    <div className="relative" ref={boxRef}>
      <Button
        variant={variant}
        size={size}
        square
        data-testid={testId}
        aria-haspopup="menu"
        aria-expanded={open}
        title={label}
        aria-label={label}
        onClick={() => setOpen((o) => !o)}
        icon={icon}
      />
      {open ? (
        <Panel
          role="menu"
          ariaLabel={label}
          floating
          testId={menuTestId}
          className={[
            'absolute z-50 min-w-[218px] py-1',
            align === 'right' ? 'right-0' : 'left-0',
            direction === 'up' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          ].join(' ')}
          style={{ background: 'var(--surface-card)' }}
        >
          {items.map((it) => (
            <button
              key={it.id}
              type="button"
              role="menuitem"
              data-testid={it.id}
              disabled={it.disabled}
              onClick={() => { setOpen(false); it.onSelect() }}
              className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-[var(--surface-hover)] disabled:opacity-45"
            >
              {it.icon ? (
                <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md" style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}>
                  {it.icon}
                </span>
              ) : null}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12.5px] font-medium">{it.label}</span>
                {it.hint ? <span className="mt-0.5 block text-[11px] leading-snug muted">{it.hint}</span> : null}
              </span>
            </button>
          ))}
        </Panel>
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ ConfirmDialog */

/** A confirmation step for a destructive action.
 *
 * The repository had *no* `confirm()` calls and no replacement UI: the canvas's
 * "clear" and all four editors' "delete" took effect on a single click, and
 * deleting an object type also dropped its properties (leaving any link that
 * referenced them dangling). For an action that destroys unpublished work, one
 * click is not enough.
 *
 * Rendered as a modal dialog so it cannot be missed, with the same focus
 * contract as the node drawer (focus moves in, Tab stays in, focus returns). */
export function ConfirmDialog({
  open, title, message, confirmLabel, cancelLabel, onConfirm, onCancel, tone = 'danger',
}: {
  open: boolean
  title: ReactNode
  message?: ReactNode
  confirmLabel: ReactNode
  cancelLabel: ReactNode
  onConfirm: () => void
  onCancel: () => void
  tone?: 'danger' | 'warning'
}) {
  const ref = useFocusTrap<HTMLDivElement>(open)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  // portal to <body>: pages wrap content in a transform-animated container,
  // which would otherwise become the containing block for this `fixed` overlay
  // and clip it to the content column
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.45)' }}>
      <div
        ref={ref}
        role="alertdialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        data-testid="confirm-dialog"
        className="ontogeny-card ontogeny-modal w-full max-w-md p-5"
      >
        <div className="flex items-start gap-3">
          <span
            className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg"
            style={{ background: tone === 'danger' ? 'var(--tone-danger-bg)' : 'var(--tone-warning-bg)', color: tone === 'danger' ? 'var(--tone-danger-fg)' : 'var(--tone-warning-fg)' }}
          >
            <IconWarning width={16} height={16} />
          </span>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{title}</h2>
            {message ? <div className="mt-1 text-[12.5px] secondary-text">{message}</div> : null}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button data-testid="confirm-cancel" onClick={onCancel}>{cancelLabel}</Button>
          <Button
            variant={tone === 'danger' ? 'danger' : 'primary'}
            data-testid="confirm-accept"
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* --------------------------------------------------------------- LiveRegion */

/** Polite announcer for a result that appears without a navigation.
 *
 * Nothing in the app had `aria-live` at all: a validation verdict, a query
 * result or a save outcome appeared silently, so a screen-reader user had to go
 * hunting for it. Wrap the *status text* (not the whole panel) so the
 * announcement is one sentence rather than a re-read of the page. */
export function LiveRegion({ children, className, testId = 'live-region' }: {
  children: ReactNode
  className?: string
  testId?: string
}) {
  return (
    <div role="status" aria-live="polite" aria-atomic="true" className={className} data-testid={testId}>
      {children}
    </div>
  )
}
