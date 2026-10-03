// 分析页：左栏条款列表（引用/术语悬浮），右栏 分析 / 原文 / 智读 三标签。
// 本地回退逻辑自 yueding/app.js 原样移植；后端可用时走 analyze→screen→suggest。
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import type { Finding, ScreenFinding, ScreenResult } from '@/api/client'
import {
  backendFindingKey,
  backendFindingTitle,
  backendTopicForQuestion,
  questionFocusTypes,
  useApp,
  type AnswerState,
} from '@/state'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

// ── 通用小工具 ────────────────────────────────────────────────

function esc(s: unknown): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] || c)
}

// 外部数据防御性读取：非对象一律视为空记录，结构异常不抛错。
function rec(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object' && !Array.isArray(v)) return v as Record<string, unknown>
  return {}
}

function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)).filter(Boolean) : []
}

function validIndex(index: number, clauses: string[]): number {
  return Number.isInteger(index) && index >= 0 && index < clauses.length ? index : -1
}

// ── 本地回退：条款定位与要点卡片（app.js 原样移植） ─────────────

const CLAUSE_INDEX_REGEX: Record<string, RegExp> = {
  deposit: /押金/,
  wall: /打孔|书架|改动/,
  modification: /打孔|书架|改动/,
  repair: /维修/,
  leave: /提前|解除|退租/,
  early_termination: /提前|解除|退租/,
  privacy: /推荐|撤回/,
  consent_withdrawal: /推荐|撤回|同意|注销|删除/,
  salary: /奖金|绩效/,
  compensation: /奖金|绩效|工资|薪酬/,
}

function clauseIndex(topic: string, clauses: string[]): number {
  const regex = CLAUSE_INDEX_REGEX[topic]
  return regex ? clauses.findIndex((x) => regex.test(x)) : -1
}

function findingsData(sample: string | null, clauses: string[]): Finding[] {
  const items: Array<[string, string, string]> =
    sample === 'privacy'
      ? [['consent_withdrawal', '同意与撤回', '撤回同意与个人信息处理']]
      : sample === 'labor'
        ? [['compensation', '绩效奖金', '考核方案与发放条件']]
        : [
            ['deposit', '押金返还', '退还时间与扣减条件'],
            ['modification', '墙面改动', '安装书架前的书面确认'],
            ['repair', '维修责任', '设施损坏由谁负责'],
            ['early_termination', '提前退租', '通知时间与费用约定'],
          ]
  return items.map(([k, t, d]) => ({
    key: backendFindingKey(k),
    type: k,
    title: t,
    desc: d,
    index: clauseIndex(k, clauses),
    status: 'confirmed',
    confidence: 0,
    message: '',
    action_card: null,
    contract_evidence: [],
    severity: 'unknown',
    consequences: [],
    provenance: 'local',
  }))
}

const SAMPLE_ANSWERS: Record<string, [string, string]> = {
  wall: ['需房东书面确认', '示例合同要求墙面打孔须取得出租人书面同意。建议先确认安装位置、方式及退租恢复标准。'],
  modification: ['需房东书面确认', '示例合同要求墙面打孔须取得出租人书面同意。建议先确认安装位置、方式及退租恢复标准。'],
  deposit: ['七日内返还剩余押金', '示例合同约定结清费用并交还房屋后七日内退还剩余押金；具体扣减项目和凭证还需确认。'],
  repair: ['需核对损坏原因', '示例合同对使用不当造成的损坏约定由承租人承担责任；自然损耗和设施老化的安排仍需确认。'],
  leave: ['提前三十日书面通知', '示例合同要求提前三十日书面通知，但费用写为另行协商，建议把金额或计算方式写清。'],
  early_termination: ['提前三十日书面通知', '示例合同要求提前三十日书面通知，但费用写为另行协商，建议把金额或计算方式写清。'],
  privacy: ['可在设置中撤回同意', '示例协议允许撤回个性化推荐同意。可进一步确认关闭后的处理范围。'],
  consent_withdrawal: ['可在设置中撤回同意', '示例协议允许撤回个性化推荐同意。可进一步确认关闭后的处理范围。'],
  retention_period: ['注销后三十日内删除', '示例协议约定注销账户后三十日内删除或匿名化处理；依法需保留的除外。'],
  salary: ['奖金标准需进一步确认', '示例合同引用了另行制定的考核方案，未写明具体标准。建议签约前索取并核对方案。'],
  compensation: ['奖金标准需进一步确认', '示例合同引用了另行制定的考核方案，未写明具体标准。建议签约前索取并核对方案。'],
  probation_period: ['试用期约定需核对', '请核对示例合同中试用期的期限与薪资约定。'],
  overtime: ['加班安排需核对', '请核对工时与调休安排是否明确。'],
  termination: ['解除条件需核对', '请核对解除情形与经济补偿安排。'],
  non_compete: ['竞业限制需核对', '请核对竞业限制范围、期限与补偿。'],
  processing_scope: ['收集范围需核对', '请核对个人信息收集范围与处理目的是否明确。'],
  sharing_delegation: ['共享范围需核对', '请核对第三方共享与委托处理的范围和约束。'],
  security_breach_notice: ['安全义务需核对', '请核对加密与泄露通知的应急安排。'],
}

function answerFor(q: string, clauses: string[], isSample: boolean): AnswerState {
  const topic = backendTopicForQuestion(q)
  const i = topic ? clauseIndex(topic, clauses) : -1
  if (i < 0)
    return {
      title: '需要进一步核对',
      text: '未找到能够直接回答该问题的相关约定。请核对完整合同，并向对方书面确认。当前体验版仅进行关键词匹配。',
      index: -1,
    }
  if (!isSample)
    return {
      title: '找到相关原文，待人工确认',
      text: '下方定位到了包含相关关键词的段落，请结合完整上下文核对。体验版不对这份合同作自动法律判断。',
      index: i,
    }
  const hit = (topic && SAMPLE_ANSWERS[topic]) || [
    '相关条款需进一步确认',
    '已定位到与该问题相关的示例条款，请结合完整上下文核对。',
  ]
  return { title: hit[0], text: hit[1], index: i }
}

// ── 立场初筛（本地规则） ──────────────────────────────────────

