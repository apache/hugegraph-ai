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
import { useI18n } from '../i18n'
import { Badge } from './ui'
import { fmtDate } from '../lib/rows'

/** Vertical version timeline for one object (system-versioned history). */
export function Timeline({ versions }: { versions: Array<Record<string, unknown>> }) {
  const { t, lang } = useI18n()
  if (!versions.length) return <p className="text-[12.5px] muted">{t('common.empty')}</p>
  const ordered = [...versions].reverse()

  return (
    <ol className="relative ml-1.5 flex flex-col gap-4" data-testid="timeline" style={{ borderLeft: '1px solid var(--border-subtle)' }}>
      {ordered.map((v, i) => {
        const previous = ordered[i + 1]
        return (
          <li key={i} className="ml-4">
            <span
              className="absolute -left-[6.5px] mt-1.5 size-3 rounded-full"
              style={{
                background: i === 0 ? 'var(--color-brand-500)' : 'var(--border-strong)',
                boxShadow: '0 0 0 3px var(--surface-card)',
              }}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="ontogeny-code">_rev {String(v._rev)}</span>
              {i === 0 ? <Badge tone="success">{t('object.timeline.current')}</Badge> : null}
              <span className="muted text-[11.5px]">
                {v._valid_to
                  ? `${fmtDate(String(v._valid_from), lang)} → ${fmtDate(String(v._valid_to), lang)}`
                  : fmtDate(String(v._valid_from), lang)}
              </span>
            </div>
            <div className="mt-1 text-[12px] secondary-text">
              {previous ? diff(previous, v, t) : t('object.timeline.initial')}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/** Field-level delta between two revisions. The two strings it needs used to be
 *  written as inline `lang === 'zh' ? … : …` ternaries, which bypasses the
 *  dictionary entirely and so was invisible to any key-coverage check. */
function diff(
  previous: Record<string, unknown>,
  current: Record<string, unknown>,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  const changes: string[] = []
  for (const key of Object.keys(current)) {
    if (key.startsWith('_')) continue
    const a = JSON.stringify(previous[key] ?? null)
    const b = JSON.stringify(current[key] ?? null)
    if (a !== b) changes.push(`${key}: ${short(previous[key], t)} → ${short(current[key], t)}`)
  }
  return changes.length ? changes.join(' · ') : t('timeline.noChange')
}

function short(v: unknown, t: (key: string) => string): string {
  if (v === null || v === undefined) return t('timeline.emptyValue')
  const s = String(v)
  return s.length > 22 ? `${s.slice(0, 22)}…` : s
}
