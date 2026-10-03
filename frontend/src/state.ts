// 约定合同阅读器 — 共享应用状态（单一事实来源）
// 页面通过 AppContext/useApp 读写状态，避免多份平行状态定义。
import { createContext, useContext } from 'react'
import {
  BackendClient,
  type BackendConfig,
  type Finding,
  type KbHit,
  type KbItem,
  type KbListItem,
  type LegalCorpus,
  type LegalProvision,
  type ScreenResult,
  type UploadResult,
} from './api/client'

export type Page = 'home' | 'analysis' | 'workshop' | 'contracts' | 'templates' | 'legal' | 'help'
export type ImportTab = 'text' | 'pdf' | 'image' | 'url'
export type AnalysisTab = 'analysis' | 'source' | 'smart'
export type WorkTab = 'message' | 'alternative' | 'supplement'

export interface ContractDoc {
  name: string
  title: string
  intro: string
  clauses: string[]
  isSample: boolean
  question?: string
  goal?: string
}

export interface AnswerState {
  title: string
  text: string
  index: number
  consequences?: string[]
  legalRefs?: string[]
  model?: string
}

export interface BackendState {
  contractId: string | null
  versionId: string | null
  qualityStatus: string | null
  qualityReasons: string[]
  pages: unknown[]
 }

export interface DraftState {
  message: string
  alternative: string
  supplement: string
}

export interface AppState {
  page: Page
  tab: ImportTab
  text: string
  question: string
  goal: string
  condition: boolean
  sample: string | null
  doc: ContractDoc | null
  selected: number
  workTab: WorkTab
  analysisTab: AnalysisTab
  answer: AnswerState | null
  answerQuestion: string
  findings: Finding[] | null
  focusTypes: string[]
  suggestedQuestions: Array<{ question: string }>
  homeSuggested: string[]
  homeSuggestionSource: string
  file: File | null
  pendingUpload: UploadResult | null
  fileText: string
  fetchUrl: string
  screen: ScreenResult | null
  obligationDone: Record<string, boolean>
  legalCorpus: LegalCorpus | null
  legalResults: LegalProvision[] | null
  legalQuery: string
  kbList: KbListItem[] | null
  kbItem: KbItem | null
  kbQuery: string
  kbHits: KbHit[] | null
  legalScope: string
  kbShowAll: boolean
   backend: BackendState
  history: ContractDoc[]
  drafts: DraftState
 }

export interface AppApi {
  patch: (partial: Partial<AppState>) => void
  client: BackendClient
  navigate: (page: Page) => void
  notify: (message: string) => void
}

export const AppContext = createContext<{ state: AppState; api: AppApi } | null>(null)

export function useApp(): { state: AppState; api: AppApi } {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp 必须在 AppContext.Provider 内使用')
  return ctx
}

// 兼容外壳约定的别名（App.tsx 口径使用 useAppState）
export const useAppState = useApp

export function createInitialState(): AppState {
  return {
    page: 'home',
    tab: 'text',
    text: '',
    question: '',
    goal: '',
    condition: true,
    sample: null,
    doc: null,
    selected: 2,
    workTab: 'message',
    analysisTab: 'analysis',
    answer: null,
    answerQuestion: '',
    findings: null,
    focusTypes: [],
    suggestedQuestions: [],
    homeSuggested: [],
    homeSuggestionSource: '',
    file: null,
    pendingUpload: null,
    fileText: '',
    fetchUrl: '',
    screen: null,
    obligationDone: {},
    legalCorpus: null,
    legalResults: null,
    legalQuery: '',
    kbList: null,
    kbItem: null,
    kbQuery: '',
    kbHits: null,
    legalScope: 'kb',
    kbShowAll: false,
    backend: { contractId: null, versionId: null, qualityStatus: null, qualityReasons: [], pages: [] },
    history: [],
    drafts: { message: '', alternative: '', supplement: '' },
  }
}

// ── 本地回退：问题主题识别（app.js backendTopicForQuestion 原样移植） ──

export function backendTopicForQuestion(question: string): string | null {
  const q = String(question || '')
  if (/押金|保证金|押付/.test(q)) return 'deposit'
  if (/打孔|书架|改动|装修|改建|安装/.test(q)) return 'wall'
  if (/维修|修理|维护|故障|损坏|报修/.test(q)) return 'repair'
  if (/解除劳动合同|辞退/.test(q)) return 'termination'
  if (/撤回|同意|推荐|个性化/.test(q)) return 'consent_withdrawal'
  if (/退卡|注销|关闭|停用|终止服务|删除|保存期限|存储期限|保存|保留/.test(q)) return 'retention_period'
  if (/退租|解约|解除|提前/.test(q)) return 'leave'
  if (/试用期/.test(q)) return 'probation_period'
  if (/加班/.test(q)) return 'overtime'
  if (/竞业|服务期/.test(q)) return 'non_compete'
  if (/工资|报酬|薪资|薪酬|绩效|奖金/.test(q)) return 'compensation'
  if (/共享|第三方|委托/.test(q)) return 'sharing_delegation'
  if (/泄露|加密|应急预案/.test(q)) return 'security_breach_notice'
  if (/收集|个人信息|隐私|信息/.test(q)) return 'processing_scope'
  return null
}

