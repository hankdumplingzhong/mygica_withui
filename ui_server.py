import os, sys, re, json, queue, threading, argparse, subprocess, pathlib, time, json
from pathlib import Path
from typing import Dict, Set, Tuple
from datetime import datetime
from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    render_template,
    Response,
    abort,
)
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder="static", template_folder="templates")

# -----------------------
# 配置与安全（仅限 ROOT 内）
# -----------------------
ROOT_DIR: pathlib.Path
ALLOWED_PATTERNS = re.compile(r"^([\w\- .()\[\]]+)$")  # 简单文件名白名单（根目录内）
BUILD_CMD_TEMPLATE = os.environ.get(
    "MYGICA_BUILD", f"{sys.executable} A_compiler.py --config {{file}}"
)

# 运行中任务管理（极简）
JOBS = {}
JOB_ID_COUNTER = 0
JOBS_LOCK = threading.Lock()

CACHE_DIR_NAME = "cache_dir"
UPLOAD_DIR_NAME = "user_uploads"
VIS_SOURCE_JSON = "vis_source.json"

UPLOAD_URL_PREFIXES = ["/media/", "/uploads/"]

def get_upload_dir():
    p = ROOT_DIR / "user_uploads"
    p.mkdir(exist_ok=True)
    return p

def inside_root(name: str) -> pathlib.Path:
    if not name or any(c in name for c in ('/', '\\')):
        abort(400, description="Illegal filename.")
    p = ROOT_DIR / name
    if not p.exists() or not p.is_file():
        abort(404, description="File not found in project root.")
    try:
        p.resolve().relative_to(ROOT_DIR.resolve())
    except Exception:
        abort(403, description="Out of root.")
    return p


@app.route("/")
def home():
    return render_template("home.html")

@app.get("/editor")
def editor():
    return render_template("editor.html")

@app.get("/visedit")
def visedit():
    return render_template("visedit.html")

