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
/** Raw DSL resources, as the editors see them.
 *
 * The editors hold the compiled resources verbatim — `{apiVersion, kind,
 * metadata, spec}` — and mutate single fields inside them, so load → edit →
 * save round-trips with nothing stripped (`GET /admin/builder/resources` is the
 * lossless counterpart of the lossy `/meta/ontology` consumer view). A
 * client-side mirror of the model would have to drop every field it does not
 * understand — effects, derived properties, capability values — and then write
 * that loss back to disk.
 *
 * Reads are defensive on purpose: the spec is validated server-side, but a
 * half-written draft must never crash a form.
 */
import type { OntologyResource } from './types'

export type ResourceKind =
  | 'ObjectType' | 'LinkType' | 'Projection' | 'Action' | 'Function' | 'PolicySet'

export type { OntologyResource }

/** Stable identity of one resource across the draft, the touched set and the
 *  `deletes` list the save endpoint expects ("Kind/name"). */
export const rkey = (kind: ResourceKind, name: string): string => `${kind}/${name}`

export const splitKey = (key: string): { kind: string; name: string } => {
  const i = key.indexOf('/')
  return { kind: key.slice(0, i), name: key.slice(i + 1) }
}

/* ------------------------------------------------------------- spec reads */

export const asStr = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback)
export const asNum = (v: unknown, fallback = 0): number => (typeof v === 'number' ? v : fallback)
export const asBool = (v: unknown, fallback = false): boolean => (typeof v === 'boolean' ? v : fallback)
export const asObj = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
export const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
export const asStrList = (v: unknown): string[] =>
  asList(v).filter((x): x is string => typeof x === 'string')

/** `{a: {...}}` → `[{name:'a', ...}]`, for the DSL's map-shaped collections
 *  (properties, parameters, include.objects) which a list UI edits row by row. */
export function asNamed<T extends Record<string, unknown>>(
  v: unknown,
  defaults: Partial<Omit<T, 'name'>>,
): Array<{ name: string } & T> {
  return Object.entries(asObj(v)).map(
    ([name, raw]) => ({ ...defaults, ...asObj(raw), name }) as unknown as { name: string } & T,
  )
}

/** The inverse of `asNamed`, preserving the given row order. */
export function fromNamed<T extends { name: string }>(rows: T[]): Record<string, Omit<T, 'name'>> {
  const out: Record<string, Omit<T, 'name'>> = {}
  for (const { name, ...rest } of rows) {
    if (!name) continue
    out[name] = rest as Omit<T, 'name'>
  }
  return out
}

/** A name not already taken, so a freshly added row never collides. */
export function uniqueName(base: string, taken: Iterable<string>): string {
  const used = new Set(taken)
  if (!used.has(base)) return base
  for (let i = 2; ; i += 1) {
    const next = `${base}-${i}`
    if (!used.has(next)) return next
  }
}

/** The property type vocabulary the DSL accepts (ParamDef validates it too). */
export const PROPERTY_TYPES = [
  'string', 'integer', 'decimal(10,2)', 'boolean', 'date', 'timestamp', 'enum[A, B, C]',
] as const

export const CARDINALITIES = ['ONE_TO_ONE', 'ONE_TO_MANY', 'MANY_TO_MANY'] as const

/** Capability kinds a function may declare.
 *
 * This list must mirror the sandbox boundary, which is the authority: the
 * validator's `FN-CAP` rule rejects anything outside `{read-objects, llm}`, and
 * those are exactly the two RPCs the child process can make (`ontogeny.query` and
 * `ontogeny.llm`). An `http` entry used to sit here as a switch that no backend ever
 * implemented — picking it produced a package the validator refused, so the
 * model could not be published. Offering a capability that cannot exist is
 * worse than not offering it. */
export const CAPABILITY_KINDS = ['read-objects', 'llm', 'http'] as const

/** Function bodies come in two flavours: code in the package, or a declared
 *  pipeline the platform executes itself (prompt-shaped logic that can be
 *  edited here, diffed, and version-pinned). */
export const FUNCTION_RUNTIMES = ['python', 'declarative'] as const

/** Step kinds a declarative function may use, mirroring FunctionStep.kind. */
export const STEP_KINDS = ['read', 'llm', 'http'] as const
