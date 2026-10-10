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
/** Read-only helpers over the compiled ontology snapshot.
 *
 * Shared by the ontology canvas (legend, node cards), the type detail panel
 * and the data-preview catalogue so all three describe the model identically. */
import type { Cardinality, OntologyMeta } from '../api/types'

/** A declared LinkType with the object types it connects. The compiled meta
 * lists a link on every endpoint it touches; source→target direction is not
 * part of the snapshot, so links are presented as undirected relations. */
interface LinkInfo {
  name: string
  /** The connected object types (source first when the direction is known). */
  types: string[]
  /** Direction, when the snapshot states it (`meta.linkTypes`). */
  source?: string
  target?: string
  cardinality?: Cardinality
}

/** The declared LinkTypes.
 *
 * `meta.linkTypes` is authoritative and carries direction. A snapshot without
 * it only lists a link on both endpoints, so the declaring types are paired
 * and the direction is left unstated. */
export function linkIndex(meta: OntologyMeta): LinkInfo[] {
  if (meta.linkTypes) {
    return Object.entries(meta.linkTypes).map(([name, lt]) => ({
      name,
      types: [lt.source, lt.target],
      source: lt.source,
      target: lt.target,
      cardinality: lt.cardinality,
    }))
  }
  const map = new Map<string, string[]>()
  for (const [type, obj] of Object.entries(meta.objects)) {
    for (const link of obj.links) {
      const list = map.get(link) ?? []
      if (!list.includes(type)) list.push(type)
      map.set(link, list)
    }
  }
  return Array.from(map, ([name, types]) => ({ name, types }))
}

/** For one object type: each of its links paired with the other endpoint(s). */
export function linkPeers(meta: OntologyMeta, type: string): Array<{ link: string; peers: string[] }> {
  const index = new Map(linkIndex(meta).map((l) => [l.name, l.types]))
  return (meta.objects[type]?.links ?? []).map((link) => ({
    link,
    peers: (index.get(link) ?? []).filter((t) => t !== type),
  }))
}

interface OntologyStats {
  types: number
  properties: number
  links: number
  actions: number
  functions: number
  policies: number
  projections: number
}

/** Headline counts for the model overview chips. */
export function ontologyStats(meta: OntologyMeta): OntologyStats {
  return {
    types: Object.keys(meta.objects).length,
    properties: Object.values(meta.objects).reduce((n, o) => n + Object.keys(o.properties).length, 0),
    links: linkIndex(meta).length,
    actions: Object.keys(meta.actions).length,
    functions: Object.keys(meta.functions).length,
    policies: Object.keys(meta.policies ?? {}).length,
    projections: Object.keys(meta.projections).length,
  }
}
