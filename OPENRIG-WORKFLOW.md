# Hackathon 完整体后端开发工作流

这个工作区使用 `hackathon-dev` rig，只推进合同阅读器完整体后端。Codex 负责主流程：Astra
负责编排和决策，`gpt-6-sol` 负责实现与验证；Claude 用 `glm-5.3` 做深度评审，用
`glm-5.3-flash` 做快速反馈。权威路线是 `missions/backend-full.md`；MVP 是其中的 Phase 0，
不是完整交付范围。当前工作不改前端，不把规划当成完成。

## 启动

```sh
cd /Users/xiexingyu/Documents/项目/Hackathon
rig requirements ./rig-hackathon.yaml
rig up ./rig-hackathon.yaml --cwd . --plan
rig up ./rig-hackathon.yaml --cwd .
rig ps --nodes --rig hackathon-dev
```

首次启动前确认已登录所选运行时：

```sh
codex login status
claude auth status
```

如果只使用 Codex，Claude seat 会因为缺少认证而无法启动；这不影响 YAML
本身的工作流定义，但需要在启用辅助评审前完成 Claude 登录。

## 一次任务的完整路径

### 1. 启动和确认身份

```sh
cd /Users/xiexingyu/Documents/项目/Hackathon
rig whoami --json
rig ps --nodes --rig hackathon-dev --full
rig queue list --owned --limit 1000
```

如果 daemon 没启动，先运行 `rig up ./rig-hackathon.yaml --cwd .`。不要重复启动已经在运行的 rig。

### 2. 受理和拆解

`orchestration-lead` 先读 `AGENTS.md`、`SPEC.md`、当前 mission/slice 和相关代码，
把用户目标改写成一个可验收的结果：

- 目标行为和不做的范围
- 受影响的文件、接口或用户路径
- 验收命令和预期结果
- 风险、依赖和需要用户决策的事项

编排席用 Astra 做方案比较、依赖排序和风险判断，不直接假设实现细节。

后端切片按 `missions/backend-full.md` 的 Phase 0-9 推进：先完成可运行的租房合同
MVP，再依次补齐文档摄取/OCR、非 LLM 法律检索与意图对齐、引用式证据契约、受约束
LLM 链路、生命周期与履约、异步任务、权限隐私与成本控制、生产运维，最后做回归评估
和发布门槛。每个 Phase 再拆成单一边界的 slice，前一 slice 的验收证据进入后一 slice
的上下文。

法律检索和合同条款意图对齐是程序化链路：法律语料、版本、FTS/BM25、规则和命中证据
必须先产生结构化候选；LLM 只能在候选证据范围内生成解释和行动建议。引用式结果必须
能回到合同页码/span 与法律条文版本，证据不足时输出 `not_found` 或 `needs_review`。

### 3. 建立 durable work

把任务写进队列，避免只靠终端消息维持上下文：

```sh
cat > /tmp/hackathon-task.md <<'EOF'
Outcome: <可观察的最终结果>
Scope: <允许修改的边界>
Acceptance:
- <检查命令或用户路径>
- <第二项必要检查>
Constraints: preserve unrelated changes; do not publish.
EOF

rig queue create \
  --destination development-implementer@hackathon-dev \
  --tags "workflow:development" \
  --body-file /tmp/hackathon-task.md
```

### 4. 实现

`development-implementer` 使用 `gpt-6-sol`：先检查现状，再做最小完整改动，
运行与风险相称的测试，记录 diff、测试输出和未验证项。实现阶段不扩大范围，
不覆盖用户已有修改。

### 5. 独立验证

`development-verifier` 使用 `gpt-6-sol`，针对实现席交付的精确候选重新检查：

```sh
# Git 仓库运行 `git diff --check`；非 Git 目录运行项目已有的格式检查
# 项目定义的测试、构建、lint 或真实用户路径
```

它应报告通过项、失败项、复现命令和剩余风险，而不是只回复“看起来没问题”。
实现席根据结果修复后再次交付同一候选边界。

