import { useEffect, useRef, useState } from 'react'
import { Alert } from '../components/ui/alert'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Separator } from '../components/ui/separator'
import { Switch } from '../components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import { Textarea } from '../components/ui/textarea'
import { useApp, type WorkTab } from '../state'

export interface WorkshopDrafts {
  message: string
  alternative: string
  supplement: string
}

const WORK_TABS: Array<{ key: WorkTab; label: string; title: string }> = [
  { key: 'message', label: '消息', title: '给对方的确认消息' },
  { key: 'alternative', label: '备选', title: '备选：换一种方式达成目标' },
  { key: 'supplement', label: '补充约定', title: '补充约定草稿' },
]

const LLM_MARK = '——由 GLM 基于合同证据生成'

interface DraftInput {
  clauses: string[]
  selected: number
  goal: string
  condition: boolean
}

// 本地草稿模板，复刻 yueding/app.js makeDrafts
export function makeDrafts(state: DraftInput): WorkshopDrafts {
  const excerpt = state.clauses[state.selected] || '合同未明确相关约定'
  const goal = state.goal
  const wall = /书架|打孔|安装/.test(goal)
  return {
    message: wall
      ? '您好，我想在客厅安装书架。如果需要打孔，想先征得您的书面同意。我们能否一起确认安装位置、安装方式和退租时的恢复标准，并把这些写入补充约定？'
      : `您好，关于「${goal}」，想在签约前和您进一步确认。合同中写到「${excerpt}」。我们能否把具体条件、各自责任和处理方式明确下来，并以书面形式确认？`,
    alternative: wall
      ? '如果不方便打孔，我可以考虑免打孔或落地书架。也请您告诉我可接受的安装方式，我们再一起确认。'
      : `如果暂时无法按「${goal}」安排，我希望了解您可以接受的替代条件，并一起确认具体时间、费用及各自责任。`,
    supplement: `补充约定（待双方核对）\n\n一、协商事项：${goal}。\n二、具体安排：[由双方填写位置、方式、时间及其他条件]。\n三、责任承担：${
      state.condition
        ? '可接受退租时恢复墙面，具体标准须由双方确认。'
        : '[由双方另行填写并确认]'
    }\n四、本草稿待双方核对具体内容后，再按双方认可的方式确认。\n\n甲方：________　乙方：________\n日期：________`,
  }
}

