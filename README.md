# 约定 YUEDING · 合同阅读器（交互原型）

> 读懂约定，再做决定。上传合同或协议，找到与你有关的答案。

「约定」是一个**纯静态、可离线**的合同阅读交互原型：导入材料 → 阅读与提问 → 确认与协商，三步完成一次合同阅读。内置租房合同、隐私协议、劳动合同三个虚构示例。首页和模板库还提供三个独立的 Dify AI 核对工作流入口；点击入口后由用户在 Dify 页面主动上传材料。

**在线体验（GitHub Pages）**：<https://alghaporthos.github.io/yueding/>

## 独立演示页

[`demo.html`](demo.html) 集中展示租房、入职和应用权限三个虚构场景，包含原文节选、行动卡及各自的 agentic workflow。每个场景都可跳转至已发布的 Dify 工作流实际运行。演示页为独立 HTML 文件，可直接在浏览器打开；页面中的示例内容不调用模型，也不会上传材料。演示页也已单独同步至 GitHub Pages 的 `main` 分支，可从 <https://alghaporthos.github.io/yueding/demo.html> 访问。

## 快速开始

- **在线**：直接打开上面的 GitHub Pages 地址。
- **离线**：clone 或下载本仓库，用 Chrome / Edge 打开 `index.html` 即可，无需安装、无需构建、无后端。

```
index.html   网站入口
demo.html    独立演示页
style.css    页面样式
app.js       交互逻辑 + Multi-Agent 接入层（AgentBridge）
使用说明.txt 离线分享版说明
docs/        接入文档
examples/    智能体端点示例服务端
```

## 功能范围

- 示例合同的解读为预设内容；粘贴文本按关键词辅助定位。
- PDF / 截图支持本地选择与预览，文本提取（OCR）为预留能力，见接入文档。
- 合同与阅读记录只在当前页面会话中保留，刷新后清空；**默认不向任何服务发送数据**。
- Dify 工作流与本地原型分开运行；本页不会自动把已粘贴的合同发给 Dify，也不在静态代码中存放 API Key。

## Dify 工作流

| 场景 | 已发布入口 |
| --- | --- |
| 租房行动核对 | <https://udify.app/workflow/ruuUvJWryY8SboIS> |
| 入职条款核对 | <https://udify.app/workflow/tI2nxuqPTklugoKl> |
| 应用权限核对 | <https://udify.app/workflow/xTDGTuzyGf0M9o3R> |

三个流程均经过虚构材料测试。使用方式、输入字段与数据边界见 [Dify 接入说明](docs/DIFY_INTEGRATION.md)。

## Multi-Agent 接入

前端内置 `AgentBridge` 接入层：**默认全本地运行**（零网络请求、行为与离线版一致），同时保留接入多智能体后端的完整接口，三种能力：

| 能力 | 触发时机 | 说明 |
| --- | --- | --- |
| `analyze` | 开始分析 / 继续提问 | 条款定位 + 问答，可由 locator + qa 两个子 Agent 编排 |
| `draft` | 工坊「生成方案」 | 协商消息 / 替代方案 / 补充约定草稿 |
| `extract`（预留） | PDF / 截图导入 | 文本提取，接线位已在文档中说明 |

接入方式（任选其一，均不需要改动业务代码）：

```html
<!-- 方式 A：HTTP 端点（服务端 Multi-Agent 编排，推荐） -->
<script>window.YUEDING_AGENT_CONFIG={endpoint:'https://your-domain/api/agent'};</script>
<script src="app.js"></script>
```

```js
// 方式 B：JS Provider（浏览器内 Agent / MCP 场景）
window.YuedingAgent.registerProvider('myAgent', { analyze, draft, extract });
```

完整协议（请求/响应 JSON 契约、子 Agent 角色划分、CORS、错误回退、隐私要求）见
**[docs/MULTI_AGENT_INTERFACE.md](docs/MULTI_AGENT_INTERFACE.md)**；零依赖示例服务端见
[examples/agent-server.example.mjs](examples/agent-server.example.mjs)（`node examples/agent-server.example.mjs`）。

## 说明与免责

- 本项目为交互原型，示例合同均为虚构内容，输出不构成法律意见。
- 未附带开源许可证；如需开放二次使用，请自行添加 LICENSE。
