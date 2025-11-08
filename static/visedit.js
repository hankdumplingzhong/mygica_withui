const $ = s => document.querySelector(s);
const api = async (p, o) => { const r = await fetch(p, o); if (!r.ok) throw new Error(await r.text()); return r.json(); };

// 兼容两种 items 结构：string 或 {path,url}
function normalizeItem(v) {
    if (typeof v === 'string') return { path: v, url: undefined };
    if (v && typeof v === 'object') return { path: v.path || '', url: v.url || undefined };
    return { path: '', url: undefined };
}

let SOURCES = {};       // 键名 -> 本地路径/URL
let CLIPS = [];         // {source, start, end, volume?}

function log(x, isErr) { const c = $('#log'); const div = document.createElement('div'); div.textContent = `[${new Date().toLocaleTimeString()}] ${x}`; if (isErr) div.classList.add('err'); c.appendChild(div); c.scrollTop = c.scrollHeight; }

function renderSources() {
    const box = $('#sourcesList'); box.innerHTML = '';
    const keys = Object.keys(SOURCES).sort();
    keys.forEach(k => {
        const row = document.createElement('div'); row.className = 'row';
        const v = SOURCES[k];
        const pathTxt = (typeof v === 'object') ? (v.path || '') : v;
        const urlTxt = (typeof v === 'object' && v.url) ? ` · <a href="${v.url}" target="_blank">URL</a>` : '';
        row.innerHTML = `<strong>${k}</strong> → <span style="opacity:.8">${pathTxt}</span>${urlTxt}
      <button data-k="${k}" style="float:right">删除</button>`;
        row.querySelector('button').onclick = () => { delete SOURCES[k]; renderSources(); renderSrcSelect(); renderPreviewSelect(); renderPreviewSelect(); };
        box.appendChild(row);
    });
}

function renderSrcSelect() {
    const sel1 = document.querySelector('#clipSource');
    const sel2 = document.querySelector('#previewSource');
    [sel1, sel2].forEach(sel => { if (sel) sel.innerHTML = ''; });
    Object.keys(SOURCES).sort().forEach(k => {
        [sel1, sel2].forEach(sel => {
            if (!sel) return;
            const opt = document.createElement('option');
            opt.value = k; opt.textContent = k;
            sel.appendChild(opt);
        });
    });
}

function renderClips() {
    const box = $('#clipsList'); box.innerHTML = '';
    CLIPS.forEach((c, idx) => {
        const row = document.createElement('div'); row.className = 'row';
        row.innerHTML = `#${idx + 1} · source=${c.source} · start=${c.start} · end=${c.end}` + (Number.isFinite(c.volume) ? ` · volume=${c.volume}dB` : '') +
            `<button data-i="${idx}" style="float:right">移除</button>`;
        row.querySelector('button').onclick = () => { CLIPS.splice(idx, 1); renderClips(); };
        box.appendChild(row);
    });
}

function parseFPS(str) {
    const s = String(str || '').trim();
    if (!s) return null;
    if (s.includes('/')) { const [a, b] = s.split('/').map(Number); if (a > 0 && b > 0) return a / b; return null; }
    const f = Number(s); return f > 0 ? f : null;
}

async function loadSources() {
    try {
        const { items } = await api('/vis/sources');
        const out = {};
        Object.entries(items || {}).forEach(([k, v]) => out[k] = normalizeItem(v));
        SOURCES = out;
        renderSources(); renderSrcSelect(); renderPreviewSelect();
        log('已加载素材映射');
    } catch (e) { log('加载素材映射失败: ' + e.message, true); }
}
async function saveSources() {
    try {
        await api('/vis/sources', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: SOURCES }) });
        log('已保存素材映射');
    } catch (e) { log('保存素材映射失败: ' + e.message, true); }
}

