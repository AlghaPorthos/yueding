# 约定 YUEDING · 后端完整链路

> 更新：2026-10-03。本文是后端全链路的权威描述：每个环节对应真实函数，含数据形态、门禁、降级路径与耗时预算。架构图见 `docs/diagrams/`（本文件为文字版，图示更新滞后时以本文为准）。

## 0. 运行形态

- 纯标准库 WSGI（`serve.py`，监听 127.0.0.1:8000），SQLite 持久化（`backend/data/contracts.sqlite3`），无外部服务依赖。
- 启动：`cd backend && ./start-dev.sh`（自动配置法律语料路径与 GLM 模型链）。
- 模型链：主 **glm-5.3-flash**（ZCode coding plan 的 Anthropic 兼容端点，`AnthropicCompatibleProvider`，thinking 禁用）→ 备 **glm-4-flash**（BigModel 开放平台，`OpenAICompatibleProvider`）。`LLMRouter` 逐级尝试，预算/超时可配。
- Jev（SystemOne 判断 API）：可选精排层，`CONTRACT_READER_JEV_API_KEY` 配置即启用。

## 1. 摄取链路（Ingest）

入口四类，全部汇入同一提取管线：

| 入口 | 路径 | 提取方式 |
|---|---|---|
| 粘贴文本 | `POST /v1/contracts`（text/plain） | UTF-8 解码，`\f` 分页 |
| 可检索 PDF | `POST /v1/contracts`（application/pdf） | pypdf 文字层 |
| 扫描 PDF / 截图 | `POST /v1/contracts`（pdf 无文字层 / image） | **macOS Vision OCR**：`app/macos_ocr.swift`（swiftc 预编译二进制，多页并发 ≤4），`app/ocr.py` 解析置信度/尺寸元数据 |
| 网页链接 | `POST /v1/fetch` | urllib 抓取（≤2MB，utf-8/gb18030）→ `HTMLParser` 剔除 script/style → 合成 multipart 复用上传管线 |

**核心函数**：`_upload → _parse_multipart → _extract_document`（分流）→ `assess_pages` + `ocr_quality_reasons`（质量评估）→ 质量门禁 → `sha256` 去重判定 → SQLite 落库（contracts / contract_versions / document_pages / text_spans）。

**质量门禁（分级）**：
- `ready`：正常进入全部分析。
- `needs_review`（OCR 置信度 <0.55、图片 <600px、文本覆盖不足等）：**阻断确定性条款结论**（Phase 0 findings 返回复核占位），但 `/generate` 仍放行（见 §4），响应保留复核标记。
- 上传响应即返回全部页文本，前端据此在首页生成「猜你想问」（文件不直接跳分析页）。

**耗时预算**：文本 <100ms；OCR 单图 ~0.5s、3 页扫描 PDF ~0.8s（热）；网页抓取视目标站 0.1–15s。

## 2. 意图理解与「猜你想问」（Suggest）

`POST /v1/questions/suggest {text}` → `_question_suggestions`，四级链路：

1. **Flash 通读全文生成**（主路径，`_generate_question_candidates`）：glm-5.3-flash 阅读 ≤6000 字全文，生成 8 个候选问题（每个 ≤30 字、须有条款依据、附 importance 1-10）。`_validate_question_candidates` 校验。**实测 4.4–5.1s**。
2. **Jev 精选**（配了 key 才走）：Jev 对 8 个候选打重要度分（0-100）取前三 → `source: "llm+jev"`。
3. **Flash 自评分排序**（无 Jev）：按 importance 降序取前三 → `source: "llm"`。
4. **确定性兜底**（LLM 全挂）：跨规则包模板候选，关键词命中排序（泛词封顶 5 + 包级零信号剔除 + 同包加成 10）→ `source: "deterministic"`。

类型识别 `_detect_contract_type`：四类关键词计数（含子串碰撞正则，如"住宿服务期限"不含"服务期"信号）；rental 为默认包且有正向词表。

## 3. 确定性分析与法律检索（零 LLM）

**分析** `POST /contracts/{cid}/versions/{vid}/analyze {question}`：
- `_question_topics` 把问题映射到条款类型（focus_types）；
- 规则包抽取 `_finding` → 挂证据 `_attach_finding_evidence` → 风险分级 `_finding_severity`（confirmed+不利+高关注=high / confirmed+不利=medium / confirmed=low / 其余 unknown）→ 出口统一校验 `_validate_finding_payload`（非法枚举就地修正、空引用剔除）；
- 立场初筛 `/screen`：`_deterministic_screen_row`（SCREEN_STANCE_RULES + 弱方默认视角）产出 favorable/unfavorable/neutral 与 priority，前端渲染「对我方不利」徽章。

**检索** `LegalIndex.search`（`app/legal.py`）：
- `_tokenize`：中文重叠 bigram + 英文按词；
- `SYNONYMS` 口语同义扩展（房东→出租人、扣钱→押金/扣减…），扩展词进 `reasoning.expanded_terms`；
- IDF 打分 + **命中门槛**：≥2 个 bigram 命中，或至少一个完整查询词命中（防"改变房屋"碰"房屋"误命中）；
- 每条结果带 `matched_terms`、`index_version`（语料内容哈希前 12 位）。

