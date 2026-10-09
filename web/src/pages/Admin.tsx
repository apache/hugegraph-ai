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
 * Operations console — ONE page, read top to bottom, but never a flat stream:
 * every card belongs to a labelled category, and a chip row under the health
 * strip jumps straight to one.
 *
 *   运行状态     the compiled snapshot the platform serves right now (the
 *              single source of truth) and the one button that refreshes it;
 *   §1 运行配置   the LLM gateway and storage backend, WITH their capability
 *              probes: what you configure is what gets verified, in place;
 *   §2 扩展与能力 what loaded from extensions/ and which engines it provides;
 *   §3 本体与发布 the authoritative package: publish + compiled snapshot;
 *   §4 演示环境   the throwaway demo helpers — one card, nothing repeated.
 *
 * Each fact is rendered exactly once: capability status lives in the config
 * section that produces it, and the health strip only summarizes. Old ?tab=…
 * deep-links simply land on the same page, and the refresh button re-probes
 * everything below.
 */
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { invalidateMeta, keys, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, KeyValue, StatBar } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { JsonView } from '../components/JsonView'
import { ExtensionsPanel } from './Extensions'
import { RuntimeConfigCard } from '../components/RuntimeConfigCard'
import {
  IconCheck, IconCog, IconCube, IconLayers, IconNetwork, IconPlay, IconRefresh, IconX,
} from '../components/icons'
import type { BadgeTone } from '../components/ui'

/** A labelled category: small-caps header + one-line description, with an id
 *  the chip row above can anchor to. The page's grouping used to live only in
 *  source comments — operators saw a dozen sibling cards and no way to tell
 *  registry from config from demo. */
function Section({
  id, icon, title, description, children,
}: {
  id: string
  icon: ReactNode
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="flex scroll-mt-2 flex-col gap-3">
      <header className="flex items-center gap-2.5">
        <span
          className="grid size-7 shrink-0 place-items-center rounded-lg"
          style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}
          aria-hidden="true"
        >
          {icon}
        </span>
        <div className="min-w-0">
          <h2
            id={`${id}-heading`}
            className="text-[11px] font-semibold uppercase tracking-wider"
            style={{ color: 'var(--text-secondary)' }}
          >
            {title}
          </h2>
          <p className="text-[12px] muted">{description}</p>
        </div>
      </header>
      {children}
    </section>
  )
}

