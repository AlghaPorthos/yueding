import { createServer } from 'node:http';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const MAX_FILE = 15 * 1024 * 1024;
const MAX_BODY = MAX_FILE + 128 * 1024;
const extensions = new Set(['pdf', 'docx', 'txt', 'md']);
const priorities = new Set(['更高的固定薪酬', '更明确的长期激励', '两者平衡']);
const scenarioKeys = ['rental', 'employment', 'privacy'];
const staticFiles = {
  '/': ['demo-api.html', 'text/html; charset=utf-8'],
  '/demo-api.html': ['demo-api.html', 'text/html; charset=utf-8'],
  '/demo-api.css': ['demo-api.css', 'text/css; charset=utf-8'],
  '/demo-api.js': ['demo-api.js', 'text/javascript; charset=utf-8'],
  '/sse.mjs': ['sse.mjs', 'text/javascript; charset=utf-8'],
  '/index.html': ['index.html', 'text/html; charset=utf-8'],
  '/app.js': ['app.js', 'text/javascript; charset=utf-8'],
  '/style.css': ['style.css', 'text/css; charset=utf-8'],
};

class PublicError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function makeInputs(scenario, fileId, fields) {
  const file = { type: 'document', transfer_method: 'local_file', upload_file_id: fileId };
  const question = String(fields.question || '').trim();
  const context = String(fields.context || '').trim();
  if (!question || question.length > 256) throw new PublicError(400, '请填写 1–256 字的问题。');
  if (context.length > 2000) throw new PublicError(400, '补充说明请控制在 2000 字以内。');
  if (scenario === 'rental') return { lease_file: file, goal: question, reply: context };
  if (scenario === 'employment') {
    if (!priorities.has(fields.priority)) throw new PublicError(400, '请选择谈判重点。');
    return { employment_file: file, priority: fields.priority,
      hr_claim: `招聘方说法：${context || '未提供，请仅依据文件核对。'}\n\n用户希望重点核对的问题：${question}` };
  }
  if (scenario === 'privacy') return { policy_file: file, purpose: question,
    permissions: context || '未单独提供权限弹窗。仅依据所上传协议和用户问题核对，未知部分请标为待确认。' };
  throw new PublicError(400, '请选择有效场景。');
}

function secretEqual(a, b) {
  const x = Buffer.from(a || ''); const y = Buffer.from(b || '');
  return x.length === y.length && timingSafeEqual(x, y);
}

async function readForm(req) {
  if (!String(req.headers['content-type'] || '').startsWith('multipart/form-data;'))
    throw new PublicError(415, '请使用文件上传表单。');
  if (Number(req.headers['content-length']) > MAX_BODY) throw new PublicError(413, '文件不能超过 15 MB。');
  let size = 0; const parts = [];
  for await (const part of req) {
    size += part.length;
    if (size > MAX_BODY) throw new PublicError(413, '文件不能超过 15 MB。');
    parts.push(part);
  }
  try { return await new Response(Buffer.concat(parts), { headers: { 'Content-Type': req.headers['content-type'] } }).formData(); }
  catch { throw new PublicError(400, '上传内容无效，请重新选择文件。'); }
}

function publicUpstreamError(status) {
  if ([401, 403].includes(status)) return new PublicError(502, '分析服务认证失败，请联系演示负责人检查服务配置。');
  if (status === 429) return new PublicError(429, '分析服务当前繁忙或额度不足，请稍后重试。');
  return new PublicError(502, '分析服务未接受请求，请稍后重试或重新选择文件。');
}

