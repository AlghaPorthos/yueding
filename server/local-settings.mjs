import { readFile, writeFile, rename, unlink } from 'node:fs/promises';
import { randomUUID, timingSafeEqual } from 'node:crypto';

export const keyNames = { rental: 'DIFY_RENTAL_API_KEY', employment: 'DIFY_EMPLOYMENT_API_KEY', privacy: 'DIFY_PRIVACY_API_KEY' };
const requiredInputs = { rental: ['lease_file', 'goal'], employment: ['employment_file', 'hr_claim', 'priority'], privacy: ['policy_file', 'permissions', 'purpose'] };
const labels = { rental: '租房', employment: '入职', privacy: '应用协议' };
export const isLoopback = host => ['localhost', '127.0.0.1', '::1', '[::1]', '::ffff:127.0.0.1'].includes(host);
export function isLocalRequest(req) {
  try { return isLoopback(req.socket.remoteAddress) && isLoopback(new URL(`http://${req.headers.host}`).hostname); }
  catch { return false; }
}
export function normalizeBase(value) {
  const url = new URL(String(value));
  if (url.username || url.password || url.search || url.hash || (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback(url.hostname))))
    throw new Error('请填写 HTTPS API 地址，包含 /v1；本机 Dify 可使用 HTTP。');
  return url.href.replace(/\/$/, '');
}
export async function loadLocalSettings(path) {
  try {
    const saved = JSON.parse(await readFile(path, 'utf8')); const result = {};
    if (saved.DIFY_API_BASE) result.DIFY_API_BASE = normalizeBase(saved.DIFY_API_BASE);
    for (const name of Object.values(keyNames)) if (typeof saved[name] === 'string') result[name] = saved[name];
    return result;
  } catch (err) {
    if (err.code === 'ENOENT') return {};
    throw new Error('本机配置文件无法读取，请检查 .local-dify.json。');
  }
}

export function localSettingsHandler({ path, getSettings, applySettings, fetcher }) {
  const token = randomUUID(); let saving = false;
  return async (req, res) => {
    if (new URL(req.url, 'http://localhost').pathname !== '/api/local-settings') return false;
    const respond = (status, data) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(data)); };
    if (!path || !isLocalRequest(req)) { respond(404, { error: '本机配置入口不可用。' }); return true; }
    if (req.method === 'GET') {
      const settings = getSettings();
      respond(200, { token, apiBase: settings.base, configured: Object.fromEntries(Object.entries(settings.keys).map(([k,v])=>[k,Boolean(v)])) }); return true;
    }
    if (req.method !== 'POST') { respond(405, { error: '不支持的请求。' }); return true; }
    const incoming = Buffer.from(String(req.headers['x-local-setup-token'] || '')); const expected = Buffer.from(token);
    if (req.headers.origin !== `http://${req.headers.host}` || incoming.length !== expected.length || !timingSafeEqual(incoming, expected)) {
      respond(403, { error: '请从本机设置页面重新提交。' }); return true;
    }
    if (!String(req.headers['content-type'] || '').startsWith('application/json')) { respond(415,{error:'请使用配置表单。'}); return true; }
    if (saving) { respond(409, { error: '正在验证配置，请稍候。' }); return true; }
    saving = true; let temporary;
    try {
      let size=0; const chunks=[];
      for await (const chunk of req) { size += chunk.length; if (size > 12000) throw new Error('配置内容过长。'); chunks.push(chunk); }
      let input; try { input = JSON.parse(Buffer.concat(chunks).toString()); } catch { throw new Error('配置格式不正确。'); }
      if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('配置格式不正确。');
      const current = getSettings(); let base;
      try { base = normalizeBase(input.apiBase || current.base); } catch { throw new Error('API 地址无效，请使用 HTTPS 地址并包含 /v1。'); }
      const keys = { ...current.keys }; let changed = base !== current.base;
      for (const scene of Object.keys(keyNames)) {
        const value = input.keys?.[scene];
        if (value != null && (typeof value !== 'string' || value.length > 2048 || /[\r\n]/.test(value))) throw new Error('应用 Key 格式不正确。');
        if (typeof value === 'string' && value.trim()) { keys[scene] = value.trim(); changed = true; }
      }
      if (!Object.values(keys).some(Boolean)) throw new Error('请至少填写一个场景的 Dify 应用 API Key。');
      if (!changed) throw new Error('请填写要新增或更新的 Key；留空会保留已有配置。');
      // Validate credentials and the application's expected inputs without uploading documents or invoking a model.
      for (const [scene, key] of Object.entries(keys)) {
        if (!key) continue;
        let response;
        try { response = await fetcher(`${base}/parameters`, { headers: { Authorization: `Bearer ${key}` }, redirect: 'error', signal: AbortSignal.timeout(15000) }); }
        catch { throw new Error(`${labels[scene]}服务连接失败，请检查网络和 API 地址。`); }
        if (!response.ok) throw new Error(`${labels[scene]} Key 验证失败（HTTP ${response.status}），请检查对应工作流的 API 访问设置。`);
        const data = await response.json().catch(()=>null);
        const fields = Array.isArray(data?.user_input_form) ? data.user_input_form.flatMap(item=>Object.values(item).map(field=>field?.variable)) : [];
        if (!requiredInputs[scene].every(field=>fields.includes(field))) throw new Error(`${labels[scene]} Key 对应的工作流字段不匹配，请使用「约定」对应场景的工作流 Key。`);
      }
      const saved = { DIFY_API_BASE: base };
      for (const [scene,name] of Object.entries(keyNames)) if (keys[scene]) saved[name]=keys[scene];
      temporary = `${path}.${randomUUID()}.tmp`;
      await writeFile(temporary, JSON.stringify(saved,null,2)+'\n', { mode: 0o600, flag: 'wx' });
      await rename(temporary,path); temporary=null; applySettings({base,keys});
      respond(200, { ok: true, configured: Object.fromEntries(Object.entries(keys).map(([k,v])=>[k,Boolean(v)])) });
    } catch (err) {
      const message = err.code ? '无法保存本机配置，请检查目录写入权限。' : err.message;
      respond(400,{error:message || '配置失败，请重试。'});
    } finally { if (temporary) await unlink(temporary).catch(()=>{}); saving=false; }
    return true;
  };
}
