# 约定 YUEDING · 合同阅读器（交互原型）

> 读懂约定，再做决定。上传合同或协议，找到与你有关的答案。

「约定」是一个**本地优先、可离线**的合同阅读交互原型：导入材料 → 阅读与提问 → 确认与协商，三步完成一次合同阅读。内置租房合同、隐私协议、劳动合同三个虚构示例。

**在线体验（GitHub Pages）**：<https://alghaporthos.github.io/yueding/>

## 快速开始

- **在线**：直接打开上面的 GitHub Pages 地址。
- **离线**：clone 或下载本仓库，用 Chrome / Edge 打开 `index.html` 即可，无需安装、无需构建、无后端。

```
index.html   网站入口
style.css    页面样式
app.js       交互逻辑 + Hackathon 后端适配层 + Multi-Agent 接入层
使用说明.txt 离线分享版说明
docs/        接入文档
examples/    智能体端点示例服务端
```

## 功能范围

- 示例合同的解读为预设内容；未配置后端时，粘贴文本按关键词辅助定位。
- 未配置后端时，PDF / 截图只做本地选择与预览；配置后端后，可检索 PDF 由后端提取文字，图片会返回待人工复核状态。
- 合同与阅读记录只在当前页面会话中保留，刷新后清空；**未配置后端或智能体时不向任何服务发送数据**。

## Hackathon 后端对接

`index.html` 会在本地静态服务器（`localhost` / `127.0.0.1`）上自动把 `baseUrl` 指向
`http://127.0.0.1:8000`。也可以在引入 `app.js` 前覆盖配置：

```html
<script>
  window.YUEDING_BACKEND_CONFIG = {
    baseUrl: 'https://api.example.com',
    headers: { 'X-User-ID': '…', 'X-Workspace-ID': '…' },
    timeout: 60000
  };
</script>
```

前端使用后端已有接口：文本/PDF/图片上传到 `POST /v1/contracts`，随后调用
`POST /contracts/{contract_id}/versions/{version_id}/analyze`；工坊生成方案调用
`POST /v1/contracts/{contract_id}/versions/{version_id}/generate`。后端返回的页级文本、引用和四类 finding 会适配到现有阅读界面。后端不可用、文档需要复核或模型未配置时，前端继续显示本地关键词定位和沟通模板。

当前后端的 `generate` 返回的是受证据约束的解释结果（`summary/actions/consequences`），不是三段完整草稿，所以前端只把这些字段追加到本地草稿，不把它伪装成完整的 `message/alternative/supplement`。

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
