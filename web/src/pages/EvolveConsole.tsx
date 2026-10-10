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
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { keys } from '../api/queries'
import { apiClient } from '../api/client'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, Page, toneForStatus } from '../components/ui'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'
import { IconRefresh, IconShield, IconSpark, IconTrash } from '../components/icons'
import { EvolveDemo } from './evolve/EvolveDemo'
import { DiagnoseModal } from './evolve/DiagnoseModal'
import { ProposalModal } from './evolve/ProposalModal'
import { LoopStrip } from './evolve/LoopStrip'
import type { ProposalSummary, SignalRow } from '../api/types'

/** True while the one-click demo is mid-run. The demo mutates the same tables
 *  as the standalone buttons, so the buttons step aside while it runs. */
function useDemoRunning(): boolean {
  const [running, setRunning] = useState(false)
  useEffect(() => {
    const on = () => setRunning(true)
    const off = () => setRunning(false)
    window.addEventListener('ontogeny-demo-start', on)
    window.addEventListener('ontogeny-demo-end', off)
    return () => { window.removeEventListener('ontogeny-demo-start', on); window.removeEventListener('ontogeny-demo-end', off) }
  }, [])
  return running
}

/** Number colour per vitals tone (a zeroed counter stays neutral). */
const toneFg: Record<string, string> = {
  warning: 'var(--tone-warning-fg)',
  success: 'var(--tone-success-fg)',
  info: 'var(--tone-info-fg)',
}

