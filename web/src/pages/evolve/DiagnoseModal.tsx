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
 * DiagnoseModal — the 诊断并提案 run dialog.
 *
 * The button used to fire a POST and paint a tiny alert: no input, no output,
 * no sense of what the LLM was doing. This modal walks the round visibly:
 *
 *   输入(适应度信号) → 逐信号归因 + LLM 决策(思考过程,可中断) → 输出(提案/婉拒)
 *
 * Interruptible: the POST carries an AbortSignal; aborting flips the round to
 * an honest "已中断" state (the server may still finish writing rows) with
 * retry. Works in demo mode too — it drives the same API doors as the demo.
 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import { apiClient, ApiError } from '../../api/client'
import { keys } from '../../api/queries'
import { useI18n } from '../../i18n'
import { Badge, Button } from '../../components/ui'
import { ErrorBanner } from '../../components/ErrorBanner'
import { MutationDiff } from '../../components/MutationDiff'
import { IconCheck, IconRefresh, IconX } from '../../components/icons'
import type { Mutation, SignalRow } from '../../api/types'

type Phase = 'running' | 'done' | 'aborted' | 'error'

interface DiagnoseProposal {
  id: number
  gap_kind: string
  origin?: 'llm' | 'heuristic' | 'human'
  diff: Array<Record<string, string>>
  rationale: string
  analysis?: string | null
}

interface Decision {
  signal_id: number | null
  kind: string
  outcome: 'llm' | 'heuristic' | 'human' | 'declined' | 'informational' | 'skipped'
  analysis: string | null
  rationale: string | null
}

interface RoundResult {
  proposals: DiagnoseProposal[]
  decided_by?: { llm_decided?: number; llm_declined?: number; llm_rejected?: number; fallback?: number }
  decisions?: Decision[]
}

/** Rotating "what's happening" lines shown while the round is in flight — the
 *  backend is one POST, so progress is staged honestly (input read → model
 *  deciding → rule validation) rather than faked per-signal. */
const THINKING_STEPS = [
  'evolve.diag.think.1',
  'evolve.diag.think.2',
  'evolve.diag.think.3',
  'evolve.diag.think.4',
] as const

const OUTCOME_LABEL: Record<Decision['outcome'], { key: string; tone: 'violet' | 'neutral' | 'warning' | 'info' }> = {
  llm: { key: 'evolve.diag.outcome.llm', tone: 'violet' },
  heuristic: { key: 'evolve.diag.outcome.fallback', tone: 'neutral' },
  human: { key: 'evolve.diag.outcome.human', tone: 'info' },
  declined: { key: 'evolve.diag.outcome.declined', tone: 'warning' },
  informational: { key: 'evolve.diag.outcome.informational', tone: 'neutral' },
  skipped: { key: 'evolve.diag.outcome.skipped', tone: 'neutral' },
}

