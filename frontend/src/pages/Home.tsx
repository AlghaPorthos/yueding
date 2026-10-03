// 首页（app.js home()/inputContent() 移植）：导入材料 → 提问 → 开始分析
import { useEffect, useRef, useState } from 'react'
import type { UploadResult } from '../api/client'
import { localQuestionSuggestions, useApp } from '../state'
import type { ImportTab } from '../state'
import { exampleKeys, exampleMeta, examples } from '../lib/examples'
import { pagesToClauses } from '../lib/pages'
import type { ExampleKey } from '../lib/examples'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import { Textarea } from '../components/ui/textarea'

export interface HomeProps {
  onChooseSample: (key: ExampleKey) => void
  onStartTextAnalysis: (text: string, question: string) => void
  onStartFileAnalysis: (file: File, upload: UploadResult, question: string) => void
  onStartUrlAnalysis: (url: string, question: string) => void
}

const IMPORT_TABS: Array<{ key: ImportTab; icon: string; label: string }> = [
  { key: 'text', icon: '♧', label: '粘贴文本' },
  { key: 'pdf', icon: '↥', label: '上传 PDF' },
  { key: 'image', icon: '▧', label: '截图识别' },
  { key: 'url', icon: '⌁', label: '输入链接' },
]

const FILE_TABS = ['pdf', 'image'] as const

const SUGGESTION_SOURCE_LABELS: Record<string, string> = {
  'llm+jev': 'Flash 生成 · Jev 精选',
  llm: 'Flash 通读全文生成',
  jev: 'Jev 模板精选',
  deterministic: '模板建议',
  'jev-demo': '模板建议（本地）',
}