export function createApp(options = {}) {
  const env = options.env || process.env;
  const base = (env.DIFY_API_BASE || 'https://api.dify.ai/v1').replace(/\/$/, '');
  const baseURL = new URL(base);
  if (baseURL.protocol !== 'https:' && !['localhost', '127.0.0.1', '[::1]'].includes(baseURL.hostname))
    throw new Error('DIFY_API_BASE must use HTTPS');
  const keys = { rental: env.DIFY_RENTAL_API_KEY, employment: env.DIFY_EMPLOYMENT_API_KEY, privacy: env.DIFY_PRIVACY_API_KEY };
  const fetcher = options.fetch || fetch;
  const rates = new Map(); let active = 0;
  return createServer(async (req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    const origin = req.headers.origin;
    const ownOrigins = [`http://${req.headers.host}`, `https://${req.headers.host}`];
    const allowed = !origin || ownOrigins.includes(origin) || origin === env.ALLOWED_ORIGIN;
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Cache-Control', 'no-store');
    if (path.startsWith('/api/')) {
      if (!allowed) { res.writeHead(403).end(); return; }
      if (origin) { res.setHeader('Access-Control-Allow-Origin', origin); res.setHeader('Vary', 'Origin'); }
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Demo-Code');
      if (req.method === 'OPTIONS') { res.writeHead(204).end(); return; }
    }
    const json = (status, value) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(value)); };
    if (path === '/api/config' && req.method === 'GET') {
      json(200, { scenarios: Object.fromEntries(scenarioKeys.map(k => [k, Boolean(keys[k])])), accessCodeRequired: Boolean(env.DEMO_ACCESS_CODE), maxFileBytes: MAX_FILE }); return;
    }
    if (req.method === 'GET' && staticFiles[path]) {
      try {
        res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src blob:; frame-src blob:; connect-src 'self'; img-src 'self' blob: data:; base-uri 'none'; frame-ancestors 'none'");
        const [file, type] = staticFiles[path];
        const body = await readFile(join(root, file)); res.writeHead(200, { 'Content-Type': type }); res.end(body);
      } catch { json(404, { error: '页面不存在。' }); }
      return;
    }
    if (path !== '/api/analyze' || req.method !== 'POST') { json(404, { error: '接口不存在。' }); return; }
    if (env.DEMO_ACCESS_CODE && !secretEqual(req.headers['x-demo-code'], env.DEMO_ACCESS_CODE)) { json(401, { error: '请输入正确的演示访问码。' }); return; }
    const now = Date.now();
    // Use the socket address; untrusted forwarded headers must not bypass limits.
    const ip = req.socket.remoteAddress || 'unknown';
    for (const [key, entry] of rates) if (entry.reset < now) rates.delete(key);
    const entry = rates.get(ip) || { count: 0, reset: now + 3600000 };
    if (entry.count >= 20 || active >= 3) { json(429, { error: '请求较多，请稍后再试。' }); return; }
    entry.count++; rates.set(ip, entry); active++;
    const controller = new AbortController();
    let taskId; let user; let apiKey; let finished = false; let heartbeat;
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 240000);
    const send = (event, data) => { if (!res.destroyed && !res.writableEnded) res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); };
    res.on('close', () => { if (!finished) controller.abort(); });
    try {
      const form = await readForm(req);
      const scenario = String(form.get('scenario') || '');
      if (!scenarioKeys.includes(scenario)) throw new PublicError(400, '请选择有效场景。');
      apiKey = keys[scenario];
      if (!apiKey) throw new PublicError(503, '此场景的分析服务尚未连接。');
      const file = form.get('file');
      if (!file || typeof file.arrayBuffer !== 'function' || !file.size) throw new PublicError(400, '请选择非空文件。');
      if (file.size > MAX_FILE) throw new PublicError(413, '文件不能超过 15 MB。');
      const ext = file.name.split('.').pop().toLowerCase();
      if (!extensions.has(ext)) throw new PublicError(400, '请上传 PDF、DOCX、TXT 或 Markdown 文件。');
      const fields = { question: form.get('question'), context: form.get('context'), priority: form.get('priority') };
      makeInputs(scenario, 'validate-only', fields);
      user = `demo-${randomUUID()}`;
      res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive' });
      res.flushHeaders();
      heartbeat = setInterval(() => { if (!res.destroyed) res.write(': keep-alive\n\n'); }, 15000);
      send('progress', { stage: 'upload', message: '正在上传文件…' });
      const upload = new FormData();
      // Avoid forwarding a person's name in the local filename.
      upload.set('file', file, `document.${ext}`); upload.set('user', user);
      const headers = { Authorization: `Bearer ${apiKey}` };
      const uploaded = await fetcher(`${base}/files/upload`, { method: 'POST', headers, body: upload, signal: controller.signal });
      if (!uploaded.ok) throw publicUpstreamError(uploaded.status);
      const metadata = await uploaded.json();
      if (!metadata.id || typeof metadata.id !== 'string') throw new PublicError(502, '文件上传未返回有效编号，请重试。');
      send('progress', { stage: 'extract', message: '文件已上传，正在读取条款…' });
      const response = await fetcher(`${base}/workflows/run`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ inputs: makeInputs(scenario, metadata.id, fields), response_mode: 'streaming', user }), signal: controller.signal });
      if (!response.ok) throw publicUpstreamError(response.status);
      const { readSSE } = await import('../sse.mjs');
      let llmNodes = new Set();
      for await (const frame of readSSE(response.body)) {
        const event = frame.data;
        if (!event || typeof event !== 'object') continue;
        if (event.task_id) taskId = event.task_id;
        if (event.event === 'node_started') {
          const node = event.data || {};
          if (node.node_type === 'llm') {
            llmNodes.add(node.node_id || node.id);
            send('progress', llmNodes.size > 1 ? { stage: 'review', message: '正在复核依据与回答…' } : { stage: 'analyze', message: '正在分析条款与问题…' });
          }
        }
        if (event.event === 'error') throw new PublicError(502, '工作流运行失败，请稍后重试。');
        if (event.event === 'workflow_finished') {
          const data = event.data || {};
          if (data.status !== 'succeeded') throw new PublicError(502, '工作流未成功完成，请重新上传或联系演示负责人。');
          const answer = data.outputs?.result;
          if (typeof answer !== 'string' || !answer.trim()) throw new PublicError(502, '工作流没有返回有效答案。');
          send('result', { answer, elapsedSeconds: data.elapsed_time ?? null });
          finished = true; break;
        }
      }
      if (!finished) throw new PublicError(502, '分析连接中断，尚未收到完整结果。请重试。');
    } catch (err) {
      const message = err instanceof PublicError ? err.message : controller.signal.aborted ? '请求已停止或等待超时，请重试。' : '分析服务暂时不可用，请稍后重试。';
      if (!res.headersSent) json(err instanceof PublicError ? err.status : 502, { error: message });
      else send('error', { message });
    } finally {
      clearTimeout(timeout); clearInterval(heartbeat);
      if (!finished && taskId && user && apiKey) {
        void fetcher(`${base}/workflows/tasks/${encodeURIComponent(taskId)}/stop`, { method: 'POST',
          headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ user }), signal: AbortSignal.timeout(5000) }).catch(() => {});
      }
      active--; finished = true; res.end();
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const host = process.env.HOST || '127.0.0.1';
  if (!['127.0.0.1', 'localhost', '::1'].includes(host) && !process.env.DEMO_ACCESS_CODE)
    throw new Error('Set DEMO_ACCESS_CODE before listening on a public interface.');
  createApp().listen(Number(process.env.PORT || 8787), host, () => console.log(`Yueding API demo: http://${host}:${process.env.PORT || 8787}`));
}
