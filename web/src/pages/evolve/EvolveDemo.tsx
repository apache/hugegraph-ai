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
 * EvolveDemo — the one-click walk-through of the evolution loop.
 *
 * Every step goes through the same API doors a real user or agent uses (the
 * queries even generate their own telemetry through the normal path), so what
 * the demo proves is the system, not a script:
 *
 *   缺口 → 真实流量 → ① 信号 → ② 提案 → 评测 → 晋升(T0) → 生效验证
 *
 * Repeatability: step 1 picks the first not-yet-modelled field from a candidate
 * list, so each run closes the loop on a fresh gap; once every candidate is
 * modelled the run ends in the loop's true steady state ("converged") instead
 * of faking another cycle. `ontogeny serve --demo --reseed` resets everything.
 */
import { useCallback, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { apiClient, ApiError } from '../../api/client'
import { keys, useMeta } from '../../api/queries'
import { useI18n } from '../../i18n'
import { Badge, Button, Card } from '../../components/ui'
import { IconCheck, IconSpark, IconX } from '../../components/icons'

type StepStatus = 'pending' | 'running' | 'ok' | 'warn' | 'fail'

interface DemoStep {
  id: string
  title: string
  status: StepStatus
  detail?: string
  /** Link shown beside the detail (proposal, type detail …). */
  to?: { href: string; label: string }
}

const CANDIDATE_FIELDS = ['zone', 'line', 'batch_code', 'station']
/** Target objects in order of preference — the first one declared by the served
 *  package wins. The demo must adapt to whatever package is loaded (the story
 *  packages differ), and equipment reads best: "users keep filtering machines
 *  by their line/zone" is a gap a plant can feel. */
const DEMO_OBJECTS = ['equipment', 'sales-order', 'customer', 'work-order']

/** One filtered query round: the rejected ones ARE the signal. */
async function probeField(type: string, field: string): Promise<{ rejected: number; ok: number }> {
  let rejected = 0
  let ok = 0
  for (let i = 0; i < 6; i += 1) {
    try {
      await apiClient.queryObjects(type, { filter: { field, op: 'eq', value: 'L1' }, limit: 5 })
      ok += 1
    } catch {
      rejected += 1
    }
  }
  return { rejected, ok }
}

async function probeEmpty(type: string, field: string): Promise<number> {
  let empty = 0
  for (let i = 0; i < 2; i += 1) {
    try {
      const out = await apiClient.queryObjects(type, {
        filter: { field, op: 'eq', value: '__no_such_value__' }, limit: 5,
      })
      if (out.total === 0) empty += 1
    } catch { /* an errored probe still fed telemetry; count nothing */ }
  }
  return empty
}

export function EvolveDemo({ onFinished }: { onFinished?: () => void }) {
  const { t } = useI18n()
  const meta = useMeta()
  const qc = useQueryClient()
  const [steps, setSteps] = useState<DemoStep[]>([])
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState<null | 'ok' | 'converged' | 'stopped'>(null)
  const mounted = useRef(true)

  const patch = useCallback((id: string, patchStep: Partial<DemoStep>) => {
    if (!mounted.current) return
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, ...patchStep } : s)))
  }, [])

  const run = useCallback(async () => {
    if (running || !meta.data) return
    mounted.current = true
    setRunning(true)
    setDone(null)
    window.dispatchEvent(new Event('ontogeny-demo-start'))
    const initial: DemoStep[] = [
      { id: 'prepare', title: t('evolve.demo.step.prepare'), status: 'pending' },
      { id: 'traffic', title: t('evolve.demo.step.traffic'), status: 'pending' },
      { id: 'aggregate', title: t('evolve.demo.step.aggregate'), status: 'pending' },
      { id: 'diagnose', title: t('evolve.demo.step.diagnose'), status: 'pending' },
      { id: 'eval', title: t('evolve.demo.step.eval'), status: 'pending' },
      { id: 'promote', title: t('evolve.demo.step.promote'), status: 'pending' },
      { id: 'verify', title: t('evolve.demo.step.verify'), status: 'pending' },
    ]
    setSteps(initial)

    const finish = (outcome: 'ok' | 'converged' | 'stopped') => {
      if (mounted.current) { setRunning(false); setDone(outcome) }
      window.dispatchEvent(new Event('ontogeny-demo-end'))
      onFinished?.()
    }

    try {
      // ---- 1. pick the gap -------------------------------------------------
      patch('prepare', { status: 'running' })
      const snap = (await apiClient.meta())
      const objectType = DEMO_OBJECTS.find((t) => t in snap.objects) ?? Object.keys(snap.objects)[0]
      const properties = Object.keys(snap.objects[objectType].properties)
      const field = CANDIDATE_FIELDS.find((f) => !properties.includes(f))
      if (!field) {
        patch('prepare', { status: 'warn', detail: t('evolve.demo.noCandidate') })
        finish('converged')
        return
      }
      patch('prepare', { status: 'ok', detail: t('evolve.demo.prepOk', { type: objectType, field }) })

      // ---- 2. real traffic through the real query door ---------------------
      patch('traffic', { status: 'running' })
      const probes = await probeField(objectType, field)
      const probeField2 = Object.keys(snap.objects[objectType].properties)[0] ?? 'status'
      const empties = await probeEmpty(objectType, probeField2)
      patch('traffic', {
        status: 'ok',
        detail: t('evolve.demo.trafficOk', { rejected: probes.rejected, field, empty: empties }),
      })

      // ---- 3. ① aggregate ---------------------------------------------------
      patch('aggregate', { status: 'running' })
      const aggregated = await apiClient.aggregateSignals()
      const created = aggregated.created ?? []
      patch('aggregate', {
        status: 'ok',
        detail: created.length
          ? t('evolve.demo.aggOk', { count: created.length, kinds: created.map((s) => s.kind).join(' · ') })
          : t('evolve.demo.aggNone'),
      })

      // ---- 4. ② diagnose ----------------------------------------------------
      patch('diagnose', { status: 'running' })
      const diagnosed = await apiClient.diagnose()
      const proposal = diagnosed.proposals[0]
      if (!proposal) {
        patch('diagnose', { status: 'warn', detail: t('evolve.demo.diagNone') })
        finish('converged')
        return
      }
      const mutation = proposal.diff[0] as { object?: string; prop?: string; display?: string } | undefined
      const by = diagnosed.decided_by
      patch('diagnose', {
        status: 'ok',
        detail: t('evolve.demo.diagOk', {
          id: proposal.id,
          kind: proposal.gap_kind,
          target: mutation ? `${mutation.object}.${mutation.prop}` : proposal.gap_kind,
          who: proposal.origin === 'llm'
            ? t('evolve.demo.byLlm', { display: mutation?.display ?? '' })
            : t('evolve.demo.byRules'),
          meta: by ? t('evolve.demo.roundMeta', {
            llm: by.llm_decided ?? 0, declined: by.llm_declined ?? 0,
            rejected: by.llm_rejected ?? 0, fallback: by.fallback ?? 0,
          }) : '',
        }),
      })

      // ---- 5. eval -----------------------------------------------------------
      patch('eval', { status: 'running' })
      const evalResult = await apiClient.evalProposal(proposal.id)
      if (!evalResult.passed) {
        patch('eval', { status: 'fail', detail: t('evolve.demo.evalRed') })
        finish('stopped')
        return
      }
      patch('eval', { status: 'ok', detail: t('evolve.demo.evalOk') })

      // ---- 6. promote ---------------------------------------------------------
      patch('promote', { status: 'running' })
      let promoted: Awaited<ReturnType<typeof apiClient.promoteProposal>>
      try {
        promoted = await apiClient.promoteProposal(proposal.id)
      } catch (e) {
        const code = e instanceof ApiError ? e.code : 'ERROR'
        patch('promote', {
          status: 'fail',
          detail: t('evolve.demo.promoteFail', { reason: e instanceof ApiError ? e.message : String(e) }),
        })
        if (code === 'CONSTITUTION_VIOLATION') {
          patch('promote', { status: 'warn', detail: t('evolve.demo.promoteHuman', { tier: 't3', reason: t('proposal.constitution') }) })
        }
        finish('stopped')
        return
      }
      if (promoted.status !== 'promoted') {
        patch('promote', { status: 'warn', detail: t('evolve.demo.promoteHuman', { tier: promoted.tier ?? '—', reason: promoted.reason ?? '' }) })
        finish('stopped')
        return
      }
      patch('promote', {
        status: 'ok',
        detail: t('evolve.demo.promoteT0', {
          used: promoted.budget_used ?? '—',
          cap: promoted.budget_cap ?? '—',
          hash: (promoted.content_hash ?? '').slice(0, 8),
        }),
      })

      // ---- 7. verify: the original failing query now goes through ------------
      patch('verify', { status: 'running' })
      let verifyOut: { rejected: number; ok: number }
      try {
        verifyOut = await probeField(objectType, field)
      } catch {
        verifyOut = { rejected: 6, ok: 0 }
      }
      const snapAfter = await apiClient.meta()
      const nowModelled = field in (snapAfter.objects[objectType]?.properties ?? {})
      if (verifyOut.ok === 0 && !nowModelled) {
        patch('verify', { status: 'fail', detail: t('evolve.demo.verifyFail', { reason: 'query still rejected' }) })
        finish('stopped')
        return
      }
      patch('verify', {
        status: 'ok',
        detail: t('evolve.demo.verifyOk', { type: objectType, field }),
        to: { href: `/ontology/${objectType}`, label: t('data.openType') },
      })
      // the published snapshot changed: drop every cached meta consumer
      qc.invalidateQueries({ queryKey: keys.meta })
      finish('ok')
    } catch (e) {
      // a step failed mid-flight: mark the first pending step as its failure
      setSteps((prev) => {
        const idx = prev.findIndex((s) => s.status === 'running' || s.status === 'pending')
        return idx >= 0
          ? prev.map((s, i) => (i === idx ? { ...s, status: 'fail', detail: e instanceof ApiError ? `${e.code}: ${e.message}` : String(e) } : s))
          : prev
      })
      finish('stopped')
    }
  }, [running, meta.data, patch, qc, t, onFinished])

  // The launcher lives in the header; the run panel must NOT (a card squeezed
  // into the header's action row), so it portals into the page-level slot.
  const launcher = (
    <Button
      variant="primary"
      data-testid="demo-run"
      disabled={running || meta.isLoading}
      onClick={run}
      icon={<IconSpark width={14} height={14} />}
    >
      {t('evolve.demo.run')}
    </Button>
  )
  if (steps.length === 0) return launcher


  const statusIcon = (status: StepStatus) => {
    if (status === 'running') return <span className="ontogeny-skeleton inline-block size-3 rounded-full" />
    if (status === 'ok') return <IconCheck width={13} height={13} className="shrink-0" style={{ color: 'var(--tone-success-fg)' }} />
    if (status === 'warn') return <span className="text-[13px] leading-none" style={{ color: 'var(--tone-warning-fg)' }}>!</span>
    if (status === 'fail') return <IconX width={13} height={13} className="shrink-0" style={{ color: 'var(--tone-danger-fg)' }} />
    return <span className="inline-block size-1.5 rounded-full" style={{ background: 'var(--border-strong)' }} />
  }

  const panel = (
    <Card
      title={t('evolve.demo.title')}
      description={done ? t(done === 'ok' ? 'evolve.demo.doneOk' : done === 'converged' ? 'evolve.demo.doneConverged' : 'evolve.demo.doneStopped') : t('evolve.demo.running')}
      actions={
        <>
          {!running ? (
            <Button size="sm" onClick={run} data-testid="demo-rerun" icon={<IconSpark width={13} height={13} />}>
              {t('evolve.demo.rerun')}
            </Button>
          ) : null}
          <Button size="sm" variant="subtle" onClick={() => { setSteps([]); setDone(null) }} data-testid="demo-dismiss">
            {t('evolve.demo.close')}
          </Button>
        </>
      }
    >
      <ol className="flex flex-col">
        {steps.map((step, i) => (
          <li key={step.id} className="flex items-start gap-3 py-2" style={{ borderTop: i ? '1px solid var(--border-subtle)' : undefined }}>
            <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md" style={{ background: 'var(--surface-sunken)' }}>
              {statusIcon(step.status)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className={`text-[12.5px] ${step.status === 'pending' ? 'muted' : 'font-medium'}`}>{step.title}</span>
                <Badge tone={step.status === 'ok' ? 'success' : step.status === 'fail' ? 'danger' : step.status === 'warn' ? 'warning' : 'neutral'}>
                  {t(`evolve.demo.status.${step.status}`)}
                </Badge>
                {step.to ? <Link className="ontogeny-link text-[12px]" to={step.to.href}>{step.to.label} →</Link> : null}
              </span>
              {step.detail ? <span className="mt-0.5 block font-mono text-[11.5px] secondary-text">{step.detail}</span> : null}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  )

  const slot = document.getElementById('ontogeny-demo-slot')
  return slot ? createPortal(panel, slot) : panel
}
