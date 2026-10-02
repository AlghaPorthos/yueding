# 后端联调手册（前端对接用）

本手册面向前端联调，全部端点、请求/响应字段与错误码均来自 `app/main.py` 的 `_route` 路由与
`tests/test_phase2_alignment.py`、`tests/test_role_alignment.py`、`tests/test_matters_projection.py`
中的真实 fixture；示例响应为真实运行输出（UUID 每次不同，超长引文以「……」截断）。

## 1. 启动

```sh
cd backend
PYTHONPATH=. python3 serve.py                       # 默认 http://127.0.0.1:8000
PYTHONPATH=. python3 serve.py --host 0.0.0.0 --port 8080
CONTRACT_READER_PORT=9000 PYTHONPATH=. python3 serve.py
```

- 地址解析优先级：`--host`/`--port` 命令行参数 > `CONTRACT_READER_HOST`/`CONTRACT_READER_PORT`
  环境变量 > 默认 `127.0.0.1:8000`。
- `serve.py` 基于标准库 `wsgiref` 单线程，仅用于开发联调。
- 等价备选（README 同款一行式）：

  ```sh
  PYTHONPATH=. python3 -c 'from wsgiref.simple_server import make_server; from app.main import app; make_server("127.0.0.1", 8000, app).serve_forever()'
  ```

**推荐联调启动**（带上语料，`/align`、`/v1/legal/search` 才有法条结果）：

```sh
cd backend
CONTRACT_READER_LEGAL_CORPUS=data/legal_corpus.jsonl PYTHONPATH=. python3 serve.py
```

## 2. 环境变量

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `CONTRACT_READER_HOST` / `CONTRACT_READER_PORT` | `serve.py` 绑定地址/端口 | `127.0.0.1` / `8000` |
| `CONTRACT_READER_CORS_ORIGINS` | 浏览器 CORS 白名单，逗号分隔完整 origin（不支持 `*`） | `http://localhost:4173,http://127.0.0.1:4173,http://localhost:8080,http://127.0.0.1:8080,https://alghaporthos.github.io` |
| `CONTRACT_READER_LEGAL_CORPUS` | 法律语料 JSONL 路径（仓库内置 `data/legal_corpus.jsonl`，95 条） | 未设置 → `/align` 的 `legal_provisions` 恒为空（alignment_status=not_found），`/v1/legal/search` 返回 `status:"not_found"` 且 `reason:"legal_corpus_not_configured"` |
| `CONTRACT_READER_JEV_API_KEY` / `TYPESAFE_API_KEY` | 可选 Jev 判定（两者取先设置者）：`/align` 命中后的二次精化，以及 `/screen` 初筛的首选引擎 | 未设置 → `/align` 纯确定性；`/screen` 依 LLM 配置降级（见 §8） |
| `CONTRACT_READER_JEV_URL` / `CONTRACT_READER_JEV_MODEL` | Jev 判定 endpoint / 模型 | `https://api.typesafe.ai/v1` / `jev-latest` |
| `CONTRACT_READER_LLM_PRIMARY_*` / `CONTRACT_READER_LLM_FALLBACK_*` / `CONTRACT_READER_LLM_TIMEOUT_SECONDS` / `CONTRACT_READER_LLM_MAX_COST` | `/v1/contracts/{cid}/versions/{vid}/generate` 的 LLM provider 配置 | 显式变量优先；未设置时若存在本地 `ZAI_API_KEY`，自动使用 `https://open.bigmodel.cn/api/paas/v4/chat/completions` 与 `glm-4.7` |
| `ZAI_API_KEY` / `ZAI_API_URL` / `ZAI_BASE_URL` / `ZAI_MODEL` | 普通 LLM 的本地 Z.AI 兼容配置；`ZAI_API_URL` 与 `ZAI_BASE_URL` 可覆盖 v4 endpoint，`ZAI_MODEL` 可覆盖模型 | 只读取 presence，不返回或记录 key |

## 3. 通用约定

- 除 `OPTIONS`（204 无正文）外，所有响应均为 JSON：`Content-Type: application/json; charset=utf-8`。
- 错误统一为：

  ```json
  {"error": {"code": "invalid_request", "message": "请求字段 user_role 无效", "request_id": "884e70ff-…"}}
  ```

  `code` 见 §6；`request_id` 用于排查日志。
- 身份头**可选**：`X-User-ID`、`X-Workspace-ID`。不带即匿名，可完整走通
  upload → analyze → align → matters 主线；带了则要求用户存在于 `users` 表且为工作区成员，
  否则 `403 forbidden`。
- 上传走 `multipart/form-data`，文件字段名固定为 `file`；JSON 请求需 `Content-Type: application/json`。

