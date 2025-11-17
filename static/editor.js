let editor; let currentFile = ""; let currentModel = null; let sse = null;

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }
function fmtBytes(n) { if (n < 1024) return n + " B"; const u = ['KB', 'MB', 'GB']; let i = -1; do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1); return n.toFixed(1) + ' ' + u[i]; }
function ts(x) { const d = new Date(x * 1000); return d.toLocaleString(); }
async function api(path, opts) { const r = await fetch(path, opts); if (!r.ok) { const t = await r.text(); throw new Error(t || r.statusText); } return r.json(); }

// 归一化选择的名字/路径为 *.MyGICA.toml
function normalizeMyGicaName(input) {
  if (!input) return "";
  const p = String(input).trim();
  if (p.toLowerCase().endsWith(".mygica.toml")) return p;
  if (p.toLowerCase().endsWith(".toml")) return p.replace(/\.toml$/i, ".MyGICA.toml");
  return p + ".MyGICA.toml";
}

function initTabs() {
  $all('.tab').forEach(btn => btn.addEventListener('click', () => {
    $all('.tab').forEach(b => b.classList.remove('active'));
    $all('.tabpane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $('#tab-' + btn.dataset.tab).classList.add('active');
  }));
}

function drawTimeline(model) {
  const canvas = $('#timeline'); if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.clientWidth; const H = canvas.height; canvas.width = W;
  ctx.clearRect(0, 0, W, H);
  if (!model || !model.project || !model.ranges) return;

  const fps = Number(model.project.fps_float || 0);
  const ranges = model.ranges.filter(r => Number.isFinite(r.start) && Number.isFinite(r.end));
  if (!ranges.length) return;

  const minStart = Math.min(...ranges.map(r => r.start));
  const maxEnd = Math.max(...ranges.map(r => r.end));
  const span = Math.max(1, maxEnd - minStart);
  const palette = ['#4f46e5', '#059669', '#ea580c', '#dc2626', '#0891b2', '#7c3aed'];

  ranges.forEach((r, i) => {
    const x = ((r.start - minStart) / span) * W;
    const w = ((r.end - r.start) / span) * W;
    ctx.fillStyle = palette[i % palette.length];
    ctx.fillRect(x, 20, Math.max(2, w), 50);
  });

  ctx.fillStyle = '#666';
  const label = fps > 0
    ? `frames ${minStart} ~ ${maxEnd}  ·  ${(span / fps).toFixed(2)}s`
    : `frames ${minStart} ~ ${maxEnd}`;
  ctx.fillText(label, 8, 14);
}

async function refreshList() {
  const items = await api('/project/list');
  const sel = $('#fileSelect'); sel.innerHTML = '';
  items.forEach(it => {
    const opt = document.createElement('option');
    opt.value = it.name; opt.textContent = it.name + '  ·  ' + ts(it.mtime);
    sel.appendChild(opt);
  });
  if (items[0]) sel.value = items[0].name;
}

async function loadFile() {
  // 对选择名做归一化，并回写下拉，保证一致性
  let name = $('#fileSelect').value; if (!name) return;
  name = normalizeMyGicaName(name);
  $('#fileSelect').value = name;
  const { text } = await api('/project/load?file=' + encodeURIComponent(name));
  currentFile = name; editor.setValue(text); parseNow(); outputsList();
}

async function saveFile() {
  if (!currentFile) return alert('未选择文件');
  const text = editor.getValue();
  try {
    const res = await api('/project/save?file=' + encodeURIComponent(currentFile), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text })
    });
    if (res.parsed === false) {
      log(`保存成功，但存在语义问题：${(res.errors || []).map(e => e.message).join('; ')}`, true);
    } else {
      log(`保存成功: ${currentFile}`);
    }
  } catch (e) {
    log('保存失败: ' + e.message, true);
  }
}

