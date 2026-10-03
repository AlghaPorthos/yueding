// 后端 pages 数组的统一解析（App/Contracts/Home 共用）
// 页可能是字符串、{ text } 或 { quote } 对象，逐行拆成条款。
export function pagesToClauses(pages: readonly unknown[]): string[] {
  const out: string[] = []
  for (const p of pages) {
    let text = ''
    if (typeof p === 'string') text = p
    else if (p && typeof p === 'object' && 'text' in p && typeof (p as { text: unknown }).text === 'string')
      text = (p as { text: string }).text
    else if (p && typeof p === 'object' && 'quote' in p && typeof (p as { quote: unknown }).quote === 'string')
      text = (p as { quote: string }).quote
    for (const line of text.trim().split(/\n+/)) {
      const t = line.trim()
      if (t) out.push(t)
    }
  }
  return out
}