## 4. 端点速查表

### 4.1 联调主线

| 方法 | 路径 | 请求 | 成功响应 | 关键响应字段 |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | — | 200 | `status:"ok"` |
| GET | `/readyz` | — | 200 | `status:"ready"`, `database:"ok"`, `llm:{providers,configured,max_cost}` |
| GET | `/metrics` | — | 200 | `jobs`（按状态计数）, `llm_invocations`, `llm_estimated_cost` |
| POST | `/contracts` 或 `/v1/contracts` | `multipart/form-data`，字段 `file`（`text/plain`/`text/markdown`/`application/pdf`/图片） | 新建：`/contracts`→201，`/v1/contracts`→200；同内容重复上传→200 | `contract_id`, `version_id`, `status`, `page_count`, `duplicate`, `pages[]`, `workspace_id`, `quality_status`, `quality_reasons[]`, `quality_metrics{}`, `quality{}` |
| GET | `/contracts/{cid}/versions/{vid}`（`/v1/` 前缀亦可） | — | 200 | 同上（多 `sha256`，`pages[]` 为存储页） |
| POST | `/contracts/{cid}/versions/{vid}/analyze` | 无 body | 200 | `contract_id`, `version_id`, `quality_status`, `findings[4]` |
| POST | `/contracts/{cid}/versions/{vid}/align`（`/v1/` 前缀亦可） | 空 body，或 `application/json`：`{"user_role":"承租人"|"出租人"}`（可选） | 200 | `contract_id`, `version_id`, `status`, `quality_status`, `findings[4]`（`alignments` 为同一数组的别名） |
| POST | `/contracts/{cid}/versions/{vid}/screen`（`/v1/` 前缀亦可） | 空 body，或 `application/json`：`{"user_role": ...}`（可选，取值见 §8） | 200 | `status:"ok"`, `perspective`, `engine`, `findings[]`, `next{}`, `disclaimer`（详见 §8） |
| POST | `/contracts/{cid}/versions/{vid}/matters`（`/v1/` 前缀亦可） | 无 body | 200 | `contract_id`, `version_id`, `quality_status`, `extracted_facts[]`, `issues[]`, `missing_items[]`, `actions[]`, `drafts:[]` |
| GET | `/v1/legal/search?q=押金&limit=10` | 查询参数：`q`（必填）、`limit`（默认 10，0–50）、`version`、`jurisdiction`、`effective_on`（均可选） | 200 | `status:"confirmed"|"not_found"`, `query`, `results[]`, `reasoning:{retrieval}` |

**路径陷阱（务必注意）**：

- `analyze` 只有无 `v1` 前缀的路径：`POST /contracts/{cid}/versions/{vid}/analyze`。
  `POST /v1/contracts/.../analyze` 返回 `404 not_found`。
- 反之 `generate` 只有 `v1` 前缀；upload/version/align/matters 两种前缀都可用。
- 上传新建时状态码依路径不同：`/contracts` → 201，`/v1/contracts` → 200（测试与下方示例均用 `/v1/contracts` + 200）。
- 相同文件内容再次上传 → 200 + `duplicate:true`，复用原 `contract_id`/`version_id`。

### 4.2 其余端点（后台/运维，前端联调可忽略）

| 方法 | 路径 | 请求 | 成功 |
| --- | --- | --- | --- |
| POST | `/v1/users` | JSON：`display_name`、`email` | 201 |
| POST | `/v1/workspaces` | JSON：`name`、`owner_id` | 201 |
| GET | `/v1/audit-events?workspace_id=&limit=` | 需 `X-User-ID`（editor 以上） | 200 |
| POST/GET | `/v1/contracts/{id}/reminders` / `checklist` / `drafts` | JSON：`title`…；需身份头 | 201 / 200 |
| POST | `/v1/checklist/{item_id}/complete` | 需身份头 | 200 |
| POST | `/v1/jobs` | JSON：`kind`、`payload{}`、可选 `contract_id`/`idempotency_key`/`max_attempts` | 201 |
| GET | `/v1/jobs?status=&limit=` | — | 200 |
| GET | `/v1/jobs/{job_id}` | — | 200 |
| POST | `/v1/jobs/{job_id}/claim`（或 `/run`） | JSON：`worker_id`、可选 `lease_seconds` | 200 |
| POST | `/v1/jobs/{job_id}/status` | JSON：`status`（succeeded/failed/canceled）、可选 `progress`/`result`/`error_code`/`error_message` | 200 |
| POST | `/v1/jobs/{job_id}/retry`、`/cancel` | — | 200 |
| POST | `/v1/jobs/recover-stale` | — | 200 |
| POST | `/v1/contracts/{cid}/versions/{vid}/generate` | 空 body 或 JSON：`task` 等 | 200 |

