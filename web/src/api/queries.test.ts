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
/** Contract for the query-key table.
 *
 * Regression: four endpoints had two keys each, so one screen showed fresh data
 * while another showed stale — `/graph/projection` was read as `['projection']`
 * by ProjectionView but `['projection-summary']` by Admin and Extensions, so
 * "rebuild projection" refreshed only one of them; a single agent session was
 * polled under two keys at 4s and 1.2s. Separately, `['meta']` was written out
 * by hand in 15 places, two of them with `staleTime: 60_000` and thirteen taking
 * the 5s global default, so the sidebar's `content_hash` could disagree with a
 * just-published one.
 *
 * jsdom cannot observe cache identity across a real app, so this pins the
 * *source* invariants that make the keys unifiable.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(entry) && !/\.test\./.test(entry)) out.push(full)
  }
  return out
}

/** Strip comments before scanning: this module (and several pages) documents
 *  the very aliases we are asserting are gone, and a comment is not a call. */
function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const sources = walk(SRC).map((f) => ({
  path: relative(SRC, f),
  text: stripComments(readFileSync(f, 'utf8')),
}))

describe('query keys', () => {
  it('has exactly one key for the graph projection', () => {
    // 'projection-summary' named the same endpoint as 'projection'
    const offenders = sources.filter((s) => s.text.includes("'projection-summary'"))
    expect(offenders.map((s) => s.path)).toEqual([])
  })

  it('has exactly one key per agent session, whichever page polls it', () => {
    const offenders = sources.filter((s) => /queryKey: \['ext-scenario'/.test(s.text))
    expect(offenders.map((s) => s.path)).toEqual([])
  })

  it('does not spell the empty audit filter two ways', () => {
    // Dashboard asked ['revisions','latest'] where Audit asked ['revisions',{}]
    const offenders = sources.filter((s) => /queryKey: \['revisions', 'latest'\]/.test(s.text))
    expect(offenders.map((s) => s.path)).toEqual([])
  })

  it('reads the compiled snapshot only through metaQuery()', () => {
    // the only literal allowed is inside the factory module itself
    const offenders = sources.filter(
      (s) => s.path !== join('api', 'queries.ts') && /queryKey: \['meta'\]/.test(s.text),
    )
    expect(offenders.map((s) => s.path)).toEqual([])
  })

  it('never invalidates the entire cache', () => {
    // a bare invalidateQueries() throws away meta, extensions and the
    // projection whenever any unrelated mutation succeeds
    const offenders = sources.filter((s) => /invalidateQueries\(\s*\)/.test(s.text))
    expect(offenders.map((s) => s.path)).toEqual([])
  })

  it('keeps the snapshot immutable by default', () => {
    const queries = sources.find((s) => s.path === join('api', 'queries.ts'))
    expect(queries, 'api/queries.ts must exist').toBeTruthy()
    expect(queries!.text).toMatch(/staleTime:\s*Infinity/)
  })
})
