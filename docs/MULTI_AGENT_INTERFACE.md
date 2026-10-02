# 约定 · Multi-Agent 接入说明

> 版本：`protocol v1`（对应 `app.js` 中 `AgentBridge`，`client: 'yueding-web'`）
> 适用：约定（YUEDING）合同阅读器交互原型

本文档说明如何把「约定」前端接入一个多智能体（Multi-Agent）后端。**默认情况下网站完全本地运行、不发出任何网络请求**；只有按下文配置后，才会把合同文本发送给你指定的智能体服务。

---

## 1. 设计原则

| 原则 | 说明 |
| --- | --- |
| 本地优先 | 未配置任何智能体时，所有分析与草稿生成都在浏览器内完成（关键词定位 + 预设模板），与离线版行为一致 |
| 渐进增强 | 配置了智能体后，本地结果先立即上屏，智能体结果返回后再替换，页面永不空白 |
| 失败回退 | 智能体超时、报错、返回格式不符时，自动回退本地实现并提示用户，功能不中断 |
| 单一接缝 | 前端只认识 `AgentBridge` 这一个抽象；后端是单 Agent 还是 Multi-Agent 编排，前端不感知 |

## 2. 架构

```
┌─────────────────────── 浏览器（本仓库前端） ───────────────────────┐
│  index.html + app.js                                              │
│    ├─ UI 流程：导入 → 阅读提问 → 确认协商                           │
│    └─ AgentBridge（唯一接缝）                                      │
│         │  capability: analyze / draft / extract                  │
│         ├─ ① JS Provider（页面内注册，浏览器内 Agent / MCP 场景）    │
│         ├─ ② HTTP 端点（推荐：服务端 Multi-Agent 编排）             │
│         └─ ③ localAgent（内置本地实现，兜底）                       │
└────────────────────────────┬───────────────────────────────────────┘
                             │  POST {capability, payload} （JSON）
                             ▼
              ┌─────────────────────────────┐
              │  Orchestrator（编排器，你实现） │
              │  按 capability 分发给子 Agent： │
              │   · 条款定位 Agent（locator）   │
              │   · 问答解读 Agent（qa）        │
              │   · 协商草稿 Agent（drafter）   │
              │   · 文档解析 Agent（extractor， │
              │     PDF/OCR，可选）            │
              └─────────────────────────────┘
```

前端不关心 Orchestrator 内部如何编排（LangGraph / AutoGen / CrewAI / Dify / 自建路由均可），只要端点遵守第 4 节的 HTTP 协议即可。

## 3. 两种接入方式

### 方式 A：HTTP 端点（推荐，适合服务端 Multi-Agent）

在 `index.html` 中、**引入 `app.js` 之前**加一段配置：

```html
<script>
  window.YUEDING_AGENT_CONFIG = {
    endpoint: 'https://your-domain.example/api/agent', // 必填：你的编排器地址
    headers: { 'Authorization': 'Bearer <token>' },    // 可选：鉴权等自定义头
    timeout: 60000                                     // 可选：毫秒，默认 60s
  };
</script>
<script src="app.js"></script>
```

配置后自动生效，无需改动任何业务代码：

- 「开始分析」/「继续提问」→ 调用 `analyze`
- 工坊里点「生成方案 / 重新生成」→ 先出本地模板，再调用 `draft` 用智能体结果覆盖
- 端点失败/超时 → toast 提示并保留本地结果

> 注意：配置 endpoint 后，用户粘贴的合同文本会发送到该端点。请在你自己的部署中明示这一点（页脚与帮助中心默认文案为本地模式）。

### 方式 B：JS Provider（页面内 / 浏览器内 Agent）

适合 Agent 与页面同处一个运行环境（如浏览器内 MCP、本地伴随进程注入、iframe 嵌入）：

