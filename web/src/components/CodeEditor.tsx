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
/**
 * A tiny read/write Python code editor: syntax-highlighted text under a
 * transparent caret.
 *
 * Built from two stacked elements rather than a real editor component — the
 * colored <pre> renders the tokenized source, and the <textarea> on top holds
 * all interaction with its text painted invisible (caret kept visible). The
 * two must share font, padding and `white-space: pre` (no soft wrap: both
 * scroll together, horizontally too) so the colors sit exactly under the
 * glyphs they belong to.
 *
 * The tokenizer is deliberately a single regex pass, not a parser: this is
 * coloring for a human, executed on every keystroke, and a mis-colored corner
 * case costs nothing — while a 300 kB highlighting dependency is a permanent
 * weight on every console load.
 */
import { useRef, useState } from 'react'

const PY_KEYWORDS = new Set([
  'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break',
  'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally',
  'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal',
  'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
])

const PY_BUILTINS = new Set([
  'abs', 'all', 'any', 'bool', 'dict', 'divmod', 'enumerate', 'filter',
  'float', 'format', 'int', 'isinstance', 'len', 'list', 'max', 'min',
  'print', 'range', 'repr', 'round', 'set', 'sorted', 'str', 'sum', 'tuple',
  'type', 'zip',
])

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const span = (cls: string, text: string) => `<span class="ontogeny-tok-${cls}">${escapeHtml(text)}</span>`

// Alternation order matters: comments and triple-quoted strings must win over
// the single-line string they may visually contain, names come last so the
// keyword/builtin classes can be decided per match afterwards. The optional
// prefix (`?`) is required on BOTH quote branches: without it a plain "..." —
// the most common string in Python — cannot match, because the engine insists
// on a leading r/b/f/u and skips the token entirely.
const TOKEN_RE =
  /(#[^\n]*)|('''[\s\S]*?'''|"""[\s\S]*?""")|((?:[rbfu]|rb|br|fr|rf)?'(?:\\.|[^\\\n])*'|(?:[rbfu]|rb|br|fr|rf)?"(?:\\.|[^\\\n])*")|(@[\w.]+)|(\b\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?\b)|([A-Za-z_]\w*)/g

/** Source → HTML with `ontogeny-tok-*` spans. Input is escaped; output is only ever
 *  interpolated via dangerouslySetInnerHTML into an aria-hidden mirror. */
export function highlightPython(src: string): string {
  let out = ''
  let last = 0
  for (const m of src.matchAll(TOKEN_RE)) {
    const start = m.index ?? 0
    out += escapeHtml(src.slice(last, start))
    last = start + m[0].length
    const [tok, comment, triple, str, deco, num, name] = m
    if (comment) out += span('cmt', tok)
    else if (triple || str) out += span('str', tok)
    else if (deco) out += span('dec', tok)
    else if (num) out += span('num', tok)
    else if (name) {
      if (PY_KEYWORDS.has(name)) out += span('kw', tok)
      else if (/(\bdef\s+|\bclass\s+)$/.test(src.slice(0, start))) out += span('fn', tok)
      else if (PY_BUILTINS.has(name)) out += span('bi', tok)
      else out += escapeHtml(tok)
    }
  }
  return out + escapeHtml(src.slice(last))
}

export function PythonEditor({ value, onChange, testId, label, rows = 18 }: {
  value: string
  onChange: (v: string) => void
  testId?: string
  /** Accessible name: the mirror <pre> is decorative, the textarea is the input. */
  label: string
  rows?: number
}) {
  const mirror = useRef<HTMLPreElement>(null)
  // IME composition (Chinese/Japanese/Korean input) lives only in the textarea:
  // the mirror renders the committed value, so composing text painted with the
  // textarea's transparent color would be INVISIBLE. While composing, the two
  // layers swap roles — the textarea shows its own (opaque) text, the mirror
  // hides — so the pre-edit string and the caret stay in place. Highlighting
  // resumes on compositionend, which also re-commits the final value.
  const [composing, setComposing] = useState(false)
  // one scroll position, owned by the textarea; the mirror just follows
  const onScroll = (e: React.UIEvent<HTMLTextAreaElement>) => {
    const pre = mirror.current
    const ta = e.currentTarget
    if (pre) {
      pre.scrollTop = ta.scrollTop
      pre.scrollLeft = ta.scrollLeft
    }
  }
  // Tab indents with four spaces (Shift-Tab outdents the line's head) — a code
  // box that moves focus on Tab is a box nobody can write Python in.
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Tab') return
    e.preventDefault()
    const ta = e.currentTarget
    const { selectionStart: s, selectionEnd: end } = ta
    if (e.shiftKey) {
      const lineStart = value.lastIndexOf('\n', s - 1) + 1
      const indent = value.slice(lineStart, lineStart + 4).match(/^ {1,4}/)?.[0].length ?? 0
      if (!indent) return
      const next = value.slice(0, lineStart) + value.slice(lineStart + indent)
      onChange(next)
      requestAnimationFrame(() => ta.setSelectionRange(s - indent, s - indent))
    } else {
      const next = `${value.slice(0, s)}    ${value.slice(end)}`
      onChange(next)
      requestAnimationFrame(() => ta.setSelectionRange(s + 4, s + 4))
    }
  }

  return (
    <div className="ontogeny-code font-mono" data-testid={testId}>
      <pre
        ref={mirror}
        aria-hidden
        className={composing ? 'ontogeny-code-mirror ontogeny-code-hidden' : 'ontogeny-code-mirror'}
        dangerouslySetInnerHTML={{ __html: highlightPython(value) + '\n' }}
      />
      <textarea
        aria-label={label}
        className={composing ? 'ontogeny-code-input ontogeny-code-composing' : 'ontogeny-code-input'}
        spellCheck={false}
        wrap="off"
        rows={rows}
        value={value}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={(e) => {
          setComposing(false)
          // Safari orders compositionend before the final input event; commit
          // from the element so the last frame of the composition cannot be lost
          onChange(e.currentTarget.value)
        }}
        onChange={(e) => onChange(e.target.value)}
        onScroll={onScroll}
        onKeyDown={onKeyDown}
      />
    </div>
  )
}
