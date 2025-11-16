from pathlib import Path

import click
import pysrt


def time_to_frames(time: pysrt.SubRipTime, fps: float) -> int:
    """
    将SubRipTime对象转换为帧序号

    Args:
        time: pysrt.SubRipTime对象
        fps: 帧率

    Returns:
        int: 帧序号
    """
    # 将时间转换为总秒数
    total_seconds = time.hours * 3600 + time.minutes * 60 + time.seconds + time.milliseconds / 1000.0
    # 转换为帧序号
    frame_number = int(round(total_seconds * fps))
    return frame_number


def adjust_subtitle(subtitle_path: Path, fps: float = 24000 / 1001) -> None:
    subs = pysrt.open(subtitle_path, encoding="utf-8")
    first = True

    for sub in subs:
        # 获取开始时间的帧序号
        start_frame = time_to_frames(sub.start, fps)
        # 获取结束时间的帧序号
        end_frame = time_to_frames(sub.end, fps)

        # print("-" * 50)
        # print(f"字幕序号: {sub.index}")
        # print(f"开始时间: {sub.start} -> 开始帧: {start_frame}")
        # print(f"结束时间: {sub.end} -> 结束帧: {end_frame}")
        # print(f"字幕内容: {sub.text}")

        print('[[ranges]]')
        print(f'start = {start_frame}')
        print(f'end = {end_frame}')
        text = repr(sub.text).strip("\"\'")
        if sub.text.strip():
            print('[[ranges.texts]]')
            print(f'text = "{text}"')
        if first:
            first = False
            print("[[ranges.clips]]")
            print("source = 'black'")
            print("start = 0")
        print()


@click.command()
@click.argument('srt_file', type=click.Path(exists=True, path_type=Path))
def cli(srt_file: Path) -> None:
    """调整字幕时间并输出为指定格式"""
    adjust_subtitle(srt_file)


if __name__ == "__main__":
    pass
