from dataclasses import dataclass, field
from typing import Optional

from dacite import from_dict, Config
from loguru import logger


@dataclass
class Clip:
    source: str  # source 的 key
    start: Optional[int] = None
    end: Optional[int] = None
    volume: float = 0.0
    sound: Optional[str] = None  # sound 的 key

    def __post_init__(self):
        if self.source == 'black':
            self.volume = -50


@dataclass
class Text:
    text: str
    x: int = 960
    y: int = 934
    fontsize: int = 78
    fontcolor: str = 'white'
    borderw: int = 6
    bordercolor: str = '#333333'


@dataclass
class Range:
    start: int
    end: int
    clips: list[Clip] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)


@dataclass
class ProjectConfig:
    fps: str
    project_name: str
    sources: dict[str, str]
    colors: dict[str, str]
    ranges: list[Range]
    start: Optional[int] = None
    end: Optional[int] = None

    def __post_init__(self):
        if self.start is None:
            self.start = min((r.start for r in self.ranges), default=0)
        if self.end is None:
            self.end = max((r.end for r in self.ranges), default=0)

        # assert sum(1 for r in self.ranges if r.start < self.start or r.end > self.end) == 0, \
        #     "所有 Range 的 start 和 end 必须在 ProjectConfig 的 start 和 end 范围内"

        # 检查 start end 有序性
        assert self.start < self.end, "ProjectConfig 的 start 必须小于 end"
        for r in self.ranges:
            assert r.start < r.end, f"Range 的 start 必须小于 end, {r=}"
        for i in range(len(self.ranges) - 1):
            assert self.ranges[i].end <= self.ranges[i + 1].start, f"Range 之间不能重叠, {self.ranges[i]=}, {self.ranges[i + 1]=}"

        # 检查所有 Range 的 start 和 end 是否在 ProjectConfig 的 start 和 end 范围内，自动调整超出部分
        if sum(1 for r in self.ranges if r.start < self.start or r.end > self.end) != 0:
            logger.warning("警告: 有 Range 的 start 和 end 不在 ProjectConfig 的 start 和 end 范围内, 将自动调整 Range 的 start 和 end")
            new_range = []
            for r in self.ranges:
                if r.end <= self.start or r.start >= self.end:
                    logger.warning(f"警告: Range {r} 完全在 ProjectConfig 范围外, 将被移除")
                    continue
                new_start = max(r.start, self.start)
                new_end = min(r.end, self.end)
                if new_start != r.start or new_end != r.end:
                    logger.warning(f"警告: Range {r} 的 start 或 end 超出 ProjectConfig 范围, 将被调整为 ({new_start}, {new_end})")
                new_range.append(Range(start=new_start, end=new_end, clips=r.clips, texts=r.texts))
            self.ranges = new_range

        # 所有 Range 的时间段必须完整覆盖 ProjectConfig 的时间段，自动补全空白部分
        if sum(r.end - r.start for r in self.ranges) != self.end - self.start:
            logger.warning("警告: 所有 Range 的时间段未完整覆盖 ProjectConfig 的时间段，或有重叠部分，自动补全空白部分")
            new_ranges = []
            current_start = self.start
            for r in self.ranges:
                if r.start > current_start:
                    logger.warning(f"警告: 在 {current_start} 到 {r.start} 之间有空白时间段, 将自动补全一个 Range")
                    new_ranges.append(Range(start=current_start, end=r.start, clips=[], texts=[]))
                new_ranges.append(r)
                current_start = r.end
            if current_start < self.end:
                logger.warning(f"警告: 在 {current_start} 到 {self.end} 之间有空白时间段, 将自动补全一个 Range")
                new_ranges.append(Range(start=current_start, end=self.end, clips=[], texts=[]))
            self.ranges = new_ranges

        # 检查 Clip 的 source 是否在 sources 中
        all_sources = set(self.sources.keys())
        for r in self.ranges:
            for clip in r.clips:
                assert clip.source in all_sources, f"Clip source '{clip.source}' not found in sources"

        # 检查 Text 的 fontcolor 是否在 colors 中
        all_colors = set(self.colors.keys()) | {'white', 'black'}
        for r in self.ranges:
            for text in r.texts:
                assert text.fontcolor in all_colors, f"Text fontcolor '{text.fontcolor}' not found in colors"

        # 检查 Clip 的 start 和 end 为 None 的总数不超过 1
        for r in self.ranges:
            none_count = sum(1 for clip in r.clips if clip.start is None and clip.end is None)
            assert none_count <= 1, "每个 Range 内 Clip 的 start 和 end 同时为 None 的数量不能超过 1"

        # 填充 Clip 的 start 和 end
        last_source = 'black'
        last_end = None
        last_volume = 0

        for r in reversed(self.ranges):
            if r.clips:
                last_source = r.clips[0].source
                last_end = r.clips[0].start if r.clips[0].start is not None else last_end - (r.end - r.start)
                last_volume = r.clips[0].volume
            elif last_end is not None:
                last_end = last_end - (r.end - r.start)

        for r in self.ranges:
            sum_length = sum((clip.end - clip.start) for clip in r.clips if clip.start is not None and clip.end is not None)
            if len(r.clips) == 0:
                logger.debug(f"日志: Range {r} 内没有任何 Clip, 自动延续上一个 Clip")
                r.clips.append(Clip(source=last_source, start=last_end if last_source != 'black' else 0, volume=last_volume))
            for clip in r.clips:
                if clip.start is None:
                    clip.start = clip.end - (r.end - r.start - sum_length)
                    sum_length += (clip.end - clip.start)
                if clip.end is None:
                    clip.end = clip.start + (r.end - r.start - sum_length)
                    sum_length += (clip.end - clip.start)
            assert sum_length == r.end - r.start, f"每个 Range 内 Clip 的总长度必须等于 Range 的长度 {r}"
            last_source = r.clips[-1].source
            last_end = r.clips[-1].end
            last_volume = r.clips[-1].volume


def parse_config(data) -> ProjectConfig:
    # 配置 dacite 忽略额外字段（可选），并支持嵌套
    config = Config(
        forward_references={"Clip": Clip, "Text": Text, "Range": Range},
        strict=True
        # 不强制所有字段都存在（允许 dict 多余键）
    )
    project_config = from_dict(
        data_class=ProjectConfig,
        data=data,
        config=config
    )
    return project_config


if __name__ == '__main__':
    pass
