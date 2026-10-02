# Contract Reader Backend

这是合同阅读器的标准库后端基线。当前代码覆盖 Phase 0–4 的主要本地能力，并包含 Phase 5–8 的部分生命周期、任务和运维骨架；按完整任务验收条目估算，整体完成度约 45%。详细阶段判断见 [`STATUS.md`](STATUS.md)。

## 当前能力

- 接受 UTF-8 文本、可检索 PDF 和图片输入，写入 SQLite 合同和版本记录。
- 返回页级文本、字符 span 和可核验引用；押金、房屋改动、维修、提前退租四类条款使用确定性规则生成卡片。
- 保存 SHA-256、质量状态、质量原因和质量指标。图片或质量不足的文档会返回 `needs_review`，没有 OCR 时不会猜测合同内容。
- 从 `CONTRACT_READER_LEGAL_CORPUS` 指定的 JSONL 加载法律来源、条文、版本、生效期和内容 hash，执行确定性短语检索与条款对齐。当前内置语料只有 71 条记录、2 个来源，不能替代完整的法律资料治理。
- 提供用户、工作区成员角色、提醒、履约清单、草稿版本、审计事件和任务状态接口。
- 提供受证据约束的 LLM provider 接口：主备 provider、超时、费用上限、JSON 校验和引用存在性校验。未配置 provider 时，确定性结果仍可用。
- 提供 `/healthz`、`/readyz` 和 `/metrics`。

## 运行

```sh
cd backend
PYTHONPATH=. python3 -c 'from wsgiref.simple_server import make_server; from app.main import app; make_server("127.0.0.1", 8000, app).serve_forever()'
```

健康检查：`GET /healthz`。

浏览器跨域访问默认允许本地 `4173/8080` 静态服务器和项目 GitHub Pages。部署到其他前端域名时设置 `CONTRACT_READER_CORS_ORIGINS`，值为逗号分隔的完整 origin（例如 `https://app.example.com`），不要使用 `*`。

上传：`POST /v1/contracts`，字段名为 `file`。带 `X-User-ID` 和 `X-Workspace-ID` 时会执行工作区访问检查。

法律检索：`GET /v1/legal/search?q=押金`。设置 `CONTRACT_READER_LEGAL_CORPUS` 指向 UTF-8 JSONL 语料后启用确定性短语检索；没有语料时返回 `not_found`，不虚构条文。

条款与法律语料对齐：
`POST /v1/contracts/{contract_id}/versions/{version_id}/align`。

受证据约束的生成：
`POST /v1/contracts/{contract_id}/versions/{version_id}/generate`。

错误响应固定为 `{"error":{"code":"...","message":"..."}}`。日志只记录 ID、状态和字节数等必要元数据，不记录合同正文、凭据或完整个人信息。

## 测试

```sh
cd backend
PYTHONPATH=. python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 -m unittest discover -s . -p 'test*.py' -q
```

当前 `tests` 目录 35 项通过；包含 `app/test_judge.py` 在内共 39 项通过。测试覆盖本地 SQLite、WSGI 接口、引用校验、质量阻断、法律对齐、身份访问、任务状态和 LLM 输出约束。

## 当前边界

尚未达到完整体交付门槛的部分包括：真实 OCR 和扫描件处理、完整法律语料和 FTS/BM25 索引、统一证据契约、注册登录和 OAuth、对象存储及加密、真实 worker/消息队列、提醒渠道、删除/导出/回滚、生产部署监控、脱敏回归集和发布阻断规则。

系统不提供律师代理、自动签约、自动代表用户谈判或个案法律最终裁判。
