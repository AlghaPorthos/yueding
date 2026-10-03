# 约定 YUEDING · 合同阅读器

读懂约定，再做决定。

签合同之前，与其把 PDF 拖进聊天框问 AI「这条有没有坑」、得到一段说不清依据在哪页的回答，不如用「约定」：把合同拆成**能核对的原文、能追问的条款、能直接拿去沟通的草稿**。一次完整使用大致是——

导入材料（粘贴 / PDF / 截图 / 链接）→ 选立场（如承租人）→ 条款卡片与原文对照 → 追问关心的点 → 协商工坊生成消息草稿。

每条结论都能回到原文定位；找不到依据时明确返回「未找到相关约定」，不编。

在线演示：<https://hack.cachoidx.top>（Hackathon 原型，示例合同均为虚构内容）

## 快速开始

需要 Node.js 18+ 和 Python 3.11+，前后端两个终端：

```sh
# 终端 1：后端（127.0.0.1:8000）
cd backend
bash start-dev.sh          # 首次先建 venv：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 终端 2：前端（http://localhost:5173）
cd frontend
npm install                # 首次
npm run dev
```

前端检测到 localhost 会自动连本地后端。不起后端也行：前端进入纯本地模式，示例合同、关键词定位、沟通模板照常可用。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `frontend/` | React 19 + TypeScript + Vite + Tailwind CSS v4 单页应用，详见 [frontend/README.md](frontend/README.md) |
| `backend/` | 纯标准库 Python WSGI 后端（解析 / SQLite / 确定性法律检索 / 受证据约束的 LLM 链），详见 [backend/README.md](backend/README.md) 与 [backend/STATUS.md](backend/STATUS.md) |
| `PRODUCT.md` | 产品手册：功能详解、架构说明、隐私与数据、常见问题的完整版 |
| `SPEC.md` | 项目意图与后端完整体边界 |
| `OPENRIG-CULTURE.md` / `OPENRIG-WORKFLOW.md` | 工作区协作约定 |

## 技术栈一览

- **前端**：React 19 · TypeScript · Vite · Tailwind CSS v4 · shadcn 风格组件（Base UI）
- **后端**：Python 标准库 WSGI（wsgiref + ThreadingMixIn），零第三方 Web 框架；SQLite 持久化；macOS Vision OCR
- **LLM**：GLM 模型链（主 `glm-5.3-flash` / 备 `glm-4-flash`），仅用于深度分析与协商拟写，输入受已校验证据约束；未配置 key 时确定性能力照常工作

## 边界与免责

不收费、不代替律师、不自动签约、不代发消息。输出是「辅助阅读 + 沟通草稿」，不构成法律意见；示例合同均为虚构内容。
