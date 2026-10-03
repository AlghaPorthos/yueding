// 约定合同阅读器 — 后端 API 客户端（单一事实来源）
// 所有页面通过此模块调用后端，保证调用点与响应形状一致。

const DEFAULT_BASE = 'http://127.0.0.1:8000'
const DEFAULT_TIMEOUT = 60_000

export interface BackendConfig {
  baseUrl: string
  timeout: number
}

// ── 共享响应类型 ──────────────────────────────────────────────

export interface UploadResult {
  contract_id: string
  version_id: string
  quality_status: string | null
  quality_reasons: string[]
  pages: string[]
}

export interface ContractSummary {
  contract_id: string
  version_id?: string
  name: string
  created_at?: string
  page_count?: number
  quality_status?: string | null
}

export interface ContractVersion {
  contract_id: string
  version_id: string
  quality_status: string | null
  quality_reasons: string[]
  pages: string[]
  quality_metrics?: Record<string, unknown>
}

export interface LegalProvision {
  article: string
  content_hash: string
  quote: string
  version?: string
  effective_from?: string
}

export interface LegalSource {
  source: string
  source_display?: string
  count: number
  provisions: LegalProvision[]
}

export interface LegalCorpus {
  status: string
  sources: LegalSource[]
}

export interface KbListItem {
  id: string
  title: string
  type: string
  category: string
}

export interface KbItem {
  title: string
  category?: string
  source?: string
  articles: [string, string][]
}

export interface KbHit {
  doc_id: string
  doc_title: string
  no: string
  doc_type: string
  snippet: string
}

export interface Finding {
  key: string
  type: string
  title: string
  desc: string
  index: number
  status: string
  confidence: number
  message: string
  action_card: Record<string, unknown> | null
  contract_evidence: Array<{ quote?: string }>
  severity: string
  consequences: string[]
  provenance: string
}

export interface AnalyzeResult {
  findings: Finding[]
  focus_types: string[]
  suggested_questions: string[]
  quality_status?: string | null
}

export interface ScreenFinding {
  clause_type: string
  status: string
  stance: string
  interest_note: string
  priority: string
  evidence: { quote?: string }
  negotiation_hint: string
}

export interface ScreenResult {
  status: string
  perspective: string
  engine: string
  disclaimer: string
  role: string
  findings: ScreenFinding[]
  next: Record<string, unknown> | null
}

export interface LlmResult {
  summary: string
  actions: string[]
  consequences: string[]
  legal_refs?: Array<{ article?: string }>
  drafts?: { message?: string; supplement?: string }
}

export interface GenerateResult {
  llm: { result: LlmResult }
}

// ── 客户端 ────────────────────────────────────────────────────

export class BackendClient {
  private baseUrl: string
  private timeout: number

  // undefined config → local dev default; explicit baseUrl='' → local-only mode
  constructor(config?: BackendConfig) {
    this.baseUrl = config === undefined
      ? DEFAULT_BASE
      : String(config.baseUrl ?? '').replace(/\/$/, '')
    this.timeout = (config?.timeout) || DEFAULT_TIMEOUT
  }

  setConfig(config: BackendConfig) {
    this.baseUrl = String(config.baseUrl ?? '').replace(/\/$/, '')
    this.timeout = config.timeout || DEFAULT_TIMEOUT
  }

  enabled(): boolean {
    return !!this.baseUrl
  }