### 6. Claude 辅助评审

`review-fast-reviewer` 使用 `glm-5.3-flash`，在实现席提交候选后快速检查 schema、API
契约、回归和明显安全问题，尽早反馈。`review-reviewer` 使用 `glm-5.3`，只在验证席
通过后做深度独立评审，重点看：

- 用户行为是否与目标一致
- 边界条件、回归和错误处理
- 测试是否覆盖真正的失败模式
- 是否引入不必要的复杂度或安全问题

评审意见必须绑定到文件、行为或命令。需要修复时回到实现席；不修复时由编排席
记录明确理由，不把未解决意见伪装成通过。

### 7. 收尾

编排席在最终候选上复跑关键检查，更新队列记录并交付：变更内容、验证证据、未验证
范围和下一步。只有经过验证的候选才可以进入下一项任务。

## 怎么用 rig 推进后端

先由编排席为一个 slice 建立队列项。示例：

```sh
cat >/tmp/hackathon-backend-slice.md <<'EOF'
Outcome: 完成完整体后端路线中的一个明确 slice（例如 Phase 0 的上传、任务状态和统一错误结构）
Scope: 只改后端入口、schema、测试和必要文档；不改前端，不接真实外部模型
Acceptance:
- 合法文本 PDF 可创建任务并查询状态
- 非法类型、超限和解析失败返回统一错误结构
- 测试覆盖成功、失败和脱敏日志边界
- 如果后端目录是 Git 仓库，`git diff --check` 通过；否则运行该项目已有的格式检查
Constraints: preserve unrelated changes; do not publish or push; never log contract contents
EOF

rig queue create \
  --destination development-implementer@hackathon-dev \
  --mission backend-full \
  --slice api-input \
  --tags "workflow:backend" \
  --body-file /tmp/hackathon-backend-slice.md
```

实现席完成后，用队列交接给验证席，而不是只发一句“完成”：

```sh
rig queue handoff <implement-qitem-id> \
  --to development-verifier@hackathon-dev \
  --body-file /tmp/hackathon-verification.md
```

验证席必须针对同一工作区运行项目测试、适用的格式检查和可执行的真实后端路径，
把命令输出、失败复现和未验证项写回队列。验证通过后，编排席再用 `rig send` 把稳定候选
交给 `review-reviewer@hackathon-dev` 做深度独立评审；实现早期可先交给
`review-fast-reviewer@hackathon-dev` 做快速检查。发现问题就回到实现席，不能跳过修复。

查看推进状态：

```sh
rig status
rig ps --nodes --rig hackathon-dev
rig queue list --all-rigs --full --limit 1000
rig queue show <qitem-id> --full
rig capture orchestration-lead@hackathon-dev
rig transcript orchestration-lead@hackathon-dev
rig tui --shared
```

一个 slice 的完成判据是：实现 diff 存在、验证席有实际命令证据、评审意见已处理或被编排席明确记录、队列项已交接/关闭。完成后再创建下一个 slice，不要同时让多个 seat 修改同一后端边界。

保存并停止：

```sh
rig down hackathon-dev --snapshot
```

恢复同一 rig：

```sh
rig up hackathon-dev
```

## 模型分工

| Seat | Runtime | Model | 责任 |
| --- | --- | --- | --- |
| `orchestration-lead` | Codex | `gpt-6-astra` | 编排、拆解、依赖、风险、最终综合 |
| `development-implementer` | Codex | `gpt-6-sol` | 实现、测试、局部调试 |
| `development-verifier` | Codex | `gpt-6-sol` | 独立验证、复现和证据 |
| `review-reviewer` | Claude | `glm-5.3` | 深度独立评审、回归和用户路径检查 |
| `review-fast-reviewer` | Claude | `glm-5.3-flash` | 快速 schema/API/回归检查，尽早发现明显问题 |

模型选择只作用于这个 rig 的 seat；不要把它理解成全局 Codex 或 Claude 配置。
