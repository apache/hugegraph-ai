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
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { KindMeta } from '../../api/types'
import { I18nProvider } from '../../i18n'
import { ArchBoard } from './ArchBoard'
import { KIND_LABELS, PLATFORM_FALLBACK } from './kindVisuals'

/** The exact payload `/meta/ontology.kinds` returns: 9 platform resources + 2 manifest. */
const META_KINDS: KindMeta[] = [
  { kind: 'ObjectType', group: 'core', layer: 'semantic', core: false, platform: true },
  { kind: 'LinkType', group: 'core', layer: 'semantic', core: false, platform: true },
  { kind: 'Action', group: 'core', layer: 'kinetic', core: true, platform: true },
  { kind: 'Function', group: 'extension', layer: 'kinetic', core: false, platform: true },
  { kind: 'PolicySet', group: 'core', layer: 'governance', core: false, platform: true },
  { kind: 'AgentPlugin', group: 'extension', layer: 'agent', core: false, platform: true },
  { kind: 'Projection', group: 'adapter', layer: 'derived', core: false, platform: true },
  { kind: 'EvalSuite', group: 'extension', layer: 'evolution', core: true, platform: true },
  { kind: 'EvolutionPolicy', group: 'baseline', layer: 'evolution', core: false, platform: true },
  { kind: 'Store', group: 'manifest', layer: 'binding', core: false, platform: false },
  { kind: 'Ontology', group: 'manifest', layer: 'manifest', core: false, platform: false },
]

function renderBoard(kinds?: KindMeta[], lang: 'en' | 'zh' = 'en') {
  return render(
    <I18nProvider initial={lang}>
      <ArchBoard kinds={kinds} />
    </I18nProvider>,
  )
}

const chips = () => Array.from(screen.getByTestId('arch-board').querySelectorAll('[data-kind]'))
const chip = (kind: string) => screen.getByTestId('arch-board').querySelector(`[data-kind="${kind}"]`) as HTMLElement

describe('ArchBoard platform resources', () => {
  it('renders one chip per platform resource and none for the manifest resources', () => {
    renderBoard(META_KINDS)
    expect(chips().map((c) => c.getAttribute('data-kind'))).toEqual([
      'ObjectType',
      'LinkType',
      'Action',
      'PolicySet',
      'Function',
      'AgentPlugin',
      'EvalSuite',
      'Projection',
      'EvolutionPolicy',
    ])
    expect(chip('Store')).toBeNull()
    expect(chip('Ontology')).toBeNull()
    expect(screen.getByTestId('arch-board').textContent).toContain('(9)')
  })

  it('falls back to the same nine platform resources when meta has not loaded', () => {
    renderBoard()
    expect(chips()).toHaveLength(9)
    expect(chips().map((c) => c.getAttribute('data-kind')).sort()).toEqual(PLATFORM_FALLBACK.map((k) => k.kind).sort())
  })

  it('groups the nine kinds as 4 + 3 + 1 + 1', () => {
    renderBoard(META_KINDS)
    const groups = screen.getAllByTestId('kind-group')
    expect(groups.map((g) => g.getAttribute('data-group'))).toEqual(['core', 'extension', 'adapter', 'baseline'])
    expect(groups.map((g) => g.getAttribute('data-count'))).toEqual(['4', '3', '1', '1'])
    expect(groups.map((g) => g.querySelectorAll('[data-kind]').length)).toEqual([4, 3, 1, 1])
    expect(groups[0].textContent).toContain('CORE')
    expect(groups[0].textContent).toContain('4')
  })

  it('names the two manifest resources without drawing chips for them', () => {
    renderBoard(META_KINDS)
    const note = screen.getByTestId('kind-manifest-note')
    expect(note.textContent).toContain('2 manifest resources')
    expect(note.textContent).toContain('Store')
    expect(note.textContent).toContain('Ontology')
    expect(chips()).toHaveLength(9)
  })

  it('still names the manifests when meta has not loaded', () => {
    renderBoard()
    const note = screen.getByTestId('kind-manifest-note')
    expect(note.textContent).toContain('Store')
    expect(note.textContent).toContain('Ontology')
  })

  it('no longer tags Action/EvalSuite as CORE, keeps the human-only tag', () => {
    renderBoard(META_KINDS)
    expect(chip('Action').textContent).not.toContain('CORE')
    expect(chip('EvalSuite').textContent).not.toContain('CORE')
    expect(chip('EvolutionPolicy').textContent).toContain('HUMAN')
  })

  it('is data-driven: a platform kind the UI has never seen still renders', () => {
    const extended = [
      ...META_KINDS,
      { kind: 'Subscription', group: 'extension', layer: 'kinetic', core: false, platform: true } as KindMeta,
    ]
    renderBoard(extended)
    expect(chips()).toHaveLength(10)
    // no drawing yet -> the kind name is shown rather than an empty chip
    expect(chip('Subscription').textContent).toContain('Subscription')
  })

  it('every platform kind has a zh/en label', () => {
    // backend adds a platform kind -> this fails until the console can draw it
    for (const k of META_KINDS.filter((k) => k.platform)) {
      const look = KIND_LABELS[k.kind]
      expect(look, `missing KIND_LABELS entry for ${k.kind}`).toBeTruthy()
      expect(look.zh.length).toBeGreaterThan(0)
      expect(look.en.length).toBeGreaterThan(0)
      expect(look.core).toBe(k.core)
      expect(look.group).toBe(k.group)
    }
  })

  it('localizes the one-word labels', () => {
    renderBoard(META_KINDS, 'zh')
    expect(chip('ObjectType').textContent).toContain('对象')
    expect(chip('EvolutionPolicy').textContent).toContain('基线')
  })
})