function Workshop() {
  const { state, api } = useApp()
  const { selected, goal, condition, workTab } = state
  const clauses = state.doc?.clauses ?? []
  const client = api.client

  // 草稿为 Workshop 本地状态（AppState 无 drafts 字段），由目标/条件/条款驱动
  const [drafts, setDrafts] = useState<WorkshopDrafts>(() =>
    makeDrafts({ clauses, selected, goal, condition }),
  )
  // 后端草稿已合入后，目标编辑不再回退到本地模板
  const [merged, setMerged] = useState(false)
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const toastTimer = useRef<number>(0)

  const showToast = (msg: string) => {
    setToastMsg(msg)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToastMsg(null), 2600)
  }
  useEffect(() => () => clearTimeout(toastTimer.current), [])

  // 目标/条件/条款变化时同步本地草稿（后端草稿已合入则保留）
  useEffect(() => {
    if (merged) return
    setDrafts(makeDrafts({ clauses, selected, goal, condition }))
  }, [merged, clauses, selected, goal, condition])


  // 后端生成：成功则合并 LLM 草稿，失败保留本地模板
  useEffect(() => {
    const { contractId, versionId } = state.backend
    if (!contractId || !versionId || !client.enabled()) return
    let cancelled = false
    ;(async () => {
      try {
        if (!(await client.ready())) return
        const r = await client.generate(contractId, versionId, 'drafts')
        if (cancelled) return
        const llm = r.llm?.result
        if (!llm) return
        const dm = (llm.drafts?.message ?? '').trim()
        const ds = (llm.drafts?.supplement ?? '').trim()
        const mergedDrafts = { ...makeDrafts({ clauses, selected, goal, condition }) }
        if (dm) mergedDrafts.message = dm + `\n\n${LLM_MARK}，可编辑`
        else if (llm.summary.trim()) mergedDrafts.message += '\n\n【后端核对摘要】\n' + llm.summary.trim()
        if (ds) mergedDrafts.supplement = ds + `\n\n${LLM_MARK}，可编辑`
        else if (llm.consequences.length)
          mergedDrafts.supplement += '\n\n【可能影响】\n' + llm.consequences.join('\n')
        setDrafts(mergedDrafts)
        setMerged(true)
        showToast('后端已补充证据约束的沟通草稿')
      } catch {
        if (!cancelled) showToast('后端生成不可用，已保留本地草稿')
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.backend.contractId, state.backend.versionId])

  const copyDraft = async (text: string) => {
    if (!text.trim()) {
      showToast('草稿为空，请先生成或输入内容')
      return
    }
    try {
      await navigator.clipboard.writeText(text)
      showToast('已复制，可粘贴到聊天中')
    } catch {
      showToast('复制失败，请手动选择文本复制')
    }
  }

  const excerpt = clauses[selected] || '未找到相关约定'

  return (
    <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-6 px-5 py-8">
      <Button variant="ghost" className="w-fit px-2" onClick={() => api.navigate('analysis')}>
        ‹　返回分析
      </Button>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">确认与协商工坊</h1>
          <p className="text-sm text-muted-foreground">把想法说清楚，为下一步沟通做好准备。</p>
        </div>
        <span className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">待双方确认</span>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>⌂　当前协商事项</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">依据</span>
              <div className="rounded-lg bg-muted p-3 text-sm">
                <p className="mb-1 text-xs text-muted-foreground">
                  ▤　合同原文 · {selected >= 0 ? `第 ${selected + 1} 段` : '未找到相关约定'}
                </p>
                <p className="max-h-40 overflow-y-auto leading-relaxed">{excerpt}</p>
              </div>
            </div>
            <Separator />
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">我的目标</span>
              <Textarea
                value={goal}
                maxLength={200}
                onChange={(e) => api.patch({ goal: e.target.value })}
                aria-label="我的目标"
                placeholder="想确认或争取的安排，如：在客厅安装书架"
              />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm">同意承担相关责任</span>
              <Switch checked={condition} onCheckedChange={(checked) => api.patch({ condition: checked })} />
            </div>
            <p className="text-xs text-muted-foreground">
              所有内容均为沟通草稿。补充约定需双方核对与确认。
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>准备好下一步沟通</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Tabs
              value={workTab}
              onValueChange={(value) => {
                const tab = WORK_TABS.find((t) => t.key === value)
                api.patch({ workTab: tab ? tab.key : 'message' })
              }}
            >
              <TabsList className="grid w-full grid-cols-3">
                {WORK_TABS.map((t) => (
                  <TabsTrigger key={t.key} value={t.key}>
                    {t.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {WORK_TABS.map((t) => (
                <TabsContent key={t.key} value={t.key} className="mt-4 flex flex-col gap-3">
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-sm">{t.title}</strong>
                    <span className="text-xs text-emerald-600">草稿</span>
                  </div>
                  <Textarea
                    readOnly
                    value={drafts[t.key]}
                    aria-label={t.title}
                    className={`resize-none ${t.key === 'supplement' ? 'min-h-72' : 'min-h-44'}`}
                  />
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">{drafts[t.key].length} 字</span>
                    <Button variant="outline" onClick={() => copyDraft(drafts[t.key])}>
                      ▢　复制
                    </Button>
                  </div>
                  {t.key === 'message' && (
                    <p className="text-xs text-muted-foreground">
                      沟通小提示：先说明想做什么，再询问对方的条件，最后留下双方认可的书面记录。
                    </p>
                  )}
                </TabsContent>
              ))}
            </Tabs>
          </CardContent>
        </Card>
      </div>

      {toastMsg && (
        <Alert className="fixed bottom-6 left-1/2 z-50 w-max max-w-[90vw] -translate-x-1/2 shadow-lg">
          {toastMsg}
        </Alert>
      )}
    </div>
  )
}

export default Workshop
