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
 * YAML preview of the resources a save would write.
 *
 * The DSL is YAML on disk, and a modelling page owes the user a look at exactly
 * what it is about to send — a form can hide a field it does not model, and the
 * preview is how that becomes visible. Written by hand (no yaml dependency) so
 * the bundle stays small and the output is deterministic: the same resource
 * always renders the same text, which is what makes it usable in a diff.
 */

/** Readable YAML for a list of DSL resources. */
export function toYaml(resources: Array<Record<string, unknown>>): string {
  const out: string[] = []
  for (const r of resources) {
    const meta = r.metadata as Record<string, unknown> | undefined
    out.push(`# ${r.kind}: ${meta?.name ?? '?'}${meta?.display ? ` (${meta.display})` : ''}`)
    emitMapping(r, 0, out)
    out.push('')
  }
  return out.join('\n')
}

/** YAML scalar rendering; quotes anything YAML would misread. */
function scalar(v: unknown): string | null {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'boolean' || typeof v === 'number') return String(v)
  if (typeof v === 'string') {
    const needsQuote =
      v === '' ||
      v !== v.trim() ||
      /[:{}[\],&*?|>'"%@`#]/.test(v) ||
      /^(true|false|null|~|-?\d+(\.\d+)?)$/i.test(v) ||
      v.startsWith('- ')
    return needsQuote ? `'${v.replace(/'/g, "''")}'` : v
  }
  return null
}

function emitMapping(m: Record<string, unknown>, indent: number, out: string[]) {
  const pad = '  '.repeat(indent)
  for (const [k, v] of Object.entries(m)) {
    const s = scalar(v)
    if (s !== null) {
      out.push(`${pad}${k}: ${s}`)
    } else if (Array.isArray(v)) {
      if (v.length === 0) out.push(`${pad}${k}: []`)
      else if (v.every((x) => scalar(x) !== null)) out.push(`${pad}${k}: [${v.map((x) => scalar(x)).join(', ')}]`)
      else
        for (const item of v) {
          if (scalar(item) !== null) out.push(`${pad}- ${scalar(item)}`)
          else emitInlineMappingEntry(item as Record<string, unknown>, pad, out)
        }
    } else if (typeof v === 'object' && v !== null) {
      const entries = Object.entries(v as Record<string, unknown>)
      if (entries.length === 0) out.push(`${pad}${k}: {}`)
      else {
        out.push(`${pad}${k}:`)
        emitMapping(v as Record<string, unknown>, indent + 1, out)
      }
    }
  }
}

/** First key on the `- ` line, remaining keys nested underneath. */
function emitInlineMappingEntry(m: Record<string, unknown>, pad: string, out: string[]) {
  const entries = Object.entries(m)
  entries.forEach(([ik, iv], i) => {
    const bullet = i === 0 ? '- ' : '  '
    const s = scalar(iv)
    if (s !== null) {
      out.push(`${pad}${bullet}${ik}: ${s}`)
    } else if (Array.isArray(iv)) {
      out.push(`${pad}${bullet}${ik}: [${iv.map((x) => scalar(x)).join(', ')}]`)
    } else {
      out.push(`${pad}${bullet}${ik}:`)
      emitMapping(iv as Record<string, unknown>, indentOf(pad) + 2, out)
    }
  })
}

const indentOf = (pad: string) => pad.length
