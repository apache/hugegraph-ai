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
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { PythonEditor, highlightPython } from './CodeEditor'

describe('highlightPython', () => {
  it('wraps keywords, strings, comments and numbers in token spans', () => {
    const html = highlightPython('def run(x):  # note\n    return "a" + 1\n')
    expect(html).toContain('ontogeny-tok-kw">def')
    expect(html).toContain('ontogeny-tok-cmt"># note')
    expect(html).toContain('ontogeny-tok-str">"a"')
    expect(html).toContain('ontogeny-tok-num">1')
  })

  it('colors the name after def as a function', () => {
    expect(highlightPython('def mtbf(): pass')).toContain('ontogeny-tok-fn">mtbf')
  })

  it('escapes HTML so the innerHTML mirror cannot inject markup', () => {
    const html = highlightPython('x = "<script>alert(1)</script>"\n# <img src=x onerror=alert(1)>')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
  })

  it('leaves an unterminated quote as plain (safe mid-typing degradation)', () => {
    const html = highlightPython('x = "unterminated')
    expect(html).not.toContain('ontogeny-tok-str')
  })
})

describe('PythonEditor', () => {
  const setup = (value = 'def run():\n    return 1\n') => {
    const changes: string[] = []
    renderWithProviders(
      <PythonEditor label="code" testId="py" value={value} onChange={(v) => changes.push(v)} />,
    )
    const textarea = screen.getByLabelText('code') as HTMLTextAreaElement
    const box = screen.getByTestId('py')
    return { changes, textarea, box }
  }

  it('keeps the textarea value in sync with the buffer', () => {
    const { textarea, changes } = setup()
    expect(textarea.value).toBe('def run():\n    return 1\n')
    fireEvent.change(textarea, { target: { value: 'x = 2' } })
    expect(changes.at(-1)).toBe('x = 2')
  })

  it('swaps layers while an IME composition is active (Bug B regression)', () => {
    const { textarea, box } = setup('x = 1  # comment')
    const mirror = box.querySelector('.ontogeny-code-mirror') as HTMLElement
    // before: mirror carries the colored text, textarea text is transparent
    expect(mirror).not.toHaveClass('ontogeny-code-hidden')
    expect(textarea).not.toHaveClass('ontogeny-code-composing')

    fireEvent.compositionStart(textarea)
    expect(mirror).toHaveClass('ontogeny-code-hidden')
    expect(textarea).toHaveClass('ontogeny-code-composing')

    // the composition's final text commits on compositionend and colors return
    fireEvent.compositionEnd(textarea, { target: { value: 'x = 2  # done' } })
    expect(mirror).not.toHaveClass('ontogeny-code-hidden')
    expect(textarea).not.toHaveClass('ontogeny-code-composing')
  })

  it('indents with Tab and outdents with Shift-Tab', () => {
    // a controlled harness: the editor is only meaningful when the host feeds
    // each change back as the new value (the Tab handler re-reads `value`)
    const changes: string[] = []
    function Harness({ initial }: { initial: string }) {
      const [v, setV] = useState(initial)
      return <PythonEditor label="code" testId="py" value={v} onChange={(nv) => { setV(nv); changes.push(nv) }} />
    }
    renderWithProviders(<Harness initial={'def run():\nreturn 1'} />)
    const textarea = screen.getByLabelText('code') as HTMLTextAreaElement

    // 'def run():\n' is 11 chars, so line 2's content starts at index 11
    textarea.setSelectionRange(11, 11)
    fireEvent.keyDown(textarea, { key: 'Tab' })
    expect(changes.at(-1)).toBe('def run():\n    return 1')
    expect(textarea.value).toBe('def run():\n    return 1')

    // outdent the same line again
    textarea.setSelectionRange(11, 11)
    fireEvent.keyDown(textarea, { key: 'Tab', shiftKey: true })
    expect(changes.at(-1)).toBe('def run():\nreturn 1')
  })
})
