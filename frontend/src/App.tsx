// 约定合同阅读器 — 应用外壳：全局状态、页头与页面切换
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ContractVersion, UploadResult } from './api/client'
import {
  AppContext,
  backendClient,
  createInitialState,
  localQuestionSuggestions,
  questionFocusTypes,
} from './state'
import type { AppApi, AppState, BackendState, ContractDoc, Page } from './state'
import { examples } from './lib/examples'
import { pagesToClauses } from './lib/pages'
import type { ExampleKey } from './lib/examples'
import { Button } from './components/ui/button'
import BrandMark from './components/BrandMark'
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
          <BrandMark className="h-7 w-7" />
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
  const demoTimers = useRef<number[]>([])
  const demoRunRef = useRef(false)

  useEffect(
    () => () => {
      window.clearTimeout(toastTimer.current)
      demoTimers.current.forEach((t) => window.clearTimeout(t))
    },
    [],
  )

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

  // app.js chooseSample：示例直接进入分析，不经过后端。
  // 模板库仿真流程会把自动选中的问题与建议列表传入；其他入口用本地规则生成建议，
  // 让分析页与真实上传链路一样展示「猜你想问」。
  const chooseSample = useCallback((key: ExampleKey, opts?: { question?: string; suggestions?: string[] }) => {
    const sample = examples[key]
    const question = opts?.question || sample.question
    const suggestions = (
      opts?.suggestions?.length
        ? opts.suggestions
        : [sample.question, ...localQuestionSuggestions(sample.clauses.join('\n')).filter((q) => q !== sample.question)]
    )
      .filter(Boolean)
      .slice(0, 3)
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
      question,
      goal: sample.goal,
      selected: key === 'rental' ? 2 : 1,
      workTab: 'message',
      analysisTab: 'analysis',
      answer: null,
      answerQuestion: '',
      findings: null,
      focusTypes: questionFocusTypes(question),
      suggestedQuestions: suggestions.map((q) => ({ question: q })),
      drafts: EMPTY_DRAFTS,
      history: prev.history.some((x) => x.name === sample.name) ? prev.history : [...prev.history, doc],
    }))
    window.scrollTo(0, 0)
  }, [])

  // 模板库演示回放：用真实主页 UI 复刻「拖入文件 → 停顿 → 生成猜你想问 → 选中 → 开始分析 → 生成答案」
  // 全程 demoRunning 盖住交互，结束后停留在正常的分析页。
  const simulateTemplate = useCallback(
    (key: ExampleKey) => {
      if (demoRunRef.current) return
      demoRunRef.current = true
      demoTimers.current.forEach((t) => window.clearTimeout(t))
      demoTimers.current = []
      const sample = examples[key]
      const pool = localQuestionSuggestions(sample.clauses.join('\n')).filter((q) => q !== sample.question)
      const suggestions = [sample.question, ...pool].filter(Boolean).slice(0, 3)
      const question = suggestions[0]
      const demoFile = new File([sample.clauses.join('\n')], `${sample.name}（演示）.pdf`, {
        type: 'application/pdf',
      })
      const pendingUpload: UploadResult = {
        contract_id: '',
        version_id: '',
        quality_status: 'ok',
        quality_reasons: [],
        pages: sample.clauses,
      }
      const at = (ms: number, fn: () => void) => {
        demoTimers.current.push(window.setTimeout(fn, ms))
      }

      // 1. 回到主页的 PDF 标签，清空上次导入痕迹
      setState((prev) => ({
        ...prev,
        page: 'home',
        tab: 'pdf',
        demoRunning: true,
        demoAnalyzing: false,
        demoDeep: false,
        file: null,
        pendingUpload: null,
        fileText: '',
        homeSuggested: [],
        homeSuggestionSource: 'jev-demo',
        question: '',
      }))
      window.scrollTo(0, 0)
      notify('示例演示开始')

      // 2. 拖入文件：先出现文件名（解析中）
      at(900, () => setState((prev) => ({ ...prev, file: demoFile })))
      // 3. 解析完成：已解析 N 页 + 预览，停顿后生成猜你想问
      at(2400, () => {
        setState((prev) => ({ ...prev, pendingUpload, fileText: sample.clauses.join('\n') }))
        notify(`已解析 ${pendingUpload.pages.length} 页，正在生成猜你想问…`)
      })
      // 4. 猜你想问逐条出现
      at(3500, () => setState((prev) => ({ ...prev, homeSuggested: suggestions.slice(0, 1) })))
      at(3880, () => setState((prev) => ({ ...prev, homeSuggested: suggestions.slice(0, 2) })))
      at(4260, () => setState((prev) => ({ ...prev, homeSuggested: suggestions })))
      // 5. 选中一条，填入问题框
      at(5100, () => {
        setState((prev) => ({ ...prev, question }))
        notify('已填入你的问题')
      })
      // 6. 开始分析：进入分析页的回答加载界面
      at(5900, () => {
        chooseSample(key, { question, suggestions })
        setState((prev) => ({ ...prev, demoAnalyzing: true }))
        notify('正在生成答案…')
      })
      // 7. 答案生成完毕，停留阅读
      at(7900, () => {
        setState((prev) => ({ ...prev, demoAnalyzing: false }))
      })
      // 8. 停留后切入「智读」界面：义务清单 / 术语表 / 交叉引用的整理加载
      at(10600, () => {
        setState((prev) => ({ ...prev, analysisTab: 'smart', demoDeep: true }))
        notify('正在整理智读内容…')
      })
      // 9. 智读内容呈现，停留阅读
      at(12800, () => {
        setState((prev) => ({ ...prev, demoDeep: false }))
        notify('智读整理完成')
      })
      // 10. 停留后进入协商工坊的消息草稿界面
      at(15500, () => {
        setState((prev) => ({ ...prev, page: 'workshop', workTab: 'message' }))
        window.scrollTo(0, 0)
      })
      // 11. 工坊停留后演示结束，页面静止可交互
      at(18200, () => {
        setState((prev) => ({ ...prev, demoRunning: false }))
        demoRunRef.current = false
      })
    },
    [notify, chooseSample],
  )

  const cancelDemo = useCallback(() => {
    demoTimers.current.forEach((t) => window.clearTimeout(t))
    demoTimers.current = []
    demoRunRef.current = false
    setState((prev) => ({
      ...prev,
      demoRunning: false,
      demoAnalyzing: false,
      demoDeep: false,
      file: null,
      pendingUpload: null,
      fileText: '',
      homeSuggested: [],
    }))
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
              onChooseSample={simulateTemplate}
              onStartTextAnalysis={startTextAnalysis}
              onStartFileAnalysis={startFileAnalysis}
              onStartUrlAnalysis={startUrlAnalysis}
            />
          ) : null}
          {state.page === 'analysis' ? <Analysis /> : null}
          {state.page === 'workshop' ? <Workshop /> : null}
          {state.page === 'contracts' ? <Contracts /> : null}
          {state.page === 'templates' ? <Templates onChooseSample={simulateTemplate} /> : null}
          {state.page === 'legal' ? <Legal /> : null}
          {state.page === 'help' ? <Help /> : null}
        </main>
        {state.demoRunning ? (
          <div className="fixed inset-0 z-[60]" role="presentation" aria-label="示例演示进行中">
            <div className="absolute top-4 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-full border bg-background/95 px-4 py-2 shadow-lg backdrop-blur">
              <span
                aria-hidden
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent"
              />
              <span className="text-sm">示例演示进行中</span>
              <button
                type="button"
                className="text-xs text-muted-foreground underline hover:text-foreground"
                onClick={cancelDemo}
              >
                取消演示
              </button>
            </div>
          </div>
        ) : null}
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