export function EvolveConsole() {
  const { t } = useI18n()
  const qc = useQueryClient()
  const demoRunning = useDemoRunning()
  const signals = useQuery({ queryKey: keys.signals, queryFn: () => apiClient.signals() })
  const proposals = useQuery({ queryKey: keys.proposals, queryFn: () => apiClient.proposals() })

  // dialogs: ② runs its round in place; a clicked proposal opens in place too
  const [diagOpen, setDiagOpen] = useState(false)
  const [openProposal, setOpenProposal] = useState<number | null>(null)

  const aggregate = useMutation({
    mutationFn: () => apiClient.aggregateSignals(),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.signals }),
  })
  const removeSignal = useMutation({
    mutationFn: (id: number) => apiClient.deleteSignal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.signals }),
  })
  const removeProposal = useMutation({
    mutationFn: (id: number) => apiClient.deleteProposal(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.proposals })
      setOpenProposal(null)
    },
  })

  const list = proposals.data?.proposals ?? []
  const promotedCount = list.filter((p) => p.status === 'promoted').length
  const signalCount = signals.data?.signals.length ?? 0

  const vitals = [
    { label: t('evolve.hero.stat.signals'), value: signalCount, tone: signalCount > 0 ? 'warning' : 'success' },
    { label: t('evolve.hero.stat.proposals'), value: list.length, tone: 'info' },
    { label: t('evolve.hero.stat.promoted'), value: promotedCount, tone: 'success' },
  ] as const

  const columns: Array<Column<ProposalSummary>> = [
    { key: 'id', label: t('evolve.id'), render: (r) => <span className="ontogeny-link font-mono">#{r.id}</span> },
    { key: 'gap_kind', label: t('evolve.gapKind'), render: (r) => <span className="font-mono text-[12px]">{r.gap_kind}</span> },
    // provenance: who decided this mutation -- the model, or the fallback
    { key: 'origin', label: t('evolve.origin'), render: (r) => (
      r.origin === 'llm'
        ? <Badge tone="violet" mono title={t('evolve.origin.llmHint')}>LLM</Badge>
        : r.origin === 'human'
          ? <Badge tone="info">{t('evolve.origin.human')}</Badge>
          : <Badge tone="neutral" mono title={t('evolve.origin.heuristicHint')}>{t('evolve.origin.heuristic')}</Badge>
    ) },
    { key: 'tier', label: t('evolve.tier'), render: (r) => r.tier ? <Badge tone={toneForStatus(r.tier)} mono>{r.tier}</Badge> : <span className="muted">—</span> },
    { key: 'status', label: t('evolve.status'), render: (r) => <Badge tone={toneForStatus(r.status)}>{t(`proposal.${r.status}`)}</Badge> },
    {
      key: 'actions', label: '', align: 'right',
      render: (r) => (
        <Button
          size="sm"
          square
          variant="subtle"
          data-testid={`delete-proposal-${r.id}`}
          title={t('evolve.deleteProposal')}
          aria-label={t('evolve.deleteProposal')}
          onClick={(e) => { e.stopPropagation(); removeProposal.mutate(r.id) }}
          icon={<IconTrash width={13} height={13} />}
          style={{ color: 'var(--tone-danger-fg)' }}
        />
      ),
    },
  ]

  // same table rhythm as the proposals card on the right: id · kind · the
  // evidence itself · a right-aligned delete action
  const signalColumns: Array<Column<SignalRow>> = [
    { key: 'id', label: t('evolve.id'), render: (r) => <span className="muted font-mono">#{r.id}</span> },
    { key: 'kind', label: t('evolve.kind'), render: (r) => <Badge tone="warning" mono>{r.kind}</Badge> },
    {
      key: 'evidence', label: t('evolve.evidence'),
      render: (r) => (
        <span className="font-mono text-[12px] secondary-text">
          {Object.entries(r.evidence).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}
        </span>
      ),
    },
    {
      key: 'actions', label: '', align: 'right',
      render: (r) => (
        <Button
          size="sm"
          square
          variant="subtle"
          data-testid={`delete-signal-${r.id}`}
          title={t('evolve.deleteSignal')}
          aria-label={t('evolve.deleteSignal')}
          disabled={removeSignal.isPending}
          onClick={() => removeSignal.mutate(r.id)}
          icon={<IconTrash width={13} height={13} />}
          style={{ color: 'var(--tone-danger-fg)' }}
        />
      ),
    },
  ]

  return (
    <Page>
      {/* hero: the loop's identity — a visible title, the one-line RSI story and
          the live vitals, so the page states what self-evolution IS before the
          two data cards show what it produced */}
      <section
        data-testid="evolve-hero"
        className="relative overflow-hidden rounded-2xl"
        style={{
          background: 'linear-gradient(115deg, var(--tone-brand-bg) 0%, var(--surface-card) 46%, var(--tone-violet-bg) 115%)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:gap-7">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg" style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}>
                <IconSpark width={16} height={16} />
              </span>
              <h1 className="text-[17px] font-bold tracking-tight">{t('evolve.title')}</h1>
              <Badge tone="brand" mono>{t('evolve.hero.badge')}</Badge>
              {/* the bounded-recursion badge: the headline promise is not just
                  "recursive" but "bounded" -- the badge and the line below it
                  say together what the system may and may not evolve */}
              <Badge tone="warning">{t('evolve.hero.boundedBadge')}</Badge>
            </div>
            <p className="mt-2 max-w-3xl text-[12.5px] leading-relaxed secondary-text">
              {t('evolve.hero.subtitle')}
            </p>
            {/* the boundedness statement, set apart so it reads as a term of
                the contract, not more marketing copy */}
            <div
              className="mt-3 flex max-w-3xl items-start gap-2.5 rounded-xl px-3.5 py-2.5"
              style={{ background: 'var(--surface-card)', border: '1px dashed var(--border-strong)' }}
              data-testid="evolve-bounded"
            >
              <span className="mt-[2px] shrink-0" style={{ color: 'var(--tone-warning-fg)' }} aria-hidden="true">
                <IconShield width={14} height={14} />
              </span>
              <p className="min-w-0 text-[12px] leading-relaxed secondary-text">
                <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{t('evolve.hero.boundedBadge')}：</span>
                {t('evolve.hero.bounded')}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            {vitals.map((v) => (
              <div
                key={v.label}
                title={v.label}
                className="min-w-[96px] rounded-xl px-3.5 py-2.5"
                style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}
              >
                <div className="text-[18px] font-bold leading-none tnum" style={{ color: v.value > 0 ? toneFg[v.tone] : 'var(--text-primary)' }}>
                  {v.value}
                </div>
                <div className="mt-1.5 truncate text-[10.5px] muted">{v.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* the loop spine; the two loop actions live on the cards they drive —
          ① aggregates into the signal feed, ② diagnoses into the proposal
          table — so each trigger sits on its own output */}
      <div className="flex flex-wrap items-center gap-3">
        <LoopStrip className="min-w-0 flex-1" />
        <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">
          <Button
            square
            onClick={() => { signals.refetch(); proposals.refetch() }}
            icon={<IconRefresh width={15} height={15} />}
            data-testid="evolve-refresh"
            title={t('common.refresh')}
            aria-label={t('common.refresh')}
          />
          <EvolveDemo onFinished={() => { signals.refetch(); proposals.refetch() }} />
        </div>
      </div>

      {/* the one-click demo portals its run panel here (a card cannot live in
          the action row) */}
      <div id="ontogeny-demo-slot" />

      <div className="grid gap-5 lg:grid-cols-[1fr_1.15fr]">
        <Card
          className="h-full"
          title={t('evolve.signals')}
          description={t('evolve.signalsHint')}
          actions={
            <span className="flex items-center gap-2">
              {signalCount ? <Badge tone="neutral" mono>{signalCount}</Badge> : null}
              <Button
                size="sm"
                onClick={() => aggregate.mutate()}
                disabled={aggregate.isPending || demoRunning}
                data-testid="aggregate-signals"
              >
                {t('evolve.step1')}
              </Button>
            </span>
          }
          padded={false}
        >
          {/* the aggregate result belongs to this card: it lands right above
              the feed the new signals joined */}
          {aggregate.error ? <div className="px-5 pt-4"><ErrorBanner error={aggregate.error} /></div> : null}
          {aggregate.data ? (
            <div className="px-5 pt-4">
              <Alert tone="info" testId="aggregate-summary">
                {aggregate.data.created.length
                  ? t('evolve.aggregateCreated', { count: aggregate.data.created.length, kinds: aggregate.data.created.map((x) => x.kind).join(' · ') })
                  : t('evolve.aggregateNone')}
              </Alert>
            </div>
          ) : null}
          {/* an unreadable signal feed must not render as "no signals found" —
              on this page the empty state is a *finding*, not a blank slate */}
          {signals.error ? (
            <div className="px-5 pb-5 pt-4"><ErrorBanner error={signals.error} /></div>
          ) : (
            <DataTable
              columns={signalColumns}
              rows={signals.data?.signals.slice(0, 14) ?? []}
              rowKey={(r) => String(r.id)}
              loading={signals.isLoading}
              empty={t('evolve.noSignals')}
            />
          )}
        </Card>

        <Card
          className="h-full"
          title={t('evolve.proposals')}
          description={t('evolve.proposalsHint')}
          actions={
            <span className="flex items-center gap-2">
              {list.length ? (
                <span className="flex items-center gap-1.5">
                  <Badge tone="neutral" mono>{list.length}</Badge>
                  {promotedCount ? <Badge tone="success" mono>✓ {promotedCount}</Badge> : null}
                </span>
              ) : null}
              {/* the round runs inside a dialog: input, thinking, output,
                  abortable -- also while the one-click demo is running (same
                  API doors) */}
              <Button size="sm" onClick={() => setDiagOpen(true)} data-testid="diagnose-signals">
                {t('evolve.step2')}
              </Button>
            </span>
          }
        >
          {proposals.error ? <ErrorBanner error={proposals.error} /> : (
            <DataTable
              columns={columns}
              rows={list}
              rowKey={(r) => String(r.id)}
              onRowClick={(r) => setOpenProposal(r.id)}
              loading={proposals.isLoading}
              empty={t('evolve.noProposals')}
            />
          )}
          <div className="mt-3 flex items-center gap-2 text-[12px] muted">
            <IconSpark width={13} height={13} />
            {t('evolve.tierHint')}
          </div>
        </Card>
      </div>

      <DiagnoseModal open={diagOpen} onClose={() => setDiagOpen(false)} />
      <ProposalModal id={openProposal} onClose={() => setOpenProposal(null)} />
    </Page>
  )
}
