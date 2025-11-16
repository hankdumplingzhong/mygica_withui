from pathlib import Path

from src.MyGICA.betterer import subprocess_run

base = Path('cache_in/test_video_basic.mkv')
base.parent.mkdir(parents=True, exist_ok=True)
# 均为最后 -c:v copy 片段考虑，格式和项目一致
cmd1 = [
    'ffmpeg', '-y', '-hide_banner',
    # 生成测试视频，10分钟，1920x1080，24000/1001
    '-f', 'lavfi',
    '-i', 'testsrc2=duration=600:size=1920x1080:rate=24000/1001',  # rate=24000/1001，需要和项目 fps 一致，否则报错
    '-f', 'lavfi',
    '-i', 'sine=frequency=440:duration=600:sample_rate=44100',
    '-ac', '2',  # 立体声，或在编译器中指定，否则默认单声道，立体声项目只有左声道
    '-pix_fmt', 'yuv420p10le',
    '-c:v', 'hevc_nvenc',
    base
]

subprocess_run(cmd1)
