from dataclasses import dataclass, field
from typing import Optional

from dacite import from_dict, Config


@dataclass
class Clip:
    source: str
    start: Optional[int] = None
    end: Optional[int] = None
    volume: float = 0.0

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

        assert sum(1 for r in self.ranges if r.start < self.start or r.end > self.end) == 0, \
            "所有 Range 的 start 和 end 必须在 ProjectConfig 的 start 和 end 范围内"

        assert sum(r.end - r.start for r in self.ranges) == self.end - self.start, \
            "所有 Range 的时间段必须完整覆盖 ProjectConfig 的时间段，且不能重叠"

        assert sum(self.ranges[i].end == self.ranges[i + 1].start for i in range(len(self.ranges) - 1)) == len(self.ranges) - 1, \
            "所有 Range 的时间段必须完整覆盖 ProjectConfig 的时间段，且不能重叠"

        assert sum(1 for r in self.ranges if r.start >= r.end) == 0, \
            "所有 Range 的 start 必须小于 end"

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
        for r in self.ranges:
            sum_length = sum((clip.end - clip.start) for clip in r.clips if clip.start is not None and clip.end is not None)
            if len(r.clips) == 0:
                print(f"日志: Range {r} 内没有任何 Clip, 自动延续上一个 Clip")
                r.clips.append(Clip(source=last_source, start=last_end if last_source != 'black' else 0))
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


def parse_config(data) -> ProjectConfig:
    # 配置 dacite 忽略额外字段（可选），并支持嵌套
    config = Config(
        forward_references={"Clip": Clip, "Text": Text, "Range": Range},
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
