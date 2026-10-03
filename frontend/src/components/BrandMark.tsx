// 品牌图形：蓝橙两个相扣的方形对话气泡（2026-10 品牌标识）
// 左蓝右橙，各自带外八的气泡尾巴，中央胶囊条双色相接；
// 相叠处用 mask 挖出背景色分离带，深浅主题下都成立。
import { useId } from 'react'

const BLUE = '#1E3F9E'
const ORANGE = '#F05A1E'

// 左侧蓝色气泡（开口朝右，中央手臂越过中线与橙色手臂搭接，尾巴在左下）；
// 橙色 = 同一路径水平镜像（translate+scale）
const BUBBLE_PATH =
  'M12 5H23A3 3 0 0 1 26 8V9A3 3 0 0 1 23 12H11.5A1.5 1.5 0 0 0 10 13.5V16' +
  'A1.5 1.5 0 0 0 11.5 17.5H25.5A3.5 3.5 0 0 1 25.5 24.5H11.5A1.5 1.5 0 0 0 10 26V28.5' +
  'A1.5 1.5 0 0 0 11.5 30H23A3 3 0 0 1 26 33V34A3 3 0 0 1 23 37H12A9 9 0 0 1 3 28V14' +
  'A9 9 0 0 1 12 5ZM13 37 2 45.5 5 37Z'

export function BrandMark({ className }: { className?: string }) {
  const maskId = `brand-mask-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden="true" focusable="false">
      <defs>
        <mask id={maskId}>
          <rect width="48" height="48" fill="#fff" />
          <path d={BUBBLE_PATH} fill="#000" stroke="#000" strokeWidth="1.5" />
        </mask>
      </defs>
      <g mask={`url(#${maskId})`}>
        <path d={BUBBLE_PATH} fill={ORANGE} transform="translate(48 0) scale(-1 1)" />
      </g>
      <path d={BUBBLE_PATH} fill={BLUE} />
    </svg>
  )
}

export default BrandMark