const STANCE_CN: Record<string, string> = { unfavorable: '对我方不利', favorable: '有利', neutral: '中性', uncertain: '待确认' }
const PRIORITY_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' }
const PRIORITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 }

function localStanceOf(text: string): 'unfavorable' | 'favorable' | 'neutral' {
  if (/不得|必须|须提前|应当.{0,10}(书面|同意|通知)|承担.{0,6}(费用|责任|赔偿)|另行协商/.test(text)) return 'unfavorable'
  if (/可以|有权|退还|返还|由(出租人|甲方|用人单位|处理者|对方)承担|书面同意后|撤回/.test(text)) return 'favorable'
  return 'neutral'
}

function localScreenFor(f: Finding, clauses: string[]): ScreenFinding {
  const text = validIndex(f.index, clauses) >= 0 ? clauses[f.index] : ''
  const stance = localStanceOf(text)
  return {
    stance,
    priority: stance === 'unfavorable' ? 'high' : 'medium',
    interest_note:
      stance === 'unfavorable'
        ? '本地初筛：该条可能限制你的行动，建议核对影响范围'
        : stance === 'favorable'
          ? '本地初筛：该条支持你的目标，可作为协商依据'
          : '本地初筛：影响待确认，建议结合上下文判断',
    evidence: { quote: text },
    clause_type: f.type,
    negotiation_hint: '',
    status: 'not_found',
  }
}

type Scene = 'rental' | 'privacy' | 'labor' | 'legal_aid'
const PRIVACY_KEYS = ['processing_scope', 'consent_withdrawal', 'sharing_delegation', 'retention_period', 'security_breach_notice']
const LABOR_KEYS = ['probation_period', 'overtime', 'compensation', 'non_compete', 'termination']
const LEGAL_AID_KEYS = ['eligibility', 'service_scope', 'application_process', 'confidentiality', 'responsibility']
const ROLE_OPTIONS: Record<Scene, string[]> = {
  rental: ['承租人', '出租人'],
  privacy: ['数据主体', '个人信息处理者'],
  labor: ['员工', '用人单位'],
  legal_aid: ['当事人'],
}
const DEFAULT_ROLE: Record<Scene, string> = { privacy: '数据主体', labor: '员工', legal_aid: '当事人', rental: '承租人' }

function screenScene(sample: string | null, findings: Finding[] | null): Scene {
  const keys = (findings || []).map((f) => f.key)
  if (sample === 'privacy' || keys.some((k) => PRIVACY_KEYS.includes(k))) return 'privacy'
  if (sample === 'labor' || keys.some((k) => LABOR_KEYS.includes(k))) return 'labor'
  if (keys.some((k) => LEGAL_AID_KEYS.includes(k))) return 'legal_aid'
  return 'rental'
}

function screenFor(key: string, screen: ScreenResult | null): ScreenFinding | null {
  if (!screen || !Array.isArray(screen.findings)) return null
  return screen.findings.find((s) => backendFindingKey(s.clause_type) === key) || null
}

function screenDeepItems(screen: ScreenResult | null): ScreenFinding[] {
  return (screen && Array.isArray(screen.findings) ? screen.findings : [])
    .filter((s) => s.stance !== 'neutral')
    .sort((a, b) => (PRIORITY_RANK[a.priority] ?? 1) - (PRIORITY_RANK[b.priority] ?? 1))
    .slice(0, 3)
}

function deepDiveTask(items: ScreenFinding[], perspective: string): string {
  const block = (s: ScreenFinding) => {
    const mapped = backendFindingTitle(s.clause_type)
    return (
      '用户立场：' +
      perspective +
      '\n以下条款经初筛标记为' +
      (STANCE_CN[s.stance] || '待确认') +
      '：\n「' +
      (mapped === '合同要点' ? s.clause_type : mapped) +
      '」' +
      s.interest_note +
      '；协商提示：' +
      s.negotiation_hint +
      '；原文：' +
      String(s.evidence && s.evidence.quote || '') +
      '\n请进行深度分析与协商拟写事项。'
    )
  }
  return (items.length
    ? items.map(block).join('\n')
    : '用户立场：' + perspective + '\n请基于初筛结果进行深度分析并拟写协商事项。'
  ).slice(0, 1000)
}

// ── 后端 findings 适配（wire 格式 → 前端 Finding，全部防御性取默认） ──

const TOPIC_PATTERNS: Record<string, RegExp[]> = {
  deposit: [/押金|保证金|押付/],
  modification: [/打孔|书架|改动|装修|改建|安装/],
  repair: [/维修|修理|修缮|故障|损坏|报修/, /维护/],
  early_termination: [/提前退租|提前解除|提前终止|退租|解约|解除|提前/],
  processing_scope: [/个人信息|敏感个人信息|自动化决策|处理目的/, /收集/],
  consent_withdrawal: [/撤回|同意|授权|知情/],
  sharing_delegation: [/共享|第三方|委托|对外提供|转让|受托/],
  retention_period: [/保存期限|存储期限/, /保存|删除|保留/],
  security_breach_notice: [/泄露|加密|应急预案|补救/, /安全/],
  probation_period: [/试用期|试用/],
  compensation: [/工资|报酬|薪资|薪酬/],
  overtime: [/加班|调休|工时|工作时间/],
  termination: [/解除|终止|辞退|经济补偿/],
  non_compete: [/竞业限制|竞业|服务期|违约金|保密/],
  eligibility: [/经济困难|符合法定条件|申请法律援助|受援人/],
  service_scope: [/法律咨询|代拟法律文书|刑事辩护|诉讼代理|法律援助服务/],
  application_process: [/申请|受理|审查|条件和程序|法律援助机构/],
  confidentiality: [/个人隐私|商业秘密|国家秘密|保密/],
  responsibility: [/不得向受援人收取|法律责任|违法|责任/],
}

function evidenceQuoteOf(f: Record<string, unknown>): string {
  const evidence = Array.isArray(f.contract_evidence) ? f.contract_evidence : []
  const q = rec(evidence[0]).quote
  return String((typeof q === 'string' ? q : '') || f.content || '').trim()
}

