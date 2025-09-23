import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from pprint import pprint
from typing import Literal, Union

from betterer import subprocess_run
from structure import parse_config, Range, Text, ProjectConfig


@dataclass
class ScriptConfig:
    MyGICA_path: Path
    project: ProjectConfig = None
    output: Path = None
    fontfile: Path = Path("SC-Heavy.otf")
    video_width: int = 1920
    video_height: int = 1080
    tmpdir: Path = Path('cache_dir')
    output_dir: Path = Path('cache_output')
    video_preset: list[str] = field(default_factory=lambda: ['-c:v', 'hevc_nvenc', '-cq', '18', '-sn', '-dn'])
    video_preset_cat: list[str] = field(default_factory=lambda: ['-c:v', 'copy', '-c:a', 'copy'])
    # video_preset_cat: list[str] = field(default_factory=lambda: ['-c:v', 'hevc_nvenc', '-cq', '18'])
    video_preset_cat_all: list[str] = field(default_factory=lambda: ['-c:v', 'copy', '-c:a', 'copy'])

    def __post_init__(self):
        assert self.MyGICA_path.suffixes[-2:] == ['.MyGICA', '.toml'], 'need .MyGICA.toml file'
        assert self.MyGICA_path.exists(), '.MyGICA.toml file should exists'
        assert self.fontfile.exists(), 'font file should exists'
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # =============================
        # 解析配置文件，并且生成 ProjectConfig 对象时排除不合法的情况
        # =============================
        with self.MyGICA_path.open('rb') as f:
            self.project = parse_config(tomllib.load(f))

        assert self.project.project_suffix in {'.mp4', '.mkv', '.mov'}, 'output file should be .mp4/.mkv/.mov'
        self.output = self.output_dir / self.MyGICA_path.with_suffix(self.project.project_suffix)


# =============================
# 工具函数
# =============================
def frame_to_timestamp(frame: int, fps: Union[str, Literal['24000/1001']]) -> str:
    total_seconds = frame_to_time(frame, fps)
    ms = int((total_seconds - int(total_seconds)) * 1000)
    s = int(total_seconds)
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


def frame_to_time(frame: int, fps: Union[str, Literal['24000/1001']]) -> float:
    """帧转时间字符串 (HH:MM:SS.mmm)"""
    assert frame >= 0, 'frame should >= 0'
    assert re.compile(r'^[\d/.]+$').match(fps), 'fps should be number or fraction string'
    if '/' in fps:
        num, denom = map(int, fps.split('/'))
        fps = num / denom
    else:
        fps = float(fps)
    total_seconds = frame / fps
    return total_seconds


def escape_toml_string(s: str) -> str:
    """转义字符串用于 drawtext"""
    return s.replace("'", r"\'").replace(":", r"\:")


def is_image(file_path: Path) -> bool:
    """判断文件是否为图片格式"""
    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp'}
    return file_path.suffix.lower() in image_extensions


def build_drawtext_filters(
        texts: list[Text], project: ProjectConfig, fontfile: str
) -> str:
    """
    构建 ffmpeg drawtext 滤镜字符串，使用指定字体文件，避免 fontconfig 崩溃
    参数:
        texts: 字幕列表，每个元素包含 text, fontsize, fontcolor, y, borderw, bordercolor
        fontfile: 字体文件路径（支持 .ttf, .otf）
        video_width, video_height: 输出分辨率
    返回:
        drawtext 滤镜字符串
    """
    filters: list[str] = []
    for txt in texts:
        # 提取参数，带默认值
        text_str = escape_toml_string(txt.text)
        fontcolor = txt.fontcolor
        fontsize = txt.fontsize
        x = txt.x
        y = txt.y
        borderw = txt.borderw
        bordercolor = txt.bordercolor

        if fontcolor in project.colors:
            fontcolor = project.colors[fontcolor]

        # 构建 drawtext 参数
        dt_args = [
            f"fontfile={fontfile}",  # 使用指定字体
            f"text='{text_str}'",  # 显示文本
            f"fontcolor={fontcolor}",
            f"fontsize={fontsize}",
            f"x={x}-text_w/2",  # 水平居中
            f"y={y}-text_h/2",  # 垂直居中于 y 位置
            f"borderw={borderw}",
            f"bordercolor={bordercolor}"
        ]
        filters.append(f"drawtext={':'.join(dt_args)}")

    return ",".join(filters)