function SuggestionList({
  questions,
  source,
  textMode,
  onPick,
}: {
  questions: string[]
  source: string
  textMode: boolean
  onPick: (question: string) => void
}) {
  if (!questions.length) return null
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">
        猜你想问
        <span className="ml-1">
          {SUGGESTION_SOURCE_LABELS[source] || '建议'} · {textMode ? '停止编辑后生成' : '文件解析后生成'}
        </span>
      </div>
      <div className="grid gap-2">
        {questions.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onPick(question)}
            className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-left text-sm transition-colors hover:border-primary/50 hover:bg-muted/50"
          >
            <span className="min-w-0 truncate">{question}</span>
            <span className="shrink-0 text-xs text-muted-foreground">填入问题　›</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function Home({
  onChooseSample,
  onStartTextAnalysis,
  onStartFileAnalysis,
  onStartUrlAnalysis,
}: HomeProps) {
  const { state, api } = useApp()
  const [drag, setDrag] = useState(false)
  const [inputError, setInputError] = useState('')
  const questionRef = useRef<HTMLInputElement>(null)
  // 跳过首次执行：载入/返回首页时不自动生成建议，仅在编辑后触发（与 app.js 一致）
  const mounted = useRef(true)

  // 文本模式停止编辑 850ms 后生成「猜你想问」（app.js scheduleSuggestions/suggestQuestions）
  useEffect(() => {
    if (mounted.current) {
      mounted.current = false
      return
    }
    if (state.tab !== 'text') return
    const requestText = state.text.trim()
    api.patch({ homeSuggested: [] })
    if (requestText.length < 15) return
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const result = api.client.enabled()
          ? await api.client.suggest(requestText)
          : { source: 'jev-demo', questions: localQuestionSuggestions(requestText) }
        if (cancelled) return
        api.patch({
          homeSuggested: result.questions.map(String),
          homeSuggestionSource: String(result.source || 'jev-demo'),
        })
      } catch {
        if (!cancelled) {
          api.patch({ homeSuggested: localQuestionSuggestions(requestText), homeSuggestionSource: 'jev-demo' })
        }
      }
    }, 850)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // api 来自 context，由 App 保证稳定；仅 text/tab 变化时重新调度
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.text, state.tab])

  function switchTab(value: string) {
    const next = IMPORT_TABS.find((t) => t.key === value)
    if (!next || next.key === state.tab) return
    api.patch({ tab: next.key, file: null, pendingUpload: null, fileText: '', homeSuggested: [] })
  }

  async function selectFile(file: File | undefined) {
    if (!file) return
    const valid =
      state.tab === 'pdf'
        ? file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
        : file.type.startsWith('image/')
    if (!valid) return api.notify('请选择对应格式的文件')
    const maxMb = api.client.enabled() ? 5 : 20
    if (file.size > maxMb * 1024 * 1024) return api.notify(`请选择小于 ${maxMb} MB 的文件`)
    api.patch({ file, pendingUpload: null, fileText: '', homeSuggested: [] })
    if (!api.client.enabled()) return api.notify('已选择文件，可打开本地预览')
    api.notify('正在解析文件…')
    try {
      const data = await api.client.upload(file, file.name)
      const joined = pagesToClauses(data.pages).join('\n').slice(0, 50000)
      api.patch({ pendingUpload: data, fileText: joined })
      api.notify(`已解析 ${data.pages.length} 页，正在生成猜你想问…`)
      try {
        const result = await api.client.suggest(joined)
        api.patch({
          homeSuggested: result.questions.map(String),
          homeSuggestionSource: String(result.source || 'jev-demo'),
        })
      } catch {
        api.patch({ homeSuggested: localQuestionSuggestions(joined), homeSuggestionSource: 'jev-demo' })
      }
    } catch {
      api.notify('文件上传失败，仍可打开本地预览')
    }
  }

  function openFilePreview() {
    if (!state.file) return
    const url = URL.createObjectURL(state.file)
    window.open(url, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }

  function fetchAndAnalyze(url: string) {
    if (!/^https?:\/\//i.test(url)) return api.notify('请输入 http/https 链接')
    if (!api.client.enabled()) return api.notify('抓取网页需要后端服务，请粘贴正文或选择示例')
    api.notify('正在抓取网页…')
    api.patch({ fetchUrl: url })
    onStartUrlAnalysis(url, state.question.trim())
  }

  function startAnalysis() {
    setInputError('')
    if (state.tab === 'url') return fetchAndAnalyze(state.fetchUrl.trim())
    if (state.tab === 'pdf' || state.tab === 'image') {
      if (!state.file || !state.pendingUpload) {
        setInputError('请先选择或拖入文件')
        return
      }
      onStartFileAnalysis(state.file, state.pendingUpload, state.question.trim())
      return
    }
    const text = state.text.trim()
    if (text.length < 15) {
      setInputError('请粘贴至少 15 个字的合同内容，或选择下方示例。')
      return
    }
    onStartTextAnalysis(text, state.question.trim())
  }

  function fillQuestion(question: string) {
    api.patch({ question })
    api.notify('已填入你的问题')
    questionRef.current?.focus()
  }

  return (
    <div className="mx-auto w-full max-w-[1360px] 2xl:max-w-[2040px] space-y-10 px-5 py-8">
      <section className="space-y-2 pt-2 text-center">
        <h1 className="text-[clamp(1.5rem,3.5vw,2.25rem)] font-semibold tracking-tight">读懂约定，再做决定</h1>
        <p className="text-muted-foreground">上传合同或协议，找到与你有关的答案</p>
      </section>

      <section className="space-y-4">
        <p className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">没有合同？试试示例</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {exampleKeys.map((key) => {
            const sample = examples[key]
            const meta = exampleMeta[key]
            return (
              <button
                key={key}
                type="button"
                onClick={() => onChooseSample(key)}
                className="motion-card group relative flex items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-all duration-150 hover:border-foreground/15 hover:shadow-sm"
              >
                <span
                  aria-hidden
                  className="absolute inset-y-0 left-0 w-[3px] rounded-l-xl opacity-0 transition-opacity duration-150 group-hover:opacity-100"
                  style={{ background: meta.tone }}
                />
                <span
                  aria-hidden
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg"
                  style={{ backgroundColor: `${meta.tone}18`, color: meta.tone }}
                >
                  {meta.icon}
                </span>
                <span className="min-w-0 flex-1 space-y-1">
                  <span
                    className="inline-block rounded-full border px-1.5 py-0 text-[10px] font-medium leading-5 tracking-wide"
                    style={{ color: meta.tone, borderColor: `${meta.tone}55` }}
                  >
                    {meta.tag}
                  </span>
                  <strong className="block text-[13px] font-semibold leading-snug">{sample.title}</strong>
                  <small className="block text-[11px] leading-relaxed text-muted-foreground">
                    {meta.points.join(' · ')}
                  </small>
                </span>
                <span aria-hidden className="mt-0.5 text-xs text-muted-foreground/30 transition-all group-hover:translate-x-0.5 group-hover:text-muted-foreground/60">→</span>
              </button>
            )
          })}
        </div>
      </section>

      <Card className="gap-4 rounded-2xl p-5 shadow-none">
        <Tabs value={state.tab} onValueChange={(value) => switchTab(typeof value === 'string' ? value : '')}>
          <TabsList className="grid w-full grid-cols-4">
            {IMPORT_TABS.map((t) => (
              <TabsTrigger key={t.key} value={t.key} className="gap-1 px-1 text-xs sm:text-sm">
                <span aria-hidden>{t.icon}</span>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="text" className="mt-4 space-y-3">
            <Textarea
              aria-label="合同文本"
              maxLength={50000}
              placeholder="在这里粘贴合同或协议内容…"
              value={state.text}
              onChange={(e) => api.patch({ text: e.target.value })}
              className="max-h-96 min-h-48"
            />
            <div className="text-right text-xs text-muted-foreground">
              {state.text.length.toLocaleString()} / 50,000
            </div>
            <SuggestionList
              questions={state.homeSuggested}
              source={state.homeSuggestionSource}
              textMode
              onPick={fillQuestion}
            />
          </TabsContent>

          {FILE_TABS.map((tabKey) => (
            <TabsContent key={tabKey} value={tabKey} className="mt-4 space-y-3">
              <label
                onDragOver={(e) => {
                  e.preventDefault()
                  setDrag(true)
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDrag(false)
                  void selectFile(e.dataTransfer.files[0])
                }}
                className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed p-8 text-center transition-colors ${
                  drag ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40'
                }`}
              >
                <span aria-hidden className="text-3xl text-primary/70">
                  {tabKey === 'pdf' ? '▤' : '▧'}
                </span>
                <strong className="text-sm font-medium">
                  {state.file ? state.file.name : `点击选择或拖拽${tabKey === 'pdf' ? ' PDF 文件' : '合同截图'}`}
                </strong>
                <span className="text-xs text-muted-foreground">
                  {state.pendingUpload
                    ? `✓ 已解析 ${state.pendingUpload.pages.length} 页 · 可在下方选问题后开始分析`
                    : api.client.enabled()
                      ? tabKey === 'pdf'
                        ? '选择后自动提取文字（无文字层走 OCR）'
                        : '选择后自动 OCR 识别'
                      : '文件仅用于本地预览，尚未接入'}
                </span>
                <input
                  type="file"
                  className="hidden"
                  accept={tabKey === 'pdf' ? '.pdf' : 'image/*'}
                  onChange={(e) => {
                    void selectFile(e.target.files?.[0])
                    e.target.value = ''
                  }}
                />
                <small className="text-xs text-muted-foreground">
                  {api.client.enabled() ? '后端文件大小限制为 5 MB' : '要体验分析，请粘贴正文或选择下方示例'}
                </small>
              </label>
              {state.file && (
                <Button variant="outline" size="sm" className="w-full sm:w-auto" onClick={openFilePreview}>
                  打开文件预览
                </Button>
              )}
              {state.fileText && (
                <div className="rounded-lg bg-muted p-3 text-xs leading-relaxed text-muted-foreground">
                  <b className="mb-1 block font-medium text-foreground">解析预览（前 200 字）</b>
                  {state.fileText.replace(/\s+/g, ' ').slice(0, 200)}…
                </div>
              )}
              <SuggestionList
                questions={state.homeSuggested}
                source={state.homeSuggestionSource}
                textMode={false}
                onPick={fillQuestion}
              />
            </TabsContent>
          ))}

          <TabsContent value="url" className="mt-4 space-y-3">
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-8 text-center">
              <span className="text-sm font-medium">粘贴协议链接</span>
              <Input
                type="url"
                aria-label="协议链接"
                placeholder="https://example.com/privacy"
                value={state.fetchUrl}
                onChange={(e) => api.patch({ fetchUrl: e.target.value })}
              />
              <Button className="w-full sm:w-auto" onClick={() => fetchAndAnalyze(state.fetchUrl.trim())}>
                ⤓　抓取网页并分析
              </Button>
              <small className="text-xs text-muted-foreground">
                后端抓取网页正文（≤2MB）后进入同一分析链路；动态渲染的页面请复制正文到「粘贴文本」
              </small>
            </div>
          </TabsContent>
        </Tabs>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <span
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
            >
              ♧
            </span>
            <Input
              ref={questionRef}
              aria-label="你最关心的问题"
              placeholder="你最关心什么？（可选）"
              maxLength={200}
              className="pl-8"
              value={state.question}
              onChange={(e) => api.patch({ question: e.target.value })}
            />
          </div>
          <Button size="lg" className="w-full sm:w-auto" onClick={startAnalysis}>
            ✧　开始分析
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          例如：我能在墙上装书架吗？ / 押金怎么退？ / 可以提前解约吗？
        </p>
        {inputError && (
          <p role="alert" className="text-sm text-destructive">
            {inputError}
          </p>
        )}
      </Card>

      <p className="text-center text-xs text-muted-foreground">
        ◇　{api.client.enabled() ? '内容将发送到已配置的合同分析后端' : '输入仅在当前页面内处理'} · 示例内容为虚构材料
      </p>
    </div>
  )
}
