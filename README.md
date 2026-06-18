# Recorder — 教学网视频自动笔记工具

自动抓取 PKU 教学网 (Blackboard Learn) 课程视频，提取音频，Whisper 转写，DeepSeek 生成结构化笔记。

## 主程序入口

| 入口 | 功能 |
|------|------|
| `recorder/lecture.py` | 录音 + 转录 + AI 笔记 |
| `pku-downloader/scripts/main.py` | 课件下载 + AI 解析 + Zotero 导入 |

## 快速开始

```powershell
# 1. 克隆仓库
git clone https://github.com/Xshun37/Recorder.git
cd Recorder

# 2. 安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cu121  # GPU 版

# 3. 配置凭据
copy .env.example .env
# 编辑 .env 填入你的 Cookie（获取方法见下文）
setx DEEPSEEK_API_KEY "sk-xxxxxxxx"  # DeepSeek API Key

# 4. 运行
python lecture.py
```

## 工作模式

| 模式 | 命令 | 说明 |
|------|------|------|
| **HLS 直下** (默认) | `python lecture.py` | Selenium 抓取 m3u8 → ffmpeg 直下音频 (无实时播放，极快) |
| Stream 录制 | `python lecture.py --mode stream` | 浏览器实时播放 + 系统音频录制 (需 VB-Cable) |
| 断点续传 | `python lecture.py --resume` | 扫描已下载/已转录文件，接着跑 |

### HLS 模式流程

```
选课程 → 选视频 → Phase 1: 抓取 m3u8 URL (10s/视频)
                      → Phase 2: 并行下载音频 (4 路并发)
                      → Phase 3: Whisper 转录
                      → Phase 4: DeepSeek 并行摘要
```

```powershell
python lecture.py --workers 8 --summarize-workers 12  # 调并发
```

### Stream 模式 (fallback)

需安装 [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)，浏览器音频路由到 VB-Cable 后运行：

```powershell
python lecture.py --mode stream --speed 2.0
```

## Cookie 获取

1. 浏览器登录 `course.pku.edu.cn`
2. F12 → 应用程序 → Cookie
3. 从以下域复制值，填入 `.env`：

| Cookie | 域 | 路径 | 必需 |
|--------|------|------|------|
| `JSESSIONID` | `course.pku.edu.cn` | `/webapps/portal` 或 `/` | ✅ |
| `s_session_id` | `course.pku.edu.cn` | `/` | ✅ |
| `JWTUser` | `.pku.edu.cn` | `/` | ✅ |
| `_token` | `.pku.edu.cn` | `/` | ✅ HLS 模式必需 |

## 并发参数

| 参数 | 默认 | 作用 |
|------|------|------|
| `--workers` | 4 | Phase 2: ffmpeg 并行下载数 |
| `--summarize-workers` | 4 | Phase 4: DeepSeek 并行摘要数 |
| `--transcribe-workers` | 1 | Phase 3: Whisper 转录并行数 (GPU 8GB=1) |
| `--speed` | 2.0 | Stream 模式倍速 |

## 输出

```
records/
  INDEX.md              # 笔记索引 (按课程分组)
  分子生物学(25-26学年第2学期)/
    2026-05-07 15_10_00/
      audio.wav          # 音频文件
      audio.s.txt        # 转写文本
      audio.s.summary.txt # AI 摘要
      audio.md           # 最终笔记
```

## 前置依赖

| 依赖 | 用途 | 安装 |
|------|------|------|
| Python 3.10+ | 运行环境 | [python.org](https://www.python.org/downloads/) |
| PyTorch | Whisper 后端 | `pip install torch` (GPU: CUDA 12.1) |
| ffmpeg | 音频下载/处理 | 仓库自带 `ffmpeg.exe` |
| Edge 浏览器 | Selenium 驱动 | Windows 11 预装 |

## 文件结构

| 文件 | 用途 |
|------|------|
| `lecture.py` | 主编排：交互选择 + HLS/Stream 双模式流水线 |
| `scraper.py` | 课程列表/视频列表解析，Cookie 管理 |
| `player.py` | Selenium: 视频播放 / m3u8 抓取 / HLS 下载 |
| `transcribe_s.py` | Whisper 转录 + 去噪 + 繁转简 |
| `summarize.py` | DeepSeek 学术笔记生成 |
| `make_md.py` | Markdown 格式化输出 |
| `record.py` | ffmpeg 系统音频录制工具 (Stream 模式底层) |

## FAQ

- **Cookie 过期**：重新从浏览器复制，更新 `.env`
- **HLS 下载失败**：`_token` cookie 可能过期，重新获取
- **ffmpeg 找不到**：确认 `ffmpeg.exe` 在仓库根目录
- **转录垃圾数据**：个别视频 Whisper 可能产生幻觉，删掉 `audio.s.txt` 后 `--resume` 重试
- **GPU 显存不足**：`--transcribe-workers` 保持 1，或改用 CPU 运行 Whisper

## 隐私

所有数据（音频、文本、笔记）均保存在本地 `records/` 目录下，不上传到任何服务器（除 DeepSeek API 用于摘要生成）。

---

# PKU Course Downloader + AI Slide Analyzer

下载北京大学教学网 (Blackboard) 课程资料，使用 Qwen 视觉模型自动解析 PPT/PDF 课件，将 AI 教学笔记注入 Zotero 以便学习。

## 快速开始

```bash
cd pku-downloader
python -m venv venv
venv\Scripts\activate
pip install openai pillow pymupdf python-pptx pywin32 python-dotenv
```

使用 recorder 已有的 `.env` 即可（Cookie + API Key 已配置）。

```bash
python scripts/main.py --all          # 全流程：下载→转换→导入→分析→笔记
python scripts/main.py --course "分子生物学" --skip-analysis  # 仅下载+导入
```

## 管道流程

```
PPT/PDF 文件
  → PyMuPDF / PowerPoint COM 渲染为图片
    → Qwen3.7-Plus 视觉模型 (12 线程并发)
      → 每页中文 HTML 分析输出
        → 合并为 Zotero 子笔记
```

## 文件结构

| 文件 | 用途 |
|------|------|
| `scripts/main.py` | 主编排：下载→PPT转PDF→导入Zotero→分析→笔记 |
| `scripts/pipeline_core.py` | 核心引擎：PDF渲染、Qwen分析、Zotero写入 |
| `scripts/auth.py` | PKU 教学网认证 |
| `scripts/scraper.py` | 课程/资源解析 |
| `scripts/zotero_sync.py` | 下载器 + RIS 生成 |
| `scripts/generate_report.py` | HTML 对比报告 (原图 vs AI 分析) |

## 价格参考

| 模型 | 单页均价 | 1028 页 |
|------|:---:|:---:|
| Qwen3.7-Plus | ~CNY 0.02 | ~CNY 25 |

## 依赖

- Python 3.9+
- PowerPoint COM (Windows only, PPT→PDF 转换)
- Zotero 9.x (笔记写入)
- DashScope API (Qwen 视觉模型)