function bind() {
    $('#btnAddSrc').onclick = () => {
        const k = $('#srcKey').value.trim(); const p = $('#srcPath').value.trim();
        if (!k || !p) return;
        SOURCES[k] = p; renderSources(); renderSrcSelect(); renderPreviewSelect();
        $('#srcKey').value = ''; $('#srcPath').value = '';
    };
    $('#btnSaveSources').onclick = saveSources;
    $('#btnReloadSources').onclick = loadSources;

    const upBtn = $('#btnUploadBind'); if (upBtn) upBtn.onclick = uploadAndBind;

    $('#btnAddClip').onclick = () => {
        const source = $('#clipSource').value;
        const start = Number($('#clipStart').value);
        const end = Number($('#clipEnd').value);
        const volRaw = $('#clipVolume').value.trim();
        const volume = volRaw === '' ? undefined : Number(volRaw);
        if (!(source && Number.isFinite(start) && Number.isFinite(end) && end > start)) {
            return log('Clip 参数不合法', true);
        }
        if (Number.isFinite(volume) && (volume < -50 || volume > 0)) return log('volume 合法范围 -50~0', true);
        CLIPS.push({ source, start, end, ...(Number.isFinite(volume) ? { volume } : {}) });
        renderClips();
        $('#clipStart').value = ''; $('#clipEnd').value = ''; $('#clipVolume').value = '';
    };

    $('#btnGen').onclick = genToml;

    bindPreview();
}

document.addEventListener('DOMContentLoaded', () => { bind(); loadSources(); bindPreviewButtons();bindTomlButtons();});


function renderPreviewSelect() {
    const sel = $('#previewSource'); if (!sel) return;
    sel.innerHTML = '';
    Object.keys(SOURCES).sort().forEach(k => {
        const opt = document.createElement('option'); opt.value = k; opt.textContent = k; sel.appendChild(opt);
    });
}


async function uploadAndBind() {
  const key = $('#bindKey').value.trim();
  const fileEl = $('#filePicker');
  if (!key || !fileEl.files || !fileEl.files[0]) {
    return log('请选择文件并填键名', true);
  }
  const fd = new FormData();
  fd.append('key', key);
  fd.append('file', fileEl.files[0]);
  try {
    const res = await api('/vis/upload', { method: 'POST', body: fd });
    // 兼容 string 与 {path,url}
    const cur = SOURCES[key] || { path: '', url: undefined };
    SOURCES[key] = { path: res.path || cur.path, url: res.url || cur.url };
    renderSources(); renderSrcSelect(); renderPreviewSelect();
    $('#bindKey').value = ''; fileEl.value = '';
    log(`已上传并绑定：${key}`);
  } catch (e) {
    log('上传失败：' + e.message, true);
  }
}

function timeToFrames(t, fps) { return Math.round(Number(t) * fps); }

function bindPreview() {
    const loadBtn = $('#btnLoadPreview'); if (loadBtn) {
        loadBtn.onclick = () => {
            const key = $('#previewSource').value;
            const v = SOURCES[key];
            if (!v || !v.url) { log('该素材尚无可访问 URL，请先上传或提供 URL。', true); return; }
            const video = $('#previewPlayer'); video.src = v.url;
            video.play().catch(() => { });
        };
    }
    const markStart = $('#btnMarkStart'); if (markStart) {
        markStart.onclick = () => {
            const video = $('#previewPlayer'); const fps = parseFPS($('#fpsInput').value) || 24;
            const f = timeToFrames(video.currentTime, fps);
            $('#clipStart').value = String(f);
            $('#previewInfo').textContent = `Start = ${f}帧（${video.currentTime.toFixed(3)}s）`;
        };
    }
    const markEnd = $('#btnMarkEnd'); if (markEnd) {
        markEnd.onclick = () => {
            const video = $('#previewPlayer'); const fps = parseFPS($('#fpsInput').value) || 24;
            const f = timeToFrames(video.currentTime, fps);
            $('#clipEnd').value = String(f);
            $('#previewInfo').textContent = `End = ${f}帧（${video.currentTime.toFixed(3)}s）`;
        };
    }
}

