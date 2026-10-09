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
import { useEffect, useState } from 'react'
import { useI18n } from '../i18n'
import { Button } from './ui'
import { IconPlus, IconX } from './icons'

export interface Condition {
  id: number
  field: string
  op: string
  value: string
}

const OPS = [
  { v: 'eq', label: '=' },
  { v: 'ne', label: '≠' },
  { v: 'lt', label: '<' },
  { v: 'le', label: '≤' },
  { v: 'gt', label: '>' },
  { v: 'ge', label: '≥' },
  { v: 'in', label: 'in' },
  { v: 'contains', label: 'contains' },
  { v: 'isnull', label: 'is null' },
]

let nextId = 1

/** Compiles UI conditions into the JSON filter AST the backend expects. */
export function buildFilter(conditions: Condition[]): unknown {
  const active = conditions.filter((c) =>
    c.field.trim() === '' ? false : c.op === 'isnull' ? true : c.value.trim() !== '',
  )
  if (active.length === 0) return undefined
  const clauses = active.map((c) => {
    if (c.op === 'isnull') return { field: c.field, op: 'eq', value: null }
    let value: unknown = c.value
    if (c.op === 'in') value = c.value.split(',').map((s) => s.trim()).filter(Boolean)
    else if (/^-?\d+(\.\d+)?$/.test(c.value.trim())) value = Number(c.value)
    return { field: c.field, op: c.op, value }
  })
  return clauses.length === 1 ? clauses[0] : { and: clauses }
}

export function FilterBuilder({
  fields, value, onChange,
}: {
  fields: string[]
  value: Condition[]
  onChange: (next: Condition[]) => void
}) {
  const { t } = useI18n()
  const [, force] = useState(0)

  useEffect(() => {
    if (fields.length && value.some((c) => c.field === '')) {
      onChange(value.map((c) => (c.field === '' ? { ...c, field: fields[0] } : c)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fields])

  const add = () => {
    onChange([...value, { id: nextId++, field: fields[0] ?? '', op: 'eq', value: '' }])
    force((n) => n + 1)
  }

  return (
    <div className="flex flex-col gap-2" data-testid="filter-builder">
      {value.map((c) => (
        <div key={c.id} className="flex flex-wrap items-center gap-2">
          <select aria-label={`field-${c.id}`} className="ontogeny-input w-48" value={c.field} onChange={(e) => onChange(value.map((x) => (x.id === c.id ? { ...x, field: e.target.value } : x)))}>
            {fields.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          <select aria-label={`op-${c.id}`} className="ontogeny-input w-32" value={c.op} onChange={(e) => onChange(value.map((x) => (x.id === c.id ? { ...x, op: e.target.value } : x)))}>
            {OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
          <input
            aria-label={`value-${c.id}`}
            className="ontogeny-input min-w-[9rem] flex-1"
            placeholder={t('objects.value')}
            disabled={c.op === 'isnull'}
            value={c.value}
            onChange={(e) => onChange(value.map((x) => (x.id === c.id ? { ...x, value: e.target.value } : x)))}
          />
          <Button size="sm" variant="subtle" aria-label={`remove-${c.id}`} onClick={() => onChange(value.filter((x) => x.id !== c.id))}>
            <IconX width={14} height={14} />
          </Button>
        </div>
      ))}
      <div>
        <Button size="sm" onClick={add} data-testid="filter-add" icon={<IconPlus width={13} height={13} />}>
          {t('objects.addCondition')}
        </Button>
      </div>
    </div>
  )
}
