// 约定合同阅读器 — 应用外壳：全局状态、页头与页面切换
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ContractVersion, UploadResult } from './api/client'
import {
  AppContext,
  backendClient,
  createInitialState,
  questionFocusTypes,
} from './state'
import type { AppApi, AppState, BackendState, ContractDoc, Page } from './state'
import { examples } from './lib/examples'
import type { ExampleKey } from './lib/examples'
import { Button } from './components/ui/button'
import Home from './pages/Home'
import Analysis from './pages/Analysis'
import Workshop from './pages/Workshop'
import Contracts from './pages/Contracts'
import Templates from './pages/Templates'
import Legal from './pages/Legal'
import Help from './pages/Help'

const NAV: Array<{ key: Page; label: string }> = [
  { key: 'home', label: '首页' },
  { key: 'contracts', label: '我的合同' },
  { key: 'templates', label: '模板库' },
  { key: 'legal', label: '法条库' },
  { key: 'help', label: '帮助中心' },
]

const EMPTY_BACKEND: BackendState = {
  contractId: null,
  versionId: null,
  qualityStatus: null,
  qualityReasons: [],
  pages: [],
}

const EMPTY_DRAFTS = { message: '', alternative: '', supplement: '' }

// 各导入流程共用的分析区复位（对应 app.js startAnalysis/beginFileAnalysis 等）
const ANALYSIS_RESET: Partial<AppState> = {
  answer: null,
  answerQuestion: '',
  findings: null,
  focusTypes: [],
  suggestedQuestions: [],
  screen: null,
  drafts: EMPTY_DRAFTS,
  analysisTab: 'analysis',
}

// app.js backendPagesToClauses：页可能是 { text } / { quote } 对象，按行拆分条款
function pagesToClauses(pages: readonly unknown[]): string[] {
  const clauses: string[] = []
  for (const page of pages) {
    let text = ''
    if (typeof page === 'string') text = page
    else if (page && typeof page === 'object' && 'text' in page && typeof page.text === 'string') text = page.text
    else if (page && typeof page === 'object' && 'quote' in page && typeof page.quote === 'string') text = page.quote
    for (const line of text.trim().split(/\n+/)) {
      const trimmed = line.trim()
      if (trimmed) clauses.push(trimmed)
    }
  }
  return clauses
}

// app.js applyBackendUpload：上传 / 网页抓取 / 打开历史合同共用的文档落地
function uploadToDoc(
  data: UploadResult | ContractVersion,
  name: string,
): { doc: ContractDoc; backend: BackendState; selected: number } {
  const pages: unknown[] = Array.isArray(data.pages) ? data.pages : []
  const clauses = pagesToClauses(pages)
  return {
    doc: {
      name,
      title: '合同原文',
      intro: pages.length ? `导入材料 · ${pages.length} 页` : '待复核的图片材料',
      clauses,
      isSample: false,
    },
    backend: {
      contractId: data.contract_id || null,
      versionId: data.version_id || null,
      qualityStatus: data.quality_status || null,
      qualityReasons: Array.isArray(data.quality_reasons) ? data.quality_reasons : [],
      pages,
    },
    selected: clauses.length ? 0 : -1,
  }
}

