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
import { useMemo, useState } from 'react'
import type { ParamMeta } from '../api/types'
import { useI18n } from '../i18n'
import { Badge } from './ui'

function parseEnum(type: string): string[] | null {
  const m = /^enum\[(.*)\]$/.exec(type.trim())
  if (!m) return null
  return m[1].split(',').map((s) => s.trim()).filter(Boolean)
}

export interface ParamValues {
  [name: string]: unknown
}

/** Parameter form generated from the action/function schema in the ontology. */
export function ParamForm({
  parameters, value, onChange,
}: {
  parameters: Record<string, ParamMeta>
  value: ParamValues
  onChange: (next: ParamValues) => void
}) {
  const { t } = useI18n()
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const entries = useMemo(() => Object.entries(parameters), [parameters])

  const missing = entries
    .filter(([name, p]) => p.required && (value[name] === undefined || value[name] === null || value[name] === ''))
    .map(([name]) => name)

  if (entries.length === 0) return <p className="text-[12.5px] muted">{t('action.noParams')}</p>

  return (
    <div className="flex flex-col gap-3.5" data-testid="param-form">
      {entries.map(([name, p]) => {
        const options = parseEnum(p.type)
        const kind = options ? 'enum' : p.type
        const invalid = touched[name] && p.required && (value[name] === undefined || value[name] === null || value[name] === '')
        return (
          <div key={name}>
            <label className="ontogeny-label flex items-center gap-2" htmlFor={`param-${name}`}>
              <span>{name}</span>
              {p.required ? <span style={{ color: 'var(--tone-danger-fg)' }}>*</span> : null}
              <Badge tone="neutral" mono>{p.type}</Badge>
              {p.required ? <Badge tone="danger">{t('action.required')}</Badge> : <Badge>{t('action.optional')}</Badge>}
            </label>
            {kind === 'enum' ? (
              <select
                id={`param-${name}`}
                className="ontogeny-input"
                data-testid={`param-${name}`}
                value={(value[name] as string) ?? ''}
                onBlur={() => setTouched((s) => ({ ...s, [name]: true }))}
                onChange={(e) => onChange({ ...value, [name]: e.target.value })}
              >
                <option value="">—</option>
                {(options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : kind === 'boolean' ? (
              <input
                id={`param-${name}`}
                type="checkbox"
                className="size-4"
                data-testid={`param-${name}`}
                checked={Boolean(value[name])}
                onChange={(e) => onChange({ ...value, [name]: e.target.checked })}
              />
            ) : kind === 'integer' || kind.startsWith('decimal') ? (
              <input
                id={`param-${name}`}
                type="number"
                step={kind === 'integer' ? 1 : 'any'}
                className="ontogeny-input"
                data-testid={`param-${name}`}
                style={invalid ? { borderColor: 'var(--tone-danger-fg)' } : undefined}
                value={(value[name] as number | undefined) ?? ''}
                onBlur={() => setTouched((s) => ({ ...s, [name]: true }))}
                onChange={(e) => onChange({ ...value, [name]: e.target.value === '' ? undefined : Number(e.target.value) })}
              />
            ) : (
              <input
                id={`param-${name}`}
                type="text"
                className="ontogeny-input"
                data-testid={`param-${name}`}
                style={invalid ? { borderColor: 'var(--tone-danger-fg)' } : undefined}
                value={(value[name] as string | undefined) ?? ''}
                onBlur={() => setTouched((s) => ({ ...s, [name]: true }))}
                onChange={(e) => onChange({ ...value, [name]: e.target.value })}
              />
            )}
            {invalid ? <p className="mt-1 text-[11.5px]" style={{ color: 'var(--tone-danger-fg)' }}>{t('action.required')}</p> : null}
          </div>
        )
      })}
      {missing.length ? (
        <p className="text-[12px]" style={{ color: '#b45309' }} data-testid="param-missing">
          {t('action.missing', { fields: missing.join(', ') })}
        </p>
      ) : null}
    </div>
  )
}