未知方法/路径 → `404 not_found`（`{"error":{"code":"not_found","message":"请求资源不存在",…}}`）。

## 5. 主线响应字段详解

### 5.1 上传 `POST /v1/contracts`（multipart，字段名 `file`）

`pages[]` 每页：`span_id`（如 `p1-s1`）、`page`、`start`、`end`、`quote`、`text`。
`quality_status`：`ready` | `needs_review` | `failed`；图片（无 OCR）→ `needs_review`，reasons 含 `ocr_unavailable`。

### 5.2 `analyze` 的 `findings[4]`

固定顺序 `deposit → modification → repair → early_termination`（押金/改造/维修/提前退租）：

- 命中（`status:"confirmed"`）：`type`、`status`、`confidence:0.97`、`content`（命中行原文）、
  `contract_evidence:[{page, span_id:"p1-s1", quote}]`、
  `action_card:{question, impact, suggested_revision}`、`severity:"unknown"`、`consequences:[]`、
  `legal_provisions:[]`、`reasoning:{rules:["phase0-<type>-keyword-v1"], retrieval:"phrase"}`、
  `disclaimer`。
- 未命中（`status:"not_found"`）：`confidence:0.0`、`contract_evidence:[]`、`action_card:null`、`message:"未找到相关约定"`。
- 质量阻断（`status:"needs_review"`，如图片上传）：`message:"文档质量不足，未生成确定性条款结果"`、`quality_status` 回显。

#### 合同类型与规则包（privacy / labor）

上传后 `/analyze` 先按关键词频次做确定性类型探测（不调用 LLM）：

| 探测类型 | 触发关键词（累计 ≥3 次且占优） | `findings` 条款类型（固定顺序） |
| --- | --- | --- |
| `privacy`（隐私政策） | 个人信息 / 收集 / 处理者 / 撤回 / 算法 / 隐私政策 / 敏感个人信息 | `processing_scope → consent_withdrawal → sharing_delegation → retention_period → security_breach_notice`（处理范围/同意与撤回/共享与委托/保存期限/安全与泄露通知） |
| `labor`（劳动合同） | 劳动合同 / 用人单位 / 劳动者 / 试用期 / 竞业限制 / 工资 / 加班 / 服务期 / 劳动 | `probation_period → compensation → overtime → termination → non_compete`（试用期/劳动报酬/加班与调休/合同解除/竞业限制与服务期） |
| `rental`（默认，租房合同） | 未达阈值 | `deposit → modification → repair → early_termination`（行为与既有版本逐字节一致） |

每类规则包结构与租房四类完全一致（keywords/question/impact/suggested_revision），findings 的
字段形状、`reasoning.rules`（`phase0-<type>-keyword-v1`）与 `align`/`matters` 的
clause_type 字符串透传均不变；`align` 用对应规则包的关键词在语料中检索（语料已加入
《个人信息保护法》与《劳动合同法》核心条文，见 `data/legal_corpus.jsonl`）。

### 5.3 `align` 的 `findings[4]`（= `alignments`）

每条：`type`、`status`、`alignment_status`（`matched` | `not_found` | `needs_review`）、
`confidence`（命中 0.8，否则 0.0）、`contract_evidence[]`（同 analyze）、`legal_provisions[]`、
`reasoning:{rules:["phase2-<type>-phrase-v1"], retrieval, query?}`、命中时另有 `disclaimer`。

`legal_provisions[]` 每条：`source`、`article`、`version`、`quote`、`jurisdiction`、`effective_from`、
`effective_to`、`content_hash`、`matched_terms[]`、`provision_id`、`source_kind`、`reasoning`。

- 顶层 `status`（整体）：有 `matched` → `matched`；仅 `needs_review` → `needs_review`；否则 `not_found`。
- `user_role` 请求体：`承租人` 或 `出租人`，仅对已命中的法条做稳定重排序（溯源字段
  `source/article/version/content_hash` 不变），并在每条 `reasoning.user_role` 回显；非法值 →
  `400 invalid_request`；空 body 或非 JSON body 与不带该字段等价。

### 5.4 `matters`（法律事项工作台投影，纯确定性、无 LLM）

- `extracted_facts[]`：`{text, source_refs:[{doc_id(=version_id), page, quote}], status}`；
  `status` = `supported`（引用与语料均可核验）或 `user_only`（质量阻断/核验失败降级，`source_refs:[]`）。
- `issues[]`：`{question（RULES 固定问题文案）, rule_refs[], status:"supported"|"unknown"}`，
  仅包含 alignment 为 not_found/needs_review 的条款。