export function Admin() {
  const { t, plural } = useI18n()
  const qc = useQueryClient()
  const meta = useMeta()
  const llm = useQuery({ queryKey: keys.llmStatus, queryFn: () => apiClient.llmStatus(), retry: false })
  const inventory = useQuery({ queryKey: keys.extensions, queryFn: apiClient.extensions })
  const projection = useQuery({
    queryKey: keys.projection,
    queryFn: apiClient.projectionSummary,
    retry: false,
  })

  const publish = useMutation({
    mutationFn: () => apiClient.publish(),
    // publishing is the one thing that *does* change the compiled snapshot,
    // which is otherwise cached forever
    onSuccess: () => invalidateMeta(qc),
  })

  const refreshAll = () => {
    meta.refetch(); llm.refetch(); inventory.refetch(); projection.refetch()
  }

  const extensions = inventory.data?.extensions ?? []
  const failed = extensions.filter((e) => e.status === 'error').length
  const loaded = extensions.filter((e) => e.status === 'loaded').length

  // deployment health, summarised for the strip: any hard failure turns the
  // page badge red, a missing optional capability only turns it amber
  const extTone: BadgeTone = failed ? 'danger' : extensions.length && loaded === extensions.length ? 'success' : 'warning'
  const llmTone: BadgeTone = !llm.data?.configured ? 'neutral' : llm.data.ok ? 'success' : 'danger'
  const health: { tone: BadgeTone; label: string } = failed
    ? { tone: 'danger', label: t('ops.health.degraded') }
    : llmTone === 'danger'
      ? { tone: 'warning', label: t('ops.health.partial') }
      : { tone: 'success', label: t('ops.health.ok') }

  // the categories below, in reading order — one source for both the anchor
  // chips and the sections, so a rename can never desync the two
  const categories = [
    { id: 'ops-config', icon: <IconCog width={13} height={13} />, label: t('admin.section.config') },
    { id: 'ops-extensions', icon: <IconLayers width={13} height={13} />, label: t('admin.section.extensions') },
    { id: 'ops-registry', icon: <IconCube width={13} height={13} />, label: t('admin.section.registry') },
    { id: 'ops-demo', icon: <IconPlay width={13} height={13} />, label: t('admin.section.demo') },
  ]

  return (
    <div className="flex flex-col gap-5">
      <h1 className="sr-only">{t('admin.title')}</h1>

      {/* a failed probe must not read as "absent": on the operations console the
          two mean opposite things ("nothing configured" vs "cannot tell") */}
      {llm.error ? <ErrorBanner error={llm.error} /> : null}
      {projection.error ? <ErrorBanner error={projection.error} /> : null}
      {inventory.error ? <ErrorBanner error={inventory.error} /> : null}

      {/* ------------------------------------------------ 运行状态 strip ---- */}
      <StatBar
        size="sm"
        items={[
          {
            label: t('ops.tile.extensions'),
            value: inventory.error ? t('common.unknown')
              : extensions.length ? `${loaded}/${extensions.length}` : '—',
            hint: failed ? plural('ops.tile.extensionsFailed', failed) : t('ext.inventory'),
            tone: inventory.error ? 'danger' : extTone,
            icon: <IconLayers width={15} height={15} />,
          },
          {
            label: t('ops.tile.llm'),
            value: llm.error ? t('common.unknown')
              : !llm.data?.configured ? t('ops.llm.absent') : llm.data.ok ? t('ops.llm.ok') : t('admin.llm.unreachable'),
            hint: llm.error ? t('admin.llm.unreachable')
              : llm.data?.configured ? (llm.data.model ?? '—') : t('admin.llm.notConfigured'),
            tone: llm.error ? 'danger' : llmTone,
            icon: llm.error || llmTone === 'danger' ? <IconX width={15} height={15} /> : <IconCheck width={15} height={15} />,
          },
          {
            label: t('ops.tile.projection'),
            // A pending probe is NOT a verdict: reporting "SQL-only" while the
            // answer is still in flight is the same false claim the console used
            // to make about a configured HugeGraph, just 300ms earlier.
            value: projection.isLoading ? '…'
              : projection.error ? t('common.unknown')
              : projection.data?.configured ? (projection.data.engine ?? '—')
              : projection.data?.storage_provider === 'hugegraph' ? t('ops.runtime.storage.noDecl')
              : t('ops.projection.sqlOnly'),
            hint: projection.isLoading ? t('common.loading')
              : projection.data?.configured
                ? (projection.data.graph ?? undefined)
                : projection.data?.storage_provider === 'hugegraph'
                  ? t('admin.projection.noneHugeHint')
                  : t('admin.projection.none'),
            tone: projection.isLoading ? 'neutral'
              : projection.error ? 'danger' : projection.data?.configured ? 'violet' : 'neutral',
            icon: <IconNetwork width={15} height={15} />,
          },
          {
            label: t('ops.tile.package'),
            value: meta.data?.package ?? '—',
            // no hash hint here: the full content hash is one screen away in
            // 本体与发布, and a truncated copy of it is worse than none
            tone: 'brand',
            icon: <IconCube width={15} height={15} />,
          },
        ]}
      />

      {/* the global controls: deployment health chip and a refresh that
          re-probes everything below, plus the category jumps */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={health.tone}>{health.label}</Badge>
        <Button
          square
          icon={<IconRefresh width={15} height={15} />}
          onClick={refreshAll}
          data-testid="admin-refresh"
          title={t('common.refresh')}
          aria-label={t('common.refresh')}
        />
        <nav aria-label={t('admin.jump')} className="ml-auto flex flex-wrap items-center gap-1.5">
          {categories.map((c) => (
            <a
              key={c.id}
              href={`#${c.id}`}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-[5px] text-[12px] font-medium transition-colors hover:bg-[var(--surface-hover)]"
              style={{ background: 'var(--surface-card)', color: 'var(--text-secondary)', border: '1px solid var(--border-subtle)' }}
            >
              {c.icon}
              {c.label}
            </a>
          ))}
        </nav>
      </div>

      {/* ------------------------------------------- §1 运行配置 ---- */}
      <Section
        id="ops-config"
        icon={<IconCog width={14} height={14} />}
        title={t('admin.section.config')}
        description={t('admin.section.config.desc')}
      >
        <RuntimeConfigCard />
      </Section>

      {/* ----------------------------------------- §2 扩展与能力 ---- */}
      <Section
        id="ops-extensions"
        icon={<IconLayers width={14} height={14} />}
        title={t('admin.section.extensions')}
        description={t('admin.section.extensions.desc')}
      >
        <ExtensionsPanel />
      </Section>

      {/* ------------------------------------------- §3 本体与发布 ---- */}
      <Section
        id="ops-registry"
        icon={<IconCube width={14} height={14} />}
        title={t('admin.section.registry')}
        description={t('admin.section.registry.desc')}
      >
        {/* one card, not two: publish and the snapshot it produces are the same
            story, and the hash used to appear in both */}
        <Card title={t('admin.registry')} description={t('admin.registry.hint')}>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              onClick={() => publish.mutate()}
              disabled={publish.isPending}
              data-testid="republish"
              icon={<IconRefresh width={14} height={14} />}
            >
              {t('admin.registry.publish')}
            </Button>
            {publish.data ? <div className="w-full"><JsonView value={publish.data} /></div> : null}
          </div>
          {publish.error ? <div className="mt-3"><ErrorBanner error={publish.error} /></div> : null}
          <div className="mt-3">
            <KeyValue
              items={[
                { key: t('tour.package'), value: meta.data?.package ?? '—', mono: true },
                { key: t('ontology.hash'), value: meta.data?.content_hash ?? '—', mono: true },
                { key: t('ops.registry.objects'), value: String(Object.keys(meta.data?.objects ?? {}).length) },
                { key: t('ops.registry.actions'), value: String(Object.keys(meta.data?.actions ?? {}).length) },
              ]}
            />
          </div>
          <p className="mt-3 text-[11.5px] muted">{t('ops.registry.rebuildHint')}</p>
        </Card>
      </Section>

      {/* ----------------------------------------------- §4 演示环境 ---- */}
      <Section
        id="ops-demo"
        icon={<IconPlay width={14} height={14} />}
        title={t('admin.section.demo')}
        description={t('admin.section.demo.desc')}
      >
        {/* the demo card used to repeat package/hash/dirs already shown above;
            only the commands are demo-specific knowledge */}
        <Card title={t('admin.demo')} description={t('admin.demo.hint')}>
          <div className="flex flex-wrap gap-2 text-[12.5px]">
            <code className="ontogeny-code w-fit">ontogeny serve --demo --open</code>
            <code className="ontogeny-code w-fit">ontogeny serve --demo --reseed</code>
            <code className="ontogeny-code w-fit">docker compose up -d</code>
          </div>
          <p className="mt-3 text-[11.5px] muted">{t('ops.demo.reseedHint')}</p>
        </Card>
      </Section>
    </div>
  )
}
