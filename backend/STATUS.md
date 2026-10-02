# Backend 当前状态

更新时间：2026-10-02（Asia/Shanghai）

## 进度口径

百分比依据 [`missions/backend-full.md`](../missions/backend-full.md) 的验收条目估算，表示需求覆盖度，不表示代码行数、线上可达性或生产就绪度。当前整体按十个阶段等权约 **48%**；Phase 0–4 核心业务链路约 **59%**，Phase 5–9 生命周期和生产化能力约 **37%**。

| 阶段 | 完成度 | 当前判断 |
| --- | ---: | --- |
| Phase 0 MVP | 90% | 上传、页级文本、四类租房条款、行动卡片、引用和基础 API 已有；缺少 3 份样本、约 20 个标注点的正式回归集。 |
| Phase 1 文档/OCR 质量 | 30% | 已有 MIME/大小校验、SHA-256 去重、质量状态、质量原因和分析阻断；没有真实 OCR、扫描 PDF、分辨率/方向/表格处理和 OCR 置信度。 |
| Phase 2 法律检索/对齐 | 60% | 已有三来源可溯源语料（条例 50 + 民法典租赁章 25 + 示范文书 20，共 95 条，manifest 溯源与内容哈希由质量门禁测试钉死）、确定性检索与对齐、索引缓存按文件变更重建、角色视角条文重排、法律版本漂移重校验；缺少 FTS/BM25、同义词/正则、完整意图归一（金额/期限/条件/例外）和带回放的原子索引版本。 |
| Phase 3 证据契约 | 52% | `/matters` 已按输入输出协议投影 `extracted_facts/issues/missing_items/actions/drafts`，引用重校验（quote ⊆ 页文本、(source,article,version) ∈ 语料）失败即降级，区分 `supported/user_only/unknown`；Finding 仍缺 `severity/consequences` 字段和统一 schema 校验。 |
| Phase 4 受约束 LLM | 63% | 已有 provider、fallback、超时、预算、JSON 校验、引用约束和失败保留确定性结果；Jev 判定作为对齐保守慢路径（无键/超时/错误回退确定性）；缺少分阶段生成链路、生产认证、敏感信息检查和完整草稿生成流程。 |
| Phase 5 生命周期 | 50% | 已有用户/工作区/角色、提醒、清单、草稿版本和证据记录；缺少注册登录、合同列表、版本比较、删除/导出、审阅状态、回滚和提醒渠道。 |
| Phase 6 异步可靠性 | 55% | 已有任务表、幂等键、attempt、租约、重试、恢复和事件；没有真实 worker/queue 接入，上传、解析和 LLM 尚未自动进入任务链路。 |
| Phase 7 权限/隐私/审计/成本 | 35% | 有工作区访问控制、部分审计脱敏、provider 预算和指标；缺少加密、TLS、密钥轮换、对象存储授权、完整 PII 脱敏、保留/硬删除/导出和熔断。 |
| Phase 8 生产部署运维 | 15% | 已有 `healthz`、`readyz`、`metrics` 和 SQLite migration；缺少部署定义、对象存储、消息队列、worker、反向代理、完整监控和告警。 |
| Phase 9 回归评估发布 | 29% | 当前 67 项测试，含语料质量门禁（7 个篡改负样本）、matters 篡改降级、角色排序与标签回归；缺少脱敏样本集、人工标注集、OCR/召回/引用/法律对齐/成本指标和发布阻断门槛。 |

## 已实现能力

- **文档摄取和引用**：支持 UTF-8 文本、可检索 PDF 和图片入口；保存合同、版本、页级文本、字符 span、SHA-256、质量状态、质量原因和质量指标。图片或质量不足的文档返回 `needs_review`，不会生成确定性合同结论。
- **Phase 0 条款卡片**：对押金、房屋改动、维修、提前退租四类租房条款执行确定性抽取；结果带页码、span 和原文引用，并区分 `confirmed`、`not_found` 和待复核状态。
- **法律检索和对齐骨架**：从 JSONL 加载来源、条文号、版本、生效期和内容 hash，执行确定性短语检索；`/v1/contracts/{contract_id}/versions/{version_id}/align` 保存 `matched`、`ambiguous` 或 `not_found` 结果及匹配理由。当前 `backend/data/legal_corpus.jsonl` 有 95 条记录、3 个来源（住房租赁条例 50、民法典租赁合同章 25、市场监管总局示范文书 20），manifest 溯源与内容哈希由 `tests/test_corpus_quality.py` 门禁钉死，语料写盘原子化；仍不能视为完整法律资料包或法律意见来源。
- **角色感知对齐与协议投影**：`/align` 接受可选 `user_role`（承租人/出租人），对 confirmed 条款按角色标记词稳定重排条文（溯源字段不变）；`/matters` 将 findings 与 alignments 确定性投影为输入输出协议 output（`extracted_facts/issues/missing_items/actions/drafts`），引用与法律版本重校验失败即降级为 `user_only`，不伪造法律结论。
- **身份、生命周期和审计**：支持用户、工作区、成员角色、工作区范围访问检查，以及提醒、履约清单、清单完成和草稿版本持久化；审计事件保存脱敏后的元数据。当前是应用级身份边界，没有注册登录、OAuth 或会话系统。
- **Jev 判定慢路径**：`SystemOneProvider`（stdlib urllib，环境变量驱动）作为对齐的保守校验层——仅在确信 `no` 时降级匹配，无键/超时/解析错误一律回退确定性结果。
- **任务可靠性骨架**：支持任务创建、幂等键、领取、租约、状态更新、重试、指数退避、最大尝试次数、死信字段、进度事件、取消和过期任务恢复。当前没有后台 worker 或消息队列，业务处理仍由 API/人工任务接口触发。
- **受证据约束的 LLM 接口**：支持 OpenAI-compatible provider、主备切换、超时、费用上限、JSON 输出检查、引用存在性检查和调用指标；provider 失败时保留确定性结果并记录失败状态。
- **基础运维接口**：提供 `healthz`、`readyz`、`metrics` 和 SQLite migration，可在没有网络运行时依赖的环境中用标准库 WSGI 启动。

## 当前验证

```sh
PYTHONPATH=backend python3 -m compileall -q backend/app backend/tests
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -v
PYTHONPATH=backend python3 -m unittest discover -s backend -p 'test*.py' -q
```

结果：编译通过；`backend/tests` 63 项通过；包含 `backend/app/test_judge.py` 在内共 67 项通过。验证覆盖本地单元测试和 WSGI 路径（含真实语料端到端冒烟：上传 → 角色对齐 → matters 投影），不包含真实 OCR、真实外部模型、真实 worker/queue 或生产部署验证。

## 发布前阻塞

1. 接入真实 OCR，并保存页码、字符范围、引擎版本、坐标和置信度。
2. 建立可审核、可版本化、可回放的完整法律语料和本地全文索引。
3. 收紧统一 Finding/证据 schema、法律版本校验和所有降级路径。
4. 补齐登录认证、数据加密、对象存储授权、PII 处理、保留/删除/导出和成本熔断。
5. 把上传、解析、检索、LLM 和导出接入真实 worker/queue，并完成部署、监控和告警。
6. 建立脱敏样本集、人工标注集和发布门槛，覆盖 OCR、召回、引用、法律对齐、延迟和成本。