export function questionFocusTypes(question: string): string[] {
  const topic = backendTopicForQuestion(question)
  const map: Record<string, string[]> = {
    deposit: ['deposit'],
    wall: ['modification'],
    repair: ['repair'],
    leave: ['early_termination'],
    retention_period: ['retention_period'],
    processing_scope: ['processing_scope'],
    consent_withdrawal: ['consent_withdrawal'],
    sharing_delegation: ['sharing_delegation'],
    security_breach_notice: ['security_breach_notice'],
    probation_period: ['probation_period'],
    compensation: ['compensation'],
    overtime: ['overtime'],
    termination: ['termination'],
    non_compete: ['non_compete'],
  }
  return (topic && map[topic]) || []
}

// 本地猜你想问（app.js localQuestionSuggestions 原样移植）
export function localQuestionSuggestions(text: string): string[] {
  const source = String(text || '')
  const candidates: Array<[string, RegExp]> = [
    ['押金返还期限、扣除条件和凭证是什么？', /押金|保证金|押付|返还/],
    ['哪些装修或改造需要书面同意，恢复责任由谁承担？', /装修|改造|改建|打孔|安装|恢复/],
    ['日常维修和设施故障的报修、响应及费用由谁负责？', /维修|修理|维护|故障|损坏|报修/],
    ['提前退租的通知期限、违约金和例外情形是什么？', /提前退租|退租|解约|解除|违约金/],
    ['个人信息收集的范围和处理目的是什么？', /个人信息|隐私|收集|处理目的/],
    ['工资标准、构成和支付周期是什么？', /工资|报酬|薪资|薪酬|奖金|绩效/],
  ]
  const ranked = candidates
    .map(([question, pattern]) => ({ question, score: (source.match(pattern) || []).length }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score || a.question.localeCompare(b.question))
  return ranked.length ? ranked.slice(0, 3).map((x) => x.question) : candidates.slice(0, 3).map((x) => x[0])
}

const FINDING_KEYS: Record<string, string> = {
  deposit: 'deposit',
  modification: 'wall',
  repair: 'repair',
  early_termination: 'leave',
  processing_scope: 'processing_scope',
  consent_withdrawal: 'consent_withdrawal',
  sharing_delegation: 'sharing_delegation',
  retention_period: 'retention_period',
  security_breach_notice: 'security_breach_notice',
  probation_period: 'probation_period',
  compensation: 'compensation',
  overtime: 'overtime',
  termination: 'termination',
  non_compete: 'non_compete',
  eligibility: 'eligibility',
  service_scope: 'service_scope',
  application_process: 'application_process',
  confidentiality: 'confidentiality',
  responsibility: 'responsibility',
}

export function backendFindingKey(type: string): string {
  return FINDING_KEYS[type] || String(type || 'item')
}

const FINDING_TITLES: Record<string, string> = {
  deposit: '押金返还',
  modification: '房屋改动',
  repair: '维修责任',
  early_termination: '提前退租',
  processing_scope: '个人信息处理范围',
  consent_withdrawal: '同意与撤回',
  sharing_delegation: '共享与委托',
  retention_period: '保存期限',
  security_breach_notice: '安全与泄露通知',
  probation_period: '试用期',
  compensation: '劳动报酬',
  overtime: '加班与调休',
  termination: '合同解除',
  non_compete: '竞业限制与服务期',
  eligibility: '援助申请条件',
  service_scope: '援助服务范围',
  application_process: '申请与受理流程',
  confidentiality: '保密义务',
  responsibility: '机构与人员责任',
}

export function backendFindingTitle(type: string): string {
  return FINDING_TITLES[type] || '合同要点'
}

// ── 后端客户端单例（window.YUEDING_BACKEND_CONFIG 可覆盖） ─────

declare global {
  interface Window {
    YUEDING_BACKEND_CONFIG?: Partial<BackendConfig>
  }
}

const runtimeConfig: Partial<BackendConfig> | undefined =
  typeof window !== 'undefined' ? window.YUEDING_BACKEND_CONFIG : undefined

export const backendClient = new BackendClient(
  runtimeConfig
    ? { baseUrl: runtimeConfig.baseUrl ?? '', timeout: runtimeConfig.timeout ?? 60_000 }
    : undefined,
)