function backendClauseIndexOf(f: Record<string, unknown>, clauses: string[]): number {
  const type = String(f.type || '')
  for (const pattern of TOPIC_PATTERNS[type] || []) {
    const index = clauses.findIndex((clause) => pattern.test(clause))
    if (index >= 0) return index
  }
  const quote = evidenceQuoteOf(f)
  if (!quote) return -1
  const exact = clauses.findIndex((clause) => clause === quote || clause.includes(quote) || quote.includes(clause))
  if (exact >= 0) return exact
  return clauses.findIndex((clause) => quote.includes(clause.slice(0, Math.min(clause.length, 40))))
}

function adaptBackendFindings(list: unknown[], clauses: string[]): Finding[] {
  return list.map((item) => {
    const f = rec(item)
    const type = String(f.type || 'item')
    const severity = String(f.severity || 'unknown')
    const evidence = Array.isArray(f.contract_evidence) ? f.contract_evidence : []
    return {
      key: backendFindingKey(type),
      type,
      title: backendFindingTitle(type),
      desc:
        f.status === 'needs_review'
          ? String(f.message || '文档质量不足，需人工复核')
          : f.status !== 'confirmed'
            ? String(f.message || '未找到相关约定')
            : String(rec(f.action_card).impact || f.message || '已找到相关合同原文'),
      index: backendClauseIndexOf(f, clauses),
      status: String(f.status || 'not_found'),
      confidence: Number(f.confidence) || 0,
      message: String(f.message || ''),
      action_card: f.action_card && typeof f.action_card === 'object' ? rec(f.action_card) : null,
      contract_evidence: evidence.map((x: unknown) => {
        const q = rec(x).quote
        return { quote: typeof q === 'string' ? q : undefined }
      }),
      severity: ['high', 'medium', 'low'].includes(severity) ? severity : 'unknown',
      consequences: strList(f.consequences),
      provenance: String(f.provenance || 'deterministic'),
    }
  })
}

function answerFromBackend(
  question: string,
  clauses: string[],
  isSample: boolean,
  findings: Finding[],
  scene: Scene,
): AnswerState {
  const topic = backendTopicForQuestion(question)
  if (!topic) {
    const labels: Record<Scene, string> = {
      rental: '押金、房屋改动、维修和提前退租',
      privacy: '个人信息处理、同意撤回、共享委托、保存期限和泄露通知',
      labor: '试用期、劳动报酬、加班、解除和竞业限制',
      legal_aid: '援助申请条件、服务范围、申请流程、保密义务和责任',
    }
    return {
      title: '分析完成，请选择合同要点',
      text: '后端已整理' + labels[scene] + '。点击右侧条目即可查看对应原文。',
      index: -1,
    }
  }
  const local = answerFor(question, clauses, isSample)
  const finding = findings.find((item) => item.key === topic)
  if (!finding)
    return local.index >= 0
      ? local
      : { title: '需要进一步核对', text: '后端没有返回与当前问题对应的条款，请核对完整合同并向对方书面确认。', index: -1 }
  const quote = String(finding.contract_evidence[0]?.quote || '').trim()
  const locatedQuote = validIndex(finding.index, clauses) >= 0 ? clauses[finding.index] : quote
  if (finding.status === 'confirmed') {
    const card = rec(finding.action_card)
    const parts = [
      card.impact ? String(card.impact) : '',
      locatedQuote ? '合同原文：「' + locatedQuote + '」' : '',
    ].filter(Boolean)
    return {
      title: card.question ? String(card.question) : finding.title,
      text: parts.join(' '),
      index: validIndex(finding.index, clauses),
      consequences: finding.consequences.filter(Boolean),
    }
  }
  if (finding.status === 'needs_review')
    return {
      title: '需要人工复核',
      text: finding.message || '文档质量不足，后端没有生成确定性条款结果。请核对清晰原文后再判断。',
      index: -1,
    }
  if (local.index >= 0) return local
  return { title: '未找到相关约定', text: finding.message || '合同中未找到与当前问题直接对应的约定，请向对方书面确认。', index: -1 }
}

// ── 智读提取：义务清单 / 交叉引用 / 术语表（app.js 原样移植） ──

interface Obligation {
  id: number
  clauseIndex: number
  text: string
  deadline: string
  subject: string
  done: boolean
}

function documentObligations(clauses: string[], done: Record<string, boolean>): Obligation[] {
  const marker = /(应当|应|须|必须|不得|需要|通知|支付|提交|归还|退还|承担|提供|保存|删除|续期|续租|同意)/
  return clauses
    .map((text, index) => ({ text: String(text), index }))
    .filter((item) => marker.test(item.text))
    .slice(0, 12)
    .map((item, id) => {
      const deadline =
        (item.text.match(/(?:提前|在|于|自).{0,12}(?:日|天|个月|月|年|日期)/) || item.text.match(/\d+\s*(?:日|天|个月|月|年)/) || [''])[0]
      const subject = (item.text.match(/^(出租人|承租人|甲方|乙方|用人单位|劳动者|处理者|用户)/) || ['合同一方'])[0]
      return { id, clauseIndex: item.index, text: item.text, deadline, subject, done: !!done[String(id)] }
    })
}

interface TermDef {
  term: string
  definition: string
}

const GLOSSARY_DEFAULTS: Record<string, string> = {
  承租人: '签署租赁合同并占有、使用房屋的一方。',
  出租人: '提供房屋并收取租金的一方。',
  被许可方: '获得软件等标的物使用许可的一方。',
  许可方: '授予使用许可并保留权利的一方。',
  个人信息: '与已识别或可识别的自然人有关的各种信息。',
  衍生作品: '基于原作品进行改编、翻译、注释或整理形成的作品。',
  Licensee: '获得许可使用权的一方。',
  'Derivative Works': '基于原作品创作的改编、翻译或其他衍生内容。',
}