  private url(path: string): string {
    return this.baseUrl + path
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeout)
    try {
      const res = await fetch(this.url(path), { ...options, signal: controller.signal })
      const text = await res.text()
      let data: T | null = null
      try { data = text ? (JSON.parse(text) as T) : null } catch { /* empty */ }
      if (!res.ok) {
        const err = data as { error?: { message?: string } } | null
        throw new Error(err?.error?.message ?? `后端请求失败（HTTP ${res.status}）`)
      }
      return data ?? ({} as T)
    } finally {
      clearTimeout(timer)
    }
  }

  upload(file: File, name?: string): Promise<UploadResult> {
    const form = new FormData()
    form.append('file', file, file.name || 'contract.txt')
    if (name) form.append('name', name)
    return this.request<UploadResult>('/v1/contracts', { method: 'POST', body: form })
  }

  listContracts(): Promise<{ contracts: ContractSummary[] }> {
    return this.request<{ contracts: ContractSummary[] }>('/v1/contracts')
  }

  getVersion(contractId: string, versionId: string): Promise<ContractVersion> {
    return this.request<ContractVersion>(
      `/v1/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}`,
    )
  }

  legalCorpus(): Promise<LegalCorpus> {
    return this.request<LegalCorpus>('/v1/legal/corpus')
  }

  legalSearch(q: string, limit = 12): Promise<{ status: string; results: LegalProvision[] }> {
    return this.request<{ status: string; results: LegalProvision[] }>(
      `/v1/legal/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    )
  }

  kbList(): Promise<{ status: string; items: KbListItem[] }> {
    return this.request<{ status: string; items: KbListItem[] }>('/v1/kb/list')
  }

  kbItem(id: string): Promise<KbItem> {
    return this.request<KbItem>(`/v1/kb/item/${encodeURIComponent(id)}`)
  }

  kbSearch(q: string): Promise<{ status: string; hits: KbHit[] }> {
    return this.request<{ status: string; hits: KbHit[] }>(`/v1/kb/search?q=${encodeURIComponent(q)}`)
  }

  analyze(contractId: string, versionId: string, question: string): Promise<AnalyzeResult> {
    return this.request<AnalyzeResult>(
      `/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}/analyze`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: String(question).slice(0, 300) }),
      },
    )
  }

  suggest(text: string): Promise<{ source: string; questions: string[] }> {
    return this.request<{ source: string; questions: string[] }>('/v1/questions/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: String(text).slice(0, 50_000) }),
    })
  }

  fetchUrl(url: string): Promise<UploadResult> {
    return this.request<UploadResult>('/v1/fetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
  }

  generate(contractId: string, versionId: string, task: string): Promise<GenerateResult> {
    return this.request<GenerateResult>(
      `/v1/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}/generate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task }),
      },
    )
  }

  async screen(contractId: string, versionId: string, userRole?: string): Promise<ScreenResult> {
    const role = String(userRole || '').trim()
    const raw = await this.request<Record<string, unknown>>(
      `/v1/contracts/${encodeURIComponent(contractId)}/versions/${encodeURIComponent(versionId)}/screen`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(role ? { user_role: role } : {}),
      },
    )
    return normalizeScreen(raw)
  }

  async ready(): Promise<boolean> {
    if (!this.enabled()) return false
    try {
      const data = await this.request<Record<string, unknown>>('/readyz')
      const llm = data.llm
      return !!(llm && typeof llm === 'object' && 'configured' in llm && (llm as { configured?: unknown }).configured)
    } catch {
      return false
    }
  }
}

// /screen 响应字段全部防御性取默认，结构异常不抛错。
function normalizeScreen(raw: Record<string, unknown>): ScreenResult {
  const itemsRaw = Array.isArray(raw.findings) ? raw.findings : []
  const findings: ScreenFinding[] = itemsRaw.map((f: unknown) => {
    const x = (f && typeof f === 'object' && !Array.isArray(f) ? f : {}) as Record<string, unknown>
    const ev = x.evidence && typeof x.evidence === 'object' && !Array.isArray(x.evidence)
      ? (x.evidence as Record<string, unknown>)
      : {}
    return {
      clause_type: String(x.clause_type || 'item'),
      status: String(x.status || 'not_found'),
      stance: ['favorable', 'unfavorable', 'neutral'].includes(String(x.stance)) ? String(x.stance) : 'uncertain',
      interest_note: String(x.interest_note || ''),
      priority: ['high', 'medium', 'low'].includes(String(x.priority)) ? String(x.priority) : 'medium',
      evidence: { quote: typeof ev.quote === 'string' ? ev.quote : undefined },
      negotiation_hint: String(x.negotiation_hint || ''),
    }
  })
  const next = raw.next && typeof raw.next === 'object' && !Array.isArray(raw.next)
    ? (raw.next as Record<string, unknown>)
    : null
  return {
    status: String(raw.status || ''),
    perspective: String(raw.perspective || ''),
    engine: String(raw.engine || ''),
    disclaimer: String(raw.disclaimer || ''),
    role: '',
    findings,
    next,
  }
}