```html
<script src="app.js"></script>
<script>
  window.YuedingAgent.registerProvider('myAgent', {
    // 三个方法均可选；支持 async；缺省能力自动回退本地实现
    analyze: async (payload) => { /* 返回第 5.1 节结构 */ },
    draft:   async (payload) => { /* 返回第 5.2 节结构 */ },
    extract: async (payload) => { /* 返回第 5.3 节结构 */ }
  });
</script>
```

注册后立即接管对应能力（`config.mode` 自动切换为该 Provider）。

此外，`app.js` 末尾保留了一个浏览器内 MCP（`document.modelContext`）钩子，向前端环境注册 `open_contract_example` 工具，可用于让宿主 Agent 直接操控页面打开示例合同——这是第三种（宿主侧）接入面，与本文协议互不冲突。

## 4. HTTP 协议（方式 A）

**请求**：`POST <endpoint>`，`Content-Type: application/json`

```json
{
  "capability": "analyze | draft | extract",
  "payload": { "…": "见第 5 节" },
  "client": "yueding-web",
  "version": 1
}
```

**响应**：HTTP 200

```json
{ "result": { "…": "与 capability 对应的结果结构" } }
```

失败时二选一：HTTP 非 200，或 200 且 `{ "error": "人类可读的错误说明" }`。
前端对两种失败的处理相同：toast 提示 + 回退本地实现。

CORS：端点需允许来自页面源（如 `https://<user>.github.io`）的跨域 POST。最小响应头：

```
Access-Control-Allow-Origin: https://<user>.github.io
Access-Control-Allow-Headers: Content-Type, Authorization
Access-Control-Allow-Methods: POST, OPTIONS
```

## 5. 能力契约（Capability Contracts）

### 5.1 `analyze` — 条款定位 + 问答

用户导入合同或继续提问时触发。

请求 `payload`：

```json
{
  "question": "押金怎么退？",
  "contract": {
    "title": "合同原文",
    "intro": "导入的合同内容",
    "clauses": ["6.1　承租人应……", "6.2　……"],
    "isSample": false
  }
}
```

- `clauses`：按空行/换行切分的条款数组，**所有 `index` 均指该数组下标（0 起）**。
- `isSample: true` 的虚构示例不会触发自动调用（保留人工编写的解读），但工坊手动生成会调用。

响应 `result`：

```json
{
  "findings": [
    { "key": "deposit",  "title": "押金返还", "desc": "退还时间与扣减条件", "index": 5 },
    { "key": "custom-1", "title": "违约金过高", "desc": "建议协商上限或计算方式", "index": 7 }
  ],
  "answer": {
    "title": "七日内返还剩余押金",
    "text": "合同第 7.2 条约定……建议进一步确认扣减凭证。",
    "index": 5
  }
}
```

- `findings`：右侧「合同要点」列表，2–5 条为宜；`index: -1` 表示未定位到原文（界面会显示「未找到相关约定」）。
- `answer`：对 `question` 的直接回答，会展示在问答区并联动高亮原文。`title` 必填；`index` 为 -1 时不显示「查看原文」按钮。
- 两字段均可选，返回哪个更新哪个；返回的内容前端会做 HTML 转义，可安全包含用户合同里的文本。

### 5.2 `draft` — 协商草稿生成

工坊里点「生成方案 / 重新生成」时触发（本地模板会先上屏，智能体结果返回后覆盖）。

请求 `payload`：

```json
{
  "goal": "我想在客厅安装书架",
  "condition": true,
  "clause": "6.3　未经出租人书面同意，承租人不得擅自改变房屋结构或在墙面打孔。",
  "contract": { "title": "…", "clauses": ["…"], "isSample": false }
}
```

- `goal`：用户目标（工坊左栏可编辑）；`clause`：当前选中的依据条款原文；`condition`：用户勾选的可接受条件。

响应 `result`（三个字符串字段均可选，提供哪个覆盖哪个）：

```json
{
  "message":     "您好，关于「我想在客厅安装书架」……（给对方的确认消息）",
  "alternative": "如果不方便打孔，我可以考虑免打孔或落地书架……（替代方案）",
  "supplement":  "补充约定（待双方核对）\n\n一、协商事项：……（补充约定草稿）"
}
```

