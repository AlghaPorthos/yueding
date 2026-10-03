import { useState } from 'react'
import { useApp } from '../state'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'

const FAQ: [string, string][] = [
  [
    '这份网站可以做什么？',
    '你可以体验导入、原文对照、条款定位、提问反馈、协商模板生成、编辑与复制。租房、隐私和劳动合同示例均为虚构。',
  ],
  [
    '分析结果从哪里来？',
    '示例合同使用预先编写的解读；启用后端后，文本和可检索 PDF 会由后端提取页级原文，并用确定性规则生成押金、改动、维修和提前退租条款卡片。后端找不到依据或文档质量不足时会保留不确定性。启用后端时还会按你选择的立场（如承租人/出租人）对条款做初筛，标注「对我方不利/有利/中性/待确认」和关注度，并可一键发起深度分析与协商拟写（需配置 LLM）。',
  ],
  [
    'PDF、截图与链接如何使用？',
    '启用后端时，可检索 PDF 会提取文字层；没有文字层的扫描 PDF 和图片截图会调用 macOS Vision OCR 识别文字（预编译二进制 + 多页并发，秒级返回）。「输入链接」会由后端抓取网页正文（≤2MB）并进入同一分析链路；动态渲染页面请复制正文到文本框。',
  ],
  [
    '合同内容会被保存吗？',
    '未配置后端时，内容只在浏览器页面内存中处理。配置后端时，上传内容会写入后端合同版本和 SQLite 数据库；前端的"我的合同"仍只记录本次会话，刷新后清空。',
  ],
  [
    '生成的消息会自动发送吗？',
    '不会。你可以修改并复制草稿，由你决定何时通过自己的沟通渠道发送。补充约定也需要双方核对后确认。',
  ],
  [
    '接入后端或智能体后，合同内容会发送到哪里？',
    '后端配置通过 YUEDING_BACKEND_CONFIG 指定，合同会发送到该地址的合同接口；智能体配置通过 docs/MULTI_AGENT_INTERFACE.md 指定。任一服务不可用时，前端保留本地关键词定位和沟通模板。',
  ],
]

export default function Help() {
  const { api } = useApp()
  const [open, setOpen] = useState<number | null>(0)

  return (
    <div className="mx-auto w-full max-w-[1360px] 2xl:max-w-[2040px] px-5 py-8">
      <Button variant="ghost" size="sm" onClick={() => api.navigate('home')}>
        ‹　返回首页
      </Button>

      <div className="mt-6 mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">帮助中心</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            了解约定的工作方式、数据处理和使用限制。
          </p>
        </div>
        <Badge variant="outline" className="mt-1 shrink-0">FAQ</Badge>
      </div>

      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
        {FAQ.map(([q, a], i) => {
          const isOpen = open === i
          return (
            <div key={i}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : i)}
                className={`flex w-full items-start justify-between gap-4 px-5 py-4 text-left transition-colors ${
                  isOpen ? 'bg-muted/40' : 'hover:bg-muted/20'
                }`}
              >
                <span className={`text-[13.5px] leading-snug ${isOpen ? 'font-semibold' : 'font-medium'}`}>
                  {q}
                </span>
                <span
                  aria-hidden
                  className={`mt-0.5 shrink-0 text-[10px] text-muted-foreground transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`}
                >
                  ▾
                </span>
              </button>
              {isOpen && (
                <div className="accordion-open border-t border-border/50 bg-muted/20 px-5 py-4">
                  <p className="text-sm leading-[1.75] text-muted-foreground">{a}</p>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <p className="mt-6 text-center text-xs text-muted-foreground/60">
        约定 · Hackathon 交互原型 · 不构成法律建议
      </p>
    </div>
  )
}
