import { readSSE } from './sse.mjs';
const $ = selector => document.querySelector(selector);
const apiBase = document.querySelector('meta[name="yueding-api-base"]').content.replace(/\/$/, '');
const info = {
  rental: { placeholder: '例如：我想在墙上打两个孔装书架，需要先取得同意吗？', context: '房东已有回复或你的入住安排', questions: ['退租时押金怎么扣？', '墙上打孔前需要确认什么？', '自己打扫后还要付清洁费吗？'] },
  employment: { placeholder: '例如：HR 说总包 80 万，合同中哪些部分已经写清楚了？', context: '招聘方口头或聊天中的承诺', questions: ['年终奖的发放条件写清楚了吗？', '离职时还没归属的期权怎么办？', '哪些收入是固定的？'] },
  privacy: { placeholder: '例如：我只浏览内容，可以拒绝通讯录和精确位置吗？', context: '应用请求的权限和你的使用目的', questions: ['可以拒绝通讯录权限吗？', '协议说会与谁共享信息？', '注销后数据会怎么处理？'] },
};
const state = { scene: 'rental', config: null, busy: false, file: null, answer: '', controller: null, previewURL: null };

const escape = text => String(text).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inline = text => escape(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
// The upstream answer is untrusted. Only escaped text and a small set of formatting tags are emitted.
function markdown(text) {
  const lines = text.replace(/\r/g, '').split('\n'); let html = ''; let list = false;
  const close = () => { if (list) { html += '</ul>'; list = false; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) { close(); continue; }
    if (line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
      close(); const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(x => x.trim());
      html += '<div class="table-scroll"><table><thead><tr>' + cells(line).map(x => `<th>${inline(x)}</th>`).join('') + '</tr></thead><tbody>'; i += 2;
      for (; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) html += '<tr>' + cells(lines[i]).map(x => `<td>${inline(x)}</td>`).join('') + '</tr>';
      i--; html += '</tbody></table></div>'; continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)/);
    if (heading) { close(); const level = Math.min(4, heading[1].length + 1); html += `<h${level}>${inline(heading[2])}</h${level}>`; }
    else if (/^[-*+]\s+/.test(line) || /^\d+[.)]\s+/.test(line)) {
      if (!list) { html += '<ul>'; list = true; } html += `<li>${inline(line.replace(/^(?:[-*+]|\d+[.)])\s+/, ''))}</li>`;
    } else { close(); html += line.startsWith('>') ? `<blockquote>${inline(line.slice(1).trim())}</blockquote>` : /^[-*_]{3,}$/.test(line) ? '<hr>' : `<p>${inline(line)}</p>`; }
  }
  close(); return html;
}