function Header({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex h-12 w-full max-w-[1360px] items-center justify-between gap-3 px-5">
        <button type="button" className="flex items-center gap-2" onClick={() => onNavigate('home')} aria-label="回到首页">
          <span aria-hidden className="text-2xl leading-none font-bold text-primary">约</span>
          <span className="text-sm font-semibold tracking-tight">约定</span>
          <span className="text-[11px] font-medium tracking-[0.16em] text-muted-foreground">YUEDING</span>
        </button>
        <nav className="hidden items-center gap-0.5 md:flex" aria-label="主导航">
          {NAV.map((item) => (
            <Button
              key={item.key}
              size="sm"
              variant={page === item.key ? 'default' : 'ghost'}
              className={page === item.key ? 'text-xs' : 'text-[13px] font-normal'}
              onClick={() => onNavigate(item.key)}
            >
              {item.label}
            </Button>
          ))}
        </nav>
        <Button
          size="icon"
          variant="ghost"
          className="md:hidden"
          aria-label={open ? '关闭主导航' : '打开主导航'}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden className="text-lg leading-none">
            {open ? '✕' : '☰'}
          </span>
        </Button>
      </div>
      {open ? (
        <nav
          className="animate-in fade-in slide-in-from-top-1 bg-background/95 shadow-lg backdrop-blur-sm duration-150 md:hidden"
          aria-label="移动端导航"
        >
          <div className="mx-auto grid w-full max-w-[1360px] gap-0.5 px-5 py-2">
            {NAV.map((item) => (
              <Button
                key={item.key}
                size="sm"
                variant={page === item.key ? 'default' : 'ghost'}
                className={page === item.key ? 'text-xs' : 'justify-start text-[13px] font-normal'}
                onClick={() => {
                  onNavigate(item.key)
                  setOpen(false)
                }}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </nav>
      ) : null}
    </header>
  )
}

export default function App() {
  const [state, setState] = useState<AppState>(createInitialState)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const toastTimer = useRef<number>(0)

  useEffect(() => () => window.clearTimeout(toastTimer.current), [])

  const notify = useCallback((message: string) => {
    setToastMsg(message)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToastMsg(null), 2600)
  }, [])

  const api = useMemo<AppApi>(
    () => ({
      patch: (partial) => setState((prev) => ({ ...prev, ...partial })),
      client: backendClient,
      navigate: (page) => {
        setState((prev) => ({ ...prev, page }))
        window.scrollTo(0, 0)
      },
      notify,
    }),
    [notify],
  )

  // app.js chooseSample：示例直接进入分析，不经过后端
  const chooseSample = useCallback((key: ExampleKey) => {
    const sample = examples[key]
    const doc: ContractDoc = { ...sample, clauses: [...sample.clauses], isSample: true }
    setState((prev) => ({
      ...prev,
      page: 'analysis',
      sample: key,
      file: null,
      pendingUpload: null,
      fileText: '',
      homeSuggested: [],
      backend: EMPTY_BACKEND,
      screen: null,
      doc,
      question: sample.question,
      goal: sample.goal,
      selected: key === 'rental' ? 2 : 1,
      workTab: 'message',
      analysisTab: 'analysis',
      answer: null,
      answerQuestion: '',
      findings: null,
      focusTypes: questionFocusTypes(sample.question),
      suggestedQuestions: [],
      drafts: EMPTY_DRAFTS,
      history: prev.history.some((x) => x.name === sample.name) ? prev.history : [...prev.history, doc],
    }))
    window.scrollTo(0, 0)
  }, [])

  // app.js startAnalysis 文本分支：本地先出结果，后端可用时再上传换取确定性分析
  const startTextAnalysis = useCallback(
    (text: string, question: string) => {
      const doc: ContractDoc = {
        name: '我的合同 · 文本',
        title: '合同原文',
        intro: '导入的合同内容',
        clauses: text.split(/\n+/).map((x) => x.trim()).filter(Boolean),
        isSample: false,
      }
      setState((prev) => ({
        ...prev,
        page: 'analysis',
        text,
        question,
        sample: null,
        screen: null,
        backend: EMPTY_BACKEND,
        doc,
        selected: 0,
        goal: question || '我希望确认这份合同中尚未明确的安排',
        ...ANALYSIS_RESET,
        history: [...prev.history, doc],
      }))
      window.scrollTo(0, 0)
      if (!backendClient.enabled()) return
      notify('正在上传合同…')
      void (async () => {
        try {
          const data = await backendClient.upload(
            new File([text], 'contract.txt', { type: 'text/plain' }),
            '我的合同 · 文本',
          )
          const loaded = uploadToDoc(data, '我的合同 · 文本')
          setState((prev) => ({
            ...prev,
            backend: loaded.backend,
            doc: loaded.doc,
            selected: loaded.selected,
            history: prev.history.map((x, i) => (i === prev.history.length - 1 ? loaded.doc : x)),
          }))
          notify('合同已上传，准备分析')
        } catch {
          notify('后端不可用，已保留本地分析结果')
        }
      })()
    },
    [notify],
  )

  // app.js beginFileAnalysis：Home 已完成上传拿到 pendingUpload，这里直接落地
  const startFileAnalysis = useCallback((file: File, upload: UploadResult, question: string) => {
    const loaded = uploadToDoc(upload, file.name || '导入合同')
    setState((prev) => ({
      ...prev,
      page: 'analysis',
      question,
      goal: question || '我希望确认这份合同中尚未明确的安排',
      sample: null,
      ...ANALYSIS_RESET,
      backend: loaded.backend,
      doc: loaded.doc,
      selected: loaded.selected,
      history: [...prev.history, loaded.doc],
    }))
    window.scrollTo(0, 0)
  }, [])

  // app.js fetchAndAnalyze：先占位抓取中，成功后替换文档并进入分析
  const startUrlAnalysis = useCallback(
    (url: string, question: string) => {
      const target = url.trim()
      const name = target.replace(/^https?:\/\//, '')
      const placeholder: ContractDoc = {
        name: name.slice(0, 40),
        title: '网页正文',
        intro: '正在抓取网页',
        clauses: [],
        isSample: false,
      }
      setState((prev) => ({
        ...prev,
        page: 'analysis',
        fetchUrl: target,
        question,
        goal: question || '我希望确认这份合同中尚未明确的安排',
        sample: null,
        ...ANALYSIS_RESET,
        backend: EMPTY_BACKEND,
        doc: placeholder,
        selected: -1,
        history: [...prev.history, placeholder],
      }))
      window.scrollTo(0, 0)
      if (!backendClient.enabled()) {
        notify('链接抓取需要后端服务，可改用粘贴文本')
        return
      }
      void (async () => {
        try {
          const loaded = uploadToDoc(await backendClient.fetchUrl(target), name.slice(0, 50))
          setState((prev) => ({
            ...prev,
            backend: loaded.backend,
            doc: loaded.doc,
            selected: loaded.selected,
            history: prev.history.map((x, i) => (i === prev.history.length - 1 ? loaded.doc : x)),
          }))
        } catch {
          notify('网页抓取失败，请检查链接或稍后重试')
        }
      })()
    },
    [notify],
  )

  const contextValue = useMemo(() => ({ state, api }), [state, api])

  return (
    <AppContext.Provider value={contextValue}>
      <div className="min-h-screen bg-background text-foreground">
        <Header page={state.page} onNavigate={api.navigate} />
        <main key={state.page} className="mx-auto w-full max-w-[1360px] px-5 py-8 fade-in">
          {state.page === 'home' ? (
            <Home
              onChooseSample={chooseSample}
              onStartTextAnalysis={startTextAnalysis}
              onStartFileAnalysis={startFileAnalysis}
              onStartUrlAnalysis={startUrlAnalysis}
            />
          ) : null}
          {state.page === 'analysis' ? <Analysis /> : null}
          {state.page === 'workshop' ? <Workshop /> : null}
          {state.page === 'contracts' ? <Contracts /> : null}
          {state.page === 'templates' ? <Templates onChooseSample={chooseSample} /> : null}
          {state.page === 'legal' ? <Legal /> : null}
          {state.page === 'help' ? <Help /> : null}
        </main>
        {toastMsg ? (
          <div
            role="status"
            className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground shadow-lg"
          >
            {toastMsg}
          </div>
        ) : null}
      </div>
    </AppContext.Provider>
  )
}