# =============================
# 缓存剪辑
# =============================
def cache_clip(cmd: list[str], cache: bool = True) -> Path:
    """使用命令签名缓存剪辑，要求 cmd 最后一个参数为输出文件"""
    # 获取输出文件
    output_file = cmd[-1]
    output_path = Path(output_file)
    if cache:
        # 生成命令签名，保存在文件名中
        cmd_signature = hashlib.md5(' '.join(cmd[:-1]).encode()).hexdigest()
        new_output_path = output_path.with_suffix(f'.{cmd_signature[:6]}{output_path.suffix}')
        # 如果签名文件存在且匹配，跳过执行
        if new_output_path.exists():
            print(f"⏭️  跳过缓存文件: {new_output_path}")
            return new_output_path

        cmd[-1] = str(new_output_path)  # 更新输出文件名为带签名的文件
    else:
        new_output_path = output_path
    print(f"🎬 执行命令: {' '.join(cmd)}")
    subprocess_run(cmd)
    print(f"✅ 成功生成: {new_output_path}")
    return new_output_path


# =============================
# 主函数
# =============================
def work(config: ScriptConfig) -> None:
    project = config.project
    pprint(project)

    print(f"🎬 开始处理项目: {config.MyGICA_path}")
    segment_files = []

    # =============================
    # 🎬 正常剪辑片段
    # =============================
    for i, rng in enumerate(project.ranges):
        seg_file = config.tmpdir / f"seg_{rng.start}.mp4"
        new_seg_file = work_clips(config, rng, seg_file)
        segment_files.append(new_seg_file)

    # =============================
    # 拼接所有片段
    # =============================
    # new_output = cat_video_str(config.output, segment_files, config, config.video_preset_cat_all)
    cat_video(config.output, segment_files, config, config.video_preset_cat_all)
    new_output = config.output

    # =============================
    # 拼接完成后添加背景音乐 / 在片段中添加背景音乐跳过此处
    # =============================
    add_bgm(Path(project.sources['bgm']), frame_to_time(project.start, project.fps), new_output)


def work_clips(config: ScriptConfig, rng: Range, seg_file: Path) -> Path:
    # 构建字幕滤镜
    texts = rng.texts
    if texts:
        drawtext_filter = build_drawtext_filters(texts, config.project, fontfile=str(config.fontfile))
        vf_filter = drawtext_filter
    else:
        vf_filter = ""
    # vf = f"fps={config.project.fps},scale={config.video_width}:{config.video_height},format=yuv420p10le"

    segment_files = []
    now_time = rng.start
    for i, clip in enumerate(rng.clips):
        src_path = config.project.sources[clip.source]
        project_start_time = frame_to_time(now_time, config.project.fps)
        # bgm = config.project.sources['bgm']
        frame_count = clip.end - clip.start  # 精确帧数

        clip_file = seg_file.with_stem(seg_file.stem + f'_{i}') if len(rng.clips) > 1 else seg_file

        af = ['-af', f'volume={clip.volume}dB'] if clip.volume is not None else []
        af_inline = f'volume={clip.volume}dB' if clip.volume is not None else ''
        af_in = f'[0:a]{af_inline}[a0_vol];[a0_vol]' if clip.volume is not None else '[0:a]'

        # 判断 source 是否是图片
        if is_image(Path(src_path)):
            # 基础滤镜：缩放和填充
            base_filter = f'scale={config.video_width}:{config.video_height}:force_original_aspect_ratio=decrease,pad={config.video_width}:{config.video_height}:(ow-iw)/2:(oh-ih)/2'

            # 合并滤镜（如果有字幕）
            if vf_filter:
                final_filter = f'{base_filter},{vf_filter}'
            else:
                final_filter = base_filter

            # 图片 -> 视频：循环 + 精确帧数控制
            cmd = [
                      'ffmpeg', '-y', '-hide_banner',
                      '-f', 'lavfi',  # 使用 lavfi 生成静音
                      '-i', 'anullsrc',
                      '-t', str(frame_to_time(frame_count, config.project.fps)),  # 设置音频时长与视频匹配
                      '-loop', '1',
                      '-i', str(src_path),
                      '-vframes', str(frame_count),  # 精确控制帧数
                      '-r', str(config.project.fps),  # 设置帧率
                      '-vf', final_filter,  # 合并所有滤镜
                      '-pix_fmt', 'yuv420p10le',
                  ] + config.video_preset + [str(clip_file)]
        else:
            # 正常视频处理（保持原来的精确帧数控制）
            start_time = frame_to_timestamp(clip.start, config.project.fps)
            if clip.sound:
                sound_path = config.project.sources[clip.sound]
                # 如果在片段中替换音频
                cmd = [
                    'ffmpeg', '-y', '-hide_banner',
                    '-ss', start_time,
                    '-i', src_path,
                    '-i', sound_path,  # 替换音频
                    '-map', '0:v',
                    '-map', '1:a',
                ]
            else:
                cmd = [
                    'ffmpeg', '-y', '-hide_banner',
                    '-ss', start_time,
                    '-i', src_path,
                ]
            cmd.extend([
                '-vframes', str(frame_count),  # 使用精确帧数
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', '44100',  # 统一采样率
                '-ac', '2',  # 统一声道数
            ])
            # 添加视频滤镜（如果有）
            if vf_filter:
                cmd.extend(['-vf', vf_filter])
            # cmd.extend(config.video_preset + [str(clip_file)])
            cmd.extend(af + config.video_preset + [str(clip_file)])

        print(f"✂️ 剪辑: {clip.source} [{clip.start}:{clip.end}] ({frame_count} 帧) → {clip_file.name}")
        new_clip_file = cache_clip(cmd)
        segment_files.append(new_clip_file)
        # assert (res := check_frame(new_clip_file)) == clip.end - clip.start, RuntimeError(f'帧数不匹配, {res} != {clip.end - clip.start}, {new_clip_file.name}')

        now_time += frame_count

    if len(rng.clips) > 1:
        new_seg_file = seg_file
        cat_video(seg_file, segment_files, config, config.video_preset_cat)
        # assert (res := check_frame(seg_file)) == rng.end - rng.start, RuntimeError(f'帧数不匹配, {res} != {rng.end - rng.start}, {seg_file.name}')
        return new_seg_file
    else:
        return segment_files[0]


