import { useEffect, useState, type FormEvent } from 'react'
import { useApp } from '../state'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import type { KbListItem, LegalProvision } from '../api/client'
import { Card, CardContent } from '../components/ui/card'
import { Input } from '../components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select'
import { Separator } from '../components/ui/separator'
import { Skeleton } from '../components/ui/skeleton'

function categoryLabel(category: string): string {
  if (category === '维基文库_法律法规') return '法律法规'
  if (category === '官方_示范文书') return '案例文书'
  return category
}

function KbBadge({ type, className }: { type: string; className?: string }) {
  return type === '法条' ? (
    <Badge variant="secondary" className={className}>
      法条
    </Badge>
  ) : (
    <Badge variant="outline" className={className}>
      案例
    </Badge>
  )
}

function ProvisionItem({ p }: { p: LegalProvision }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <strong className="text-[13px] font-semibold leading-snug">{p.article || '条文'}</strong>
        <span className="shrink-0 rounded border border-dashed border-border px-1.5 py-0 font-mono text-[10px] text-muted-foreground/60" title="内容哈希（可溯源）">
          {String(p.content_hash || '').slice(0, 8)}
        </span>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed">{p.quote}</p>
      {p.version ? (
        <p className="mt-2 text-[11px] text-muted-foreground">
          版本 {p.version}{p.effective_from ? ` · 自 ${p.effective_from} 生效` : ''}
        </p>
      ) : null}
    </div>
  )
}