export function DiagnoseModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const [phase, setPhase] = useState<Phase>('running')
  const [stage, setStage] = useState<'signals' | 'diagnose'>('signals')
  const [inputSignals, setInputSignals] = useState<SignalRow[]>([])
  const [result, setResult] = useState<RoundResult | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [thought, setThought] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  // animate the thinking panel while the round is in flight
  useEffect(() => {
    if (phase !== 'running') return
    const tick = setInterval(() => {
      setThought((i) => (i + 1) % THINKING_STEPS.length)
      setElapsed((s) => s + 1)
    }, 1600)
    return () => clearInterval(tick)
  }, [phase])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && phase !== 'running') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, phase, onClose])

  const run = async () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setPhase('running')
    setStage('signals')
    setInputSignals([])
    setResult(null)
    setError(null)
    setElapsed(0)
    try {
      const sig = await apiClient.signals({ signal: ctrl.signal })
      if (!mounted.current || ctrl.signal.aborted) return
      setInputSignals(sig.signals)
      setStage('diagnose')
      const out = await apiClient.diagnose({ signal: ctrl.signal })
      if (!mounted.current || ctrl.signal.aborted) return
      setResult(out)
      setPhase('done')
      // the round wrote rows: refresh the console behind the dialog
      qc.invalidateQueries({ queryKey: keys.signals })
      qc.invalidateQueries({ queryKey: keys.proposals })
    } catch (e) {
      if (!mounted.current || ctrl.signal.aborted) return
      if (e instanceof ApiError && e.code === 'ABORTED') {
        setPhase('aborted')
      } else {
        setError(e instanceof ApiError ? e : new ApiError('ERROR', String(e), 0))
        setPhase('error')
      }
    }
  }

  // start (and re-start) on demand: every open runs a fresh round
  useEffect(() => {
    if (open) void run()
    return () => abortRef.current?.abort()
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null

  const created = result?.proposals ?? []
  const decisions = result?.decisions ?? []
  const noOutput = decisions.filter((d) => d.outcome === 'declined' || d.outcome === 'informational' || d.outcome === 'skipped')
  const decidedBy = result?.decided_by

  // portal to <body>: an ancestor carries a transform animation (ontogeny-animate-in)
  // which makes it the containing block for `fixed` — the backdrop would then
  // only cover the content column instead of the whole viewport
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.45)' }}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('evolve.diag.title')}
        data-testid="diagnose-dialog"
        className="ontogeny-card ontogeny-modal flex max-h-[88vh] w-full max-w-2xl flex-col p-5"
      >
        {/* header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{t('evolve.diag.title')}</h2>
            <p className="mt-0.5 text-[12px] muted">{t('evolve.diag.subtitle')}</p>
          </div>
          <button
            type="button"
            aria-label={t('common.cancel')}
            data-testid="diagnose-close"
            onClick={() => { abortRef.current?.abort(); onClose() }}
            className="grid size-7 shrink-0 place-items-center rounded-lg muted transition-colors"
            style={{ background: 'var(--surface-sunken)' }}
          >
            <IconX width={14} height={14} />
          </button>
        </div>

        {/* body */}
        <div className="mt-4 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-0.5">
          {/* 输入 */}
          <section data-testid="diagnose-input">
            <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.06em] muted">
              {t('evolve.diag.input')}
              {inputSignals.length ? <Badge tone="neutral" mono>{inputSignals.length}</Badge> : null}
            </div>
            {stage === 'signals' && phase === 'running' ? (
              <div className="rounded-lg px-3 py-2.5 text-[12px] muted" style={{ background: 'var(--surface-sunken)' }}>
                {t('evolve.diag.readingSignals')}
              </div>
            ) : inputSignals.length === 0 ? (
              <div className="rounded-lg px-3 py-2.5 text-[12px] muted" style={{ background: 'var(--surface-sunken)' }}>
                {t('evolve.noSignals')}
              </div>
            ) : (
              <ul className="flex max-h-28 flex-col gap-1 overflow-y-auto rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }}>
                {inputSignals.slice(0, 12).map((s) => (
                  <li key={s.id} className="flex items-center gap-2 text-[11.5px]">
                    <Badge tone="warning" mono>{s.kind}</Badge>
                    <span className="min-w-0 flex-1 truncate font-mono secondary-text">
                      {Object.entries(s.evidence).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
                    </span>
                    <span className="muted">#{s.id}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 过程 + LLM 思考 */}
          <section data-testid="diagnose-thinking" className="rounded-xl p-3.5" style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}>
            <div className="flex items-center gap-2">
              {phase === 'running' ? <span className="ontogeny-skeleton inline-block size-3 rounded-full" />
                : phase === 'aborted' ? <span className="text-[13px] font-bold leading-none" style={{ color: 'var(--tone-warning-fg)' }}>!</span>
                : <IconCheck width={14} height={14} style={{ color: 'var(--tone-success-fg)' }} />}
              <span className="text-[12.5px] font-medium">{phase === 'aborted' ? t('evolve.diag.stage.aborted') : stage === 'signals' ? t('evolve.diag.stage.signals') : t('evolve.diag.stage.diagnose')}</span>
              {phase === 'running' ? (
                <span className="ml-auto font-mono text-[11px] muted">{t('evolve.diag.elapsed', { s: elapsed })}</span>
              ) : null}
            </div>
            {phase === 'running' ? (
              <div className="mt-2.5 font-mono text-[11.5px]" style={{ color: 'var(--tone-info-fg, var(--text-secondary))' }} data-testid="diagnose-thinking-text">
                {t(THINKING_STEPS[thought])}
                <span className="ontogeny-skeleton ml-2 inline-block h-3 w-16 rounded" />
              </div>
            ) : decidedBy ? (
              <div className="mt-2 flex flex-wrap gap-1.5" title={t('evolve.decidedBy.hint')}>
                <Badge tone="violet" mono>LLM {decidedBy.llm_decided ?? 0}</Badge>
                <Badge tone="warning" mono>{t('evolve.diag.declinedShort')} {decidedBy.llm_declined ?? 0}</Badge>
                <Badge tone="danger" mono>{t('evolve.diag.rejectedShort')} {decidedBy.llm_rejected ?? 0}</Badge>
                <Badge tone="neutral" mono>{t('evolve.diag.fallbackShort')} {decidedBy.fallback ?? 0}</Badge>
              </div>
            ) : null}
          </section>

          {/* 输出 */}
          {phase === 'done' ? (
            <section data-testid="diagnose-output">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('evolve.diag.output')}</div>
              {created.length === 0 ? (
                <div className="rounded-lg px-3 py-2.5 text-[12px] muted" style={{ background: 'var(--surface-sunken)' }}>
                  {t('evolve.diag.none')}
                </div>
              ) : (
                <ul className="flex flex-col gap-3">
                  {created.map((p) => (
                    <li key={p.id} className="rounded-xl p-3.5" style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-[12.5px] font-semibold">#{p.id}</span>
                        <Badge tone="brand" mono>{p.gap_kind}</Badge>
                        {p.origin === 'llm' ? <Badge tone="violet" mono>LLM</Badge> : <Badge tone="neutral" mono>{t('evolve.origin.heuristic')}</Badge>}
                      </div>
                      {/* LLM 思考:分析在前,方案在后 */}
                      {p.analysis ? (
                        <p className="mt-2 rounded-lg px-2.5 py-2 text-[12px] leading-relaxed" style={{ background: 'var(--surface-card)' }} data-testid="diagnose-analysis">
                          <span className="font-semibold" style={{ color: 'var(--tone-violet-fg, var(--text-primary))' }}>{t('evolve.diag.thought')} </span>
                          {p.analysis}
                        </p>
                      ) : null}
                      <p className="mt-2 text-[12px] secondary-text"><span className="font-semibold">{t('proposal.rationale')} </span>{p.rationale}</p>
                      <div className="mt-2.5"><MutationDiff mutations={p.diff as Mutation[]} /></div>
                    </li>
                  ))}
                </ul>
              )}
              {/* 本轮未产出提案的信号:婉拒/信息型/已有提案在处理 */}
              {noOutput.length ? (
                <div className="mt-3">
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('evolve.diag.noOutputTitle')}</div>
                  <ul className="flex flex-col gap-1">
                    {noOutput.map((d, i) => (
                      <li key={i} className="flex items-center gap-2 text-[11.5px]">
                        <Badge tone="neutral" mono>{d.kind}</Badge>
                        <Badge tone={OUTCOME_LABEL[d.outcome].tone}>{t(OUTCOME_LABEL[d.outcome].key)}</Badge>
                        {d.signal_id != null ? <span className="muted">#{d.signal_id}</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}

          {/* 中断 / 错误 */}
          {phase === 'aborted' ? (
            <div className="rounded-lg px-3 py-2.5 text-[12px]" style={{ background: 'var(--tone-warning-bg)', color: 'var(--tone-warning-fg)' }} data-testid="diagnose-aborted">
              {t('evolve.diag.aborted')}
            </div>
          ) : null}
          {error ? <ErrorBanner error={error} /> : null}
        </div>

        {/* footer */}
        <div className="mt-4 flex items-center justify-end gap-2 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          {phase === 'running' ? (
            <Button
              variant="danger"
              data-testid="diagnose-abort"
              onClick={() => { abortRef.current?.abort(); setPhase('aborted') }}
            >
              {t('evolve.diag.abort')}
            </Button>
          ) : (
            <>
              <Button
                data-testid="diagnose-retry"
                onClick={() => void run()}
                icon={<IconRefresh width={14} height={14} />}
              >
                {t('evolve.diag.rerun')}
              </Button>
              <Button variant="primary" data-testid="diagnose-done" onClick={onClose}>{t('settings.done')}</Button>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
