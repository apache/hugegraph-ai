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
 * GraphLegend — the canvas's visual key: three quiet icon+label marks.
 *
 * Compact on purpose: the label sits ABOVE the glyph, the whole key is a bare
 * transparent row (no glass plate — a plate would be one more box on the
 * drawing), and pointer events are off so panning works right through it.
 */
export interface GraphLegendItem {
  id: string
  label: string
  color: string
  /** Optional glyph (entity cards draw their kind icon); a colour dot otherwise. */
  iconSrc?: string
}

export function GraphLegend({ items, testId = 'graph-legend' }: {
  items: GraphLegendItem[]
  testId?: string
}) {
  if (items.length === 0) return null
  return (
    <div
      data-testid={testId}
      className="pointer-events-none flex flex-col justify-center gap-1.5 px-0.5"
    >
      {items.map((it) => (
        <div key={it.id} className="flex items-center gap-1.5">
          {it.iconSrc ? (
            <img src={it.iconSrc} width={14} height={14} alt="" draggable={false} style={{ display: 'block' }} />
          ) : (
            <span className="size-2.5 shrink-0 rounded-full" style={{ background: it.color }} />
          )}
          <span className="text-[10.5px] leading-none" style={{ color: 'var(--text-secondary)' }}>
            {it.label}
          </span>
        </div>
      ))}
    </div>
  )
}
