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
 * The dashboard's architecture board — a compact re-draw of the "总览架构图"
 * from docs/architecture/01-overall-architecture.md, reduced to three horizontal layers. Accent palette is
 * exactly three hues with shades: PURPLE = modeling / agents, BLUE = the
 * gated write & policy sides, GREEN = the loop / assurance:
 *
 *   ① the eight DSL first-class citizens as one chip strip; Action and
 *      EvalSuite carry the CORE tag (the only write gate / the selection box);
 *   ② the two engines side by side — the online pipeline (left: build the
 *      ontology, explore the knowledge, execute actions, govern access,
 *      audit everything) and the offline RSI loop (right, each beat with a
 *      one-line description plus the "selection never outsourced" footer) —
 *      joined by a dashed spine on which the AgentPlugin mediator sits: a
 *      dashed, white-backed EXTERNAL box (the dashed frame marks it as
 *      outside the platform proper) whose reads/writes cross the pipeline's
 *      gates and whose traces & approvals return as loop signals;
 *   ③ three cards left to right — storage & registry, compute & governance,
 *      and the cross-cutting mechanisms.
 *
 * Rows flex to fill their cards (justify-between), so no card ends in blank
 * space; nothing is absolutely positioned except the spine's dashed connector
 * (pills and the agent node sit above it with opaque backgrounds).
 */
import { useI18n } from '../../i18n'

/** Slim pill band heading, e.g. "一等公民 · 声明式 DSL 资源". */
function BandLabel({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-full px-2.5 py-[3px] text-[9.5px] font-extrabold tracking-[0.1em]"
      style={{
        background: `var(--tone-${tone}-bg)`,
        color: `var(--tone-${tone}-fg)`,
        border: `1px solid var(--tone-${tone}-ring)`,
      }}
    >
      <span className="size-[5px] shrink-0 rounded-full" style={{ background: 'currentColor' }} />
      {children}
    </span>
  )
}

type StageTone = 'violet' | 'brand' | 'info' | 'success'

/** The AgentPlugin mediator on the spine — drawn as a DASHED, white-backed
 *  box on purpose: dashed frame + the solid dark EXT tag mark it as an
 *  extensible plugin from OUTSIDE the platform proper. Its reads and writes
 *  still cross the pipeline's very gates, and its traces & approvals return
 *  into the loop as fitness signals. */
