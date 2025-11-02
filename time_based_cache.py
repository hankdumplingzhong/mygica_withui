import atexit
import pickle
from datetime import datetime, timedelta
from pathlib import Path


class TimeBasedCache:
    def __init__(self, cache_file: str = "time_data.pkl", allowed_directories: list = None):
        """
        初始化缓存管理器

        Args:
            cache_file: 缓存数据保存的文件名
            allowed_directories: 允许清理的目录列表，如果为None则不限制
        """
        self.cache_file: Path = Path(cache_file)
        self.allowed_directories: list = allowed_directories or ['cache_dir']
        self.cache: dict = self._load_cache()

        # 注册程序退出时的清理函数
        atexit.register(self._save_cache)

    def _load_cache(self) -> dict:
        """从文件加载缓存数据"""
        if self.cache_file.exists():
            with self.cache_file.open('rb') as f:
                return pickle.load(f)
        return {}

    def _save_cache(self) -> None:
        """保存缓存数据到文件"""
        with self.cache_file.open('wb') as f:
            pickle.dump(self.cache, f)

    def update(self, items: list, timestamp: datetime = None) -> None:
        """
        更新列表中每个元素的最近出现时间

        Args:
            items: 要更新的元素列表
            timestamp: 可选的时间戳，如果不提供则使用当前时间
        """
        if timestamp is None:
            timestamp = datetime.now()

        for item in items:
            item_path = Path(item)
            # 保留旧的时间戳，如果新时间戳更早则不更新
            save_timestamp = timestamp.timestamp()
            if str(item) in self.cache:
                old_timestamp = self.cache[str(item)]['last_access']
                if old_timestamp > save_timestamp:
                    save_timestamp = old_timestamp
            if item_path.exists():
                self.cache[str(item)] = {
                    'last_access': save_timestamp,
                    'file_path': str(item_path),
                    'exists': True
                }
            else:
                self.cache[str(item)] = {
                    'last_access': save_timestamp,
                    'file_path': None,
                    'exists': False
                }

        # 立即保存缓存
        self._save_cache()

    def clearcache(self, time_diff: timedelta, dry_run: bool = False) -> None:
        """
        清理早于指定时间差的元素及其对应的文件

        Args:
            time_diff: 时间差对象，用于判断哪些元素需要被清理
            dry_run: 如果为True，则只打印将要删除的元素和文件，而不实际删除
        """
        current_time = datetime.now()
        items_to_remove = []
        count = 0
        size = 0

        for item, info in self.cache.items():
            last_access = info['last_access']
            last_access = datetime.fromtimestamp(last_access)
            if current_time - last_access > time_diff:
                # 检查是否在允许的目录范围内
                if info['file_path']:
                    file_path = Path(info['file_path'])
                    if self.allowed_directories:
                        # 检查文件路径是否在允许的目录列表中
                        allowed = False
                        for allowed_dir in self.allowed_directories:
                            allowed_path = Path(allowed_dir)
                            try:
                                file_path.relative_to(allowed_path)
                                allowed = True
                                break
                            except ValueError:
                                continue
                        if not allowed:
                            continue  # 跳过不在允许目录中的文件
                    items_to_remove.append(item)
                    count += 1
                    if Path(info['file_path']).exists():
                        size += Path(info['file_path']).stat().st_size
                else:
                    # 如果没有文件路径，也添加到移除列表（对于非文件元素）
                    items_to_remove.append(item)

        for item in items_to_remove:
            # 如果对应的是文件，尝试删除
            if self.cache[item]['file_path'] and Path(self.cache[item]['file_path']).exists():
                if dry_run:
                    print(f"[Dry Run] Would delete file: {self.cache[item]['file_path']}")
                    continue
                Path(self.cache[item]['file_path']).unlink()
                print(f"Deleted file: {self.cache[item]['file_path']}")

            # 从缓存中移除
            del self.cache[item]
            print(f"Removed from cache: {item}")

        print(f"Total items removed: {count}, Total size freed: {size / (1024 * 1024):.2f} MB")

        # 保存更新后的缓存
        self._save_cache()

    def get_cache_info(self) -> dict:
        """获取缓存信息（用于调试）"""
        # 将时间戳转换为可读格式
        readable_cache = {}
        for item, info in self.cache.items():
            readable_info = info.copy()
            readable_info['last_access'] = datetime.fromtimestamp(info['last_access']).strftime('%Y-%m-%d %H:%M:%S')
            readable_cache[item] = readable_info
        return readable_cache

    def __del__(self) -> None:
        """析构函数，确保缓存被保存"""
        self._save_cache()


if __name__ == '__main__':
    folder = Path('cache_dir')
    cache = TimeBasedCache(allowed_directories=['cache_dir'])  # 只允许清理cache_dir目录下的文件

    # for file in list(folder.glob('*.mkv')) + list(folder.glob('*.mp4')):
    #     print(file)
    #     cache.update([str(file)], Path(file).stat().st_mtime)

    cache.clearcache(timedelta(days=1), dry_run=True)
    # cache.clearcache(timedelta(days=1))
    # print(cache.get_cache_info())