**对齐** `POST …/align`：`_normalize_intent` 规则化提取金额/期限/条件/例外（rule_ids v1）挂到 confirmed finding；匹配分类 matched/ambiguous/not_found；法律版本漂移重校验失败即降级。

**语料**：`data/legal_corpus.jsonl`，114 条、5 个来源（住房租赁条例 / 民法典 / 个保法 / 劳动合同法 / 市场监管总局示范文书），每条带 source/article/version/jurisdiction/effective/content_hash。全量视图 `GET /v1/legal/corpus`（按来源分组，前端「法条库」页）；检索 `GET /v1/legal/search?q=`（注意参数名是 **q**）。

## 4. 受约束双阶段生成（Generate）

`POST /v1/contracts/{cid}/versions/{vid}/generate {task}`：

**质量门禁（分级放行）**：仅当"无 findings 证据 **且** 无非空页文本"才跳过生成（`quality_needs_review`）；OCR 低置信等场景放行并保留复核标记。alignment 无证据时**退回页级原文**（≤6 页 × 240 字）构造 Stage A 证据——模型永远拿得到真实文本。

**上下文组装**：slim evidence（≤6 条 ×240 字）+ `compact_findings`（类型/状态/立场/引文 ≤120 字）+ 法律语料 top-6（`_legal_query_from_task` 关键词归一后检索，条文 ≤400 字）。

**Stage A（证据摘要·风险·法条）**：schema `{summary, severity, consequences[], legal_refs[], citations[]}`；`validate_generated_json` 剔除越界 citations（合同证据 quote 子串校验）与越界 legal_refs（条文 quote 校验）。失败 → `generation_status: failed`，确定性结果保留。

**Stage B（行动·协商草稿）**：输入 = Stage A 合法输出 + task + evidence；schema `{actions[], drafts{message, supplement}}`；`validate_staged_drafts` 校验。失败 → 保留 Stage A（`stages: {a:true, b:false}`），前端工坊回退本地模板草稿。

**观测**：两阶段各记一条 `llm_invocations`（provider/model/tokens/latency）；Stage B 耗时单列 `stage_b_latency_ms`。环境变量 `CONTRACT_READER_LLM_STAGED=off` 可退回单次生成。

**耗时预算**：Stage A ≈ 5–12s（5.3-flash，输入瘦身 + thinking 禁用）；Stage B ≈ 5–10s；全程 15–30s，前端 60s 超时。

## 5. 合同列表与持久化（我的合同）

- `GET /v1/contracts`：最近 50 份合同 + 最新版本概要（name/created_at/page_count/quality_status/version_id）。`_list_contracts`。
- `GET /v1/contracts/{cid}/versions/{vid}`：版本详情（页文本 + 质量指标），前端点击列表项恢复阅读。
- 前端上传成功即失效列表缓存；「我的合同」页从后端拉取，刷新页面不丢失（本地会话历史仅作后端未启用时的回退）。

## 6. 证据契约（对外数据形态）

每条 Finding：`{type, status, severity(low|medium|high|unknown), consequences[], confidence, provenance("deterministic"), contract_evidence[{page, span_id, quote}], action_card, intent{amount,duration,condition,exception,rule_ids}}`。
`/matters` 投影为 `{extracted_facts, issues, missing_items, actions, drafts}`，引用重校验（quote ⊆ 页文本、(source,article,version) ∈ 语料）失败降级 `user_only`，不伪造法律结论。

## 7. 可靠性与降级总表

| 故障 | 行为 |
|---|---|
| 主模型失败/限流 | LLMRouter 自动切备用 glm-4-flash |
| 双模型全失败 | 保留确定性结果，`generation_status: failed` |
| Stage B 失败 | 保留 Stage A，无 drafts |
| LLM 输出越界引用 | 就地剔除该引用，摘要与合法引用保留 |
| OCR 低置信/低分辨率 | needs_review：确定性结论阻断，生成放行带标记 |
| 语料未配置 | 检索返回 not_found，生成无 legal_refs，不虚构法条 |
| Jev 未配置/超时 | 猜你想问退 Flash 自评分 / 确定性模板排序 |
| 网页抓取失败/超2MB | fetch_failed，提示改用粘贴 |

## 8. 前端对接速查

| 能力 | 端点 |
|---|---|
| 上传（文本/PDF/图） | `POST /v1/contracts`（multipart） |
| 网页抓取 | `POST /v1/fetch` {url} |
| 猜你想问 | `POST /v1/questions/suggest` {text} |
| 分析（问题聚焦） | `POST /contracts/{cid}/versions/{vid}/analyze` {question}（无 /v1 前缀） |
| 立场初筛 | `POST /v1/contracts/{cid}/versions/{vid}/screen` {user_role?} |
| 生成（解答/草稿） | `POST /v1/contracts/{cid}/versions/{vid}/generate` {task} |
| 对齐 | `POST /v1/contracts/{cid}/versions/{vid}/align` |
| 合同列表 | `GET /v1/contracts` |
| 版本详情 | `GET /v1/contracts/{cid}/versions/{vid}` |
| 法条全量 | `GET /v1/legal/corpus` |
| 法条检索 | `GET /v1/legal/search?q=…&limit=` |
| 健康检查 | `GET /healthz` `/readyz` `/metrics` |
