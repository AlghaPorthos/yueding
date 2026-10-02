# Dify 工作流接入

此分支在首页和模板库提供三个已发布的 Dify Web 应用入口。它们是独立的在线工作流，与浏览器内的示例阅读器并列使用。

仓库的 GitHub Pages 当前从 `main` 分支构建。因此，`personal_branch` 中的页面修改在合并或调整 Pages 构建源之前，不会出现在现有 Pages 地址上。

| 场景 | Dify 工作流 | 输入 | 输出 |
| --- | --- | --- | --- |
| 租房 | [租房行动核对](https://udify.app/workflow/ruuUvJWryY8SboIS) | 租约文件、行动目标、可选的房东回复 | 条款依据、待确认事项、行动选项、可编辑沟通草稿 |
| 入职 | [入职条款核对](https://udify.app/workflow/tI2nxuqPTklugoKl) | 录用文件、招聘方说法、谈判优先级 | 书面与口头承诺对照、问题清单、谈判方案 |
| 应用权限 | [应用权限核对](https://udify.app/workflow/xTDGTuzyGf0M9o3R) | 隐私政策文件、权限请求、使用目的 | 权限与用途矩阵、协议缺口、可采取的步骤 |

每个 Dify 流程是“文档提取 → 条款分析与方案生成 → 独立依据复核 → 输出”的双阶段分析流程。引文应对应上传文件；材料没有写明的内容应列为待确认。工作流不会自动向房东、HR 或应用开发者发送消息，也不会更改手机权限。

## 数据边界

- 本页本地示例与文本阅读仍在浏览器内运行，刷新后清空。
- 点击 Dify 入口只会打开新的 Dify 页面；本页不会自动传送已粘贴的合同。
- 用户在 Dify 页面主动上传的文件会交由 Dify Cloud 处理。正式使用前，应核对该工作空间的数据留存和访问设置。演示时可先用虚构材料。
- 三个 URL 是 Web 应用入口，不是 API Key。不要把 Dify 应用 API Key 写进 `app.js`、`index.html` 或任何公开仓库文件。

## 与 AgentBridge 的关系

`app.js` 中的 `AgentBridge` 仍默认使用本地模式。Dify 的三个工作流当前需要用户上传文档，并输出完整 Markdown 行动卡；它们不能直接替代 AgentBridge 所需的 `analyze` / `draft` JSON 契约。若希望把 Dify 结果直接呈现在现有分析面板，需要新增服务端适配器：由服务端持有三个应用的 API Key，上传文档、调用对应 Dify 工作流，再把结果转换为 `docs/MULTI_AGENT_INTERFACE.md` 中的协议。GitHub Pages 只能托管静态前端，无法安全保存这些 Key。

## 更新工作流入口

三个 Web 应用地址集中定义在 `app.js` 的 `difyWorkflows` 常量中。若 Dify 重新发布后地址变化，只需更新该常量，并核对本文件与 README 中的链接。
