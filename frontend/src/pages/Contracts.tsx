import { useEffect, useState } from 'react'
import { useApp } from '../state'
import { pagesToClauses } from '../lib/pages'
import type { ContractSummary, ContractVersion } from '../api/client'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Skeleton } from '../components/ui/skeleton'

// ponytail: local EMPTY_DRAFTS avoids importing state shape
const EMPTY_DRAFTS = { message: '', alternative: '', supplement: '' }

interface ContractsProps {
  onOpenContract?: (version: ContractVersion, name: string) => void
}


export default function Contracts({ onOpenContract }: ContractsProps) {
  const { state, api } = useApp()
  const backendEnabled = api.client.enabled()
  const [list, setList] = useState<ContractSummary[] | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)

  useEffect(() => {
    if (!backendEnabled || list !== null) return
    let alive = true
    api.client
      .listContracts()
      .then((r) => { if (alive) setList(Array.isArray(r.contracts) ? r.contracts : []) })
      .catch(() => { if (alive) setList([]) })
    return () => { alive = false }
  }, [backendEnabled, list, api.client])

  const openContract = async (c: ContractSummary) => {
    if (openingId || !c.version_id) { if (!c.version_id) api.notify('载入合同失败'); return }
    setOpeningId(c.contract_id)
    try {
      const v = await api.client.getVersion(c.contract_id, c.version_id)
      if (onOpenContract) { onOpenContract(v, c.name || '我的合同'); return }
      const pages = Array.isArray(v.pages) ? v.pages : []
      const clauses = pagesToClauses(pages)
      const doc = {
        name: c.name || '我的合同',
        title: '合同原文',
        intro: pages.length ? `导入材料 · ${pages.length} 页` : '待复核的图片材料',
        clauses,
        isSample: false,
      }
      api.patch({
        doc,
        sample: null,
        file: null,
        pendingUpload: null,
        fileText: '',
        screen: null,
        selected: clauses.length ? 0 : -1,
        question: '',
        goal: '我希望确认这份合同中尚未明确的安排',
        answer: null,
        answerQuestion: '',
        findings: null,
        focusTypes: [],
        suggestedQuestions: [],
        drafts: EMPTY_DRAFTS,
        analysisTab: 'analysis',
        history: [
          ...state.history,
          {
            doc,
            question: '',
            goal: '我希望确认这份合同中尚未明确的安排',
            sample: null,
            answer: null,
            answerQuestion: '',
            findings: null,
            focusTypes: [],
            suggestedQuestions: [],
            screen: null,
          },
        ],
        backend: {
          contractId: v.contract_id,
          versionId: v.version_id,
          qualityStatus: v.quality_status,
          qualityReasons: v.quality_reasons || [],
          pages,
        },
      })
      api.navigate('analysis')
    } catch {
      api.notify('载入合同失败')
    } finally {
      setOpeningId(null)
    }
  }

  // 重开历史条目：整体还原已生成的分析快照，不重复分析
  const openHistory = (i: number) => {
    const entry = state.history[i]
    if (!entry) return
    api.patch({
      doc: entry.doc,
      sample: entry.sample,
      question: entry.question,
      goal: entry.goal || '确认合同安排',
      selected: entry.doc.name.includes('租房') ? 2 : 0,
      answer: entry.answer,
      answerQuestion: entry.answerQuestion,
      findings: entry.findings,
      focusTypes: entry.focusTypes,
      suggestedQuestions: entry.suggestedQuestions,
      screen: entry.screen,
      drafts: EMPTY_DRAFTS,
      analysisTab: 'analysis',
    })
    api.navigate('analysis')
  }

  const emptyState = (
    <Card className="border-dashed py-12">
      <CardContent className="flex flex-col items-center gap-3 px-4 text-center">
        <span className="text-3xl text-muted-foreground/30">▤</span>
        <p className="font-medium">还没有合同</p>
        <p className="text-sm text-muted-foreground">
          {backendEnabled
            ? '还没有导入过合同。上传或粘贴一份，记录会保存在后端数据库。'
            : '导入一份合同，或从示例开始体验。'}
        </p>
        <Button className="mt-1" onClick={() => api.navigate('home')}>去导入</Button>
      </CardContent>
    </Card>
  )

  return (
    <div className="mx-auto w-full max-w-[1360px] px-5 py-8">
      <Button variant="ghost" size="sm" onClick={() => api.navigate('home')}>
        ‹　返回首页
      </Button>
      <div className="mt-6 mb-8 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">我的合同</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {backendEnabled
              ? '保存在后端数据库，刷新不丢失。'
              : '当前会话记录，刷新后清空。'}
          </p>
        </div>
        <Button size="sm" onClick={() => api.navigate('home')}>+ 导入合同</Button>
      </div>

      <div className="flex flex-col gap-2.5">
        {backendEnabled && list === null
          ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-[72px] w-full rounded-xl" />)
          : null}

        {backendEnabled && list && list.length ? (
          list.map((c) => (
            <button
              key={c.contract_id}
              type="button"
              onClick={() => void openContract(c)}
              disabled={!!openingId}
              className="motion-card group flex w-full items-center gap-4 rounded-xl border border-border bg-card px-4 py-3.5 text-left transition-all hover:border-foreground/15 hover:shadow-sm disabled:opacity-60"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-base text-muted-foreground">
                ▤
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <strong className="text-sm font-medium">{c.name || '未命名合同'}</strong>
                  {c.quality_status === 'ready' && (
                    <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">就绪</Badge>
                  )}
                  {c.quality_status && c.quality_status !== 'ready' && (
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">待复核</Badge>
                  )}
                </span>
                <small className="mt-0.5 block text-[11px] text-muted-foreground">
                  {[c.created_at?.slice(0, 10) || '', c.page_count ? `${c.page_count} 页` : ''].filter(Boolean).join(' · ')}
                </small>
              </span>
              {openingId === c.contract_id ? (
                <span className="text-xs text-muted-foreground animate-pulse">载入中…</span>
              ) : (
                <span aria-hidden className="text-muted-foreground/30 transition-all group-hover:translate-x-0.5 group-hover:text-muted-foreground/60 text-sm">→</span>
              )}
            </button>
          ))
        ) : null}

        {/* 本次会话：含示例/演示/本地文本合同，重开时还原已生成的分析，不重复分析 */}
        {state.history.length ? (
          <>
            {backendEnabled ? (
              <p className="mt-3 text-xs font-medium tracking-wide text-muted-foreground">本次会话</p>
            ) : null}
            {state.history.map((entry, i) => (
              <button
                key={`${i}-${entry.doc.name}`}
                type="button"
                onClick={() => openHistory(i)}
                className="motion-card group flex w-full items-center gap-4 rounded-xl border border-border bg-card px-4 py-3.5 text-left transition-all hover:border-foreground/15 hover:shadow-sm"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-base text-muted-foreground">
                  {entry.doc.isSample ? '▧' : '▤'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <strong className="text-sm font-medium">{entry.doc.name}</strong>
                    {entry.answer && (
                      <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">已出解读</Badge>
                    )}
                  </span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                    {entry.doc.isSample ? '示例 · 虚构材料' : '本次会话'}
                    {entry.doc.clauses.length ? ` · ${entry.doc.clauses.length} 段` : ''}
                  </span>
                </span>
                <span aria-hidden className="text-muted-foreground/30 transition-all group-hover:translate-x-0.5 group-hover:text-muted-foreground/60 text-sm">→</span>
              </button>
            ))}
          </>
        ) : null}

        {!state.history.length && (!backendEnabled || (list !== null && !list.length)) ? emptyState : null}
      </div>
    </div>
  )
}