function AgentNode({ zh, className }: { zh: boolean; className?: string }) {
  return (
    <div
      className={['min-w-0 rounded-xl p-2', className].filter(Boolean).join(' ')}
      style={{ background: 'var(--surface-card)', border: '1.5px dashed var(--tone-violet-fg)' }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="grid size-[18px] shrink-0 place-items-center rounded-md text-[10px] font-extrabold"
          style={{ background: 'var(--tone-violet-fg)', color: 'var(--surface-card)' }}
        >
          {zh ? '智' : 'A'}
        </span>
        <span className="truncate text-[11px] font-extrabold" style={{ color: 'var(--tone-violet-fg)' }}>
          {zh ? 'Agent 智能体' : 'Agents'}
        </span>
        <span
          className="ml-auto shrink-0 whitespace-nowrap rounded-full px-1.5 py-px text-[7.5px] font-extrabold"
          style={{ background: 'var(--tone-violet-fg)', color: 'var(--surface-card)' }}
        >
          {zh ? '外部' : 'EXT'}
        </span>
      </div>
      <div className="mt-1.5 flex flex-col gap-0.5">
        <span className="truncate text-[9px] font-semibold" style={{ color: 'var(--text-secondary)' }}>
          {zh ? '可扩展插件 · 冻结身份' : 'extensible · frozen identity'}
        </span>
        <span className="truncate text-[9px] font-semibold" style={{ color: 'var(--text-secondary)' }}>
          {zh ? '读写经主链路 · 同一闸门' : 'reads/writes via one gate'}
        </span>
        <span className="truncate text-[9px] font-semibold" style={{ color: 'var(--text-secondary)' }}>
          {zh ? '轨迹 · 审批 回流为信号' : 'traces & approvals → loop'}
        </span>
      </div>
    </div>
  )
}

export function ArchBoard() {
  const { lang } = useI18n()
  const zh = lang === 'zh'

  // ① the citizens: name + one-word label; Action carries the CORE tag
  const citizens: Array<{ ico: string; name: string; label: string; core?: boolean }> = [
    { ico: zh ? '名' : 'N', name: 'ObjectType', label: zh ? '对象' : 'object' },
    { ico: zh ? '联' : 'L', name: 'LinkType', label: zh ? '链接' : 'link' },
    { ico: zh ? '行' : 'A', name: 'Action', label: zh ? '动作' : 'action', core: true },
    { ico: zh ? '算' : 'F', name: 'Function', label: zh ? '函数' : 'function' },
    { ico: zh ? '策' : 'P', name: 'PolicySet', label: zh ? '策略' : 'policy' },
    { ico: zh ? '智' : 'G', name: 'AgentPlugin', label: zh ? '智能体' : 'agent' },
    { ico: zh ? '投' : 'J', name: 'Projection', label: zh ? '投影' : 'projection' },
    { ico: zh ? '进' : 'E', name: 'EvalSuite', label: zh ? '自进化' : 'evolution', core: true },
  ]

  // ② left: the online pipeline — build → explore → act → govern → audit.
  // Hues: purple = the read/model sides, blue = the gated write & policy
  // sides, green = the assurance tail. 03 carries no tag on purpose: the
  // phase chain in its description already says "five-phase", and dropping
  // the tag lets the chain fit at lg widths.
  const stages: Array<{ no: string; tone: StageTone; title: string; tag?: string; core?: boolean; desc: string }> = [
    {
      no: '01', tone: 'violet', title: zh ? '本体构建' : 'Ontology build', tag: 'YAML · Git',
      desc: zh ? '声明式建模 · 数据挂载 · 一键发布' : 'declarative modeling · mount · publish',
    },
    {
      no: '02', tone: 'info', title: zh ? '知识探索' : 'Knowledge explore', tag: zh ? 'SQL ⇄ 图' : 'SQL ⇄ graph',
      desc: zh ? '查询 · 邻域探索 · 多跳追溯' : 'query, explore & traverse',
    },
    {
      no: '03', tone: 'brand', core: true, title: zh ? '动作执行' : 'Action execution',
      desc: zh ? '参数 → 规则 → 策略 → 效果 → 审计' : 'params→rules→policy→effects→audit',
    },
    {
      no: '04', tone: 'brand', title: zh ? '权限与角色' : 'Access control', tag: 'Cedar',
      desc: zh ? '角色 · 密级标记 · 行级条件 · 默认拒绝' : 'roles · markings · row-level · default deny',
    },
    {
      no: '05', tone: 'success', title: zh ? '全周期追踪 & 审计' : 'Full-cycle trace & audit', tag: 'outbox · SSE',
      desc: zh ? '版本时间线 · 不可变审计 · 事件订阅' : 'history · immutable audit · subscriptions',
    },
  ]

  // ② right: the offline RSI loop — each beat says what actually happens
  const loop: Array<{ no: string; k: string; desc: string }> = [
    {
      no: '1', k: zh ? '观察' : 'Observe',
      desc: zh ? '遥测把查询 · 动作 · Agent 轨迹聚为信号' : 'telemetry turns runs into fitness signals',
    },
    {
      no: '2', k: zh ? '提案' : 'Propose',
      desc: zh ? 'LLM 在封闭变异目录内起草，越界即拒' : 'LLM drafts in a closed mutation catalog',
    },
    {
      no: '3', k: zh ? '评测' : 'Evaluate',
      desc: zh ? '确定性评测做选择：查询回归 + 动作回放' : 'deterministic evals select, never the LLM',
    },
    {
      no: '4', k: zh ? '晋升' : 'Promote',
      desc: zh ? 'T0 自动 · T1 人审 · T2 灰度 · T3 仅人工' : 'T0 auto · T1 review · T2 canary · T3 human',
    },
    {
      no: '5', k: zh ? '热加载' : 'Hot-reload',
      desc: zh ? '编译快照热切换 · 新增列自动补齐' : 'snapshot hot-swaps · new columns auto-added',
    },
  ]

  // ③ the supporting layer, split into its two groups so each card stays full
  const supportGroups = [
    {
      no: '06', title: zh ? '存储与注册' : 'Storage & registry',
      chips: zh
        ? ['版本化对象表', '三策略同步', '编译快照', '时间旅行', '热路径零 IO']
        : ['versioned tables', '3-way sync', 'compiled registry', 'time travel', 'zero-IO hot path'],
    },
    {
      no: '07', title: zh ? '计算与治理' : 'Compute & governance',
      chips: zh
        ? ['函数沙箱', '派生 Worker', 'Cedar 引擎', '图投影 · 可选', 'LLM 网关 · 可换']
        : ['fn sandbox', 'derivation worker', 'Cedar engine', 'graph projection · opt', 'LLM gateway · swap'],
    },
  ]

  // ③ right: the invariants, keyword + one short phrase
  const mech = [
    { k: zh ? '所有权' : 'Ownership', v: zh ? '同步与动作各归其位' : 'sync vs actions, declared' },
    { k: zh ? '单通道' : 'One gate', v: zh ? '统一策略与审计' : 'one policy & audit plane' },
    { k: zh ? '真源' : 'Source', v: zh ? 'Git 声明式 · 可重建' : 'declarative Git · rebuildable' },
  ]

  return (
    <div
      className="mt-3.5 rounded-xl p-3"
      style={{
        backgroundColor: 'var(--surface-card)',
        backgroundImage: 'radial-gradient(var(--border-subtle) 1px, transparent 1.1px)',
        backgroundSize: '24px 24px',
        border: '1px solid var(--border-subtle)',
      }}
      data-testid="arch-board"
    >
      {/* ① first-class citizens — one chip strip */}
      <BandLabel tone="violet">{zh ? '一等公民 · 声明式 DSL 资源' : 'FIRST-CLASS CITIZENS · DSL RESOURCES'}</BandLabel>
      <div className="mt-1.5 grid grid-cols-2 gap-1.5 sm:grid-cols-4 xl:grid-cols-8">
        {citizens.map((c) => (
          <div
            key={c.name}
            className="flex min-w-0 items-center gap-1 rounded-lg px-1.5 py-1.5"
            style={{
              background: c.core ? 'var(--tone-violet-bg)' : 'var(--surface-card)',
              border: `1px solid ${c.core ? 'var(--tone-violet-ring)' : 'var(--border-subtle)'}`,
            }}
          >
            <span
              className="grid size-[18px] shrink-0 place-items-center rounded-md text-[10px] font-extrabold"
              style={c.core
                ? { background: 'var(--tone-violet-fg)', color: 'var(--surface-card)' }
                : { background: 'var(--tone-violet-bg)', color: 'var(--tone-violet-fg)' }}
            >
              {c.ico}
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block truncate text-[11px] font-extrabold">{c.name}</span>
              <span className="block truncate text-[9px] font-semibold" style={{ color: 'var(--text-muted)' }}>{c.label}</span>
            </span>
            {c.core ? (
              <span className="ml-auto shrink-0 rounded bg-[var(--color-brand-500)] px-[3px] py-px text-[7.5px] font-extrabold text-white">
                CORE
              </span>
            ) : null}
          </div>
        ))}
      </div>

      {/* ② the two engines side by side, joined by the agent-mediating spine */}
      <div className="mt-2 grid items-stretch gap-2 lg:grid-cols-[minmax(0,1fr)_150px_minmax(0,1fr)]">
        {/* online pipeline: title + what happens, one line each */}
        <section className="flex min-w-0 flex-col rounded-xl p-2.5" style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
          <BandLabel tone="brand">{zh ? '在线主链路 · 建模 → 执行 → 审计' : 'ONLINE PIPELINE · MODEL → ACT → AUDIT'}</BandLabel>
          <div className="mt-1.5 flex flex-1 flex-col justify-between gap-1.5">
            {stages.map((s) => (
              <div
                key={s.no}
                className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5"
                style={{
                  background: s.core ? `var(--tone-${s.tone}-bg)` : 'var(--surface-sunken)',
                  border: `1px solid ${s.core ? `var(--tone-${s.tone}-ring)` : 'var(--border-subtle)'}`,
                }}
              >
                <span
                  className="grid size-5 shrink-0 place-items-center rounded-md text-[9px] font-extrabold"
                  style={{ background: `var(--tone-${s.tone}-bg)`, color: `var(--tone-${s.tone}-fg)` }}
                >
                  {s.no}
                </span>
                <div className="min-w-0 flex-1 leading-tight">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[11.5px] font-bold">{s.title}</span>
                    {s.core ? (
                      <span className="shrink-0 rounded px-1 py-px text-[8px] font-extrabold"
                            style={{ background: 'var(--tone-brand-fg)', color: '#fff' }}>
                        {zh ? '唯一写入口' : 'CORE'}
                      </span>
                    ) : null}
                  </div>
                  <span className="block truncate text-[9px] font-semibold" style={{ color: 'var(--text-muted)' }}>{s.desc}</span>
                </div>
                {s.tag ? (
                  <span
                    className="shrink-0 whitespace-nowrap rounded px-1.5 py-px text-[8.5px] font-extrabold"
                    style={{ background: `var(--tone-${s.tone}-bg)`, color: `var(--tone-${s.tone}-fg)` }}
                  >
                    {s.tag}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        {/* stacked-mode connector: pills + the agent node, between the engines */}
        <div className="flex flex-col gap-2 lg:hidden">
          <div className="flex items-center justify-center gap-2">
            <span className="rounded-full px-2 py-1 text-[9.5px] font-extrabold"
                  style={{ background: 'var(--tone-violet-bg)', color: 'var(--tone-violet-fg)' }}>
              ↓ {zh ? '遥测' : 'telemetry'}
            </span>
            <span className="rounded-full px-2 py-1 text-[9.5px] font-extrabold"
                  style={{ background: 'var(--tone-success-bg)', color: 'var(--tone-success-fg)' }}>
              ↑ {zh ? '提案' : 'proposals'}
            </span>
          </div>
          <AgentNode zh={zh} />
        </div>

        {/* spine: dashed rail, telemetry out on top, the agent in the middle,
            proposals back at the bottom */}
        <div className="hidden lg:block">
          <div className="relative h-full">
            <span
              aria-hidden
              className="absolute inset-y-3 left-1/2 -translate-x-1/2 border-l border-dashed"
              style={{ borderColor: 'var(--border-strong)' }}
            />
            <div className="relative z-10 flex h-full flex-col gap-2.5 py-2">
              <span
                className="mx-auto whitespace-nowrap rounded-full px-2 py-1 text-[9.5px] font-extrabold"
                style={{ background: 'var(--surface-card)', border: '1px solid var(--tone-violet-ring)', color: 'var(--tone-violet-fg)' }}
              >
                {zh ? '运行痕迹 →' : 'telemetry →'}
              </span>
              <div className="flex min-h-0 flex-1 items-center">
                <AgentNode zh={zh} className="w-full" />
              </div>
              <span
                className="mx-auto whitespace-nowrap rounded-full px-2 py-1 text-[9.5px] font-extrabold"
                style={{ background: 'var(--surface-card)', border: '1px solid var(--tone-success-ring)', color: 'var(--tone-success-fg)' }}
              >
                {zh ? '← 机器提案' : '← proposals'}
              </span>
            </div>
          </div>
        </div>

        {/* offline RSI loop */}
        <section className="flex min-w-0 flex-col rounded-xl p-2.5" style={{ background: 'var(--tone-success-bg)', border: '1px solid var(--tone-success-ring)' }}>
          <BandLabel tone="success">{zh ? 'RSI 自进化闭环 · 离线' : 'OFFLINE · RSI LOOP'}</BandLabel>
          <div className="mt-1.5 flex flex-1 flex-col justify-between gap-1.5">
            {loop.map((s) => (
              <div key={s.no} className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5"
                   style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
                <span className="grid size-5 shrink-0 place-items-center rounded-md text-[9px] font-extrabold"
                      style={{ background: 'var(--tone-success-bg)', color: 'var(--tone-success-fg)' }}>{s.no}</span>
                <div className="min-w-0 leading-tight">
                  <div className="text-[11.5px] font-bold" style={{ color: 'var(--tone-success-fg)' }}>{s.k}</div>
                  <span className="block truncate text-[9px] font-semibold" style={{ color: 'var(--text-muted)' }}>{s.desc}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-1.5 border-t border-dashed pt-1.5" style={{ borderColor: 'var(--tone-success-ring)' }}>
            <span className="truncate text-[9.5px] font-bold" style={{ color: 'var(--tone-success-fg)' }}>
              {zh ? '变异外包给模型 · 选择权从不外包' : 'mutation to the model · selection never'}
            </span>
            <span
              className="ml-auto shrink-0 whitespace-nowrap rounded-full px-2 py-px text-[8.5px] font-extrabold"
              style={{ background: 'var(--surface-card)', border: '1px dashed var(--tone-violet-ring)', color: 'var(--tone-violet-fg)' }}
            >
              {zh ? '治理基线 · 仅人可改' : 'baseline: human-only'}
            </span>
          </div>
        </section>
      </div>

      {/* ③ storage · compute · cross-cutting, three cards left to right */}
      <div className="mt-2 grid items-stretch gap-2 md:grid-cols-3">
        {supportGroups.map((g) => (
          <section key={g.no} className="min-w-0 rounded-xl p-2.5" style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
            <div className="flex items-center gap-1.5">
              <span className="shrink-0 rounded-md px-1.5 py-px text-[8.5px] font-extrabold"
                    style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}>
                {g.no}
              </span>
              <span className="truncate text-[11px] font-extrabold" style={{ color: 'var(--text-secondary)' }}>
                {g.title}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {g.chips.map((chip) => (
                <span key={chip} className="rounded-full px-2 py-[2.5px] text-[9.5px] font-semibold"
                      style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
                  {chip}
                </span>
              ))}
            </div>
          </section>
        ))}

        <section className="min-w-0 rounded-xl p-2.5" style={{ background: 'var(--tone-info-bg)', border: '1px solid var(--tone-info-ring)' }}>
          <div className="flex items-center gap-1.5">
            <span className="size-2 shrink-0 rounded-full" style={{ background: 'var(--tone-info-fg)' }} />
            <span className="truncate text-[11px] font-extrabold" style={{ color: 'var(--tone-info-fg)' }}>
              {zh ? '贯穿机制 · 全链路' : 'CROSS-CUTTING · ALL THE WAY THROUGH'}
            </span>
          </div>
          <div className="mt-2 flex flex-col gap-1">
            {mech.map((m) => (
              <div key={m.k} className="flex min-w-0 items-center gap-1.5 text-[10px]">
                <span className="shrink-0 rounded px-1.5 py-px text-[9px] font-extrabold"
                      style={{ background: 'var(--surface-card)', color: 'var(--tone-info-fg)' }}>
                  {m.k}
                </span>
                <span className="truncate font-semibold" style={{ color: 'var(--text-secondary)' }}>{m.v}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
