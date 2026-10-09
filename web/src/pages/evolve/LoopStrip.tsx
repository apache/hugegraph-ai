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
import { useI18n } from '../../i18n'

/** The six beats of the self-improvement loop, rendered as one slim strip.
 *  Shared between the dashboard's RSI hero and the evolve console, where it
 *  gives the page a spine and doubles as the legend for what ①/② kick off. */
const LOOP_BEATS = ['evolve.loop.1', 'evolve.loop.2', 'evolve.loop.3', 'evolve.loop.4', 'evolve.loop.5', 'evolve.loop.6'] as const

export function LoopStrip({ className }: { className?: string }) {
  const { t } = useI18n()
  return (
    <div
      className={['flex flex-wrap items-center gap-x-1 gap-y-1.5 rounded-xl px-3.5 py-2', className].filter(Boolean).join(' ')}
      style={{
        background: 'linear-gradient(90deg, var(--tone-brand-bg) 0%, transparent 65%)',
        border: '1px solid var(--border-subtle)',
      }}
      data-testid="evolve-loop-strip"
    >
      {LOOP_BEATS.map((key, i) => (
        <span key={key} className="flex items-center gap-1">
          {i > 0 ? <span className="px-0.5 text-[11px] muted">›</span> : null}
          <span className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11.5px] font-medium" style={{ background: 'var(--surface-card)' }}>
            <span className="grid size-4 place-items-center rounded-md font-mono text-[9.5px] font-bold" style={{ background: 'var(--tone-brand-bg)', color: 'var(--tone-brand-fg)' }}>{i + 1}</span>
            {t(key)}
          </span>
        </span>
      ))}
    </div>
  )
}
