const $ = selector => document.querySelector(selector);
const scenes = ['rental', 'employment', 'privacy'];
let token;
function showConfigured(configured) {
  for (const scene of scenes) $(`#${scene}-state`).textContent = configured[scene] ? '已配置 · 留空保留' : '尚未配置';
}
try {
  const response = await fetch('/api/local-settings', { signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error('请通过本机启动器打开设置页。该入口仅对本机开放。');
  const data = await response.json(); token = data.token; $('#api-base').value = data.apiBase;
  showConfigured(data.configured); $('#save').disabled = false;
  $('#setup-status').textContent = '填入对应场景的 Key，然后验证并保存。';
} catch (err) { $('#setup-status').textContent = err.message; }
$('#setup-form').addEventListener('submit', async event => {
  event.preventDefault(); $('#save').disabled = true; $('#setup-error').hidden = true;
  $('#setup-status').textContent = '正在验证 Key 和工作流字段，请稍候…';
  try {
    const response = await fetch('/api/local-settings', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Local-Setup-Token': token },
      body: JSON.stringify({ apiBase: $('#api-base').value.trim(), keys: Object.fromEntries(scenes.map(scene => [scene, $(`#${scene}`).value])) }), signal: AbortSignal.timeout(60000) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '保存失败，请重试。');
    for (const scene of scenes) $(`#${scene}`).value = '';
    showConfigured(data.configured);
    $('#setup-status').textContent = '验证成功，已保存在本机。点击“进入体验”即可上传文件和提问。';
  } catch (err) {
    $('#setup-error').textContent = err.name === 'TimeoutError' ? '验证等待超时，请检查网络后重试。' : err.message;
    $('#setup-error').hidden = false; $('#setup-status').textContent = '配置未完成。';
  } finally { $('#save').disabled = false; }
});