- `missing_items[]`：由质量原因映射（如「补充合同页」「更清晰的扫描件/文字版」），质量 ready 时为 `[]`。
- `actions[]`：每个已确认条款一个 `{kind:"negotiate", text:"与合同相对方协商：<suggested_revision>", requires_user_approval:true}`。
- `drafts` 恒为 `[]`。

## 6. 错误码

| HTTP | `error.code` | 触发场景 |
| --- | --- | --- |
| 400 | `invalid_request` | JSON 字段缺失/非法（含 `user_role` 非法）、JSON 非对象、查询参数非法 |
| 400 | `invalid_json` | 声明 JSON 但 body 解析失败 |
| 400 | `request_too_large` | JSON body > 128 KB |
| 400 | `missing_file` / `file_too_large` | multipart 缺 `file` 字段 / 文件 > 5 MB |
| 400 | `unsupported_type` | `/v1/contracts` 上传不支持的文件类型（仅支持文本、可检索 PDF、图片） |
| 415 | `unsupported_media_type` | `/contracts`（无 v1 前缀）上传不支持的文件类型 |
| 403 | `forbidden` | 身份头无效 / 非工作区成员 / 无权访问合同 |
| 404 | `not_found` | 路由不存在（含 `/v1/.../analyze`）、合同/版本/任务不存在 |
| 409 | `conflict` / `idempotency_conflict` / `invalid_job_transition` / `max_attempts_exceeded` | 邮箱已存在 / 幂等键冲突 / 任务状态机非法迁移 |
| 503 | `legal_corpus_unavailable` | 已设置 `CONTRACT_READER_LEGAL_CORPUS` 但语料读取失败（align）/ 检索异常 |
| 500 | `internal_error` | 数据库或 IO 异常 |

## 7. curl 联调序列（真实响应示例）

前置：按 §1 推荐 `CONTRACT_READER_LEGAL_CORPUS=data/legal_corpus.jsonl` 启动；另开终端执行。
四条款 fixture 摘自 `tests/test_matters_projection.py` / `tests/test_phase2_alignment.py`。
UUID 为示例值，每次运行不同；`……` 为长引文截断。

**① 存活检查**

```sh
curl -s http://127.0.0.1:8000/healthz
```

```json
{"status": "ok"}
```

**② 上传四条款合同（multipart，字段名 `file`）**

```sh
cat > /tmp/lease.txt <<'EOF'
押金为一个月租金，退租后七日内返还。
未经出租人书面同意，承租人不得改造房屋。
房屋及附属设施的日常维修由出租人负责。
承租人提前退租，应提前三十日通知并承担违约金。
EOF

curl -s -X POST http://127.0.0.1:8000/v1/contracts \
  -F "file=@/tmp/lease.txt;type=text/plain"
```

```json
{
  "contract_id": "8bf619af-35df-4611-8a22-a9ace9808b8b",
  "version_id": "0d1e6a7c-2f2b-4d3a-9c1d-5e6f7a8b9c0d",
  "status": "ready",
  "page_count": 1,
  "duplicate": false,
  "pages": [
    {
      "span_id": "p1-s1",
      "page": 1,
      "start": 0,
      "end": 96,
      "quote": "押金为一个月租金，退租后七日内返还。\n未经出租人书面同意……",
      "text": "押金为一个月租金，退租后七日内返还。\n未经出租人书面同意……"
    }
  ],
  "workspace_id": null,
  "quality_status": "ready",
  "quality_reasons": [],
  "quality_metrics": {"bytes": 96, "page_count": 1, "text_chars": 89},
  "quality": {"quality_status": "ready", "quality_reasons": [], "quality_metrics": {"bytes": 96, "page_count": 1, "text_chars": 89}}
}
```

记下 `contract_id` / `version_id`（下称 `$CID` / `$VID`）。重复上传同一内容会得到
`"duplicate": true` 且复用原 ID。

**③ 条款分析（注意：无 v1 前缀）**

```sh
curl -s -X POST "http://127.0.0.1:8000/contracts/$CID/versions/$VID/analyze"
```

