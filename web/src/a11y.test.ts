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
/** Contract for the accessibility wiring that regresses silently.
 *
 * Each assertion here corresponds to something a browser measurement found
 * missing, and none of it fails a type-check or a normal render test:
 *
 *  - no skip link, and 16 Tab presses to reach `<main>`;
 *  - the node drawer looked like a dialog (`role="dialog"`) but moved no focus;
 *  - the canvas was invisible to assistive tech (`<canvas>`, no `role`);
 *  - no `aria-live` anywhere, so an async result was never announced;
 *  - no `<th scope>`, so a screen reader could not tell which axis a cell
 *    belonged to.
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

const sources = walk(SRC).map((f) => ({
  path: relative(SRC, f),
  text: readFileSync(f, 'utf8'),
}))

const find = (path: string) => {
  const hit = sources.find((s) => s.path === path)
  expect(hit, `${path} must exist`).toBeTruthy()
  return hit!.text
}

describe('accessibility wiring', () => {
  it('keeps a skip link that targets a focusable main', () => {
    const shell = find('components/AppShell.tsx')
    expect(shell).toContain('href="#ontogeny-main"')
    // the fragment must land on an element that accepts focus, or only the
    // scroll position moves and the next Tab starts at the sidebar again
    expect(shell).toMatch(/id="ontogeny-main"[\s\S]{0,120}tabIndex=\{-1\}/)
  })

  it('makes the drawer a real dialog', () => {
    const drawer = find('components/NodeInfoDrawer.tsx')
    expect(drawer).toContain('role="dialog"')
    expect(drawer).toContain('aria-modal="true"')
    expect(drawer, 'the drawer must trap and restore focus').toContain('useFocusTrap')
  })

  it('gives every destructive confirmation a dialog with a live trap', () => {
    const ui = find('components/ui/index.tsx')
    expect(ui).toContain('role="alertdialog"')
    expect(ui).toMatch(/ConfirmDialog[\s\S]*useFocusTrap/)
  })

  it('keeps the canvas out of the tab order but visible to assistive tech', () => {
    const graph = find('components/FlowGraph.tsx')
    // role+label rather than tabindex: a bitmap you cannot operate should not be
    // focusable, it should just say what it is
    expect(graph).toContain('role="img"')
    expect(graph).toMatch(/role="img"[\s\S]{0,120}aria-label=/)
    expect(graph).not.toMatch(/containerRef[\s\S]{0,200}tabIndex=\{0\}/)
  })

  it('announces async results and labelled disclosures', () => {
    const ui = find('components/ui/index.tsx')
    expect(ui).toMatch(/role="status"[\s\S]{0,80}aria-live="polite"/)
    // the explored-node chips are the canvas's text equivalent
    expect(find('components/ExploreGraph.tsx')).toContain('aria-live="polite"')
    expect(find('pages/OntologyExplorer.tsx')).toContain('LiveRegion')
  })

  it('scopes every hand-written table header', () => {
    // the shared DataTable sets scope itself; these are the inline <table>s
    const offenders: string[] = []
    for (const source of sources) {
      if (source.path.includes('DataTable')) continue
      const loose = source.text.match(/<th className="ontogeny-th"/g)
      if (loose) offenders.push(`${source.path} (${loose.length})`)
    }
    expect(offenders).toEqual([])
  })

  it('marks the sidebar drawer as a dialog when it is off-canvas', () => {
    const shell = find('components/AppShell.tsx')
    expect(shell, 'the mobile sidebar must trap focus too').toMatch(/isMobile && drawerOpen/)
    expect(shell).toContain('useFocusTrap')
  })
})
