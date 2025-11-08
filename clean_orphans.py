from __future__ import annotations

import json
from pathlib import Path
from loguru import logger

CACHE_DIR_NAME: str = "cache_dir"
UPLOAD_DIR_NAME: str = "user_uploads"
VIS_SOURCE_JSON: str = "vis_source.json"
SITE_URL_PREFIXES: list[str] = ["/media/", "/uploads/"]


def _abs(p: Path) -> Path:
    """统一获得绝对路径（不要求真实存在）。"""
    return p.resolve(strict=False)


def _load_vis_sources(root: Path) -> dict:
    """读取 vis_source.json；解析失败时返回空 dict（异常归类为真正异常而非逻辑分支）。"""
    js: Path = root / VIS_SOURCE_JSON
    if not js.exists():
        return {}
    text: str = js.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # 异常：数据损坏，输出日志后按空处理
        logger.error(f"解析 {js} 失败：{e}")
        return {}
    return data if isinstance(data, dict) else {}


def _collect_referenced_paths(root: Path) -> set[Path]:
    """收集所有被引用的本地文件绝对路径（URL 前缀映射到 user_uploads）。"""
    data: dict = _load_vis_sources(root)
    refs: set[Path] = set()
    upload_dir: Path = _abs(root / UPLOAD_DIR_NAME)

    def push_path_like(s: str) -> None:
        s = (s or "").strip()
        if not s:
            return
        if s.startswith("http://") or s.startswith("https://"):
            return
        for prefix in SITE_URL_PREFIXES:
            if s.startswith(prefix):
                rel = s.split(prefix, 1)[1]
                refs.add(_abs(upload_dir / rel))
                return
        p = Path(s)
        if not p.is_absolute():
            p = root / p
        refs.add(_abs(p))

    for v in data.values():
        if isinstance(v, str):
            push_path_like(v)
        elif isinstance(v, dict):
            if v.get("path"):
                push_path_like(str(v["path"]))
            if v.get("url"):
                push_path_like(str(v["url"]))

    return refs


def _list_cache_targets(cache_dir: Path) -> set[Path]:
    """列出 cache_dir 中可删的文件候选。"""
    if not cache_dir.exists():
        return set()
    out: set[Path] = set()
    for p in cache_dir.rglob("*"):
        if p.is_file() and p.name != ".gitkeep" and not p.name.startswith("."):
            out.add(_abs(p))
    return out


def _list_upload_orphans(upload_dir: Path, refs: set[Path]) -> set[Path]:
    """列出 user_uploads 下未被引用的孤儿文件（增加同名兜底：同名则保留）。"""
    if not upload_dir.exists():
        return set()
    ref_names: set[str] = {p.name.lower() for p in refs}
    out: set[Path] = set()
    for p in upload_dir.rglob("*"):
        if not p.is_file():
            continue
        ap = _abs(p)
        if ap in refs:
            continue
        if ap.name.lower() in ref_names:
            continue
        out.add(ap)
    return out


def _delete_files(paths: set[Path]) -> int:
    """删除文件；失败属于异常情况，记录日志。"""
    cnt: int = 0
    for f in sorted(paths, key=lambda x: len(str(x)), reverse=True):
        if f.is_file():
            try:
                f.unlink(missing_ok=True)
                cnt += 1
            except Exception as e:  # 异常：不可删除
                logger.warning(f"删除失败：{f} - {e}")
    return cnt


def _delete_empty_dirs(root: Path) -> int:
    """从深到浅删除空目录（仅清理 cache_dir 与 user_uploads）。"""
    removed: int = 0
    for top in [root / CACHE_DIR_NAME, root / UPLOAD_DIR_NAME]:
        if not top.exists():
            continue
        # 深度优先
        for d in sorted((x for x in top.rglob("*") if x.is_dir()), key=lambda x: len(str(x)), reverse=True):
            try:
                next(iter(d.iterdir()))
            except StopIteration:
                try:
                    d.rmdir()
                    removed += 1
                except Exception as e:  # 异常：权限/占用
                    logger.debug(f"移除空目录失败：{d} - {e}")
    return removed


def main() -> None:
    """命令行入口：--root 指定根目录，--dry 预览。"""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--dry", action="store_true", help="仅预览不执行删除")
    args = ap.parse_args()

    root: Path = Path(args.root).resolve()
    cache_dir: Path = root / CACHE_DIR_NAME
    upload_dir: Path = root / UPLOAD_DIR_NAME
    refs: set[Path] = _collect_referenced_paths(root)

    cache_targets: set[Path] = _list_cache_targets(cache_dir)
    upload_orphans: set[Path] = _list_upload_orphans(upload_dir, refs)

    logger.info(f"预览：cache 待删 {len(cache_targets)}，upload 孤儿 {len(upload_orphans)}")

    if args.dry:
        for p in cache_targets:
            logger.info(f"DEL cache: {p}")
        for p in upload_orphans:
            logger.info(f"DEL upload: {p}")
        return

    n1 = _delete_files(cache_targets)
    n2 = _delete_files(upload_orphans)
    n3 = _delete_empty_dirs(root)

    logger.success(f"完成清理：cache {n1}，upload {n2}，空目录 {n3}")


if __name__ == "__main__":
    main()