```json
{
  "contract_id": "8bf619af-…",
  "version_id": "0d1e6a7c-…",
  "quality_status": "ready",
  "findings": [
    {
      "type": "deposit",
      "status": "confirmed",
      "confidence": 0.97,
      "content": "押金为一个月租金，退租后七日内返还。",
      "contract_evidence": [{"page": 1, "span_id": "p1-s1", "quote": "押金为一个月租金，退租后七日内返还。"}],
      "action_card": {
        "question": "押金退还期限、扣除条件和凭证是什么？",
        "impact": "核对押金金额、返还期限和扣除依据。",
        "suggested_revision": "补充押金金额、返还期限、扣除情形和结算凭证。"
      },
      "severity": "unknown",
      "consequences": [],
      "legal_provisions": [],
      "reasoning": {"rules": ["phase0-deposit-keyword-v1"], "retrieval": "phrase"},
      "disclaimer": "结果仅整理合同事实，不构成针对个案的法律意见"
    },
    {"type": "modification", "status": "confirmed", "confidence": 0.97, "content": "未经出租人书面同意，承租人不得改造房屋。", "contract_evidence": [{"page": 1, "span_id": "p1-s1", "quote": "未经出租人书面同意，承租人不得改造房屋。"}], "action_card": {"question": "哪些装修或改造需要书面同意，恢复责任由谁承担？", "impact": "在装修或添置设施前确认书面同意和恢复责任。", "suggested_revision": "明确可实施项目、书面同意流程和退租恢复标准。"}, "severity": "unknown", "consequences": [], "legal_provisions": [], "reasoning": {"rules": ["phase0-modification-keyword-v1"], "retrieval": "phrase"}, "disclaimer": "结果仅整理合同事实，不构成针对个案的法律意见"},
    {"type": "repair", "status": "confirmed", "confidence": 0.97, "content": "房屋及附属设施的日常维修由出租人负责。", "contract_evidence": [{"page": 1, "span_id": "p1-s1", "quote": "房屋及附属设施的日常维修由出租人负责。"}], "action_card": {"question": "日常维修和设施故障的报修、响应及费用由谁负责？", "impact": "保存报修记录并确认费用和响应时限。", "suggested_revision": "补充维修责任、响应时限和费用承担规则。"}, "severity": "unknown", "consequences": [], "legal_provisions": [], "reasoning": {"rules": ["phase0-repair-keyword-v1"], "retrieval": "phrase"}, "disclaimer": "结果仅整理合同事实，不构成针对个案的法律意见"},
    {"type": "early_termination", "status": "confirmed", "confidence": 0.97, "content": "承租人提前退租，应提前三十日通知并承担违约金。", "contract_evidence": [{"page": 1, "span_id": "p1-s1", "quote": "承租人提前退租，应提前三十日通知并承担违约金。"}], "action_card": {"question": "提前退租的通知期限、违约金和例外情形是什么？", "impact": "需要提前退租时核对通知期限、费用和交接要求。", "suggested_revision": "明确提前解除通知期限、违约金上限和例外情形。"}, "severity": "unknown", "consequences": [], "legal_provisions": [], "reasoning": {"rules": ["phase0-early_termination-keyword-v1"], "retrieval": "phrase"}, "disclaimer": "结果仅整理合同事实，不构成针对个案的法律意见"}
  ]
}
```

（四条款全部 `confirmed`；文本质量不足或图片上传时对应 finding 变为 `needs_review`、
`confidence:0.0`、`contract_evidence:[]`、`action_card:null`。）

**④ 条款↔法条对齐（可选请求体 `user_role`）**

```sh
# 无 body 也可以；这里带角色视角
curl -s -X POST "http://127.0.0.1:8000/v1/contracts/$CID/versions/$VID/align" \
  -H 'Content-Type: application/json' \
  -d '{"user_role": "承租人"}'
```

```json
{
  "contract_id": "8bf619af-…",
  "version_id": "0d1e6a7c-…",
  "status": "matched",
  "quality_status": "ready",
  "findings": [
    {
      "type": "deposit",
      "status": "confirmed",
      "alignment_status": "matched",
      "confidence": 0.8,
      "contract_evidence": [{"page": 1, "span_id": "p1-s1", "quote": "押金为一个月租金，退租后七日内返还。"}],
      "legal_provisions": [
        {
          "source": "https://htsfwb.samr.gov.cn/View?id=2340996b-…",
          "article": "第七条 其他相关费用",
          "version": "2025",
          "quote": "租赁期内，与该房屋相关各项费用的承担方式为：……",
          "jurisdiction": "中国大陆",
          "effective_from": null,
          "effective_to": null,
          "content_hash": "…sha256…",
          "matched_terms": ["押金"],
          "provision_id": null,
          "source_kind": "external",
          "reasoning": {"retrieval": "phrase", "matched_terms": ["押金"]}
        }
      ],
      "reasoning": {
        "rules": ["phase2-deposit-phrase-v1"],
        "retrieval": "phrase",
        "query": "押金 保证金 押付",
        "user_role": "承租人"
      },
      "disclaimer": "法律对应仅基于已配置且可追溯的语料，不构成针对个案的法律意见"
    }
  ],
  "alignments": [ /* 与 findings 完全相同的数组 */ ]
}
```