// 载入预览：你原来已有 registerAndPreview(path) 或直接使用已上传的 URL
async function loadPreviewForKey(key) {
  const raw = SOURCES[key];
  if (!raw) return log(`未找到 ${key} 的路径/URL`, true);

  // 统一出 path/url 字段
  const item = (typeof raw === 'object') ? raw : { path: raw, url: undefined };
  let url = item.url;

  if (!url) {
    const candidate = item.path || '';
    if (!candidate) return log('该素材尚无可访问 URL，请先上传或提供 URL。', true);

    // 已是可访问 URL 直接用；否则请求后端注册成 /media/… 可访问
    if (/^https?:|^\/media\//.test(candidate)) {
      url = candidate;
    } else {
      try {
        const resp = await api('/vis/register_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: candidate })
        });
        url = resp.url;
        // 回写 url，避免重复注册
        SOURCES[key] = { path: candidate, url };
        renderSources(); // 让“· URL”链接也出现
      } catch (e) {
        return log(`注册URL失败：${e.message}`, true);
      }
    }
  }

  const v = document.querySelector('#preview');
  v.src = url;
  try { await v.play(); } catch (_) {}
  log(`已载入预览：${key}`);
}


// 绑定按钮
function bindPreviewButtons() {
    const sel = document.querySelector('#previewSource');
    document.querySelector('#btnLoadPreview').onclick = () => {
        if (!sel.value) return log('请选择要预览的素材键名', true);
        loadPreviewForKey(sel.value);
    };

    // 用当前时间标记 clip start/end
    const v = document.querySelector('#preview');
    const fpsVal = () => parseFPS(document.querySelector('#fpsInput').value) || 24;
    document.querySelector('#btnMarkStart').onclick = () => {
        const f = Math.round(v.currentTime * fpsVal());
        document.querySelector('#clipStart').value = f;
        log(`已标记 Clip Start = ${f} 帧`);
    };
    document.querySelector('#btnMarkEnd').onclick = () => {
        const f = Math.round(v.currentTime * fpsVal());
        document.querySelector('#clipEnd').value = f;
        log(`已标记 Clip End = ${f} 帧`);
    };
}

// 生成 TOML 后显示在右栏
function genToml() {
    const rs = Number(document.querySelector('#rangeStart').value);
    const re = Number(document.querySelector('#rangeEnd').value);
    if (!(Number.isFinite(rs) && Number.isFinite(re) && re > rs)) { log('Range 起止不合法', true); return; }
    if (!CLIPS.length) { log('请添加至少一个 clip', true); return; }

    const lines = [];
    lines.push('[[ranges]]');
    lines.push(`start = ${rs}`);
    lines.push(`end = ${re}`);
    CLIPS.forEach(c => {
        lines.push('[[ranges.clips]]');
        lines.push(`source = '${c.source}'`);
        if (Number.isFinite(c.start)) lines.push(`start = ${c.start}`);
        if (Number.isFinite(c.end)) lines.push(`end = ${c.end}`);
        if (Number.isFinite(c.volume)) lines.push(`volume = ${c.volume}`);
        lines.push('');
    });

    const out = document.querySelector('#tomlOut');
    out.textContent = lines.join('\n');
    out.scrollTop = out.scrollHeight;
    log('已生成 TOML 片段');
}

// 复制/清空 TOML
function bindTomlButtons() {
    document.querySelector('#btnCopyToml').onclick = async () => {
        const s = document.querySelector('#tomlOut').textContent || '';
        if (!s.trim()) { log('无可复制内容', true); return; }
        await navigator.clipboard.writeText(s);
        log('已复制到剪贴板');
    };
    document.querySelector('#btnClearToml').onclick = () => {
        document.querySelector('#tomlOut').textContent = '';
    };
}