def cat_video(output: Path, segment_files: list[Path], config: ScriptConfig, param: list[str]) -> None:
    """拼接视频"""
    concat_file = config.tmpdir / "concat_list.txt"
    with concat_file.open('w', encoding='utf-8') as f:
        for seg in segment_files:
            f.write(f"file '{seg.relative_to(config.tmpdir)}'\n")
    print(f"🎥 拼接 {len(segment_files)} 个片段 → {output}")
    cmd = [
              'ffmpeg', '-y', '-hide_banner',
              '-f', 'concat',
              '-i', str(concat_file),
          ] + param + [
              str(output)
          ]
    print(cmd)
    subprocess_run(cmd, stream_terminal=False)
    print(f"✅ 成功生成: {output}")


def cat_video_str(output: Path, segment_files: list[Path], config: ScriptConfig, param: list[str]) -> Path:
    """拼接视频"""
    # TODO: 拼接不成功，只有第一段视频
    concat_file = '|'.join(str(seg.as_posix()) for seg in segment_files)
    print(f"🎥 拼接 {len(segment_files)} 个片段 → {output}")
    cmd = [
              'ffmpeg', '-y', '-hide_banner',
              '-i', 'concat:' + str(concat_file),
          ] + param + [
              str(output)
          ]
    return cache_clip(cmd)


def cat_video_new(output: Path, segment_files: list[Path], config: ScriptConfig, param: list[str]) -> Path:
    """拼接视频"""
    print(f"🎥 拼接 {len(segment_files)} 个片段 → {output}")
    cmd = [
              'ffmpeg', '-y', '-hide_banner',
          ] + sum([['-i', str(seg)] for seg in segment_files], []) + [
              '-filter_complex',
              f'concat=n={len(segment_files)}:v=1:a=1[outv][outa]',
          ] + param + [
              '-map', '[outv]',
              '-map', '[outa]',
              str(output)
          ]
    return cache_clip(cmd)


def add_bgm(bgm: Path, audio_advance_sec: float, input_path: Path) -> Path:
    """添加背景音乐"""
    output_path = input_path.parent / f"{input_path.stem}_with_bgm{input_path.suffix}"

    print('添加 bgm 并提前', f'{audio_advance_sec=}')

    cmd = [
        'ffmpeg', '-y', '-hide_banner',
        '-i', str(input_path),
        '-i', str(bgm),
        '-filter_complex',
        # 关键修改：对两个音频流都进行aresample和asetpts，确保它们严格同步
        f'[0:a]aresample=async=1:first_pts=0[a0];'  # 处理视频原音频，重置时间戳并异步重采样
        f'[1:a]atrim=start={audio_advance_sec},aresample=async=1[a1];'  # 处理背景音乐
        f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]',  # 混合
        '-map', '0:v',
        '-map', '[a]',
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-b:a', '192k',
        str(output_path),
    ]

    return cache_clip(cmd, cache=False)


# =============================
# 启动
# =============================
def main() -> None:
    MyGICA_path = Path('示例.MyGICA.toml')  # noqa: N806
    config = ScriptConfig(MyGICA_path=MyGICA_path)
    work(config)


if __name__ == '__main__':
    main()