export default function Legal() {
  const { state, api } = useApp()
  const backendEnabled = api.client.enabled()
  const [kbItemLoading, setKbItemLoading] = useState(false)
  const [searching, setSearching] = useState(false)

  useEffect(() => {
    if (!backendEnabled || state.kbList !== null) return
    let alive = true
    api.client
      .kbList()
      .then((r) => {
        if (alive) api.patch({ kbList: r.status === 'confirmed' ? r.items || [] : [] })
      })
      .catch(() => {
        if (alive) api.patch({ kbList: [] })
      })
    return () => {
      alive = false
    }
  }, [backendEnabled, state.kbList, api])

  useEffect(() => {
    if (!backendEnabled || state.legalCorpus !== null) return
    let alive = true
    api.client
      .legalCorpus()
      .then((r) => {
        if (alive) api.patch({ legalCorpus: r.status === 'confirmed' ? r : null })
      })
      .catch(() => {
        if (alive) api.patch({ legalCorpus: null })
      })
    return () => {
      alive = false
    }
  }, [backendEnabled, state.legalCorpus, api])

  const openKbItem = async (id: string) => {
    if (kbItemLoading) return
    setKbItemLoading(true)
    api.notify('正在打开文档…')
    try {
      const d = await api.client.kbItem(id)
      api.patch({ kbItem: d, kbQuery: '', kbShowAll: false })
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch {
      api.notify('文档打开失败')
    } finally {
      setKbItemLoading(false)
    }
  }

  const doSearch = async (e: FormEvent) => {
    e.preventDefault()
    const q = state.legalQuery.trim()
    if (!q || searching) return
    setSearching(true)
    try {
      if (state.legalScope === 'provisions') {
        const r = await api.client.legalSearch(q)
        api.patch({ legalResults: r.status === 'confirmed' ? r.results || [] : [], kbHits: null })
      } else {
        const r = await api.client.kbSearch(q)
        api.patch({ kbHits: r.status === 'confirmed' ? r.hits || [] : [], legalResults: null })
      }
    } catch {
      api.notify('检索失败，请稍后再试')
    } finally {
      setSearching(false)
    }
  }

  const header = (
    <>
      <Button variant="ghost" onClick={() => api.navigate('home')}>
        ‹　返回首页
      </Button>
      <div className="mt-3">
        <h1 className="text-2xl font-semibold">法条、案例知识库</h1>
        <p className="mt-1 text-sm text-muted-foreground">本地法律语料 · 全文可溯源</p>
      </div>
    </>
  )

  if (!backendEnabled) {
    return (
    <div className="mx-auto w-full max-w-[1360px] px-5 py-8">
        {header}
        <Card className="mt-6 py-8">
          <CardContent className="px-4 text-center text-sm text-muted-foreground">
            知识库需要后端服务。启动后端后可浏览资料包全部文档与 114 条条文。
          </CardContent>
        </Card>
      </div>
    )
  }

  // —— 详情页：单文件独立页面 ——
  if (state.kbItem) {
    const d = state.kbItem
    const arts = (d.articles || [])
      .map((a) => ({ no: String(a[0] || ''), text: String(a[1] || '') }))
      // Filter: genuine articles start with 第N条; section headings (第N章/第N节/Chapter) are structural
      .filter((a) => !a.no || !/^第[一二三四五六七八九十百千零〇\d]+[章节篇]/.test(a.no))
    const q = state.kbQuery.trim().toLowerCase()
    const terms = q ? q.split(/\s+/).filter(Boolean) : []
    const filtered = terms.length
      ? arts.filter((a) => terms.every((t) => `${a.no} ${a.text}`.toLowerCase().includes(t)))
      : arts
    const shown = state.kbShowAll ? filtered : filtered.slice(0, 60)
    return (
    <div className="mx-auto w-full max-w-[1360px] px-5 py-8">
        <Button
          variant="ghost"
          onClick={() => api.patch({ kbItem: null, kbQuery: '', kbShowAll: false })}
        >
          ‹　返回知识库
        </Button>
        <div className="mt-3">
          <h1 className="text-2xl font-semibold">{d.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {categoryLabel(d.category || '')} · 共 {arts.length} 条
            {terms.length ? ` · 命中 ${filtered.length} 条` : ''}
            {d.source ? (
              <>
                {' · '}
                <a
                  className="text-primary underline-offset-4 hover:underline"
                  href={d.source}
                  target="_blank"
                  rel="noopener"
                >
                  查看来源
                </a>
              </>
            ) : null}
          </p>
        </div>
        <form
          className="mt-4 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            api.patch({ kbShowAll: false })
          }}
        >
          <Input
            className="min-w-0 flex-1"
            aria-label="本文内检索"
            placeholder="在本文档内检索：如 押金 / 违约金 书面…"
            maxLength={60}
            value={state.kbQuery}
            onChange={(e) => api.patch({ kbQuery: e.target.value })}
          />
          <Button type="submit">本文检索</Button>
          {state.kbQuery ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => api.patch({ kbQuery: '', kbShowAll: false })}
            >
              清除
            </Button>
          ) : null}
        </form>
        {kbItemLoading ? <Skeleton className="mt-6 h-40 w-full rounded-xl" /> : null}
        <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-2">
          {shown.map((a, i) => {
            const noParts = a.no.split('　')
            return (
              <div key={i} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <strong className="text-sm">{a.no ? a.no.split(/[　\s]/)[0] : '条文'}</strong>
                  {a.no.includes('　') ? (
                    <em className="text-xs not-italic text-muted-foreground">
                      {noParts.slice(1).join('　')}
                    </em>
                  ) : null}
                </div>
                <p className="mt-1 text-sm leading-relaxed">{a.text}</p>
              </div>
            )
          })}
        </div>
        {!shown.length ? (
          <Card className="mt-4 py-6">
            <CardContent className="px-4 text-center text-sm text-muted-foreground">
              本文档没有命中内容。
            </CardContent>
          </Card>
        ) : null}
        {filtered.length > 60 && !state.kbShowAll ? (
          <div className="mt-4 text-center">
            <Button variant="outline" onClick={() => api.patch({ kbShowAll: true })}>
              显示全部 {filtered.length} 条
            </Button>
          </div>
        ) : null}
      </div>
    )
  }

  // —— 列表页 ——
  const kbGroups: [string, KbListItem[]][] = []
  for (const x of state.kbList || []) {
    const last = kbGroups[kbGroups.length - 1]
    if (last && last[0] === x.category) last[1].push(x)
    else kbGroups.push([x.category, [x]])
  }

  return (
    <div className="mx-auto w-full max-w-[1360px] px-5 py-8">
      {header}
      <form className="mt-4 flex flex-wrap gap-2" onSubmit={doSearch}>
        <Select
          items={[
            { value: 'kb', label: '全部文档' },
            { value: 'provisions', label: '条文速查库' },
          ]}
          value={state.legalScope}
          onValueChange={(v) => api.patch({ legalScope: v === 'provisions' ? 'provisions' : 'kb' })}
        >
          <SelectTrigger aria-label="检索范围" className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="kb">全部文档</SelectItem>
            <SelectItem value="provisions">条文速查库</SelectItem>
          </SelectContent>
        </Select>
        <Input
          className="min-w-0 flex-1"
          aria-label="检索"
          placeholder="搜索法条或案例，如：押金 退还"
          maxLength={60}
          value={state.legalQuery}
          onChange={(e) => api.patch({ legalQuery: e.target.value })}
        />
        <Button type="submit" disabled={searching}>
          {searching ? '检索中…' : '检索'}
        </Button>
        {state.kbHits || state.legalResults ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => api.patch({ kbHits: null, legalResults: null, legalQuery: '' })}
          >
            回到全部
          </Button>
        ) : null}
      </form>

      {state.kbHits ? (
        state.kbHits.length ? (
          <section className="mt-6">
            <h2 className="text-sm font-medium text-muted-foreground">
              跨文档命中 {state.kbHits.length} 条
            </h2>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {state.kbHits.map((h) => (
                <button
                  key={`${h.doc_id}-${h.no}`}
                  type="button"
                  aria-label={`打开文档 ${h.doc_title}`}
                  onClick={() => void openKbItem(h.doc_id)}
                  className="motion-card group w-full rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-foreground/20 hover:shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <strong className="text-[13px] font-medium leading-snug line-clamp-2">
                      {h.doc_title} · {String(h.no || '').split('　')[0] || '节选'}
                    </strong>
                    <KbBadge type={h.doc_type} className="px-1.5 py-0 text-[10px]" />
                  </div>
                  <small className="mt-1 block line-clamp-2 text-[11px] text-muted-foreground">
                    {h.snippet}…
                  </small>
                </button>
              ))}
            </div>
          </section>
        ) : (
          <Card className="mt-6 py-6">
            <CardContent className="px-4 text-center text-sm text-muted-foreground">
              跨文档没有命中，换关键词或改用条文速查库。
            </CardContent>
          </Card>
        )
      ) : state.kbList === null ? (
        <Skeleton className="mt-6 h-40 w-full rounded-xl" />
      ) : state.kbList.length ? (
        kbGroups.map(([cat, items]) => (
          <section key={cat} className="mt-6">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">{categoryLabel(cat)}</h2>
              <Badge variant="outline">{items.length} 份</Badge>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  aria-label={`打开文档 ${x.title}`}
                  onClick={() => void openKbItem(x.id)}
                  className="motion-card group w-full rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-foreground/20 hover:shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <strong className="text-[13px] font-medium leading-snug line-clamp-2">{x.title}</strong>
                    <KbBadge type={x.type} className="px-1.5 py-0 text-[10px]" />
                  </div>
                </button>
              ))}
            </div>
          </section>
        ))
      ) : (
        <Card className="mt-6 py-6">
          <CardContent className="px-4 text-center text-sm text-muted-foreground">
            知识库文件未找到（法律文书Agent资料包）。
          </CardContent>
        </Card>
      )}

      <Separator className="my-6" />
      <h2 className="text-sm font-semibold">条文速查（来自本地法律语料）</h2>
      <div className="mt-3 flex flex-col gap-6">
        {state.legalResults ? (
          state.legalResults.length ? (
            <section>
              <h3 className="text-sm font-medium text-muted-foreground">
                检索命中 {state.legalResults.length} 条
              </h3>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                {state.legalResults.map((p, i) => (
                  <ProvisionItem key={i} p={p} />
                ))}
              </div>
            </section>
          ) : (
            <Card className="py-6">
              <CardContent className="px-4 text-center text-sm text-muted-foreground">
                没有命中条文，换个说法试试（如「押金 退还」）。
              </CardContent>
            </Card>
          )
        ) : state.legalCorpus === null ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : (
          (state.legalCorpus.sources || []).map((s, si) => (
            <section key={si}>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">{s.source_display || s.source}</h3>
                <Badge variant="outline">{s.count} 条</Badge>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                {(s.provisions || []).map((p, i) => (
                  <ProvisionItem key={i} p={p} />
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </div>
  )
}
