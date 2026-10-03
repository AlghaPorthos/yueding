import type { CSSProperties } from 'react'
import { exampleKeys, exampleMeta, examples } from '../lib/examples'
import type { ExampleKey } from '../lib/examples'
import { Button } from '../components/ui/button'
import { useApp } from '../state'

export interface TemplatesProps {
  // 点击卡片触发完整演示回放：主页拖入文件 → 猜你想问 → 选中 → 分析（见 App.tsx simulateTemplate）
  onChooseSample: (key: ExampleKey) => void
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

export default function Templates({ onChooseSample }: TemplatesProps) {
  const { api } = useApp()

  return (
    <div className="mx-auto w-full max-w-[1360px] 2xl:max-w-[2040px] px-5 py-8">
      <Button variant="ghost" size="sm" onClick={() => api.navigate('home')}>
        ‹　返回首页
      </Button>

      <div className="mt-6 mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">模板库</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          六种虚构示例合同，用于体验阅读交互。不是可直接签署的合同范本。
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
        {exampleKeys.map((key) => {
          const sample = examples[key]
          const meta = exampleMeta[key]
          return (
            <button
              key={key}
              type="button"
              onClick={() => onChooseSample(key)}
              style={{ '--tone': meta.tone } as CSSProperties}
              className="motion-card group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md"
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
                  <p className="text-[11px] text-muted-foreground/70">点击开始演示导入</p>
                  <h2 className="mt-0.5 text-[15px] font-semibold leading-snug text-foreground">
                    {sample.title}
                  </h2>
                </div>

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
