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
import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { ParamForm } from './ParamForm'

const PARAMETERS = {
  resolution: { type: 'string', required: true },
  priority: { type: 'enum[LOW, HIGH]', required: false },
  downtime_minutes: { type: 'integer', required: false },
  force: { type: 'boolean', required: false },
}

const render = (ui: React.ReactElement) => renderWithProviders(ui)

describe('ParamForm', () => {
  it('renders enum parameters as selects with the declared domain', () => {
    render(<ParamForm parameters={PARAMETERS} value={{}} onChange={() => {}} />)
    const select = screen.getByTestId('param-priority') as HTMLSelectElement
    expect([...select.options].map((o) => o.value)).toEqual(['', 'LOW', 'HIGH'])
  })

  it('picks an input kind per parameter type', () => {
    render(<ParamForm parameters={PARAMETERS} value={{}} onChange={() => {}} />)
    expect(screen.getByTestId('param-resolution')).toHaveAttribute('type', 'text')
    expect(screen.getByTestId('param-downtime_minutes')).toHaveAttribute('type', 'number')
    expect(screen.getByTestId('param-force')).toHaveAttribute('type', 'checkbox')
  })

  it('lists missing required parameters', () => {
    render(<ParamForm parameters={PARAMETERS} value={{}} onChange={() => {}} />)
    expect(screen.getByTestId('param-missing')).toHaveTextContent('resolution')
  })

  it('emits typed values on change', () => {
    const changes: Array<Record<string, unknown>> = []
    render(<ParamForm parameters={PARAMETERS} value={{}} onChange={(v) => changes.push(v)} />)
    fireEvent.change(screen.getByTestId('param-resolution'), { target: { value: 'replaced bearing' } })
    expect(changes.at(-1)).toMatchObject({ resolution: 'replaced bearing' })
    fireEvent.change(screen.getByTestId('param-downtime_minutes'), { target: { value: '42' } })
    expect(changes.at(-1)).toMatchObject({ downtime_minutes: 42 })
    fireEvent.click(screen.getByTestId('param-force'))
    expect(changes.at(-1)).toMatchObject({ force: true })
  })
})