- 顶层 `status` 此处为 `matched`；服务端未配置 `CONTRACT_READER_LEGAL_CORPUS` 时为
  `not_found` 且每条 `legal_provisions:[]`（HTTP 仍为 200）。
- 非法角色（如 `"律师"`）→ `400 {"error":{"code":"invalid_request","message":"请求字段 user_role 无效",…}}`。

**⑤ 法律事项工作台投影**

```sh
curl -s -X POST "http://127.0.0.1:8000/v1/contracts/$CID/versions/$VID/matters"
```

```json
{
  "contract_id": "8bf619af-…",
  "version_id": "0d1e6a7c-…",
  "quality_status": "ready",
  "extracted_facts": [
    {
      "text": "押金为一个月租金，退租后七日内返还。",
      "source_refs": [{"doc_id": "0d1e6a7c-…", "page": 1, "quote": "押金为一个月租金，退租后七日内返还。"}],
      "status": "supported"
    },
    {
      "text": "未经出租人书面同意，承租人不得改造房屋。",
      "source_refs": [{"doc_id": "0d1e6a7c-…", "page": 1, "quote": "未经出租人书面同意，承租人不得改造房屋。"}],
      "status": "supported"
    }
  ],
  "issues": [],
  "missing_items": [],
  "actions": [
    {
      "kind": "negotiate",
      "text": "与合同相对方协商：补充押金金额、返还期限、扣除情形和结算凭证。",
      "requires_user_approval": true
    }
  ],
  "drafts": []
}
```

（该 fixture 四条款均 confirmed → 4 条 `supported` facts + 4 个 negotiate actions；
未命中/被阻断的条款进入 `issues`，其 `question` 为 §5.3 所列固定问题文案。）

**（可选）法条检索**

```sh
curl -s "http://127.0.0.1:8000/v1/legal/search?q=押金&limit=2"
```

```json
{
  "status": "confirmed",
  "query": "押金",
  "results": [ /* legal_provisions 同构对象 */ ],
  "reasoning": {"retrieval": "phrase"}
}
```

未配置语料时：`{"status": "not_found", "query": "押金", "results": [], "reason": "legal_corpus_not_configured"}`。

## 8. 初筛与二级分发链路（screen → generate）

`POST /contracts/{cid}/versions/{vid}/screen`（`/v1/` 前缀亦可）是**立场化初筛**：
复用 `/analyze` 的确定性条款识别与访问检查，对每个条款给出「对谁有利/不利」的快速判断，
前端据此把 `stance≠neutral` 的条款拼入 `/generate` 的 `task` 做二级深度分析。

### 8.1 请求

- 空 body（或非 JSON body）：立场取合同类型默认值 —— rental→`承租人`、privacy→`数据主体`、labor→`员工`。
- `application/json`：`{"user_role": "承租人"}`。合法值为六种立场并集：
  `承租人|出租人|数据主体|个人信息处理者|员工|用人单位`（任意合同类型都可传，不按类型收窄）；
  非法值 → `400 invalid_request`（与 `/align` 的 `user_role` 报错一致）。

### 8.2 响应契约（三种引擎下逐字段同构，前端不感知引擎）

顶层：`status:"ok"`、`perspective`（实际采用的立场）、`engine`（`jev|llm|deterministic`）、
`findings[]`、`next:{endpoint, hint}`（`endpoint` 即本版本的 `/generate` 路径）、`disclaimer`。

`findings[]` 每条（顺序同 `/analyze`，条数随合同类型 4/5 条）：

| 字段 | 说明 |
| --- | --- |
| `clause_type` / `status` | 同 `/analyze` 的 `type` / `status`（confirmed / not_found / needs_review） |
| `stance` | `favorable` \| `unfavorable` \| `neutral` \| `uncertain`（相对 `perspective`） |
| `interest_note` | 一句话利益点，≤60 字；not_found/needs_review 时透传 `/analyze` 的 `message` |
| `priority` | `high` \| `medium` \| `low`（协商优先级） |
| `confidence` | 0–1 浮点；deterministic=0.5，jev/llm 用模型置信度（缺省 0.7），未命中条款=0.0 |
| `negotiation_hint` | 一句话协商建议，≤60 字 |
| `evidence` | 命中条款的 `{page, span_id, quote}`（取 `contract_evidence` 首条）；缺失时为 `{}` |
| `source` | `deterministic` \| `jev` \| `llm`（该条结论出自哪级引擎；单条映射失败会回 `deterministic`） |

not_found / needs_review 条款固定：`stance:"uncertain"`、`priority:"low"`、`evidence:{}`。
审计动作 `contract.screen`（metadata 含 `perspective`/`engine`），匿名请求不记审计行。

