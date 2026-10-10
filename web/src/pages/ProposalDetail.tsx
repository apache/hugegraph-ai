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
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { invalidateMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Page, Badge, Button, Card, KeyValue, ProgressBar, Skeleton, toneForStatus } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { EvalReport } from '../components/EvalReport'
import { JsonView } from '../components/JsonView'
import { MutationDiff } from '../components/MutationDiff'
import { IconArrowLeft, IconPlay, IconSpark } from '../components/icons'
import type { Mutation } from '../api/types'

export function ProposalDetail() {
  const { id = '' } = useParams()
  const { t } = useI18n()
  const qc = useQueryClient()
  const proposal = useQuery({ queryKey: ['proposal', id], queryFn: () => apiClient.proposal(Number(id)) })
  const [promoteResult, setPromoteResult] = useState<Record<string, unknown> | null>(null)

  const evaluate = useMutation({
    mutationFn: () => apiClient.evalProposal(Number(id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['proposal', id] }),
  })
  const promote = useMutation({
    mutationFn: () => apiClient.promoteProposal(Number(id)),
    onSuccess: (r) => {
      setPromoteResult(r as Record<string, unknown>)
      // a promotion republishes the package: its own record, the list and the
      // compiled snapshot all move; nothing else does
      qc.invalidateQueries({ queryKey: ['proposal', id] })
      qc.invalidateQueries({ queryKey: ['proposals'] })
      invalidateMeta(qc)
    },
  })

  if (proposal.isLoading) return <Skeleton rows={6} />
  if (proposal.error) return <ErrorBanner error={proposal.error} />
  const p = proposal.data!
  const suites = p.eval_report?.suites ?? {}
  const suiteNames = Object.keys(suites)
  // proposed / evaluated are the live states a human can act on; settled
  // proposals (merged / rejected / superseded) only tell their history
  const actionable = p.status === 'proposed' || p.status === 'evaluated'

  return (
    <Page>
      <h1 className="sr-only">{`${t('proposal.title')} #${p.id}`}</h1>

      <div className="grid items-start gap-5 lg:grid-cols-[1.4fr_1fr]">
        <div className="flex flex-col gap-5">
          {/* breadcrumb, proposal id and its status chips live on the diff
              panel: it is the page's one primary surface */}
          <Card
            title={
              <span className="flex items-center gap-2">
                <Link className="ontogeny-link inline-flex items-center gap-1 text-[12.5px] muted" to="/evolve">
                  <IconArrowLeft width={13} height={13} />
                  {t('nav.evolve')}
                </Link>
                <span className="muted">/</span>
                <span>{t('proposal.title')} #{p.id}</span>
              </span>
            }
            description={p.rationale}
            actions={
              <span className="flex items-center gap-2">
                <Badge tone={toneForStatus(p.status)}>{t(`proposal.${p.status}`)}</Badge>
                {p.tier ? <Badge tone={toneForStatus(p.tier)} mono>{p.tier}</Badge> : null}
                {p.origin === 'llm' ? <Badge tone="violet" mono title={t('evolve.origin.llmHint')}>LLM</Badge> : null}
              </span>
            }
          >
            <MutationDiff mutations={(p.diff ?? []) as Mutation[]} />
          </Card>

          <Card
            title={t('proposal.eval')}
            // the run button sits on the section header, next to what it
            // produces; re-runs overwrite the report, so it grays out only
            // while a run is in flight
            actions={actionable ? (
              <Button size="sm" onClick={() => evaluate.mutate()} disabled={evaluate.isPending} data-testid="eval-proposal" icon={<IconPlay width={13} height={13} />}>
                {evaluate.isPending ? t('proposal.evalRunning') : t('proposal.runEval')}
              </Button>
            ) : undefined}
          >
            {suiteNames.length === 0 ? (
              <p className="text-[12.5px] muted">{t('proposal.evalEmpty')}</p>
            ) : (
              <EvalReport suites={suites} passed={p.eval_report?.passed} />
            )}
            {evaluate.error ? <div className="mt-3"><ErrorBanner error={evaluate.error} /></div> : null}
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card title={t('proposal.promote')} description={t('proposal.promoteHint')}>
            {actionable ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => promote.mutate()} disabled={promote.isPending} data-testid="promote-proposal" icon={<IconSpark width={14} height={14} />}>
                  {promote.isPending ? t('proposal.promoting') : t('proposal.promote')}
                </Button>
              </div>
            ) : (
              <p className="text-[12px] muted">{t('proposal.settled')}</p>
            )}
            {promote.error ? (
              <div className="mt-3">
                <ErrorBanner
                  error={promote.error}
                  hint={(promote.error as { code?: string }).code === 'CONSTITUTION_VIOLATION' ? t('proposal.constitution') : undefined}
                />
              </div>
            ) : null}
            {promoteResult ? (
              <div className="mt-3" data-testid="promote-result">
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
              <div className="mt-3">
                <ProgressBar
                  value={Number(promoteResult.budget_used ?? 0)}
                  max={Number(promoteResult.budget_cap)}
                  label={<><span>T0 budget</span><span>{String(promoteResult.budget_used)}/{String(promoteResult.budget_cap)}</span></>}
                />
              </div>
            ) : null}
          </Card>
        </div>
      </div>
    </Page>
  )
}
