// 三步流程指示器 — 全宽均匀分布
const STEP_LABELS = ['导入材料', '阅读与提问', '确认与协商']

export function Steps({ current }: { current: number }) {
  return (
    <div className="flex w-full items-start">
      {STEP_LABELS.map((label, i) => {
        const s = i + 1 === current ? 'active' : i + 1 < current ? 'done' : 'future'
        return (
          <div key={label} className={`flex items-start ${i === 0 ? 'flex-none' : 'flex-1'}`}>
            {i > 0 && (
              <div className="mx-3 mt-[13px] h-px flex-1 bg-border" aria-hidden />
            )}
            <div className="flex flex-col items-center">
              <span
                className={`inline-flex size-7 items-center justify-center rounded-full text-[12px] font-medium transition-colors ${
                  s === 'active'
                    ? 'bg-foreground text-background'
                    : s === 'done'
                      ? 'bg-foreground/10 text-foreground/50'
                      : 'border border-border text-muted-foreground/40'
                }`}
              >
                {s === 'done' ? '✓' : i + 1}
              </span>
              <span
                className={`mt-1.5 whitespace-nowrap text-[11px] tracking-wide ${
                  s === 'active' ? 'font-medium text-foreground' : 'text-muted-foreground/50'
                }`}
              >
                {label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