async function parseNow() {
  const text = editor.getValue();
  try {
    const { ok, errors, model } = await api('/project/parse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    currentModel = model || null;
    if (model) {
      $('#projectView').textContent = JSON.stringify(model.project || {}, null, 2);
      $('#sourcesView').textContent = JSON.stringify(model.sources || {}, null, 2);
      $('#colorsView').textContent = JSON.stringify(model.colors || {}, null, 2);
      renderRanges(model);
      drawTimeline(model);
    }
    if (errors && errors.length) {
      log('提示: ' + errors.map(e => e.message).join('; '), true);
    }
  } catch (e) { log('解析失败: ' + e.message, true); }
}

function renderRanges(model) {
  const box = $('#rangesList'); box.innerHTML = '';
  const lst = (model && Array.isArray(model.ranges)) ? model.ranges : [];
  lst.forEach(r => {
    const el = document.createElement('div');
    el.className = 'row';
    el.innerHTML = `<span class="badge">#${r.id ?? ''}</span> start=${r.start} · end=${r.end} · clips=${(r.clips || []).length}`;
    box.appendChild(el);
  });
}

function log(msg, isErr) {
  const c = $('#console');
  const line = document.createElement('div');
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  if (isErr) line.classList.add('err');
  c.appendChild(line); c.scrollTop = c.scrollHeight;
}

async function build() {
  // 容错——没点“加载”也能直接构建
  let name = currentFile || $('#fileSelect').value;
  if (!name) return alert('未选择文件');
  name = normalizeMyGicaName(name);
  // 将 currentFile 与下拉保持一致，便于 saveFile 使用
  currentFile = name;
  $('#fileSelect').value = name;

  // 构建前自动保存编辑器内容（避免改了没存）
  try { await saveFile(); } catch { /* 忽略保存报错，后面仍尝试构建 */ }

  if (sse) { try { sse.close(); } catch { } }
  const r = await api('/build/full', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file: name })      // 明确传规范化后的文件名
  });
  log('开始构建: ' + r.cmd);
  const ev = new EventSource('/logs/stream?job_id=' + encodeURIComponent(r.job_id));
  sse = ev;
  ev.onmessage = (e) => {
    try {
      const obj = JSON.parse(e.data);
      if (obj.type === 'log') {
        const tag = obj.tag === 'stderr' ? '⚠' : '·';
        log(`${tag} ${obj.line}`, obj.tag === 'stderr');
      }
    } catch { }
  };
  ev.addEventListener('done', async (e) => {
    const data = JSON.parse(e.data);
    log('构建结束，返回码=' + data.returncode + '，耗时=' + data.took_ms + 'ms');
    ev.close(); outputsList();
  });
  ev.onerror = () => { log('日志流中断', true); ev.close(); };
}

async function outputsList() {
  const list = await api('/outputs');
  const box = $('#outputsList'); box.innerHTML = '';
  list.forEach(it => {
    const card = document.createElement('div'); card.className = 'card';
    card.innerHTML = `<div class="meta">
      <div><strong>${it.name}</strong></div>
      <div>${ts(it.mtime)} · ${fmtBytes(it.size)}</div>
    </div>
    <video controls preload="metadata" src="/outputs/${encodeURIComponent(it.name)}"></video>`;
    box.appendChild(card);
  });
}

function setupMonaco() {
  require(['vs/editor/editor.main'], function () {
    editor = monaco.editor.create(document.getElementById('editor'), {
      value: '# 请选择右上角文件并点击“加载”\n', language: 'ini', theme: 'vs-dark', automaticLayout: true,
      minimap: { enabled: false }, fontSize: 14
    });
    editor.onDidChangeModelContent(() => { if (window._pt) clearTimeout(window._pt); window._pt = setTimeout(parseNow, 500); });
  });
}

function bindUI() {
  $('#btnLoad').addEventListener('click', loadFile);
  $('#btnSave').addEventListener('click', saveFile);
  $('#btnValidate').addEventListener('click', parseNow);
  $('#btnBuild').addEventListener('click', build);

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveFile(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); build(); }
    if (e.key === 'Enter' && document.activeElement === $('#fileSelect')) { e.preventDefault(); loadFile(); }
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  initTabs(); setupMonaco(); bindUI(); await refreshList(); outputsList();
  $('#rootHint').textContent = ' · Localhost 服务已就绪';
});