function showError(text) { $('#error').textContent = text; $('#error').hidden = false; }
function availability() {
  const ready = Boolean(state.config?.scenarios[state.scene]);
  $('#submit').disabled = state.busy || !ready;
  $('#service-note').textContent = state.busy ? '正在核对，完成后会显示在右侧。' : ready ? '服务已连接，可以开始核对。' : state.config?.localSetup ? '本机中转已启动。请点击右上角“本机设置”，配置此场景的应用 API Key。' : '分析服务尚未连接。连接后即可提交文件与问题。';
}
function setFile(file) {
  if (state.busy) return;
  if (file && (!/\.(pdf|docx|txt|md)$/i.test(file.name) || !file.size || file.size > 15 * 1024 * 1024)) { showError('请选择非空的 PDF、DOCX、TXT 或 Markdown 文件，大小不超过 15 MB。'); return; }
  if (state.previewURL) URL.revokeObjectURL(state.previewURL); state.previewURL = null;
  state.file = file || null;
  $('#file-label').textContent = file ? file.name : '点击选择，或拖入文件';
  $('#file-detail').textContent = file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 已选择` : 'PDF、DOCX、TXT、Markdown · 最大 15 MB';
  $('#file-actions').hidden = !file; $('#error').hidden = true;
  if (!file) $('#document-file').value = '';
}

function selectScene(scene) {
  if (state.busy) return;
  if (scene !== state.scene) {
    setFile(null); $('#question').value = ''; $('#context').value = '';
    $('#question-count').textContent = '0 / 256';
  }
  state.scene = scene; $('#question').placeholder = info[scene].placeholder;
  $('#context-label').textContent = info[scene].context;
  $('#priority-field').hidden = scene !== 'employment';
  document.querySelectorAll('.scenario').forEach(b => { const current = b.dataset.scene === scene; b.classList.toggle('selected', current); b.setAttribute('aria-pressed', String(current)); });
  $('#suggestions').replaceChildren(...info[scene].questions.map(question => {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = question;
    button.onclick = () => { $('#question').value = question; $('#question').dispatchEvent(new Event('input')); $('#question').focus(); }; return button;
  }));
  // Avoid retaining an answer under a different scenario label.
  state.answer = ''; $('#answer').hidden = true; $('#empty').hidden = false; $('#error').hidden = true; $('#progress').hidden = true;
  $('#copy').disabled = $('#download').disabled = true; $('#result-caption').textContent = '等待你的问题';
  availability();
}

function progress(data) {
  $('#progress-text').textContent = data.message;
  const stages = ['upload', 'extract', 'analyze', 'review']; const index = stages.indexOf(data.stage);
  document.querySelectorAll('[data-stage]').forEach(el => { const i = stages.indexOf(el.dataset.stage); el.classList.toggle('done', i < index); el.classList.toggle('current', i === index); });
}

$('#analysis-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy) return;
  if (!state.file) { showError('请先选择要核对的文件。'); return; }
  if (!$('#question').value.trim()) { showError('请写下你想核对的问题。'); return; }
  if (state.config?.accessCodeRequired && !$('#access-code').value) { showError('请输入演示访问码。'); $('#access-code').focus(); return; }
  const form = new FormData(); form.set('file', state.file); form.set('scenario', state.scene);
  form.set('question', $('#question').value.trim()); form.set('context', $('#context').value.trim()); form.set('priority', $('#priority').value);
  state.busy = true; state.answer = ''; state.controller = new AbortController();
  $('#answer').hidden = true; $('#empty').hidden = true; $('#error').hidden = true; $('#progress').hidden = false; $('#stop').hidden = false;
  $('#copy').disabled = $('#download').disabled = true; $('#result-caption').textContent = '正在核对这份文件';
  document.querySelectorAll('.scenario, #analysis-form input, #analysis-form textarea, #analysis-form select, #suggestions button, #remove-file').forEach(el => el.disabled = true);
  availability(); progress({ stage: 'upload', message: '正在提交文件与问题…' });
  const started = Date.now(); $('#elapsed').textContent = '0 秒';
  const timer = setInterval(() => $('#elapsed').textContent = `${Math.floor((Date.now() - started) / 1000)} 秒`, 1000);
  let complete = false;
  try {
    const response = await fetch(`${apiBase}/api/analyze`, { method: 'POST', headers: $('#access-code').value ? { 'X-Demo-Code': $('#access-code').value } : {}, body: form, signal: state.controller.signal });
    if (!response.ok) { const value = await response.json().catch(() => ({})); throw new Error(value.error || '服务暂时不可用，请稍后重试。'); }
    for await (const event of readSSE(response.body)) {
      if (event.event === 'progress') progress(event.data);
      if (event.event === 'error') throw new Error(event.data.message || '分析未能完成，请重试。');
      if (event.event === 'result') {
        if (typeof event.data.answer !== 'string' || !event.data.answer.trim()) throw new Error('未收到有效回答。');
        state.answer = event.data.answer; $('#answer').innerHTML = markdown(state.answer); $('#answer').hidden = false;
        $('#result-caption').textContent = `核对完成 · ${Math.round((Date.now() - started) / 1000)} 秒`;
        $('#copy').disabled = $('#download').disabled = false; complete = true; break;
      }
    }
    if (!complete) throw new Error('连接已结束，但没有收到完整结果。请重试。');
  } catch (err) {
    showError(state.controller.signal.aborted ? '已停止本次请求。你可以修改问题后重新核对。' : err.message || '网络连接失败，请重试。');
    $('#result-caption').textContent = '本次核对未完成';
  } finally {
    clearInterval(timer); state.busy = false; $('#progress').hidden = true; $('#stop').hidden = true;
    document.querySelectorAll('.scenario, #analysis-form input, #analysis-form textarea, #analysis-form select, #suggestions button, #remove-file').forEach(el => el.disabled = false);
    availability();
  }
});
$('#stop').onclick = () => state.controller?.abort();
$('#question').oninput = () => $('#question-count').textContent = `${$('#question').value.length} / 256`;
document.querySelectorAll('.scenario').forEach(button => button.onclick = () => selectScene(button.dataset.scene));
$('#document-file').onchange = event => setFile(event.target.files[0]);
$('#remove-file').onclick = () => setFile(null);
$('#dropzone').ondragover = event => { event.preventDefault(); if (!state.busy) $('#dropzone').classList.add('drag'); };
$('#dropzone').ondragleave = () => $('#dropzone').classList.remove('drag');
$('#dropzone').ondrop = event => { event.preventDefault(); $('#dropzone').classList.remove('drag'); if (!state.busy) setFile(event.dataTransfer.files[0]); };
$('#preview-file').onclick = async () => {
  if (!state.file) return;
  $('#preview-title').textContent = state.file.name; const holder = $('#preview-body'); holder.replaceChildren();
  if (/\.pdf$/i.test(state.file.name)) {
    if (!state.previewURL) state.previewURL = URL.createObjectURL(state.file);
    const object = document.createElement('object'); object.type = 'application/pdf'; object.data = state.previewURL;
    const fallback = document.createElement('p'); fallback.textContent = '此浏览器不支持内嵌 PDF 预览，可使用本机 PDF 阅读器查看原文。'; object.append(fallback); holder.append(object);
  } else if (/\.(txt|md)$/i.test(state.file.name)) {
    const pre = document.createElement('pre'); pre.textContent = (await state.file.text()).slice(0,60000); holder.append(pre);
  } else { const p = document.createElement('p'); p.textContent = '文件已选择。DOCX 可在 Word 中查看原文，提交后可直接分析。'; holder.append(p); }
  $('#preview').showModal();
};
$('#close-preview').onclick = () => $('#preview').close();
$('#copy').onclick = async () => { try { await navigator.clipboard.writeText(state.answer); $('#result-caption').textContent = '回答已复制'; } catch { showError('浏览器未允许复制，可使用下载按钮保存回答。'); } };
$('#download').onclick = () => { const url = URL.createObjectURL(new Blob([state.answer], { type: 'text/markdown;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = '约定-核对结果.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000); };
selectScene('rental');
try {
  const response = await fetch(`${apiBase}/api/config`, { signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error('config');
  state.config = await response.json(); if (!state.config.scenarios) throw new Error('config');
  $('#access-field').hidden = !state.config.accessCodeRequired;
  $('#local-settings').hidden = !state.config.localSetup;
} catch { state.config = null; }
availability();