文案约定：草稿须保持「待双方确认」的中性口吻，不得给出确定性法律结论。

### 5.3 `extract` — PDF / 截图文本提取（预留）

当前 UI 仅支持本地预览，尚未接入提取；协议如下，供后续接线与服务端先行实现。

请求 `payload`：

```json
{
  "fileName": "contract.pdf",
  "mimeType": "application/pdf",
  "fileBase64": "JVBERi0xLjQK…"
}
```

响应 `result`：

```json
{ "title": "房屋租赁合同", "clauses": ["6.1　……", "6.2　……"] }
```

前端接线位置：`app.js` 中 `selectFile()`（拿到文件后调用本能力，成功则把 `clauses` 灌入 `state.doc` 走分析流程）。

## 6. Multi-Agent 编排建议

一个最小可用的编排器只需按 `capability` 路由到三个子 Agent：

| 子 Agent | 责任 | 触发的 capability |
| --- | --- | --- |
| locator（条款定位） | 把问题映射到条款下标，产出 `findings` | `analyze` |
| qa（解读问答） | 基于 locator 的条款回答 `question`，产出 `answer` | `analyze` |
| drafter（协商草稿） | 基于 goal + 依据条款生成三份草稿 | `draft` |
| extractor（文档解析，可选） | PDF/OCR → `clauses` | `extract` |

推荐数据流（`analyze` 内部两跳）：

```
question + clauses
   → locator: 选出相关条款 [{index, why}]
   → qa: 只允许引用 locator 给出的条款作答（降低幻觉）
   → 合并成 {findings, answer} 返回
```

可运行的最小示例服务端见 [`examples/agent-server.example.mjs`](../examples/agent-server.example.mjs)（Node.js，零依赖，含 CORS 与错误格式示范，`capability` 路由处即你接入自研/LangGraph/AutoGen 等编排器的位置）。

编排器实现要点：

1. **只用传入的条款作答**：`answer`/`findings` 的 `index` 必须落在 `clauses` 范围内，越界会被前端忽略。
2. **保持中性**：输出为「辅助阅读 + 沟通草稿」，不是法律意见；建议在 `text` 中保留提示语。
3. **幂等快速**：单次请求尽量控制在 `timeout` 内；超时即回退本地。
4. **可观测**：记录 `capability`、耗时、条款引用情况，便于调试子 Agent。

## 7. 错误处理与回退（前端已实现的行为）

| 情形 | 前端行为 |
| --- | --- |
| 未配置 endpoint 且未注册 Provider | 纯本地，零网络请求 |
| 请求超时 / HTTP 非 200 / `error` 字段 / 网络错误 | toast「智能体服务不可用，已回退本地分析」，界面展示本地结果 |
| `analyze` 返回缺 `findings` 或 `answer` | 只更新提供的部分 |
| `draft` 返回空/格式不符 | 保留本地模板草稿 |
| 返回的 `index` 越界或非整数 | 忽略该 `index`，按 -1 处理 |

## 8. 隐私与合规提示

- 配置 endpoint 后，**用户粘贴的合同全文**会明文发送到该端点（`draft` 还会附当前条款与目标）。请部署方：HTTPS 强制、明确告知用户、端点侧最小化留存。
- 建议端点侧不落盘日志正文，或在隐私政策中声明处理范围与期限。
- 输出内容不构成法律意见；各辖区对「自动化法律建议」监管不同，请自行评估文案边界。

## 9. 版本与兼容

- 当前协议 `version: 1`。前端按能力名调用，新增能力不影响旧端点（未实现的能力走本地兜底）。
- 破坏性变更会提升 `version` 并在本文档记录；`AgentBridge.call(capability, payload)` 亦可在控制台/测试中直接调用以便联调。

---

© 约定 YUEDING · 交互原型。示例合同均为虚构内容。
