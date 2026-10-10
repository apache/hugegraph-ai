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
/** Contract for the message catalogue.
 *
 * `Dict = Record<string, string>` means TypeScript can never notice a key that
 * was added and never wired, or deleted while still referenced — `t()` takes a
 * plain string. 82 keys had accumulated unused (12.6% of the catalogue) because
 * nothing checked.
 *
 * Two invariants:
 *  1. zh and en define exactly the same keys (a missing translation silently
 *     falls back to English, so a gap is invisible in the UI);
 *  2. no key is dead. A key counts as referenced if it appears literally in
 *     non-test source, or if it matches a dynamic family — `t(\`a.b.${x}\`)`
 *     (status/outcome/error codes) or `plural('a.b', n)` (which resolves
 *     `a.b.one` / `a.b.other`).
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { en } from './en'
import { zh } from './zh'

const SRC = resolve(process.cwd(), 'src')

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(entry) && !/\.test\./.test(entry)) out.push(full)
  }
  return out
}

/** Source files that may *reference* a key: everything but the dictionaries. */
const referencing = walk(SRC)
  .filter((f) => !relative(SRC, f).startsWith('i18n'))
  .map((f) => readFileSync(f, 'utf8'))

const literals = new Set<string>()
const families = new Set<string>()
for (const text of referencing) {
  for (const m of text.matchAll(/'([^'\\\n]*)'/g)) literals.add(m[1])
  for (const m of text.matchAll(/"([^"\\\n]*)"/g)) literals.add(m[1])
  for (const m of text.matchAll(/t\(\s*`([^`$]*)\$\{/g)) families.add(m[1])
  for (const m of text.matchAll(/plural\(\s*'([^']+)'/g)) families.add(`${m[1]}.`)
}

function isReferenced(key: string): boolean {
  if (literals.has(key)) return true
  for (const family of families) if (key.startsWith(family)) return true
  return false
}

describe('message catalogue', () => {
  it('defines the same keys in zh and en', () => {
    const onlyZh = Object.keys(zh).filter((k) => !(k in en))
    const onlyEn = Object.keys(en).filter((k) => !(k in zh))
    expect({ onlyZh, onlyEn }).toEqual({ onlyZh: [], onlyEn: [] })
  })

  it('has no dead keys', () => {
    const dead = Object.keys(zh).filter((k) => !isReferenced(k))
    // reporting the names (not a count) is what makes this actionable
    expect(dead).toEqual([])
  })

  it('has a non-empty string for every key', () => {
    const blank = Object.entries(zh).filter(([, v]) => typeof v !== 'string' || v.trim() === '')
    expect(blank).toEqual([])
  })
})
