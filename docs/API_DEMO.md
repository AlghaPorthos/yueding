# 本地中转：无需服务器

macOS 双击根目录 `start-local.command`，然后访问 http://127.0.0.1:8787/ 。需 Node.js 22.9+；启动器也会自动寻找本机 Codex 附带的 Node。

1. 点击右上角「本机设置」（http://127.0.0.1:8787/setup）。
2. 从 Dify 对应工作流的「API 访问」页面创建应用 API Key；租房场景只需填写租房 Key。不要使用模型供应商密钥或 Web App 分享链接。
3. 点击「验证并保存」。服务读取 `/parameters` 核对 Key 和工作流输入字段，不上传合同、不运行模型。配置即时生效。
4. 返回体验，选择文件、输入问题、开始核对。分析时文件和问题经本机中转发送至 Dify 与其配置的模型服务；这并非离线运行。

配置存于本机 `.local-dify.json`（权限 0600），重启自动读取；网页只收到配置状态，不会收到已保存的 Key。留空保留原配置，填写新值即可替换。删除该文件可以清除页面保存的配置。该文件已从 Git 和 Docker 构建排除，切勿分享给他人。已有 `.env` 也可继续使用，本机保存的对应项优先。

保持启动器终端窗口打开，关闭窗口或按 Ctrl+C 停止本地服务。GitHub Pages 的网页不会启动本机服务，演示时请直接打开上述本地地址。此模式默认只监听 127.0.0.1；设置 API 还检查本机 Host、Origin 和临时校验令牌。公开部署默认禁用配置入口。

## 命令行启动

```sh
npm start
```

## 服务部署（可选）

# 自有界面 + Dify Service API

`demo-api.html` 提供文件选择、拖拽、原文预览、独立问题框、场景背景、运行进度、答案复制与下载。浏览器只访问约定后端；后端通过 Dify 的正式 Service API 调用工作流。没有 Dify iframe、Web App token 或浏览器端 API Key。

## 启动

需要 Node.js 22+，无需安装 npm 依赖。

1. 将 `.env.example` 复制为 `.env`。
2. 在 Dify 三个已发布工作流的 API 访问页面取得各自的应用 API Key，填写 `DIFY_RENTAL_API_KEY`、`DIFY_EMPLOYMENT_API_KEY`、`DIFY_PRIVACY_API_KEY`。这些是工作流应用的密钥，不是模型供应商密钥，也不是 `udify.app/workflow/...` 中的公开 Web App token。
3. 执行 `npm start`，打开 `http://127.0.0.1:8787`。

可仅配置租房 Key，其他场景会显示未连接。`.env` 已被 Git 和 Docker 构建上下文排除；不要把凭据放进静态资源或提交到仓库。生产环境优先用平台的 secrets/environment 功能注入。

## 服务器部署

可用 `Dockerfile` / `compose.yaml` 部署。设置强随机 `DEMO_ACCESS_CODE`，执行 `docker compose up -d --build`。Compose 默认只向本机发布 8787 端口，请使用现有 HTTPS 反向代理转发到 `127.0.0.1:8787`。代理关闭响应缓冲，将读取超时设为大于 240 秒，以支持 SSE。容器使用非 root 用户。

普通 Node 云平台也可运行 `node server/index.mjs`，设置 `HOST=0.0.0.0`、平台提供的 `PORT`、应用密钥和访问码。服务在公共网络监听时必须有访问码。内置最多 3 个并发请求和每个来源地址每小时 20 次调用的限制；反向代理后的请求共用代理地址限制。如需大规模开放，接入平台的鉴权与限流服务。

建议前后端由同一服务提供。若保留 GitHub Pages 前端，发布前在 HTML 的 `yueding-api-base` meta 中填入 HTTPS 后端地址，并设置服务端 `ALLOWED_ORIGIN=https://alghaporthos.github.io`。API Key 仍仅留在后端。GitHub Pages 本身无法运行这个服务。

## 接口与数据流

- `GET /api/config`：只返回各场景是否配置、文件大小限制、是否需要演示访问码。不会返回密钥。
- `POST /api/analyze`：multipart 文件、`scenario`、`question`（最多 256 字）、`context`（最多 2000 字）、`priority`。若开启访问码，使用 `X-Demo-Code` 请求头。
- 服务端使用同一个随机 `user` 和同一个应用 Key，先调用 `POST /v1/files/upload`，等返回有效 ID，再调用 `POST /v1/workflows/run`，以 `local_file` 传入对应文件变量。
- Dify 节点事件转换为上传、读取、分析、复核进度。只有 `workflow_finished` 且 `status=succeeded` 时返回 `outputs.result`。中途断流、空结果和失败状态都按失败处理，不展示模型第一轮未复核草稿。
- 请求最长 240 秒；用户停止或断开时终止连接，并在拿到 task ID 时向 Dify 发送停止请求。

现有工作流变量兼容：租房问题传给 `goal`；入职问题附加在 `hr_claim` 后，保留真实背景与问题的区分；权限问题传给 `purpose`，权限背景传给 `permissions`。这些是独立 Workflow 调用，不保存多轮对话记忆。

## 数据处理

用户点击提交前，文件仅用于本地选择和预览。提交后经过约定服务端进入 Dify Cloud。服务端临时在内存中处理文件，不写文件正文和答案日志；转发时改用通用文件名。Dify 侧的文件与运行记录仍按其工作空间留存设置处理。页面的 Markdown 输出先转义原始内容，仅允许有限格式标签。

## 验证

`npm test` 使用模拟 Dify Service API 验证：三个场景参数、上传/运行身份一致、SSE 跨块与 CRLF、复核完成后输出、断流与失败不冒充成功、密钥缺失、上传限制、访问码与跨域校验。模拟测试不代表真实 Dify API 已联通；配置应用 Key 后，必须使用合成文件执行一次真实端到端检查。

官方参考：[Workflow API](https://docs.dify.ai/en/api-reference/guides/workflow)、[流式响应](https://docs.dify.ai/en/api-reference/guides/streaming)。
