import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { exampleKeys, exampleMeta, examples } from '../lib/examples'
import type { ExampleKey } from '../lib/examples'
import { localQuestionSuggestions } from '../state'
import { Button } from '../components/ui/button'
import { useApp } from '../state'

export interface TemplatesProps {
  onChooseSample: (key: ExampleKey, opts?: { question?: string; suggestions?: string[] }) => void
}

// 每种合同类型的简短介绍
const INTROS: Record<ExampleKey, string> = {
  rental: '虚构租房合同，涵盖押金、维修、墙面改动条款。适合体验条款定位和立场分析。',
  privacy: '虚构隐私协议，包含个人信息处理、撤回同意和第三方共享场景。',
  labor: '虚构劳动合同，含试用期、薪酬绩效、竞业和解除补偿条款。',
  renovation: '虚构装修合同，含工期约定、隐蔽工程验收和保修责任范围。',
  training: '虚构培训协议，包含退费条件、调课规则和效果承诺条款。',
  photography: '虚构摄影服务合同，含底片交付、版权归属和档期改期条款。',
}

// 仿真加载四个阶段：导入解析 → 生成猜你想问 → 选择 → 生成答案
// 与真实上传链路同款建议来源（localQuestionSuggestions），让演示路径和实际路径一致。
const SIM_STEPS = ['正在导入 PDF', '正在解析合同文本'] as const

type SimPhase =
  | { stage: 'steps'; step: number }
  | { stage: 'suggest'; shown: number }
  | { stage: 'select' }
  | { stage: 'answer' }

// 阶段时间轴（毫秒）：两步解析 → 三条建议逐条出现 → 选中 → 生成答案 → 进入分析
const TIMELINE: Array<{ at: number; phase: SimPhase }> = [
  { at: 0, phase: { stage: 'steps', step: 0 } },
  { at: 700, phase: { stage: 'steps', step: 1 } },
  { at: 1500, phase: { stage: 'suggest', shown: 1 } },
  { at: 1880, phase: { stage: 'suggest', shown: 2 } },
  { at: 2260, phase: { stage: 'suggest', shown: 3 } },
  { at: 3000, phase: { stage: 'select' } },
  { at: 3750, phase: { stage: 'answer' } },
]
const SIM_TOTAL_MS = 4800

// 示例的建议列表：默认问题置顶（与进入分析页后的提问保持一致），其余走本地规则
function buildSim(key: ExampleKey): { suggestions: string[]; chosen: string } {
  const sample = examples[key]
  const pool = localQuestionSuggestions(sample.clauses.join('\n')).filter((q) => q !== sample.question)
  const suggestions = [sample.question, ...pool].filter(Boolean).slice(0, 3)
  return { suggestions, chosen: suggestions[0] }
}

