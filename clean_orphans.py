# clean_orphans.py
import json
from pathlib import Path
from typing import Set

CACHE_DIR_NAME = "cache_dir"
UPLOAD_DIR_NAME = "user_uploads"
VIS_SOURCE_JSON = "vis_source.json"

def _abs(p: Path) -> Path: return p.resolve()

def load_refs(root: Path) -> Set[Path]:
    js = root / VIS_SOURCE_JSON
    if not js.exists(): return set()
    try:
        data = json.loads(js.read_text(encoding="utf-8"))
    except Exception:
        return set()
    refs: Set[Path] = set()

    def push(s: str):
        s = s.strip()
        if not s: return
        if s.startswith("http://") or s.startswith("https://"): return
        if s.startswith("/media/"):
            refs.add(_abs(root/UPLOAD_DIR_NAME/s.split("/media/",1)[1])); return
        p = Path(s)
        if not p.is_absolute(): p = root/p
        refs.add(_abs(p))

    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, str): push(v)
            elif isinstance(v, dict):
                if v.get("path"): push(v["path"])
                elif v.get("url"): push(v["url"])
    return refs

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--dry", action="store_true", help="dry-run")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    cache_dir = root / CACHE_DIR_NAME
    upload_dir = root / UPLOAD_DIR_NAME
    refs = load_refs(root)

    cache_files = [p for p in cache_dir.rglob("*") if p.is_file() and p.name!=".gitkeep"]
    orphans = [p for p in upload_dir.rglob("*") if p.is_file() and _abs(p) not in refs]

    print(f"[preview] cache files: {len(cache_files)}, upload orphans: {len(orphans)}")
    if args.dry:
        for p in cache_files: print("DEL cache:", p)
        for p in orphans: print("DEL upload:", p)
        return

    for p in cache_files + orphans:
        try: p.unlink(missing_ok=True)
        except Exception as e: print("fail:", p, e)

    # 清理空目录
    for top in [cache_dir, upload_dir]:
        if not top.exists(): continue
        for d in sorted([x for x in top.rglob("*") if x.is_dir()], key=lambda x: len(str(x)), reverse=True):
            try:
                next(iter(d.iterdir()))
            except StopIteration:
                try: d.rmdir()
                except Exception: pass

    print("[done] cleaned.")

if __name__ == "__main__":
    main()
