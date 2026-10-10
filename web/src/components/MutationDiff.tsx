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
import type { Mutation } from '../api/types'
import { Badge, toneSurface } from './ui'
import { useI18n } from '../i18n'

/** Renders a proposal's mutation list: additions in green, domain widening in blue. */
export function MutationDiff({ mutations }: { mutations: Mutation[] }) {
  const { t } = useI18n()
  if (!mutations?.length) return <p className="text-[12.5px] muted">{t('common.empty')}</p>
  return (
    <div className="flex flex-col gap-2" data-testid="mutation-diff">
      {mutations.map((m, i) => {
        const kind = m.mutation
        if (kind === 'add-optional-property') {
          return (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg px-3 py-2.5 font-mono text-[12px]" style={toneSurface('success')}>
              <Badge tone="success">+ property</Badge>
              <span className="font-semibold">{String(m.object)}.{String(m.prop)}</span>
              <span className="muted">: {String(m.type ?? 'string')}</span>
              <Badge tone="neutral">optional</Badge>
            </div>
          )
        }
        if (kind === 'enum-widen') {
          return (
            <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg px-3 py-2.5 font-mono text-[12px]" style={toneSurface('info')}>
              <Badge tone="info">~ enum</Badge>
              <span className="font-semibold">{String(m.object)}.{String(m.prop)}</span>
              <span className="muted">+=</span>
              <Badge tone="info">{String(m.value)}</Badge>
            </div>
          )
        }
        return (
          <div key={i} className="rounded-lg px-3 py-2.5 font-mono text-[12px]" style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}>
            {JSON.stringify(m, null, 2)}
          </div>
        )
      })}
    </div>
  )
}
