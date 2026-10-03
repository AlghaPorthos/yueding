# 约定 · 前端

React 19 + TypeScript + Vite + Tailwind CSS v4 的单页应用。页面流程：首页导入 → 分析阅读（条款卡片 / 原文对照 / 智读）→ 协商工坊；另有我的合同、模板库、法条库、帮助中心四个导航页。

## 命令

```sh
npm install        # 首次
npm run dev        # 开发服务器 http://localhost:5173（HMR）
npm run build      # tsc -b && vite build → dist/
npm run lint       # oxlint
npm run preview    # 本地预览 dist/
```

## 目录结构

```
src/
├── pages/          # 七个页面：Home / Analysis / Workshop / Contracts / Templates / Legal / Help
├── components/ui/  # shadcn 风格基础组件（基于 Base UI）
├── components/BrandMark.tsx  # 品牌标识（页头 logo，favicon 同款图形）
├── api/client.ts   # 唯一的后端客户端：所有请求经此发出，响应形状在此归一
├── state.ts        # 全局状态：AppContext 单一事实来源，含本地回退规则
└── lib/
    ├── examples.ts # 六类虚构示例合同 + 模板库元数据（tone 色 / 图标 / 要点）
    └── pages.ts    # 后端页级数据 → 条款切分
```

## 后端地址解析（优先级从高到低）

`index.html` 在加载业务代码前解析 `window.YUEDING_BACKEND_CONFIG`：

1. `?backend=https://…` URL 查询参数——公网演示（如 CF Tunnel）时直接在链接里指定后端；
2. 页面预写的 `window.YUEDING_BACKEND_CONFIG.baseUrl`——部署时写进 HTML；
3. `localhost / 127.0.0.1` 自动指向 `http://127.0.0.1:8000`；
4. 其他域名默认空字符串——**纯本地模式**，不发任何请求，示例合同、关键词定位、沟通模板照常可用。

后端不可用或请求失败时自动降级到本地实现并 toast 提示，页面不白屏。跨域部署记得配后端 `CONTRACT_READER_CORS_ORIGINS`。

## 单端口公网部署：serve_demo.py

`serve_demo.py` 把构建产物和后端 API 收进同一个端口，浏览器端零 CORS 配置：

```sh
npm run build
python3 serve_demo.py    # 0.0.0.0:8000 托管 dist/，API 反代到 127.0.0.1:8001
```

- 反代路径：`/v1/`、`/contracts/`、`/legal/`、`/kb/`、`/healthz`、`/readyz`（`BACKEND_HOST` / `BACKEND_PORT` 可改）；
- 自动向 index.html 注入同源后端配置（`baseUrl: location.origin`），公网 IP、SSH 隧道、本机打开行为一致；
- 后端相应用 `CONTRACT_READER_PORT=8001 bash start-dev.sh` 启动。

## 前端特性备忘

- **模板库演示回放**：点击模板卡片后用真实主页 UI 复刻完整导入链路——回到主页 PDF 标签 → 文件拖入 → 解析出预览 → 「猜你想问」逐条出现 → 自动选中填入 → 分析页回答加载 → 出结果（全程约 8 秒，顶部「示例演示进行中」遮罩可取消）；
- **入场动画约定**：`.motion-card` 等入场动画的 fill-mode 用 `backwards`（不用 `both`），避免动画结束后锁死 `opacity/transform`、覆盖后续状态类与 hover 效果；
- 改动画 / 交互时注意 `prefers-reduced-motion` 降级已有统一处理（`index.css` 底部）。
