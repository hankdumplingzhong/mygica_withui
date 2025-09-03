# MyGICA 使用文档

## 📄 简介

**MyGICA** (My Glimpse Interface for Cutting Abandon of MyGO!!!!! & MUJICA) 是一个文本化、结构化的视频剪辑工具，用于盯帧剪辑 MyGICA 填词 / MAD 视频。简单地说，就是代码剪视频且剪辑单位为帧。

目前本项目**并非 AI 项目**，只是将**视频剪辑流程文本化、结构化**，可以作为与其他人或 AI **协作的接口**，因此并不能自动剪辑。

目前发展方向有二：1、传统功能。继续优化数据结构和编译器以支持更多功能或简化使用难度。2、AI 功能。使用 AI 生成 .MyGICA.toml 文件初稿（不看好）。

MyGICA 使用 TOML 文本作为剪辑说明，扩展名为 .MyGICA.toml，Python + FFmpeg 作为编译器。

MyGICA 优先实现了符合通常 MyGICA 填词 / MAD 剪辑习惯的编译器，如：先确定时间范围，再在范围内定义字幕与片段；字幕常使用应援色；默认总有 bgm 等。

解决剪映不能导出 23.976 (24000 / 1001) 帧视频（导出24帧会和预览不一致，出现闪帧）及 PR 不能导入 .mkv 视频素材的问题。

## 🧩 功能特性

- 支持盯帧剪辑（基于帧的时间定义）
- 支持多源素材（如 MKV、MP4 等，由 ffmpeg 支持）
- 自动添加字幕（drawtext 滤镜）
- 支持字体颜色映射与样式定制
- 自动填充时间空隙（自动接续上个片段或下个片段，全留空时使用 black）
- 自动补全片段起止时间（自动推断单个缺失的 start / end）
- 支持缓存避免重复渲染

---

## 📁 项目结构说明

```
project/
├── 示例.MyGICA.toml        # 主配置文件（TOML 格式）
├── SC-Heavy.otf           # 字体文件（思源粗宋或其他字体）
├── cache_dir/             # 缓存目录（临时片段）
├── cache_output/          # 输出目录（最终视频）
├── 0_gen_black.py         # 生成 black 视频脚本，实为生成测试视频（运行一次，建议运行）
├── A_compiler.py          # 编译器脚本（主逻辑）
├── srt2MyGICA.py          # 将 SRT 转为 .MyGICA.toml 的脚本框架（可选）
└── structure.py           # 数据结构定义（用于解析 TOML，可以查看合法的定义）
```

---

## 🛠️ 配置文件格式说明（TOML）

### 全局设置

```toml
fps = '24000/1001'         # 帧率
project = "千早不思议.mkv"   # 项目名称（输出文件名）mkv 才能正常生成固定帧率的视频
#start = 0                 # 视频起始帧（闭区间）建议只在需要快速预览时定义以只渲染部分视频
#end = 5000                # 视频结束帧（开区间，下同）建议只在需要快速预览时定义以只渲染部分视频
```

### 源素材定义

```toml
[sources]
go1 = 'D:\path\to\mygo1.mkv'
# ...
ji13 = 'D:\path\to\mujica13.mkv'
black = 'cache_in\test_video_basic.mp4'  # 特殊 black 片段，运行 `0_gen_black.py` 生成，需要帧率等和项目一致，建议使用 black 填充未剪辑片段提交缓存利用率
bgm = 'background_music.wav'
```

### 颜色映射（用于字幕）

```toml
[colors]
'灯' = '#77BBDD'
'爱音' = '#FF8899'
# ...
```

### 时间范围定义（剪辑段）

```toml
[[ranges]]
start = 2020
end = 2098
[[ranges.texts]]
text = "火爆脾气一脚踢到钛合金"
[[ranges.clips]]
source = "go1"
start = 29590
end = 29626
[[ranges.clips]]
source = "go1"
start = 30852
volume = -50
#sound = 'sound_1' # 可选，替换片段自带音频
```

---

## 🧠 自动功能说明

### 1. 自动补全时间（start / end）

如果某段 clip 中只写了 `start` 或 `end`，脚本会自动推断另一个值以填满整个 range。

### 2. 自动填充空隙

如果 ranges 之间有时间空隙，脚本会自动延续片段或插入 black 片段。

### 3. 字幕颜色映射

`fontcolor` 可以使用 `colors` 表中定义的别名，如 `'灯'` → `#77BBDD`。

> 天哪，这也太自动了！接下来就要自动生成 bug 了！

---

## 🧪 示例配置

[示例.MyGICA.toml](示例.MyGICA.toml)

[示例输出.mp4](cache_output/千早不思议_sample.mp4)

---

## ▶️ 使用方法

### 1. 准备工作

- 安装依赖：`ffmpeg`、`python3`
- 安装 Python 依赖，如 `dacite`, `betterer`（已打包，无需安装）

安装 ffmpeg，在 powershell 运行
> winget install Gyan.FFmpeg

安装依赖，本项目使用 uv 作为运行环境，安装 uv 后在项目目录运行
> uv sync

亦可手动管理 Python 依赖

### 2. 修改配置文件

编辑 `示例.MyGICA.toml`，填写你的项目信息、素材路径、字幕内容等。

### 3. 运行脚本

> uv run A_compiler.py

输出文件将保存在 `cache_output/{{project_name}}`。

---

## 🎵 背景音乐处理

脚本会自动将背景音乐 `bgm` 合并到视频中：

---

## 🧾 输出目录结构

```
cache_output/
└── {{project_name}}       # 最终视频
cache_in/
└── ...                    # 可选的输入素材
cache_dir/
├── seg_*.mp4              # 各段缓存片段
└── concat_list.txt        # 拼接列表
```

---

## 🧠 注意事项

- 时间单位为帧（frame）。
- 所有视频源、字体文件、bgm 等必须存在，否则报错。

---

## 🧰 依赖工具

- [ffmpeg](https://ffmpeg.org/)
- Python 3.13
- 第三方库：`dacite`
- 自用库 `betterer`（已打包）

---

## 📬 联系方式

如需技术支持，请联系项目维护者。bilibili@不死の祥云。

---

> 🎬 MyGICA —— 让视频剪辑变得简单又自动化！（并不能）