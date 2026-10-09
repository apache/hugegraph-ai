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
/** Row-level presentation helpers shared by every table, graph and detail page.
 *
 * These used to exist as 2–4 near-identical private copies per concept, and the
 * copies had *diverged*: `pkOf` had two semantics (`_id` allowed vs not, `'id'`
 * vs `'_id'` fallback), so clicking the same node in two panels opened two
 * different detail URLs; `typeColor` had a private fork in the builder that
 * produced different colours for the same type on two pages; dates rendered as
 * `14:03:22` in one place and `2:03:22 PM` in another.
 */
import type { ReactNode } from 'react'
import { Badge } from '../components/ui'

/* ------------------------------------------------------------- identity */

/** The key whose value identifies a row in a URL: `/objects/:type/:value`.
 *
 * A row carries two kinds of key: the store's own `_id` (always present, always
 * prefixed with `_`) and the business primary key declared in the model. The URL
 * must use the business key — that is what a human recognises and what the
 * object API accepts. `primaryKeys` (from the compiled meta, when the caller has
 * it) wins, since it is the model's own statement.
 *
 * BUG FIXED HERE: two of the three copies tested `k.endsWith('_id')` without
 * excluding `_id` — and `'_id'.endsWith('_id')` is true, so on a row where the
 * store key comes first (which is the order the API emits) the "primary key"
 * resolved to the internal id.
 */
export function pkOf(row: Record<string, unknown>, primaryKeys?: readonly string[]): string {
  for (const k of primaryKeys ?? []) if (k in row) return k
  const business = Object.keys(row).find((k) => k.endsWith('_id') && k !== '_id')
  if (business) return business
  if ('id' in row) return 'id'
  return '_id'
}

/* ---------------------------------------------------------------- colour */

/** Per-type colours (stable across modules; unknown types get a palette slot). */
const TYPE_COLORS: Record<string, string> = {
  'sales-order': '#2e5bff', customer: '#0891b2', product: '#7c3aed',
  material: '#059669', bom: '#0d9488', 'production-order': '#4f46e5',
  operation: '#2563eb', 'work-report': '#0284c7', 'quality-inspection': '#dc2626',
  'maintenance-order': '#ea580c', equipment: '#b45309', 'work-center': '#a16207',
  inventory: '#16a34a', 'purchase-order': '#9333ea', supplier: '#be185d',
  part: '#65a30d',
}

/** Fallback palette: distinct, harmonious hues for types outside the map. */
const NODE_PALETTE = [
  '#2e5bff', '#0891b2', '#7c3aed', '#059669', '#2563eb', '#db2777',
  '#c2410c', '#0d9488', '#4f46e5', '#65a30d', '#0284c7', '#a16207',
]

/** Types without an explicit colour get a stable palette slot from a hash of
 *  their name — the same type keeps the same colour everywhere (graph, legend,
 *  detail panel, builder) without maintaining a hard-coded table. */
export const typeColor = (t?: string): string => {
  if (!t) return '#64748b'
  const known = TYPE_COLORS[t]
  if (known) return known
  let h = 0
  for (let i = 0; i < t.length; i += 1) h = (h * 31 + t.charCodeAt(i)) >>> 0
  return NODE_PALETTE[h % NODE_PALETTE.length]
}

/** Hex → rgba() so a surface can be tinted by the type colour. */
export function withAlpha(hex: string, alpha: number): string {
  const raw = hex.replace('#', '')
  const full = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw
  const n = Number.parseInt(full, 16)
  if (Number.isNaN(n)) return hex
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** The three tones a type needs on a canvas: the dot, the card border and the
 *  card header fill. Derived from `typeColor`, so a type is never two colours. */
export function typeTint(name: string): { dot: string; stroke: string; fill: string } {
  const dot = typeColor(name)
  return { dot, stroke: withAlpha(dot, 0.55), fill: withAlpha(dot, 0.07) }
}

/* -------------------------------------------------------------- formatting */

/** One cell value → display node. Shared by every table so a nested object is
 *  truncated the same way everywhere (it used to blow out the column on the
 *  data page and render inline JSON on the object page). */
export function formatCell(v: unknown): ReactNode {
  if (v === null || v === undefined) return <span className="muted">—</span>
  if (v === '__masked__') return <Badge tone="warning" mono title="masked">▒</Badge>
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'object') {
    const json = JSON.stringify(v)
    return <code className="ontogeny-code">{json.length > 72 ? `${json.slice(0, 72)}…` : json}</code>
  }
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return fmtDate(v)
  if (typeof v === 'string' && v.length > 72) return `${v.slice(0, 72)}…`
  return String(v)
}

/** A timestamp the way a Chinese-language UI writes it: 24-hour, no AM/PM.
 *  Explicit locale + `hour12: false` so the same instant never renders as
 *  `14:03:22` on one page and `2:03:22 PM` on another. */
export function fmtDate(iso: string | null | undefined, lang: string = 'zh'): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString(lang === 'zh' ? 'zh-CN' : 'en-GB', { hour12: false })
}

/* ---------------------------------------------------------------- columns */

/** A field's header: the model's human name with the machine name kept beside
 *  it, because a table where 订单号 replaced `so_id` entirely would leave nobody
 *  able to file a bug or read the API. Without a `display:` the machine name
 *  stands alone — which is what every table showed before the meta export
 *  carried `display` at all. */
export function fieldLabel(key: string, display?: string | null, first?: boolean): ReactNode {
  const strong = first ? 'font-semibold' : ''
  if (!display || display === key) return <span className={strong}>{key}</span>
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className={strong}>{display}</span>
      <span className="font-mono text-[10px] font-normal tracking-normal opacity-70">{key}</span>
    </span>
  )
}

/** Preview columns for a row sample: the row's own fields, internal bookkeeping
 *  trimmed, the primary key first.
 *
 * `labels` maps a field to its human name from the model (`display:`), so the
 * header reads 订单号 instead of `so_id`. Without it the table can only show the
 * machine name, which is the one thing business users cannot read.
 *
 * No `render` is emitted: the DataTable's own cell formatter (`formatCell`) is
 * the app-wide cell contract — masked sentinels become the ▒ badge, timestamps
 * become local dates, JSON and long strings are truncated. This helper used to
 * ship a private render that stringified everything, which is how the data
 * preview ended up showing raw `__masked__` and `2026-11-15T00:00:00+00:00`
 * while the object browser showed the formatted forms. */
export function columnsOf<T extends Record<string, unknown>>(
  rows: T[],
  first?: string,
  labels?: Record<string, string | null | undefined>,
): Array<{
  key: string
  label: ReactNode
}> {
  const keys = new Set<string>()
  for (const row of rows) for (const key of Object.keys(row)) if (!key.startsWith('_')) keys.add(key)
  const names = Array.from(keys)
  const ordered = first && keys.has(first) ? [first, ...names.filter((k) => k !== first)] : names
  return ordered.slice(0, 8).map((key) => ({
    key,
    label: fieldLabel(key, labels?.[key], key === first),
  }))
}
