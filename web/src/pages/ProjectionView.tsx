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
 * ProjectionView: the HugeGraph projection as it actually lives in the graph —
 * engine/graph/dialect, label inventory with live counts, the schema graph and
 * sampled rows. Lives in the Traceability page's "projection" tab; rows are
 * re-assembled from the authoritative objects (the graph is a derived index,
 * never a second source of truth).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys } from '../api/queries'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, EmptyState, KeyValue, Skeleton } from '../components/ui'
import { FlowGraph } from '../components/FlowGraph'
import { projectionToFlow } from '../components/graphAdapters'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'
import { columnsOf } from '../lib/rows'
import { IconLayers, IconNetwork, IconRefresh } from '../components/icons'
import { NodeInfoDrawer } from '../components/NodeInfoDrawer'

export function ProjectionView() {
  const { t, plural } = useI18n()
  const qc = useQueryClient()
  const [vertexLabel, setVertexLabel] = useState<string>('')
  const [edgeLabel, setEdgeLabel] = useState<string>('')
  const [rebuilt, setRebuilt] = useState<string>('')
  const [labelDrawer, setLabelDrawer] = useState<{ name: string; kind: 'vertex' | 'edge' } | null>(null)

  const projection = useQuery({ queryKey: keys.projection, queryFn: apiClient.projectionSummary })
  const summary = projection.data

  const vLabels = summary?.labels?.vertices ?? []
  const eLabels = summary?.labels?.edges ?? []
  const activeVertex = vertexLabel || vLabels[0]?.name || ''
  const activeEdge = edgeLabel || eLabels[0]?.name || ''

  const vertices = useQuery({
    queryKey: ['projection-vertices', activeVertex],
    queryFn: () => apiClient.projectionVertices(activeVertex, 20),
    enabled: Boolean(summary?.ok && activeVertex),
  })
  const edges = useQuery({
    queryKey: ['projection-edges', activeEdge],
    queryFn: () => apiClient.projectionEdges(activeEdge, 20),
    enabled: Boolean(summary?.ok && activeEdge),
  })
  const rebuild = useMutation({
    mutationFn: () => apiClient.rebuildProjection(),
    onSuccess: (res) => {
      setRebuilt(t('proj.rebuilt', { vertices: res.vertices ?? 0, edges: res.edges ?? 0 }))
      qc.invalidateQueries({ queryKey: ['projection'] })
      qc.invalidateQueries({ queryKey: ['projection-vertices'] })
      qc.invalidateQueries({ queryKey: ['projection-edges'] })
    },
  })

  const vertexColumns = useMemo(
    () => columnsOf(vertices.data?.rows ?? [], vLabels.find((v) => v.name === activeVertex)?.primary_keys?.[0]),
    [vertices.data, vLabels, activeVertex],
  )
  const edgeColumns: Array<Column<import('../api/types').ProjectionEdge>> = useMemo(
    () => [
      { key: 'link', label: t('proj.label') },
      { key: 'source', label: t('proj.endpoints'), render: (e) => `${e.source.type} · ${e.source.display}` },
      { key: 'target', label: '→', render: (e) => `${e.target.type} · ${e.target.display}` },
    ],
    [t],
  )

  if (projection.isLoading) return <Skeleton rows={6} />
  if (projection.error) return <ErrorBanner error={projection.error} />
  if (!summary?.configured) {
    return (
      <Alert tone="info" title={t('proj.notConfigured')}>
        {t('proj.notConfiguredHint')}
      </Alert>
    )
  }

  const vCounts = summary.counts?.vertices ?? {}
  const eCounts = summary.counts?.edges ?? {}
  const totalV = Object.values(vCounts).reduce((a, b) => a + b, 0)
  const totalE = Object.values(eCounts).reduce((a, b) => a + b, 0)

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconNetwork width={14} height={14} />
            {t('proj.title')}
          </span>
        }
        actions={
          <span className="flex items-center gap-2">
            <Badge tone={summary.ok ? 'success' : 'warning'}>
              {summary.ok ? t('proj.upToDate') : t('proj.unavailable')}
            </Badge>
            <Button
              size="sm"
              data-testid="rebuild-projection"
              onClick={() => rebuild.mutate()}
              disabled={rebuild.isPending}
              icon={<IconLayers width={13} height={13} />}
            >
              {rebuild.isPending ? t('proj.rebuilding') : t('proj.rebuild')}
            </Button>
          </span>
        }
      >
        <KeyValue
          items={[
            { key: t('proj.engine'), value: summary.engine ?? '—', mono: true },
            { key: t('proj.graph'), value: summary.graph ?? '—', mono: true },
            { key: t('proj.graphspace'), value: summary.graphspace ?? '—', mono: true },
            { key: t('proj.dialect'), value: summary.dialect ?? '—', mono: true },
            { key: t('proj.vertexLabels'), value: `${vLabels.length} · ${totalV} ${t('proj.total').toLowerCase()}` },
            { key: t('proj.edgeLabels'), value: `${eLabels.length} · ${totalE} ${t('proj.total').toLowerCase()}` },
          ]}
        />
        {rebuilt ? <div className="mt-3"><Alert tone="success">{rebuilt}</Alert></div> : null}
        {!summary.ok ? (
          <div className="mt-3">
            <Alert tone="warning" title={t('proj.unavailable')}>
              {summary.error ?? summary.reason}
            </Alert>
          </div>
        ) : null}
        {rebuild.error ? <div className="mt-3"><ErrorBanner error={rebuild.error} /></div> : null}
      </Card>

      {(vLabels.length > 0 || eLabels.length > 0) ? (
        <Card
          title={t('proj.schemaGraph')}
          description={t('proj.schemaGraphHint')}
          padded={false}
        >
          <div className="px-2 pb-3 pt-2">
            <FlowGraph
              key={`proj-${vLabels.length}-${eLabels.length}`}
              data={projectionToFlow(summary)}
              height={560}
              testId="projection-flow"
              onNodeClick={(n) => {
                const vertex = vLabels.find((v) => v.name === n.label)
                if (vertex) { setLabelDrawer({ name: n.label, kind: 'vertex' }); return }
                const edge = eLabels.find((e) => e.name === n.label)
                if (edge) setLabelDrawer({ name: n.label, kind: 'edge' })
              }}
            />
          </div>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('proj.vertexLabels')}>
          {vLabels.length === 0 ? (
            <EmptyState title={t('proj.empty')} description={t('proj.buildHint')} />
          ) : (
            <DataTable
              columns={[
                { key: 'name', label: t('proj.label') },
                { key: 'pk', label: t('data.pk'), render: (r) => (r.primary_keys ?? []).join(', ') || '—' },
                { key: 'n', label: t('proj.count'), align: 'right', render: (r) => String(vCounts[r.name] ?? 0) },
              ]}
              rows={vLabels}
              rowKey={(r) => r.name}
            />
          )}
        </Card>

        <Card title={t('proj.edgeLabels')}>
          {eLabels.length === 0 ? (
            <EmptyState title={t('proj.empty')} description={t('proj.buildHint')} />
          ) : (
            <DataTable
              columns={[
                { key: 'name', label: t('proj.label') },
                {
                  key: 'dir',
                  label: t('proj.endpoints'),
                  render: (r) => `${r.source_label} → ${r.target_label}`,
                },
                { key: 'n', label: t('proj.count'), align: 'right', render: (r) => String(eCounts[r.name] ?? 0) },
              ]}
              rows={eLabels}
              rowKey={(r) => r.name}
            />
          )}
        </Card>
      </div>

      <Card
        title={t('proj.sample')}
        actions={
          <span className="flex items-center gap-2">
            <select
              aria-label="vertex-label"
              className="ontogeny-input w-56"
              value={activeVertex}
              onChange={(e) => setVertexLabel(e.target.value)}
            >
              {vLabels.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name}
                </option>
              ))}
            </select>
            <Button size="sm" onClick={() => vertices.refetch()} icon={<IconRefresh width={13} height={13} />}>
              {t('common.refresh')}
            </Button>
          </span>
        }
      >
        {vertices.error ? <ErrorBanner error={vertices.error} /> : null}
        {vertices.isLoading ? (
          <Skeleton rows={3} />
        ) : (vertices.data?.rows.length ?? 0) === 0 ? (
          <EmptyState title={t('proj.empty')} description={t('proj.buildHint')} />
        ) : (
          <>
            <div className="mb-2 flex gap-2 text-[12px] muted">
              <Badge tone="neutral">{t('proj.sampled', { count: vertices.data?.sampled ?? 0 })}</Badge>
              {vertices.data?.hidden ? (
                <Badge tone="warning">{plural('proj.hidden', vertices.data.hidden)}</Badge>
              ) : null}
            </div>
            <DataTable
              columns={vertexColumns}
              rows={vertices.data?.rows ?? []}
              rowKey={(row, i) => String(row[Object.keys(row)[0]] ?? i)}
            />
          </>
        )}
      </Card>

      <Card
        title={`${t('proj.edgeLabels')} · ${t('proj.sample')}`}
        actions={
          <span className="flex items-center gap-2">
            <select
              aria-label="edge-label"
              className="ontogeny-input w-56"
              value={activeEdge}
              onChange={(e) => setEdgeLabel(e.target.value)}
            >
              {eLabels.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.name}
                </option>
              ))}
            </select>
            <Button size="sm" onClick={() => edges.refetch()} icon={<IconRefresh width={13} height={13} />}>
              {t('common.refresh')}
            </Button>
          </span>
        }
      >
        {edges.error ? <ErrorBanner error={edges.error} /> : null}
        {edges.isLoading ? (
          <Skeleton rows={3} />
        ) : (edges.data?.rows.length ?? 0) === 0 ? (
          <EmptyState title={t('proj.empty')} description={t('proj.buildHint')} />
        ) : (
          <>
            <div className="mb-2 flex gap-2 text-[12px] muted">
              <Badge tone="neutral">{t('proj.sampled', { count: edges.data?.sampled ?? 0 })}</Badge>
              {edges.data?.hidden ? (
                <Badge tone="warning">{plural('proj.hidden', edges.data.hidden)}</Badge>
              ) : null}
            </div>
            <DataTable columns={edgeColumns} rows={edges.data?.rows ?? []} rowKey={(e) => e.id} />
          </>
        )}
      </Card>

      <NodeInfoDrawer
        open={labelDrawer !== null}
        onClose={() => setLabelDrawer(null)}
        title={labelDrawer?.name ?? ''}
        subtitle={labelDrawer ? `${labelDrawer.kind === 'vertex' ? t('proj.vertexLabels') : t('proj.edgeLabels')} · hugegraph` : undefined}
        items={labelDrawer ? [
          { key: t('drawer.primaryKey'), value: (vLabels.find((v) => v.name === labelDrawer.name)?.primary_keys ?? []).join(', ') || '—' },
          { key: t('drawer.count'), value: String((labelDrawer.kind === 'vertex' ? vCounts : eCounts)[labelDrawer.name] ?? 0) },
          { key: t('drawer.links'), value: eLabels
              .filter((e) => e.source_label === labelDrawer.name || e.target_label === labelDrawer.name)
              .map((e) => e.name).join(', ') || '—' },
        ] : []}
      />
    </div>
  )
}
