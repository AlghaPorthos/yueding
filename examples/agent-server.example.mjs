// 约定 · Multi-Agent 端点最小示例（零依赖，Node.js 18+）
//
// 运行：node examples/agent-server.example.mjs [port]
// 默认监听 http://127.0.0.1:8787/agent
//
// 前端接线（index.html 中、引入 app.js 之前）：
//   <script>window.YUEDING_AGENT_CONFIG={endpoint:'http://127.0.0.1:8787/agent'};</script>
//
// 本文件演示第 4-5 节协议（docs/MULTI_AGENT_INTERFACE.md）：
//   · 按 capability 路由到不同「子 Agent」（此处为函数，替换成你的
//     LangGraph / AutoGen / CrewAI / 自研编排器即可）
//   · CORS 预检与响应头
//   · 成功 {result} / 失败 {error} 两种返回格式
import { createServer } from 'node:http';

const PORT = Number(process.argv[2] || 8787);
const ALLOWED_ORIGIN = '*'; // 生产环境请改为页面源，如 'https://<user>.github.io'

// ── 子 Agent：条款定位 ────────────────────────────────────────────
// 输入问题与条款，返回要点列表。index 必须是 clauses 的下标（0 起）。
const locatorAgent = ({ question, contract }) => {
  const keywords = [
    { key: 'deposit',  re: /押金|保证金/,  title: '押金返还', desc: '退还时间与扣减条件' },
    { key: 'wall',     re: /打孔|书架|改动/, title: '墙面改动', desc: '安装书架前的书面确认' },
    { key: 'repair',   re: /维修|损坏/,    title: '维修责任', desc: '设施损坏由谁负责' },
    { key: 'leave',    re: /提前|解除|退租/, title: '提前退租', desc: '通知时间与费用约定' },
    { key: 'privacy',  re: /推荐|撤回|个人信息/, title: '个性化推荐', desc: '撤回同意与数据处理' },
    { key: 'salary',   re: /奖金|绩效/,    title: '绩效奖金', desc: '考核方案与发放条件' },
  ];
  return keywords
    .map((k) => ({ ...k, index: contract.clauses.findIndex((c) => k.re.test(c)) }))
    .filter((k) => k.index >= 0)
    .slice(0, 4) // 2-5 条为宜
    .map(({ key, title, desc, index }) => ({ key, title, desc, index }));
};

// ── 子 Agent：解读问答 ────────────────────────────────────────────
// 只允许引用 locator 给出的条款作答（降低幻觉）。此处为规则演示，
// 实际可替换为 LLM 调用：把 question + 命中条款喂给模型并要求给出
// { title, text, index }，且 index 必须来自命中条款。
const qaAgent = ({ question, contract }, findings) => {
  const top = findings[0];
  if (!top) {
    return { title: '需要进一步核对', text: `未找到与「${question}」直接相关的约定，建议向对方书面确认。`, index: -1 };
  }
  return {
    title: `${top.title} · 智能体定位到第 ${top.index + 1} 段`,
    text: `「${contract.clauses[top.index]}」\n以上为智能体定位的相关原文，请结合完整上下文核对；本输出为辅助阅读，不构成法律意见。`,
    index: top.index,
  };
};

// ── 子 Agent：协商草稿 ────────────────────────────────────────────
const drafterAgent = ({ goal, clause }) => ({
  message: `您好，关于「${goal}」，希望在签约前和您进一步确认。相关原文：「${clause}」。我们能否把具体条件、各自责任和处理方式明确下来，并以书面形式确认？`,
  alternative: `如果暂时无法按「${goal}」安排，希望了解您可以接受的替代条件，再一起确认时间、费用与各自责任。`,
  supplement: `补充约定（待双方核对）\n\n一、协商事项：${goal}。\n二、具体安排：[由双方填写]。\n三、责任承担：[由双方另行确认]。\n\n甲方：________　乙方：________\n日期：________`,
});

// ── Orchestrator：按 capability 路由 ──────────────────────────────
async function orchestrator({ capability, payload }) {
  switch (capability) {
    case 'analyze': {
      const findings = locatorAgent(payload);
      return { findings, answer: qaAgent(payload, findings) };
    }
    case 'draft':
      return drafterAgent(payload);
    case 'extract':
      throw new Error('extract 尚未实现：请接入 PDF/OCR 服务后返回 {title, clauses}');
    default:
      throw new Error(`unknown capability: ${capability}`);
  }
}

createServer(async (req, res) => {
  const cors = {
    'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  };
  if (req.method === 'OPTIONS') return res.writeHead(204, cors).end();
  if (req.method !== 'POST' || !req.url.startsWith('/agent')) {
    return res.writeHead(404, cors).end('not found');
  }
  let body = '';
  for await (const chunk of req) body += chunk;
  try {
    const reqJson = JSON.parse(body || '{}');
    const result = await orchestrator(reqJson);
    console.log(`[${new Date().toISOString()}] ${reqJson.capability} -> ok`);
    res.writeHead(200, { ...cors, 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ result }));
  } catch (err) {
    console.error(`[${new Date().toISOString()}] error:`, err.message);
    res.writeHead(200, { ...cors, 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ error: String(err.message || err) })); // 协议约定的失败格式
  }
}).listen(PORT, () => console.log(`yueding agent example listening on http://127.0.0.1:${PORT}/agent`));