### 8.3 引擎选择

| 顺序 | 引擎 | 触发条件 | 失败行为 |
| --- | --- | --- | --- |
| 1 | `jev` | 配置了 `CONTRACT_READER_JEV_API_KEY`/`TYPESAFE_API_KEY` 且存在 confirmed 条款 | 对全部 confirmed 条款**一次批量** judge（每条 `stance`/`priority` choice + `note` noul）；任何 `JudgeError` → 整批退 3；单条答案不合法 → 仅该条退 3 |
| 2 | `llm` | Jev 未配置，但 `readyz.llm.configured=true`（LLM provider 已配置）且存在 confirmed 条款 | **一次** `generate`，严格 JSON + 字段校验；解析/校验失败 → 退 3 |
| 3 | `deterministic` | 兜底（无任何模型凭证，或上级引擎失败） | 内置关键词立场表 + 模板 note/hint，`confidence:0.5`，永不失败 |

无 confirmed 条款（如图片上传被质量阻断）时不调用任何模型，`engine:"deterministic"`。

### 8.4 curl 序列（真实响应，确定性路径）

前置：不带任何 Jev/LLM 凭证启动（默认即确定性）。上传同 §7②的四条款 fixture 后：

```sh
# 立场可省略；这里显式传承租人
curl --noproxy '*' -s -X POST "http://127.0.0.1:8000/v1/contracts/$CID/versions/$VID/screen" \
  -H 'Content-Type: application/json' \
  -d '{"user_role": "承租人"}'
```

```json
{
  "status": "ok",
  "perspective": "承租人",
  "engine": "deterministic",
  "findings": [
    {
      "clause_type": "deposit",
      "status": "confirmed",
      "stance": "unfavorable",
      "interest_note": "押金返还约定缺少逾期责任，返还保障不足",
      "priority": "medium",
      "confidence": 0.5,
      "negotiation_hint": "补充返还期限对应的逾期利息或违约责任",
      "evidence": {"page": 1, "span_id": "p1-s1", "quote": "押金为一个月租金，退租后七日内返还。"},
      "source": "deterministic"
    },
    {
      "clause_type": "modification",
      "status": "confirmed",
      "stance": "neutral",
      "interest_note": "改造或装修须经书面同意，属常见程序性限制",
      "priority": "low",
      "confidence": 0.5,
      "negotiation_hint": "明确可实施项目、同意流程与恢复标准",
      "evidence": {"page": 1, "span_id": "p1-s1", "quote": "未经出租人书面同意，承租人不得改造房屋。"},
      "source": "deterministic"
    },
    {
      "clause_type": "repair",
      "status": "confirmed",
      "stance": "favorable",
      "interest_note": "维修责任由出租人承担，承租人维修支出风险低",
      "priority": "low",
      "confidence": 0.5,
      "negotiation_hint": "补充报修响应时限与费用垫付规则",
      "evidence": {"page": 1, "span_id": "p1-s1", "quote": "房屋及附属设施的日常维修由出租人负责。"},
      "source": "deterministic"
    },
    {
      "clause_type": "early_termination",
      "status": "confirmed",
      "stance": "unfavorable",
      "interest_note": "提前解约触发违约金且无上限约定，违约成本高",
      "priority": "high",
      "confidence": 0.5,
      "negotiation_hint": "约定违约金上限、通知期限与免责情形",
      "evidence": {"page": 1, "span_id": "p1-s1", "quote": "承租人提前退租，应提前三十日通知并承担违约金。"},
      "source": "deterministic"
    }
  ],
  "next": {
    "endpoint": "/v1/contracts/$CID/versions/$VID/generate",
    "hint": "把 stance≠neutral 的条款连同立场拼入 generate 的 task 做二级深度分析"
  },
  "disclaimer": "初筛结果仅为条款利益倾向的辅助判断，不构成针对个案的法律意见"
}
```

（`next.endpoint` 中 `$CID`/`$VID` 为实际 UUID；非法 `user_role` →
`{"error":{"code":"invalid_request","message":"请求字段 user_role 无效",…}}`。）

**二级分发**：把 `stance≠neutral` 的条款（上例为 deposit 与 early_termination，均为
`unfavorable`）连同立场拼入 `/generate` 的 `task`：

```sh
curl --noproxy '*' -s -X POST "http://127.0.0.1:8000/v1/contracts/$CID/versions/$VID/generate" \
  -H 'Content-Type: application/json' \
  -d '{"task": "站在承租人立场，重点解释：1) 押金为一个月租金，退租后七日内返还。 2) 承租人提前退租，应提前三十日通知并承担违约金。（来自 screen 中 stance≠neutral 的条款）"}'
```

