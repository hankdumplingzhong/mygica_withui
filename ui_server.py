import os, sys, re, json, queue, threading, argparse, subprocess, pathlib, time
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
    return render_template("index.html")


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