export default function Templates({ onChooseSample }: TemplatesProps) {
  const { api } = useApp()
  const [loading, setLoading] = useState<{ key: ExampleKey; phase: SimPhase } | null>(null)
  const timers = useRef<number[]>([])

  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t))
    timers.current = []
  }
  useEffect(() => clearTimers, [])

  const startLoading = (key: ExampleKey) => {
    if (loading) return
    clearTimers()
    const { suggestions, chosen } = buildSim(key)
    setLoading({ key, phase: { stage: 'steps', step: 0 } })
    TIMELINE.slice(1).forEach(({ at, phase }) => {
      timers.current.push(window.setTimeout(() => setLoading({ key, phase }), at))
    })
    timers.current.push(
      window.setTimeout(() => onChooseSample(key, { question: chosen, suggestions }), SIM_TOTAL_MS),
    )
  }

  return (
    <div className="mx-auto w-full max-w-[1360px] px-5 py-8">
      <Button variant="ghost" size="sm" onClick={() => api.navigate('home')}>
        ‹　返回首页
      </Button>

      <div className="mt-6 mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">模板库</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          六种虚构示例合同，用于体验阅读交互。不是可直接签署的合同范本。
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {exampleKeys.map((key) => {
          const sample = examples[key]
          const meta = exampleMeta[key]
          const isLoading = loading?.key === key
          const ph = isLoading && loading ? loading.phase : null
          const sim = isLoading ? buildSim(key) : null
          const inSteps = ph?.stage === 'steps'
          const inAnswer = ph?.stage === 'answer'
          const isIdle = !loading
          return (
            <button
              key={key}
              type="button"
              onClick={() => startLoading(key)}
              style={{ '--tone': meta.tone } as CSSProperties}
              aria-busy={isLoading}
              className={`motion-card group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card text-left transition-all duration-200 ${
                isIdle ? 'hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md' : ''
              } ${isLoading ? 'border-foreground/20 shadow-md' : ''} ${
                loading && !isLoading ? 'pointer-events-none opacity-40' : ''
              }`}
            >
              {/* tone accent top bar */}
              <span
                aria-hidden
                className="block h-1 w-full transition-opacity"
                style={{ background: meta.tone }}
              />

              <div className="flex flex-1 flex-col gap-3 p-5">
                {/* header row */}
                <div className="flex items-start justify-between gap-3">
                  <span
                    className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-2xl"
                    style={{ background: `${meta.tone}18`, color: meta.tone }}
                    aria-hidden
                  >
                    {meta.icon}
                  </span>
                  <span
                    className="mt-0.5 rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wider"
                    style={{ color: meta.tone, borderColor: `${meta.tone}55` }}
                  >
                    {meta.tag}
                  </span>
                </div>

                {/* title */}
                <div>
                  <p className="text-[11px] text-muted-foreground/70">
                    {isLoading ? '演示解析中' : '虚构示例'}
                  </p>
                  <h2 className="mt-0.5 text-[15px] font-semibold leading-snug text-foreground">
                    {sample.title}
                  </h2>
                </div>

                {isLoading && ph && sim ? (
                  <div className="mt-auto flex flex-col gap-2.5 pt-1" role="status">
                    {/* 阶段一/二：导入 PDF → 解析条款（进入建议阶段后折叠为完成行） */}
                    {inSteps ? (
                      SIM_STEPS.map((label, i) => {
                        const done = i < (ph as { step: number }).step
                        const active = i === (ph as { step: number }).step
                        return (
                          <div
                            key={label}
                            className={`flex items-center gap-2 text-[12px] transition-colors duration-200 ${
                              done
                                ? 'text-muted-foreground'
                                : active
                                  ? 'text-foreground'
                                  : 'text-muted-foreground/40'
                            }`}
                          >
                            {done ? (
                              <span
                                aria-hidden
                                className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full text-[9px] text-white"
                                style={{ background: meta.tone }}
                              >
                                ✓
                              </span>
                            ) : active ? (
                              <span
                                aria-hidden
                                className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-t-transparent"
                                style={{ borderColor: meta.tone, borderTopColor: 'transparent' }}
                              />
                            ) : (
                              <span
                                aria-hidden
                                className="h-3.5 w-3.5 shrink-0 rounded-full border border-muted-foreground/25"
                              />
                            )}
                            <span>{label}</span>
                          </div>
                        )
                      })
                    ) : (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                        {SIM_STEPS.map((label) => (
                          <span key={label} className="flex items-center gap-1">
                            <span
                              aria-hidden
                              className="flex h-3 w-3 items-center justify-center rounded-full text-[8px] text-white"
                              style={{ background: meta.tone }}
                            >
                              ✓
                            </span>
                            {label.replace('正在', '已')}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* 阶段三/四/五：猜你想问逐条出现 → 选中 → 生成答案 */}
                    {ph.stage !== 'steps' && (
                      <>
                        <div className="text-xs text-muted-foreground">
                          猜你想问
                          <span className="ml-1 opacity-70">模板建议（本地）· 文件解析后生成</span>
                        </div>
                        <div className="flex flex-col gap-1.5">
                          {sim.suggestions.slice(0, ph.stage === 'suggest' ? ph.shown : 3).map((q) => {
                            const selected =
                              ph.stage === 'select' || ph.stage === 'answer' ? q === sim.chosen : false
                            return (
                              <div
                                key={q}
                                className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left text-[12px] transition-all duration-200 animate-in fade-in slide-in-from-bottom-1 ${
                              selected
                                  ? 'font-medium text-foreground'
                                  : inAnswer
                                    ? 'border-border/60 text-muted-foreground/50'
                                    : 'border-border text-foreground/80'
                                }`}
                                style={selected ? { borderColor: meta.tone, background: `${meta.tone}0f` } : undefined}
                              >
                                {selected ? (
                                  <span
                                    aria-hidden
                                    className="shrink-0 text-[10px] font-bold"
                                    style={{ color: meta.tone }}
                                  >
                                    ✓
                                  </span>
                                ) : (
                                  <span aria-hidden className="shrink-0 text-[10px] text-muted-foreground/40">
                                    ♧
                                  </span>
                                )}
                                <span className="min-w-0 truncate">{q}</span>
                              </div>
                            )
                          })}
                        </div>
                        {inAnswer ? (
                          <div className="flex items-center gap-2 text-[12px] text-foreground">
                            <span
                              aria-hidden
                              className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-t-transparent"
                              style={{ borderColor: meta.tone, borderTopColor: 'transparent' }}
                            />
                            <span>正在生成答案…</span>
                          </div>
                        ) : null}
                      </>
                    )}
                  </div>
                ) : (
                  <>
                    {/* intro */}
                    <p className="text-[12px] leading-relaxed text-muted-foreground">
                      {INTROS[key]}
                    </p>

                    {/* key points */}
                    <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
                      {meta.points.map((point) => (
                        <span
                          key={point}
                          className="rounded-md px-2 py-0.5 text-[11px]"
                          style={{ background: `${meta.tone}12`, color: meta.tone }}
                        >
                          {point}
                        </span>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {/* hover arrow */}
              <span
                aria-hidden
                className="absolute right-4 bottom-4 text-base text-muted-foreground/30 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-muted-foreground/60"
              >
                →
              </span>
            </button>
          )
        })}
      </div>

      <p className="mt-8 text-center text-xs text-muted-foreground">
        示例合同为虚构材料，仅用于功能演示，不构成任何法律建议。
      </p>
    </div>
  )
}