function definedTerms(clauses: string[]): TermDef[] {
  const terms: Record<string, string> = {}
  clauses.forEach((text) => {
    const match =
      text.match(/[“「"]([^”」"]{2,24})[”」"]\s*(?:是指|指|以下简称)/) ||
      text.match(/([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{1,11})\s*(?:是指|，是指)/)
    if (match) {
      const term = match[1]
      const rest = text
        .slice(text.indexOf(term) + term.length)
        .replace(/^[”」"]?\s*(?:是指|指|以下简称)[:：]?\s*/, '')
        .trim()
      terms[term] = rest || text
    }
  })
  const joined = clauses.join('\n')
  Object.entries(GLOSSARY_DEFAULTS).forEach(([term, definition]) => {
    if (joined.includes(term) && !terms[term]) terms[term] = definition
  })
  return Object.entries(terms).map(([term, definition]) => ({ term, definition }))
}

function referenceTarget(raw: string, from: number, clauses: string[]): number {
  const match = String(raw).match(/(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:条|节)|Section\s+([\d.]+)/i)
  if (!match) return -1
  const key = (match[1] || match[2]).replace('.', '\\.')
  const startHit = clauses.findIndex((c) => new RegExp('^\\s*' + key + '(?:\\s|条|款|\\.|\\b)').test(c))
  if (startHit >= 0 && startHit !== from) return startHit
  return clauses.findIndex((c, i) => i !== from && new RegExp('(?:^|\\s|第)' + key + '(?:条|\\b)').test(c))
}

const REF_CLASS = 'cross-ref cursor-pointer rounded-sm text-blue-600 underline decoration-dashed underline-offset-2 hover:text-blue-800'
const TERM_CLASS = 'glossary-term cursor-help rounded-sm border-b border-dashed border-amber-500 text-amber-700'

function decorateClause(text: string, from: number, clauses: string[], terms: TermDef[]): string {
  const source = String(text)
  const matches: Array<{ start: number; end: number; type: 'ref' | 'term'; value: string; target?: number; definition?: string }> = []
  const refRegex = /(?:第\s*\d+(?:\.\d+)?\s*条(?:第\s*\d+\s*款)?|Section\s+[\d.]+(?:\([a-z]\))?)/gi
  let match: RegExpExecArray | null
  while ((match = refRegex.exec(source))) {
    const target = referenceTarget(match[0], from, clauses)
    if (target >= 0) matches.push({ start: match.index, end: match.index + match[0].length, type: 'ref', value: match[0], target })
  }
  terms.forEach((item) => {
    let offset = source.indexOf(item.term)
    while (offset >= 0) {
      const overlap = matches.some((x) => x.start < offset + item.term.length && x.end > offset)
      if (!overlap) matches.push({ start: offset, end: offset + item.term.length, type: 'term', value: item.term, definition: item.definition })
      offset = source.indexOf(item.term, offset + item.term.length)
    }
  })
  matches.sort((a, b) => a.start - b.start || a.end - b.end)
  let html = ''
  let cursor = 0
  matches.forEach((item) => {
    if (item.start < cursor) return
    html += esc(source.slice(cursor, item.start))
    if (item.type === 'ref' && typeof item.target === 'number') {
      const clause = esc(clauses[item.target].slice(0, 180))
      html += `<span class="${REF_CLASS}" tabindex="0" role="button" data-clause="${item.target}"><span class="cross-ref-popover"><strong>↗ ${esc(item.value)}</strong>${clause}</span>${esc(item.value)}</span>`
    } else if (item.definition !== undefined) {
      html += `<span class="${TERM_CLASS}" tabindex="0"><span class="glossary-popover"><strong>Aa ${esc(item.value)}</strong>${esc(item.definition)}</span>${esc(item.value)}</span>`
    } else {
      html += esc(item.value)
    }
    cursor = item.end
  })
  return html + esc(source.slice(cursor))
}

interface SmartRef {
  from: number
  to: number
  label: string
}

function smartRefs(clauses: string[]): SmartRef[] {
  const out: SmartRef[] = []
  clauses.forEach((text, index) => {
    const regex = /(?:第\s*\d+(?:\.\d+)?\s*条(?:第\s*\d+\s*款)?|Section\s+[\d.]+(?:\([a-z]\))?)/gi
    let m: RegExpExecArray | null
    while ((m = regex.exec(text)) && out.length < 8) {
      const target = referenceTarget(m[0], index, clauses)
      if (target >= 0 && target !== index) out.push({ from: index, to: target, label: m[0] })
    }
  })
  return out.slice(0, 8)
}

// ── 页面组件 ──────────────────────────────────────────────────

export default function Analysis() {
  const { state, api } = useApp()
  const doc = state.doc
  const clauses = useMemo(() => (doc ? doc.clauses : []), [doc])
  const [loading, setLoading] = useState(false)
  const [deepLoading, setDeepLoading] = useState(false)
  const [askText, setAskText] = useState('')
  const stateRef = useRef(state)
  stateRef.current = state
  const ranKeyRef = useRef('')

  const terms = useMemo(() => definedTerms(clauses), [clauses])
  const obligations = useMemo(() => documentObligations(clauses, state.obligationDone), [clauses, state.obligationDone])
  const refs = useMemo(() => smartRefs(clauses), [clauses])

  const focusTopRisk = useCallback(
    (screen: ScreenResult) => {
      const now = stateRef.current
      const risks = screen.findings.filter((s) => s.stance === 'unfavorable')
      if (!risks.length) return
      const top = [...risks].sort((a, b) => (PRIORITY_RANK[a.priority] ?? 1) - (PRIORITY_RANK[b.priority] ?? 1))[0]
      const matched = (now.findings || []).find((x) => x.key === backendFindingKey(top.clause_type))
      let index = validIndex(matched ? matched.index : -1, clauses)
      if (index < 0) {
        const quote = String(top.evidence?.quote || '').trim()
        if (quote) index = clauses.findIndex((c) => c === quote || c.includes(quote) || quote.includes(c))
      }
      index = validIndex(index, clauses)
      if (index >= 0) api.patch({ selected: index })
    },
    [api, clauses],
  )

  const fillSuggestions = useCallback(async () => {
    const text = clauses.join('\n').slice(0, 50_000)
    if (!text) return
    try {
      const r = rec(await api.client.suggest(text))
      const questions = strList(r.questions).slice(0, 3)
      if (questions.length) api.patch({ suggestedQuestions: questions.map((question) => ({ question })) })
    } catch {
      /* suggest 失败时保留 analyze 返回的问题或空列表 */
    }
  }, [api, clauses])

  const runScreen = useCallback(
    async (role?: string) => {
      const now = stateRef.current
      if (!now.doc || now.doc.isSample) return
      const cid = now.backend.contractId
      const vid = now.backend.versionId
      if (!(api.client.enabled() && cid && vid)) return
      try {
        const s = await api.client.screen(cid, vid, role || '')
        const screen: ScreenResult = { ...s, role: role || s.perspective || DEFAULT_ROLE[screenScene(now.sample, now.findings)] }
        api.patch({ screen })
        focusTopRisk(screen)
      } catch {
        /* 初筛不可用：静默保留既有分析卡片与本地定位 */
      }
    },
    [api, focusTopRisk],
  )

  const refreshAnalysis = useCallback(
    async (question: string) => {
      const now = stateRef.current
      if (!now.doc || now.doc.isSample) return
      if (!(api.client.enabled() && now.backend.contractId && now.backend.versionId)) {
        api.patch({ focusTypes: questionFocusTypes(question) })
        return
      }
      setLoading(true)
      try {
        api.notify('后端分析中…')
        const r = rec(await api.client.analyze(now.backend.contractId, now.backend.versionId, question))
        const list = r.findings
        if (!Array.isArray(list)) throw new Error('后端分析响应格式无效')
        const adapted = adaptBackendFindings(list, clauses)
        const suggested = strList2Questions(r.suggested_questions)
        let answer = now.answer
        let answerQuestion = now.answerQuestion
        if (now.answerQuestion !== question || !now.answer) {
          answer = answerFromBackend(question, clauses, false, adapted, screenScene(now.sample, adapted))
          answerQuestion = question
        }
        api.patch({
          findings: adapted,
          focusTypes: strList(r.focus_types),
          suggestedQuestions: suggested,
          backend: {
            ...now.backend,
            qualityStatus: typeof r.quality_status === 'string' ? r.quality_status : now.backend.qualityStatus,
          },
          answer,
          answerQuestion,
          selected: answer && answer.index >= 0 ? answer.index : now.selected,
        })
        await runScreen()
        if (!suggested.length) await fillSuggestions()
      } catch {
        api.notify('后端分析不可用，已回退本地定位')
        api.patch({ focusTypes: questionFocusTypes(question) })
      } finally {
        setLoading(false)
      }
    },
    [api, clauses, runScreen, fillSuggestions],
  )

  // 进入分析页且已有后端合同版本时触发一次（同一版本不重复触发）。
  useEffect(() => {
    const key = `${state.backend.contractId}:${state.backend.versionId}`
    if (!doc || doc.isSample || !state.backend.contractId || !state.backend.versionId || ranKeyRef.current === key) return
    ranKeyRef.current = key
    void refreshAnalysis(stateRef.current.question)
  }, [doc, state.backend.contractId, state.backend.versionId, refreshAnalysis])

  // 切换原文标签或选中条款后滚动定位。
  useEffect(() => {
    const source = state.analysisTab === 'source'
    const el = document.getElementById(source ? `src-clause-${state.selected}` : `clause-${state.selected}`)
    el?.scrollIntoView({ behavior: 'smooth', block: source ? 'center' : 'nearest' })
  }, [state.selected, state.analysisTab])

  async function askBackend(q: string) {
    const now = stateRef.current
    if (!q || !doc || doc.isSample) return
    const cid = now.backend.contractId
    const vid = now.backend.versionId
    if (!(api.client.enabled() && cid && vid)) return
    if (!(await api.client.ready())) {
      api.notify('未配置 LLM，使用本地模板')
      return
    }
    try {
      api.notify('快速模型结合法律库生成专业答案…')
      const raw = rec(await api.client.generate(cid, vid, '基于已抽取的合同证据回答用户提问：' + q))
      const llmRoot = rec(raw.llm)
      const l = rec(llmRoot.result)
      const summary = String(l.summary || '').trim()
      const actions = strList(l.actions)
      const consequences = strList(l.consequences)
      const refs2 = (Array.isArray(l.legal_refs) ? l.legal_refs : [])
        .map((x: unknown) => `「${String(rec(x).article || '相关法条')}」${String(rec(x).quote || '')}`)
        .filter(Boolean)
      const text = summary || consequences.concat(actions).map((x) => '· ' + x).join(' ')
      if (!text) return
      const cite = rec((Array.isArray(l.citations) ? l.citations : [])[0])
      const quote = String(cite.quote || '')
      let index = quote ? clauses.findIndex((c) => c === quote || c.includes(quote) || quote.includes(c)) : -1
      if (index < 0)
        index = validIndex((stateRef.current.answer ?? answerFor(q, clauses, !!doc && doc.isSample)).index, clauses)
      api.patch({
        answer: {
          title: '专业解答',
          text,
          legalRefs: refs2,
          model: String(llmRoot.model || 'GLM'),
          index,
        },
      })
    } catch {
      /* 快速模型失败：保留确定性答案 */
    }
  }

  async function onAsk(raw: string) {
    const q = raw.trim()
    if (!q || !doc) return
    const local = answerFor(q, clauses, doc.isSample)
    api.patch({
      question: q,
      goal: q,
      answer: local,
      answerQuestion: '',
      findings: null,
      focusTypes: [],
      suggestedQuestions: [],
      screen: null,
      analysisTab: 'analysis',
      selected: local.index >= 0 ? local.index : stateRef.current.selected,
    })
    setAskText('')
    await refreshAnalysis(q)
    await askBackend(q)
  }

  function onSuggestedClick(q: string) {
    api.patch({
      question: q,
      goal: q,
      answer: null,
      answerQuestion: '',
      findings: null,
      focusTypes: [],
      suggestedQuestions: [],
      screen: null,
    })
    void refreshAnalysis(q)
  }

  async function deepDive() {
    const now = stateRef.current
    if (!doc || doc.isSample) return
    const cid = now.backend.contractId
    const vid = now.backend.versionId
    if (!(api.client.enabled() && cid && vid)) return api.notify('深度分析需配置 LLM（CONTRACT_READER_LLM_PRIMARY_*）')
    if (!(await api.client.ready())) return api.notify('深度分析需配置 LLM（CONTRACT_READER_LLM_PRIMARY_*）')
    const list = screenDeepItems(now.screen)
    if (!list.length) return api.notify('暂无立场相关条款，可先切换立场再试')
    setDeepLoading(true)
    try {
      api.notify('正在生成深度分析与协商拟写…')
      const raw = rec(await api.client.generate(cid, vid, deepDiveTask(list, String(now.screen?.perspective || '承租人'))))
      const l = rec(rec(raw.llm).result)
      const summary = String(l.summary || '').trim()
      const text =
        summary || strList(l.consequences)
          .concat(strList(l.actions))
          .map((x) => '· ' + x)
          .join(' ')
      if (!text) return api.notify('后端未返回深度分析结果')
      const first = list[0]
      const matched = (now.findings || []).find((x) => x.key === backendFindingKey(first.clause_type))
      api.patch({
        answer: {
          title: `深度分析与协商拟写 · ${now.screen?.perspective || '我的立场'}`,
          text,
          index: validIndex(matched ? matched.index : -1, clauses),
        },
      })
      api.notify('已生成深度分析与协商拟写')
    } catch {
      api.notify('深度分析生成失败，请稍后再试')
    } finally {
      setDeepLoading(false)
    }
  }

  function selectClause(i: number) {
    if (!(i >= 0) || i >= clauses.length) return api.notify('未找到相关约定，请向对方进一步确认')
    const mobile = window.matchMedia('(max-width: 1023px)').matches
    api.patch(mobile && state.analysisTab !== 'source' ? { selected: i, analysisTab: 'source' } : { selected: i })
  }

  // 条款内交叉引用点击（捕获阶段拦截，避免触发所在条款按钮）。
  function onClauseAreaClick(e: MouseEvent<HTMLDivElement>) {
    const el = e.target instanceof Element ? e.target.closest('.cross-ref') : null
    if (!el) return
    e.stopPropagation()
    const idx = Number(el.getAttribute('data-clause'))
    if (Number.isInteger(idx) && idx >= 0) selectClause(idx)
  }

  if (!doc) return null

  const answer: AnswerState = state.answer ?? answerFor(state.question, clauses, doc.isSample)
  const sourceLabel = doc.isSample
    ? '示例解读'
    : state.backend.contractId
      ? `后端确定性分析 · ${state.backend.qualityStatus || 'unknown'}`
      : '本地文本 · 关键词辅助定位'
  const hasScreen = !!(state.screen && state.screen.findings.length)
  const scene = screenScene(state.sample, state.findings)
  const roleOptions = ROLE_OPTIONS[scene]
  const currentRole = state.screen?.role || DEFAULT_ROLE[scene]
  const deepItems = useMemo(() => screenDeepItems(state.screen), [state.screen])
  const findingList = useMemo(() => {
    let list = (state.findings ?? findingsData(state.sample, clauses)).map((f) => ({
      f,
      s: screenFor(f.key, state.screen) || localScreenFor(f, clauses),
    }))
    if (state.focusTypes.length) list = list.filter((x) => state.focusTypes.includes(x.f.type))
    if (hasScreen)
      list = [...list].sort(
        (a, b) => (PRIORITY_RANK[a.s.priority] ?? 1) - (PRIORITY_RANK[b.s.priority] ?? 1),
      )
    return list
  }, [state.findings, state.focusTypes, state.screen, state.sample, clauses, hasScreen])
  const doneCount = obligations.filter((x) => x.done).length

  return (
    <div className="space-y-4">

      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" onClick={() => api.navigate('home')}>
            ‹ 返回首页
          </Button>
          <h1 className="truncate text-2xl font-semibold">▤ {doc.name}</h1>
          <p className="text-sm text-muted-foreground">{sourceLabel}</p>
        </div>
        {state.backend.qualityStatus === 'needs_review' && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger render={<Badge variant="destructive" className="cursor-help">⚠ 文档需人工复核</Badge>} />
              <TooltipContent className="max-w-64">
                {state.backend.qualityReasons.length ? state.backend.qualityReasons.join('；') : '文档质量不足，后端未生成确定性条款结论。'}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        {/* 左栏：条款列表（桌面常驻，移动端折叠进「原文」标签） */}
        <aside className="hidden flex-col rounded-xl border bg-card lg:flex">
          <div className="flex items-center justify-between gap-2 border-b p-3">
            <h2 className="text-sm font-semibold">合同原文</h2>
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{clauses.length} 段</Badge>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger render={<Badge variant="outline" className="cursor-help">§ 引用 / 术语</Badge>} />
                  <TooltipContent>蓝色下划虚线为条款引用，点击跳转；琥珀色虚线为定义术语，悬浮查看释义。</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </div>
          <div className="max-h-[calc(100vh-16rem)] overflow-y-auto p-3" onClickCapture={onClauseAreaClick}>
            <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground">{doc.intro}</h3>
            <div className="space-y-1.5">
              {clauses.map((x, i) => (
                <button
                  key={i}
                  id={`clause-${i}`}
                  type="button"
                  onClick={() => selectClause(i)}
                  className={`w-full rounded-md border p-3 text-left text-sm leading-relaxed transition-colors ${
                    i === state.selected ? 'border-primary/50 bg-primary/5 shadow-sm' : 'border-transparent hover:bg-muted/60'
                  }`}
                >
                  <span dangerouslySetInnerHTML={{ __html: decorateClause(x, i, clauses, terms) }} />
                </button>
              ))}
              {!clauses.length && (
                <p className="text-sm text-muted-foreground">当前没有可检索文字，请核对文件质量或改用文本/可检索 PDF。</p>
              )}
            </div>
          </div>
          <div className="border-t p-2 text-center text-xs text-muted-foreground">{doc.title} · 点击右侧条目定位原文</div>
        </aside>

        {/* 右栏：分析 / 原文 / 智读 */}
        <section className="min-w-0">
          <Tabs
            value={state.analysisTab}
            onValueChange={(v) => {
              const next = String(v)
              if (next === 'analysis' || next === 'source' || next === 'smart') api.patch({ analysisTab: next })
            }}
          >
            <TabsList className="w-full">
              <TabsTrigger value="analysis" className="flex-1">▥ 分析</TabsTrigger>
              <TabsTrigger value="source" className="flex-1">▤ 原文</TabsTrigger>
              <TabsTrigger value="smart" className="flex-1">✦ 智读</TabsTrigger>
            </TabsList>

            <TabsContent value="analysis" className="mt-4 space-y-4">
              {state.backend.qualityStatus === 'needs_review' && (
                <Alert>
                  <AlertDescription>文档质量需要人工复核，后端未生成确定性条款结论。</AlertDescription>
                </Alert>
              )}

              {loading || state.demoAnalyzing ? (
                <div className="space-y-3">
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span
                      aria-hidden
                      className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent"
                    />
                    正在定位相关条款并生成答案…
                  </p>
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-40 w-full" />
                </div>
              ) : (
                <>
                  <h3 className="text-sm font-semibold">合同要点</h3>
                  {findingList.length ? (
                    <div className="space-y-2">
                      {findingList.map(({ f, s }) => {
                        const quote = String(f.contract_evidence[0]?.quote || '').trim()
                        const card = rec(f.action_card)
                        const sev = ['high', 'medium', 'low'].includes(f.severity) ? f.severity : ''
                        return (
                          <Card
                            key={f.key}
                            className={`transition-colors ${f.index >= 0 ? 'cursor-pointer hover:border-primary/40' : ''} ${
                              f.index >= 0 && state.selected === f.index ? 'ring-2 ring-primary/40' : ''
                            }`}
                            onClick={() => f.index >= 0 && selectClause(f.index)}
                          >
                            <CardContent className="space-y-2 p-4">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <strong className="text-sm">{f.title}</strong>
                                {s.stance === 'favorable' && <Badge className="bg-green-100 text-green-800 hover:bg-green-100">有利</Badge>}
                                {s.stance === 'unfavorable' && <Badge variant="destructive">对我方不利</Badge>}
                                {s.stance === 'neutral' && <Badge variant="secondary">中性</Badge>}
                                {s.stance !== 'favorable' && s.stance !== 'unfavorable' && s.stance !== 'neutral' && (
                                  <Badge variant="outline">待确认</Badge>
                                )}
                                {sev && (
                                  <Badge variant={sev === 'high' ? 'destructive' : sev === 'medium' ? 'secondary' : 'outline'}>
                                    {sev === 'high' ? '高风险' : sev === 'medium' ? '中风险' : '低风险'}
                                  </Badge>
                                )}
                                {state.focusTypes.includes(f.type) && <Badge variant="outline" className="border-amber-300 text-amber-700">围绕当前问题</Badge>}
                                <Badge variant="secondary">关注{PRIORITY_LABEL[s.priority] || '中'}</Badge>
                              </div>
                              <p className="text-sm text-muted-foreground">
                                {f.status === 'needs_review' ? f.desc || '文档质量需要人工复核' : f.index < 0 ? f.desc || '未找到相关约定' : f.desc}
                              </p>
                              {s.interest_note && <p className="text-xs text-muted-foreground/80">◇ {s.interest_note}</p>}
                              {quote && (
                                <blockquote className="border-l-2 border-muted pl-3 text-xs leading-relaxed text-muted-foreground">
                                  合同原文：「{quote}」
                                </blockquote>
                              )}
                              {Boolean(card.question || card.impact || card.suggested_revision) && (
                                <div className="space-y-1 rounded-md bg-muted/60 p-2 text-xs">
                                  {Boolean(card.question) && (
                                    <p>
                                      <strong>问题：</strong>
                                      {String(card.question)}
                                    </p>
                                  )}
                                  {Boolean(card.impact) && (
                                    <p>
                                      <strong>影响：</strong>
                                      {String(card.impact)}
                                    </p>
                                  )}
                                  {Boolean(card.suggested_revision) && (
                                    <p>
                                      <strong>建议修订：</strong>
                                      {String(card.suggested_revision)}
                                    </p>
                                  )}
                                </div>
                              )}
                            </CardContent>
                          </Card>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">没有找到与当前问题直接对应的条款，请换一种问法或补充合同原文。</p>
                  )}

                  {state.suggestedQuestions.length > 0 && (
                    <div className="space-y-2">
                      <h3 className="text-sm font-semibold">猜你想问</h3>
                      {state.suggestedQuestions.map((item, i) => (
                        <Button
                          key={i}
                          variant="outline"
                          className="w-full justify-between font-normal"
                          onClick={() => onSuggestedClick(item.question)}
                        >
                          <span className="truncate">{item.question}</span>
                          <span aria-hidden>›</span>
                        </Button>
                      ))}
                    </div>
                  )}

                  <Separator />

                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold">你的提问</h3>
                    <div className="rounded-lg bg-muted p-3 text-sm">♧ {state.question || '哪些事项需要提前确认？'}</div>
                    <Card>
                      <CardContent className="space-y-2 p-4">
                        <div className="flex items-start justify-between gap-2">
                          <strong className="text-sm">ⓘ {answer.title}</strong>
                          <Badge variant="secondary" className="shrink-0">{sourceLabel}</Badge>
                        </div>
                        <p className="text-sm leading-relaxed">{answer.text}</p>
                        {answer.consequences && answer.consequences.length > 0 && (
                          <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                            {answer.consequences.map((c, i) => (
                              <li key={i}>{c}</li>
                            ))}
                          </ul>
                        )}
                        {answer.legalRefs && answer.legalRefs.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1">
                            <span className="text-xs text-muted-foreground">§ 依据法条 · 本地法律库</span>
                            {answer.legalRefs.map((r, i) => (
                              <Badge key={i} variant="outline">{r}</Badge>
                            ))}
                          </div>
                        )}
                        {answer.model && <p className="text-xs text-muted-foreground">✦ {answer.model} · 结合法律语料生成 · 请以合同原文为准</p>}
                        {answer.index >= 0 && (
                          <Button variant="outline" size="sm" onClick={() => api.patch({ analysisTab: 'source' })}>
                            ▤ 查看原文 · 第 {answer.index + 1} 段
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                    <form
                      className="flex gap-2"
                      onSubmit={(e) => {
                        e.preventDefault()
                        void onAsk(askText)
                      }}
                    >
                      <Input
                        value={askText}
                        onChange={(e) => setAskText(e.target.value)}
                        placeholder="继续问这份合同…"
                        maxLength={200}
                        aria-label="继续提问"
                      />
                      <Button type="submit" aria-label="提交问题">
                        ➤
                      </Button>
                    </form>
                  </div>

                  {hasScreen && (
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>
                        立场：{state.screen?.perspective || '—'} · 引擎：{state.screen?.engine || '—'}
                      </span>
                      <Select
                        value={currentRole}
                        onValueChange={(v) => {
                          const role = String(v)
                          if (role) void runScreen(role)
                        }}
                      >
                        <SelectTrigger size="sm" className="w-32" aria-label="切换我的立场">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {roleOptions.map((o) => (
                            <SelectItem key={o} value={o}>
                              {o}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2">
                    {hasScreen && deepItems.length > 0 && (
                      <Button variant="outline" onClick={() => void deepDive()} disabled={deepLoading}>
                        ✦ 深度分析与协商拟写
                      </Button>
                    )}
                    <Button onClick={() => api.navigate('workshop')}>去工坊，生成确认消息</Button>
                  </div>
                </>
              )}
            </TabsContent>

            <TabsContent value="source" className="mt-4">
              <Card>
                <CardContent className="p-0">
                  <div className="max-h-[70vh] overflow-y-auto p-4" onClickCapture={onClauseAreaClick}>
                    <h3 className="mb-3 text-sm font-medium text-muted-foreground">{doc.intro}</h3>
                    <div className="space-y-2">
                      {clauses.map((x, i) => (
                        <div
                          key={i}
                          id={`src-clause-${i}`}
                          role="button"
                          tabIndex={0}
                          onClick={() => selectClause(i)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              selectClause(i)
                            }
                          }}
                          className={`cursor-pointer rounded-md p-2 text-sm leading-relaxed transition-colors ${
                            i === state.selected ? 'bg-primary/10 ring-1 ring-primary/30' : 'opacity-50 hover:opacity-90'
                          }`}
                        >
                          <span dangerouslySetInnerHTML={{ __html: decorateClause(x, i, clauses, terms) }} />
                        </div>
                      ))}
                      {!clauses.length && <p className="text-sm text-muted-foreground">当前没有可检索文字。</p>}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="smart" className="mt-4">
              {state.demoDeep ? (
                <div className="space-y-3">
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span
                      aria-hidden
                      className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent"
                    />
                    正在整理义务清单、术语表与交叉引用…
                  </p>
                  <Skeleton className="h-24 w-full" />
                  <Skeleton className="h-40 w-full" />
                </div>
              ) : (
              <div className="space-y-3">
                <div>
                  <h3 className="text-sm font-semibold">围绕当前问题的提取</h3>
                  <p className="text-xs text-muted-foreground">「{state.question || '未填写问题'}」 · 可核验</p>
                </div>

                <Card>
                  <CardTitle className="flex items-center justify-between p-4 pb-2 text-sm">
                    ✓ 义务清单
                    <span className="text-xs font-normal text-muted-foreground">
                      {doneCount}/{obligations.length} 完成
                    </span>
                  </CardTitle>
                  <CardContent className="space-y-2 pt-2">
                    <Progress value={obligations.length ? (doneCount / obligations.length) * 100 : 0} />
                    {obligations.length ? (
                      obligations.map((item) => (
                        <label key={item.id} className={`flex items-start gap-2 text-sm ${item.done ? 'opacity-60' : ''}`}>
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={item.done}
                            onChange={(e) =>
                              api.patch({
                                obligationDone: { ...state.obligationDone, [String(item.id)]: e.target.checked },
                              })
                            }
                          />
                          <span className={item.done ? 'line-through' : ''}>
                            <strong>
                              {item.subject} · {item.text.slice(0, 88)}
                            </strong>
                            <small className="block text-xs font-normal text-muted-foreground">
                              期限：{item.deadline || '从条款中提取的待办事项'}
                            </small>
                          </span>
                        </label>
                      ))
                    ) : (
                      <p className="text-sm text-muted-foreground">未发现明确的“应当/须/通知”义务。</p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardTitle className="flex items-center justify-between p-4 pb-2 text-sm">
                    ↗ 交叉引用
                    <span className="text-xs font-normal text-muted-foreground">{refs.length} 条</span>
                  </CardTitle>
                  <CardContent className="space-y-1.5 pt-2">
                    {refs.length ? (
                      refs.map((item, i) => (
                        <Button key={i} variant="secondary" className="w-full justify-between font-normal" onClick={() => selectClause(item.to)}>
                          <span>
                            第 {item.from + 1} 段提到 {item.label}
                          </span>
                          <span aria-hidden>查看第 {item.to + 1} 段 ›</span>
                        </Button>
                      ))
                    ) : (
                      <p className="text-sm text-muted-foreground">当前文本没有可定位的条款引用。</p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardTitle className="flex items-center justify-between p-4 pb-2 text-sm">
                    Aa 术语表
                    <span className="text-xs font-normal text-muted-foreground">{terms.length} 个</span>
                  </CardTitle>
                  <CardContent className="pt-2">
                    {terms.length ? (
                      <div className="grid gap-2 sm:grid-cols-2">
                        {terms.map((item) => (
                          <div key={item.term} className="rounded-md border p-2">
                            <strong className="text-sm">{item.term}</strong>
                            <p className="text-xs text-muted-foreground">{item.definition}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">检测到定义式术语后会在原文中悬浮展开。</p>
                    )}
                  </CardContent>
                </Card>
              </div>
              )}
            </TabsContent>
          </Tabs>
        </section>
      </div>
    </div>
  )
}

// analyze 返回的 suggested_questions 可能是字符串或 {question} 对象，统一收敛。
function strList2Questions(v: unknown): Array<{ question: string }> {
  return (Array.isArray(v) ? v : [])
    .map((x: unknown) => ({ question: String(rec(x).question || x) }))
    .filter((x) => x.question && x.question !== '[object Object]')
}