实测（未配置 LLM 时）：`{"contract_id":"…","version_id":"…","generation_status":"failed",
"llm":null,"error":{"code":"not_configured","message":"未配置模型供应商"},"invocation_id":"…"}` ——
HTTP 仍为 200，`deterministic` 字段照常携带对齐证据；配置 LLM 后同请求返回
`generation_status:"succeeded"` 与 `llm.result`。

## 9. CORS 预检

- 任意路径 `OPTIONS` 请求一律返回 `204 No Content`，无需业务代码参与。
- 请求带 `Origin` 且命中白名单时，预检响应附带：
  - `Access-Control-Allow-Origin: <Origin>`（回显，非 `*`）与 `Vary: Origin`
  - `Access-Control-Allow-Methods: GET, POST, OPTIONS`
  - `Access-Control-Allow-Headers: Content-Type, X-User-ID, X-Workspace-ID, Authorization`
  - `Access-Control-Max-Age: 600`
- 简单/实际请求命中白名单时也返回 `Access-Control-Allow-Origin`；白名单外的 origin
  不返回任何 CORS 头（由浏览器拦截）。
- 前端 dev server 建议跑在 `4173` 或 `8080`（默认白名单已含 localhost/127.0.0.1 两种写法）；
  其他域名在服务端导出 `CONTRACT_READER_CORS_ORIGINS` 覆盖。

预检验证：

```sh
curl -s -i -X OPTIONS http://127.0.0.1:8000/v1/contracts \
  -H 'Origin: http://localhost:4173' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type,x-user-id'
# HTTP/1.1 204 No Content
# Access-Control-Allow-Origin: http://localhost:4173
# Access-Control-Allow-Methods: GET, POST, OPTIONS
# Access-Control-Allow-Headers: Content-Type, X-User-ID, X-Workspace-ID, Authorization
```

## 10. 冒烟脚本

一键跑完 §7 主线并逐字段断言（需 `jq`，缺失时自动回退 `python3`）：

```sh
cd backend
bash scripts/smoke_integration.sh                    # 默认 http://127.0.0.1:8000
BASE_URL=http://127.0.0.1:9000 bash scripts/smoke_integration.sh
```

一键跑完 CORS 预检 + §7 主线 + `/generate` 确定性降级并逐字段断言（需 `jq`，缺失时自动回退 `python3`；脚本内置 `no_proxy='*'` 防护，见 §12）。

任一断言失败即以非零码退出。

## 11. 前端（yueding）联调专区

`yueding/index.html` 的后端地址是**硬编码默认值**：

```js
window.YUEDING_BACKEND_CONFIG = Object.assign({
  baseUrl: /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? 'http://127.0.0.1:8000' : '',
  // ...
}, window.YUEDING_BACKEND_CONFIG || {});
```

即：从 `localhost`/`127.0.0.1` 打开页面时自动指向 `http://127.0.0.1:8000`。
**后端若不在 8000**（例如被占用，见 §12），必须在页面加载业务脚本之前覆盖：

```html
<script>window.YUEDING_BACKEND_CONFIG = { baseUrl: 'http://127.0.0.1:8001' };</script>
```

（`Object.assign` 默认值在后，覆盖值在前者优先；或直接改 index.html 第 7-10 行的默认值。）

前端静态服务器端口注意：

- 用 `python3 -m http.server 4173`（或 8080）——`python3 -m http.server` **默认 8000**，
  既与后端端口冲突、也不在 CORS 默认白名单里。

## 12. 代理与端口排障（本机实证）

**系统代理劫持 loopback（curl/urllib 表现为 502 或超时）**：

- macOS 系统级代理（`scutil --proxy`，常见 Clash/Surge `127.0.0.1:7890`）会接管对
  `127.0.0.1` 的请求；后端状态词表里没有 502，见到 502 基本可断定是代理回的。
- curl 规避：`curl --noproxy '*'` 或 `export no_proxy='*'`；`scripts/smoke_integration.sh`
  已内置该防护，可直接无人值守跑。
- **浏览器同理**：Chrome/Safari 遵循 macOS 系统代理。若页面 fetch 报 502，把
  `127.0.0.1`/`localhost` 加入代理绕行列表（Clash 系默认绕过 loopback，但取决于配置）。

**端口 8000 被占**：

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN   # 本机当前为 omlx-server 占用
```

处置二选一：停掉占用进程释放 8000；或 `serve.py --port 8001` 并按 §10 覆盖前端 baseUrl。
冒烟脚本用 `BASE_URL=http://127.0.0.1:8001 bash scripts/smoke_integration.sh` 指向实际端口。
