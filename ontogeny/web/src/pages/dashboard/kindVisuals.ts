/*
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
*/
import type { KindMeta } from '../../api/types'

/** How to draw one platform kind: its one-word label (zh/en).
 *
 *  The *list* is not owned here — it comes from `/meta/ontology.kinds`. This
 *  map only answers "how do I draw this kind", and the label-coverage test
 *  fails when the backend adds a platform kind without a drawing. */
export interface KindDrawing {
  zh: string
  en: string
  group: KindMeta['group']
  core: boolean
}

export const KIND_LABELS: Record<string, KindDrawing> = {
  ObjectType: { zh: '对象', en: 'object', group: 'core', core: false },
  LinkType: { zh: '链接', en: 'link', group: 'core', core: false },
  Action: { zh: '动作', en: 'action', group: 'core', core: true },
  Function: { zh: '函数', en: 'function', group: 'extension', core: false },
  PolicySet: { zh: '策略', en: 'policy', group: 'core', core: false },
  AgentPlugin: { zh: '智能体', en: 'agent', group: 'extension', core: false },
  Projection: { zh: '投影', en: 'projection', group: 'adapter', core: false },
  EvalSuite: { zh: '自进化', en: 'evolution', group: 'extension', core: true },
  EvolutionPolicy: { zh: '基线', en: 'baseline', group: 'baseline', core: false },
}

/** Shown when the board renders without a meta payload (tests, static export).
 *  Derived from the label map so the fallback cannot drift into a second list. */
export const PLATFORM_FALLBACK: KindMeta[] = Object.entries(KIND_LABELS).map(([kind, l]) => ({
  kind,
  group: l.group,
  layer: '',
  core: l.core,
  platform: true,
}))

/** The two package manifests. They travel with the package but are not
 *  platform resources, so the board counts them in a note instead of a chip. */
export const MANIFEST_FALLBACK: KindMeta[] = [
  { kind: 'Store', group: 'manifest', layer: 'binding', core: false, platform: false },
  { kind: 'Ontology', group: 'manifest', layer: 'manifest', core: false, platform: false },
]

/** Group headings for the kind clusters — the 4+3+1+1 split, visible. */
export interface KindGroupMeta {
  en: string
  zh: string
  tone: string
  /** outer grid span + inner card grid, so every card keeps the same width */
  col: string
  inner: string
}

export function groupMeta(group: string): KindGroupMeta {
  return (
    GROUP_META[group] ?? {
      en: group.toUpperCase(),
      zh: group.toUpperCase(),
      tone: 'violet',
      col: 'col-span-2 sm:col-span-4 lg:col-span-2',
      inner: 'grid-cols-2',
    }
  )
}

export const GROUP_META: Record<string, KindGroupMeta> = {
  core: {
    en: 'CORE', zh: 'CORE', tone: 'violet',
    col: 'col-span-2 sm:col-span-4 lg:col-span-4',
    inner: 'grid-cols-2 sm:grid-cols-4',
  },
  extension: {
    en: 'EXTENSION', zh: 'EXTENSION', tone: 'info',
    col: 'col-span-2 sm:col-span-4 lg:col-span-3',
    inner: 'grid-cols-2 sm:grid-cols-3',
  },
  adapter: {
    en: 'ADAPTER', zh: 'ADAPTER', tone: 'neutral',
    col: 'col-span-2 sm:col-span-4 lg:col-span-1',
    inner: 'grid-cols-1',
  },
  baseline: {
    en: 'BASELINE', zh: 'BASELINE', tone: 'success',
    col: 'col-span-2 sm:col-span-4 lg:col-span-1',
    inner: 'grid-cols-1',
  },
}

export interface KindGroupBucket {
  group: string
  label: KindGroupMeta
  items: KindMeta[]
}

/** Group in registry order (core -> extension -> adapter -> baseline), and keep
 *  an unknown future group visible instead of silently dropping its chips. */
export function groupPlatformKinds(items: KindMeta[]): KindGroupBucket[] {
  const groups: KindGroupBucket[] = []
  for (const kind of items) {
    let bucket = groups.find((g) => g.group === kind.group)
    if (!bucket) {
      bucket = {
        group: kind.group,
        label: groupMeta(kind.group),
        items: [],
      }
      groups.push(bucket)
    }
    bucket.items.push(kind)
  }
  return groups
}
