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
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { MutationDiff } from './MutationDiff'

const render = (ui: React.ReactElement) => renderWithProviders(ui)

describe('MutationDiff', () => {
  it('renders an added optional property', () => {
    render(<MutationDiff mutations={[{ mutation: 'add-optional-property', object: 'production-order', prop: 'workgroup', type: 'string' }]} />)
    expect(screen.getByText('production-order.workgroup')).toBeInTheDocument()
    expect(screen.getByText('+ property')).toBeInTheDocument()
    expect(screen.getByText(/string/)).toBeInTheDocument()
  })

  it('renders enum widening with the new member', () => {
    render(<MutationDiff mutations={[{ mutation: 'enum-widen', object: 'sales-order', prop: 'status', value: 'BLOCKED' }]} />)
    expect(screen.getByText('sales-order.status')).toBeInTheDocument()
    expect(screen.getByText('BLOCKED')).toBeInTheDocument()
  })

  it('falls back to raw JSON for unknown mutation kinds', () => {
    render(<MutationDiff mutations={[{ mutation: 'policy-loosen' }]} />)
    expect(screen.getByText(/policy-loosen/)).toBeInTheDocument()
  })
})