@app.get("/project/list")
def project_list():
    items = []
    for entry in sorted(ROOT_DIR.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and (
            entry.suffix.lower() == ".toml" or entry.name.endswith(".MyGICA.toml")
        ):
            items.append(
                {
                    "name": entry.name,
                    "mtime": int(entry.stat().st_mtime),
                }
            )
    return jsonify(items)


@app.get("/project/load")
def project_load():
    name = request.args.get("file", "").strip()
    p = inside_root(name)
    text = p.read_text(encoding="utf-8")
    return jsonify({"text": text})


@app.post("/project/save")
def project_save():
    data = request.get_json(force=True)
    name = request.args.get("file", "").strip()
    text = data.get("text", "")
    # 保存时不再强制阻塞；解析仅用于返回提示
    ok, errors, model = parse_toml_safe(text)
    p = inside_root(name)
    p.write_text(text, encoding="utf-8")
    return jsonify({"ok": True, "parsed": ok, "errors": errors})


@app.post("/project/parse")
def project_parse():
    data = request.get_json(force=True)
    text = data.get("text", "")
    ok, errors, model = parse_toml_safe(text)
    return jsonify({"ok": ok, "errors": errors, "model": model})

# --- 可视化编辑器的素材映射存取 ---
@app.get("/vis/sources")
def vis_sources_get():
    p = ROOT_DIR / "vis_sources.json"
    items = {}
    if p.exists():
        try:
            items = json.loads(p.read_text("utf-8"))
            if not isinstance(items, dict):
                items = {}
        except Exception:
            items = {}
    return jsonify({"items": items})

@app.post("/vis/sources")
def vis_sources_post():
    data = request.get_json(force=True)
    items = data.get("items", {})
    if not isinstance(items, dict):
        abort(400, description="items must be an object")
    p = ROOT_DIR / "vis_sources.json"
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")
    return jsonify({"ok": True})

# --- 可视化编辑器的素材映射存取 ---
@app.post("/vis/upload")
def vis_upload():
    """接收单个视频/音频文件并返回可访问URL；并回写 vis_sources.json。"""
    if "file" not in request.files:
        abort(400, description="no file")
    f = request.files["file"]
    key = request.form.get("key", "").strip()
    if not f or not f.filename:
        abort(400, description="empty file")
    if not key:
        abort(400, description="missing key")

    ext = os.path.splitext(f.filename)[1]
    fname = secure_filename(f"{int(time.time()*1000)}_{os.getpid()}" + ext)
    save_path = get_upload_dir() / fname
    f.save(save_path)

    url = f"/uploads/{fname}"

    # 更新 vis_sources.json（兼容老格式 -> 升级为 {path,url}）
    p = ROOT_DIR / "vis_sources.json"
    items = {}
    if p.exists():
        try:
            raw = json.loads(p.read_text("utf-8"))
            if isinstance(raw, dict):
                items = raw
        except Exception:
            items = {}

    old = items.get(key)
    if isinstance(old, str):
        old = {"path": old}
    if not isinstance(old, dict):
        old = {}
    old.update({"path": str(save_path), "url": url})
    items[key] = old

    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")
    return jsonify({"ok": True, "key": key, "url": url, "path": str(save_path)})

@app.get("/uploads/<path:fname>")
def serve_uploads(fname):
    return send_from_directory(get_upload_dir(), fname, conditional=True)

# --- 解析 TOML（宽容：支持顶层 fps / 分数字符串 / 别名字段） ---
try:
    import tomllib  # Python 3.11+
except Exception:
    import tomli as tomllib


def parse_fps(value):
    """把 fps 解析成 float。支持数字、'23.976'、'24000/1001' 这类分数。失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        s = value.strip()
        # 分数 a/b
        if "/" in s:
            try:
                a, b = s.split("/", 1)
                a = float(a.strip())
                b = float(b.strip())
                if b != 0:
                    res = a / b
                    return res if res > 0 else None
            except Exception:
                return None
        # 普通数字字符串
        try:
            res = float(s)
            return res if res > 0 else None
        except Exception:
            return None
    return None


def parse_toml_safe(text: str):
    try:
        data = tomllib.loads(text)
    except Exception as e:
        return False, [{"message": str(e)}], None

    # 兼容：fps 可在顶层或 [project]
    proj = data.get("project", {}) if isinstance(data.get("project", {}), dict) else {}
    fps_raw = proj.get("fps", data.get("fps"))  # 顶层优先也可
    fps_float = parse_fps(fps_raw)

    # suffix 字段别名：project_suffix / suffix（顶层与 [project] 都行）
    suffix_raw = (
        proj.get("suffix", None)
        or data.get("project_suffix", None)
        or data.get("suffix", None)
    )

    model = {
        "project": {
            "fps_raw": fps_raw,  # 原始值（可能是 '24000/1001'）
            "fps_float": fps_float,  # 解析后的浮点
            "start": proj.get("start", data.get("start")),
            "suffix": suffix_raw,
        },
        "sources": data.get("sources", {}),
        "colors": data.get("colors", {}),
        "ranges": [],
        "texts": [],
    }

    # [[ranges]]
    if "ranges" in data and isinstance(data["ranges"], list):
        for i, r in enumerate(data["ranges"]):
            model["ranges"].append(
                {
                    "id": i,
                    "start": r.get("start"),
                    "end": r.get("end"),
                    "clips": r.get("clips", []),
                    "text": r.get("text", {}),
                    "color": r.get("color"),
                }
            )

    if "texts" in data and isinstance(data["texts"], list):
        model["texts"] = data["texts"]

    # 不阻塞：语法过就 ok=True；语义问题以“提示”返回
    warnings = []
    if fps_float is None:
        warnings.append(
            {
                "message": "fps 缺失或无效（支持顶层 fps = '24000/1001' 或 [project].fps）。"
            }
        )

    return True, warnings, model


# -----------------------
# 构建与日志（SSE 流）
# -----------------------


def _next_job_id() -> str:
    global JOB_ID_COUNTER
    with JOBS_LOCK:
        JOB_ID_COUNTER += 1
        return f"job-{JOB_ID_COUNTER}-{int(time.time()*1000)}"


def _reader_thread(proc, q: queue.Queue):
    def pump(stream, tag):
        for raw in iter(stream.readline, b""):
            try:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
            except Exception:
                line = raw.decode(errors="replace").rstrip("\n")
            q.put({"type": "log", "tag": tag, "line": line})

    t1 = threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True)
    t2 = threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()


@app.post("/build/full")
def build_full():
    data = request.get_json(force=True)
    name = (data.get("file") or "").strip()
    p = inside_root(name)

    cmd = BUILD_CMD_TEMPLATE.format(file=p.name)
    env = os.environ.copy()
    # 优先 PYTHONIOENCODING；其次全局 UTF-8 模式（3.7+）
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 在项目根目录下执行（便于 A_compiler 定位资源）
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    jid = _next_job_id()
    q = queue.Queue()

    JOBS[jid] = {"proc": proc, "q": q, "start": time.time(), "cmd": cmd, "output": None}
    threading.Thread(target=_reader_thread, args=(proc, q), daemon=True).start()

    return jsonify({"ok": True, "job_id": jid, "cmd": cmd})


@app.get("/logs/stream")
def logs_stream():
    jid = request.args.get("job_id", "")
    job = JOBS.get(jid)
    if not job:
        abort(404)

    q: queue.Queue = job["q"]
    proc: subprocess.Popen = job["proc"]

    def gen():
        yield "retry: 500\n\n"  # 减少重连频率
        while True:
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    # 进程已结束，发送 done 事件
                    payload = {
                        "returncode": proc.returncode,
                        "took_ms": int((time.time() - job["start"]) * 1000),
                    }
                    yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                    break
                continue
            if item["type"] == "log":
                payload = json.dumps(item)
                yield f"data: {payload}\n\n"

    return Response(gen(), mimetype="text/event-stream")


# -----------------------
# 输出/静态文件
# -----------------------
@app.get("/outputs")
def outputs_list():
    out_dir = ROOT_DIR / "cache_output"
    files = []
    if out_dir.exists():
        for f in sorted(
            out_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".mkv"}:
                files.append(
                    {
                        "name": f.name,
                        "mtime": int(f.stat().st_mtime),
                        "size": f.stat().st_size,
                    }
                )
    return jsonify(files)


@app.get("/outputs/<path:fname>")
def outputs_get(fname):
    # 只允许从 cache_output 取文件
    base = ROOT_DIR / "cache_output"
    try:
        (base / fname).resolve().relative_to(base.resolve())
    except Exception:
        abort(403)
    return send_from_directory(base, fname, as_attachment=False)

def _abs(p: Path) -> Path:
    try:
        return p.resolve(strict=False)
    except Exception:
        return Path(str(p)).resolve(strict=False)

def _load_vis_sources(root: Path) -> Dict:
    js_path = root / VIS_SOURCE_JSON
    if not js_path.exists():
        return {}
    try:
        with open(js_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        print(f"[cleanup] fail to read {js_path}: {e}")
        return {}

def _collect_referenced_paths(root: Path) -> Set[Path]:
    """
    收集 vis_source.json 中的被引用本地文件，统一转为绝对路径。
    支持两种结构：
      "key": "path_or_url"
      "key": {"path": "...", "url": "..."}
    URL 允许以 /media/ 或 /uploads/ 开头，映射到 user_uploads/ 下对应相对路径。
    """
    data = _load_vis_sources(root)
    refs: Set[Path] = set()
    upload_dir = _abs(root / UPLOAD_DIR_NAME)

    def push_path_like(s: str):
        s = (s or "").strip()
        if not s:
            return
        # 远程 URL 跳过
        if s.startswith("http://") or s.startswith("https://"):
            return
        # 以已知前缀的站内 URL => 映射到 user_uploads/
        for prefix in UPLOAD_URL_PREFIXES:
            if s.startswith(prefix):
                rel = s.split(prefix, 1)[1]
                refs.add(_abs(upload_dir / rel))
                return
        # 其他：按文件路径解析（支持相对/绝对，Windows 反斜杠都可）
        p = Path(s)
        if not p.is_absolute():
            p = root / p
        refs.add(_abs(p))

    if isinstance(data, dict):
        for _, v in data.items():
            if isinstance(v, str):
                push_path_like(v)
            elif isinstance(v, dict):
                # 优先 path，其次 url
                if "path" in v and v["path"]:
                    push_path_like(v["path"])
                if "url" in v and v["url"]:
                    push_path_like(v["url"])

    return refs

def _scan_targets(root: Path) -> Tuple[Path, Path, Set[Path], Set[Path]]:
    cache_dir = root / CACHE_DIR_NAME
    upload_dir = root / UPLOAD_DIR_NAME
    ref_paths = _collect_referenced_paths(root)
    return cache_dir, upload_dir, ref_paths, set()

def _list_cache_to_delete(cache_dir: Path) -> Set[Path]:
    to_del = set()
    if cache_dir.exists():
        for p in cache_dir.rglob("*"):
            if p.is_file():
                if p.name in (".gitkeep",) or p.name.startswith("."):
                    continue
                to_del.add(_abs(p))
    return to_del

def _list_orphan_uploads(upload_dir: Path, ref_paths: Set[Path], root: Path) -> Set[Path]:
    """在严格绝对路径比对之外，增加一个“文件名兜底”以避免误删。"""
    orphans = set()
    if not upload_dir.exists():
        return orphans

    # 兜底集合：已引用的文件名（大小写不敏感，兼容 Windows）
    ref_basenames = {p.name.lower() for p in ref_paths}

    for p in upload_dir.rglob("*"):
        if not p.is_file():
            continue
        ap = _abs(p)
        # 严格：绝对路径命中
        if ap in ref_paths:
            continue
        # 兜底：同名即保留（避免 URL 与 path 指向同一文件却写法不同）
        if ap.name.lower() in ref_basenames:
            continue
        orphans.add(ap)
    return orphans

def _delete_files(files: Set[Path], min_age_seconds: int = 600) -> int:
    now = time.time()
    cnt = 0
    for f in sorted(files, key=lambda x: len(str(x)), reverse=True):
        try:
            if f.is_file():
                # 过新就跳过
                if now - f.stat().st_mtime < min_age_seconds:
                    continue
                f.unlink(missing_ok=True)
                cnt += 1
        except Exception as e:
            print(f"[cleanup] fail to delete file {f}: {e}")
    return cnt

def _delete_empty_dirs(root: Path) -> int:
    """从深到浅删除空目录（只影响 cache_dir/user_uploads 下的空目录）。"""
    removed = 0
    for top in [root / CACHE_DIR_NAME, root / UPLOAD_DIR_NAME]:
        if not top.exists():
            continue
        # 深度优先：先删除深层空目录
        for d in sorted([p for p in top.rglob("*") if p.is_dir()], key=lambda x: len(str(x)), reverse=True):
            try:
                # 只删完全空目录
                next(iter(d.iterdir()))
            except StopIteration:
                try:
                    d.rmdir()
                    removed += 1
                except Exception:
                    pass
    return removed

@app.get("/maintenance/preview_cleanup")
def preview_cleanup():
    root = Path(globals().get("ROOT_DIR", Path.cwd()))
    cache_dir, upload_dir, ref_paths, _ = _scan_targets(root)
    cache_files = _list_cache_to_delete(cache_dir)
    upload_orphans = _list_orphan_uploads(upload_dir, ref_paths, root)
    return jsonify({
        "root": str(root),
        "cache_dir": str(cache_dir),
        "upload_dir": str(upload_dir),
        "referenced_count": len(ref_paths),
        "delete_candidates": {
            "cache_files": [str(p) for p in sorted(cache_files)],
            "upload_orphans": [str(p) for p in sorted(upload_orphans)],
        },
        "tips": "POST /maintenance/cleanup 执行清理；传 {\"dry_run\": true} 可做一次干跑"
    })

@app.post("/maintenance/cleanup")
def do_cleanup():
    root = Path(globals().get("ROOT_DIR", Path.cwd()))
    body = request.get_json(silent=True) or {}
    dry = bool(body.get("dry_run", False))

    cache_dir, upload_dir, ref_paths, _ = _scan_targets(root)
    cache_files = _list_cache_to_delete(cache_dir)
    upload_orphans = _list_orphan_uploads(upload_dir, ref_paths, root)

    if dry:
        return jsonify({
            "dry_run": True,
            "will_delete": {
                "cache_files": len(cache_files),
                "upload_orphans": len(upload_orphans),
            }
        })

    n1 = _delete_files(cache_files)
    n2 = _delete_files(upload_orphans)
    n3 = _delete_empty_dirs(root)

    return jsonify({
        "dry_run": False,
        "deleted": {
            "cache_files": n1,
            "upload_orphans": n2,
            "empty_dirs": n3
        }
    })
# ===== end Maintenance =====

# -----------------------
# 启动入口
# -----------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Project root directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()

    ROOT_DIR = pathlib.Path(args.root).resolve()
    if not ROOT_DIR.exists():
        print("Root does not exist:", ROOT_DIR)
        sys.exit(2)

    print("Project root:", ROOT_DIR)
    print("Build command template:", BUILD_CMD_TEMPLATE)
    # 开发时可加 threaded=True，生产建议用 WSGI
    app.run(host=args.host, port=args.port, debug=True, threaded=True)
