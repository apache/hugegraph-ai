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
/** The overlay focus contract, which was absent entirely.
 *
 * Measured before: opening the node drawer left focus on `<body>`
 * (`focusMoved = false`), `aria-modal` was null and no sibling was `inert`, so
 * Tab escaped into the page behind it, and closing it dropped focus on `<body>`
 * instead of returning it to the node that was clicked.
 */
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders as render } from '../test/render'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { NodeInfoDrawer } from './NodeInfoDrawer'

function Panel() {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen(true)}>open the drawer</button>
      <button>a button behind it</button>
      <NodeInfoDrawer
        open={open}
        onClose={() => setOpen(false)}
        title="SO-1"
        items={[{ key: 'status', value: 'OPEN' }]}
        link={{ to: '/data', label: 'open the full page' }}
      />
    </div>
  )
}

describe('NodeInfoDrawer focus contract', () => {
  it('moves focus into the dialog on open', async () => {
    const user = userEvent.setup()
    render(<Panel />)
    expect(document.activeElement).toBe(document.body)

    await user.click(screen.getByText('open the drawer'))

    const drawer = screen.getByTestId('node-info-drawer')
    expect(drawer.contains(document.activeElement)).toBe(true)
    // the panel itself, so the accessible name is announced before its controls
    expect(document.activeElement).toBe(drawer)
  })

  it('is a modal dialog', async () => {
    const user = userEvent.setup()
    render(<Panel />)
    await user.click(screen.getByText('open the drawer'))
    expect(screen.getByTestId('node-info-drawer')).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByTestId('node-info-drawer')).toHaveAttribute('role', 'dialog')
  })

  it('keeps Tab inside the dialog', async () => {
    const user = userEvent.setup()
    render(<Panel />)
    await user.click(screen.getByText('open the drawer'))

    const drawer = screen.getByTestId('node-info-drawer')
    // the drawer has two stops: the close button and the footer link
    await user.tab()
    expect(drawer.contains(document.activeElement)).toBe(true)
    await user.tab()
    expect(drawer.contains(document.activeElement)).toBe(true)
    // ...and the third Tab must wrap, not escape to the sidebar/page behind it
    await user.tab()
    expect(drawer.contains(document.activeElement)).toBe(true)
    expect(document.activeElement).not.toBe(document.body)
  })

  it('returns focus to the trigger on close', async () => {
    const user = userEvent.setup()
    render(<Panel />)
    const trigger = screen.getByText('open the drawer')
    await user.click(trigger)
    await user.click(screen.getByTestId('drawer-close'))

    expect(screen.queryByTestId('node-info-drawer')).toBeNull()
    // not <body>: the whole point is that the keyboard user resumes where they were
    expect(document.activeElement).toBe(trigger)
  })

  it('closes on Escape', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <NodeInfoDrawer open onClose={onClose} title="SO-1" items={[{ key: 'a', value: 'b' }]} />,
    )
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
