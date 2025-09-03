from pathlib import Path

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


def adjust_subtitle(subtitle_path: Path) -> None:
    subs = pysrt.open(subtitle_path, encoding="utf-8")
    fps = 24000 / 1001  # 23.976 fps

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
        #         print(
        # f'''range [{start_frame}:{end_frame}]
        #     text {sub.text}
        # ''')
        print(
            f'''[[ranges]]
start = {start_frame}
end = {end_frame}''')
        if sub.text.strip():
            print(
                f'''[[ranges.texts]]
text = "{sub.text}"'''
            )
        print()


if __name__ == "__main__":
    srt_file = Path(r"D:\Videos\Chihaya不思议\Chihaya不思议(1).mod.srt")
    adjust_subtitle(srt_file)
