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
 * ProposalModal — a change proposal opened in place.
 *
 * Clicking a proposal used to navigate to /evolve/:id, yanking the user off
 * the console. The modal keeps them on the page: same content as the detail
 * route (diff, eval report, promotion, budget), same testids, and the route
 * still exists for deep links.
 */
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { invalidateMeta } from '../../api/queries'
import { useI18n } from '../../i18n'
import { Badge, Button, KeyValue, ProgressBar, Skeleton, toneForStatus } from '../../components/ui'
import { ErrorBanner } from '../../components/ErrorBanner'
import { JsonView } from '../../components/JsonView'
import { MutationDiff } from '../../components/MutationDiff'
import { EvalReport } from '../../components/EvalReport'
import { IconPlay, IconSpark, IconX } from '../../components/icons'
import type { Mutation } from '../../api/types'

export function ProposalModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const proposal = useQuery({
    queryKey: ['proposal', id],
    queryFn: () => apiClient.proposal(id!),
    enabled: id != null,
  })
  const [promoteResult, setPromoteResult] = useState<Record<string, unknown> | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  const evaluate = useMutation({
    mutationFn: () => apiClient.evalProposal(id!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['proposal', id] }),
  })
  const promote = useMutation({
    mutationFn: () => apiClient.promoteProposal(id!),
    onSuccess: (r) => {
      setPromoteResult(r as Record<string, unknown>)
      qc.invalidateQueries({ queryKey: ['proposal', id] })
      qc.invalidateQueries({ queryKey: ['proposals'] })
      invalidateMeta(qc)
    },
  })
  const reject = useMutation({
    mutationFn: () => apiClient.rejectProposal(id!, rejectReason.trim()),
    onSuccess: () => {
      setRejectOpen(false)
      setRejectReason('')
      qc.invalidateQueries({ queryKey: ['proposal', id] })
      qc.invalidateQueries({ queryKey: ['proposals'] })
    },
  })

  if (id == null) return null
  const p = proposal.data
  const suites = p?.eval_report?.suites ?? {}
  const suiteNames = Object.keys(suites)
  // proposed / evaluated are the live states a human can act on; promoted,
  // rejected and superseded proposals are settled history (the status badge
  // already says which), so the actions hide instead of erroring on click
  const actionable = p != null && (p.status === 'proposed' || p.status === 'evaluated')

  // portal to <body>: the page's transform animation (ontogeny-animate-in) would
  // otherwise become the containing block for this `fixed` backdrop and clip
  // it to the content column
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.45)' }} onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('proposal.title')}
        data-testid="proposal-dialog"
        className="ontogeny-card ontogeny-modal flex max-h-[88vh] w-full max-w-2xl flex-col p-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[14px] font-semibold">{t('proposal.title')} #{id}</h2>
              {p ? (
                <>
                  <Badge tone={toneForStatus(p.status)}>{t(`proposal.${p.status}`)}</Badge>
                  {p.tier ? <Badge tone={toneForStatus(p.tier)} mono>{p.tier}</Badge> : null}
                  {p.origin === 'llm' ? <Badge tone="violet" mono title={t('evolve.origin.llmHint')}>LLM</Badge> : null}
                </>
              ) : null}
            </div>
            {p ? <p className="mt-1 text-[12px] secondary-text">{p.rationale}</p> : null}
            {p?.llm_analysis ? (
              <div className="mt-2 rounded-lg p-2.5" style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
                   data-testid="proposal-llm-analysis">
                <div className="ontogeny-label mb-1">{t('proposal.llmAnalysis')}</div>
                <p className="whitespace-pre-wrap text-[12px] leading-relaxed secondary-text">{p.llm_analysis}</p>
              </div>
            ) : null}
            {p?.rejected_reason ? (
              <p className="mt-1 text-[12px]" style={{ color: 'var(--tone-danger-fg)' }} data-testid="proposal-rejected-reason">
                {t('proposal.rejectedReason')}: {p.rejected_reason}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            aria-label={t('common.cancel')}
            data-testid="proposal-dialog-close"
            onClick={onClose}
            className="grid size-7 shrink-0 place-items-center rounded-lg muted transition-colors"
            style={{ background: 'var(--surface-sunken)' }}
          >
            <IconX width={14} height={14} />
          </button>
        </div>

        {/* body */}
        <div className="mt-4 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-0.5">
          {proposal.isLoading ? <Skeleton rows={5} />
            : proposal.error ? <ErrorBanner error={proposal.error} />
              : p ? (
                <>
                  <section>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('proposal.diff')}</div>
                    <MutationDiff mutations={(p.diff ?? []) as Mutation[]} />
                  </section>

                  <section>
                    {/* the eval button lives on its section's header: what it
                        produces (the report below) and what triggers it read
                        as one unit. Re-runs overwrite the report, so the
                        button stays enabled -- it only grays out while a run
                        is in flight, with the label saying so. */}
                    <div className="mb-1.5 flex items-center justify-between gap-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('proposal.eval')}</div>
                      {actionable ? (
                        <Button size="sm" onClick={() => evaluate.mutate()} disabled={evaluate.isPending} data-testid="eval-proposal" icon={<IconPlay width={13} height={13} />}>
                          {evaluate.isPending ? t('proposal.evalRunning') : t('proposal.runEval')}
                        </Button>
                      ) : null}
                    </div>
                    {suiteNames.length === 0 ? (
                      <p className="text-[12.5px] muted">{t('proposal.evalEmpty')}</p>
                    ) : (
                      <EvalReport suites={suites} passed={p.eval_report?.passed} />
                    )}
                    {evaluate.error ? <div className="mt-2.5"><ErrorBanner error={evaluate.error} /></div> : null}
                  </section>

                  <section>
                    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('proposal.promote')}</div>
                    {/* what the button actually does, before the user clicks it */}
                    <p className="text-[12px] leading-relaxed secondary-text">{t('proposal.promoteHint')}</p>
                    {actionable ? (
                      <div className="mt-2.5 flex flex-wrap gap-2">
                        <Button size="sm" variant="primary" onClick={() => promote.mutate()} disabled={promote.isPending} data-testid="promote-proposal" icon={<IconSpark width={13} height={13} />}>
                          {promote.isPending ? t('proposal.promoting') : t('proposal.promote')}
                        </Button>
                        <Button size="sm" variant="subtle" onClick={() => setRejectOpen((v) => !v)} data-testid="reject-toggle" icon={<IconX width={13} height={13} />}>
                          {t('proposal.reject')}
                        </Button>
                      </div>
                    ) : (
                      <p className="mt-2.5 text-[12px] muted">{t('proposal.settled')}</p>
                    )}
                    {rejectOpen ? (
                      <div className="mt-2.5 flex items-center gap-2" data-testid="reject-row">
                        <input className="ontogeny-input min-w-0 flex-1" value={rejectReason}
                               placeholder={t('proposal.rejectPlaceholder')} data-testid="reject-reason"
                               onChange={(e) => setRejectReason(e.target.value)} />
                        <Button size="sm" variant="primary" disabled={reject.isPending || !rejectReason.trim()}
                                data-testid="reject-confirm" onClick={() => reject.mutate()}>
                          {t('common.confirm')}
                        </Button>
                      </div>
                    ) : null}
                    {promote.error ? (
                      <div className="mt-2.5">
                        <ErrorBanner
                          error={promote.error}
                          hint={(promote.error as { code?: string }).code === 'CONSTITUTION_VIOLATION' ? t('proposal.constitution') : undefined}
                        />
                      </div>
                    ) : null}
                    {promoteResult ? (
                      <div className="mt-2.5" data-testid="promote-result">
                        <KeyValue
                          items={Object.entries(promoteResult).map(([k, v]) => ({
                            key: k,
                            value: typeof v === 'object' ? <JsonView value={v} /> : String(v),
                            mono: typeof v === 'string',
                          }))}
                        />
                      </div>
                    ) : null}
                    {promoteResult && typeof promoteResult.budget_cap === 'number' ? (
                      <div className="mt-2.5">
                        <ProgressBar
                          value={Number(promoteResult.budget_used ?? 0)}
                          max={Number(promoteResult.budget_cap)}
                          label={<><span>T0 budget</span><span>{String(promoteResult.budget_used)}/{String(promoteResult.budget_cap)}</span></>}
                        />
                      </div>
                    ) : null}
                  </section>
                </>
              ) : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}
