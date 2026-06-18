# Recorder — 教学网自动化工具集

PKU 教学网 (Blackboard Learn) 课件下载 / 录播转写 / AI 解析 / Zotero 管理。

| 子项目               | 命令                                      | 功能                              |
| ----------------- | --------------------------------------- | ------------------------------- |
| `recorder/`       | `python recorder/lecture.py`            | 录播下载 → Whisper 转写 → DeepSeek 总结 |
| `pku-downloader/` | `python pku-downloader/scripts/main.py` | 课件下载 → Qwen 解析 → Zotero 笔记      |

---

## 快速开始

```powershell
git clone https://github.com/Xshun37/Recorder.git
cd Recorder
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cu121   # recorder GPU 版
copy .env.example .env
# 编辑 .env 填入 Cookie 和 API Key
```

## 配置 (.env)

`.env.example` → `.env`，填写以下内容：

| 变量                    | 用途                                       | 必需  |
| --------------------- | ---------------------------------------- |:---:|
| `COOKIE_JSESSIONID`   | PKU 教学网认证                                | ✅   |
| `COOKIE_s_session_id` | PKU 教学网认证                                | ✅   |
| `COOKIE_JWTUser`      | PKU 教学网认证                                | ✅   |
| `COOKIE__token`       | HLS 下载 (recorder)                        |     |
| `QWEN_API_KEY`        | 课件 AI 解析 (pku-downloader)                |     |
| `DEEPSEEK_API_KEY`    | 转录总结 (recorder)                          |     |
| `ZOTERO_DB_PATH`      | Zotero 数据库路径，默认自动从 `%APPDATA%/Zotero` 查找 |     |

Cookie 获取：登录 `course.pku.edu.cn` → F12 → 应用程序 → Cookie，参考 `.env.example` 字段名填入。

---

## recorder — 录播下载 + AI 笔记

```
选课程 → 选视频 → 抓取 m3u8 → ffmpeg 下载音频 → Whisper 转录 → DeepSeek 总结
```

| 参数                     | 默认  | 作用             |
| ---------------------- |:---:| -------------- |
| `--workers`            | 4   | ffmpeg 并行下载数   |
| `--summarize-workers`  | 4   | DeepSeek 并行摘要数 |
| `--transcribe-workers` | 1   | Whisper 转录并行数  |
| `--speed`              | 2.0 | Stream 模式倍速    |

```powershell
python recorder/lecture.py                     # 交互式
python recorder/lecture.py --workers 8          # 调并发
python recorder/lecture.py --resume             # 断点续传
python recorder/lecture.py --mode stream        # fallback: 系统录音
```

输出：`recorder/records/` → 按课程/日期分目录 → `audio.wav` / `audio.s.txt` / `audio.md`

## pku-downloader — 课件下载 + AI 解析 + Zotero

```
选课程 → 下载PPT/PDF → PPT转PDF → 导入Zotero → Qwen3.7-Plus 逐页解析 → 笔记注入
```

| 文件                         | 用途                        |
| -------------------------- | ------------------------- |
| `scripts/main.py`          | 入口：选课 → 下载 → 转换 → 分析 → 笔记 |
| `scripts/pipeline_core.py` | 引擎：PDF渲染、Qwen分析、Zotero写入  |
| `scripts/auth.py`          | PKU 教学网 Cookie 认证         |
| `scripts/scraper.py`       | 爬虫：课程列表 / 资源解析            |
| `scripts/zotero_sync.py`   | 下载器 + 去重                  |

```powershell
python pku-downloader/scripts/main.py                 # 交互式选课
python pku-downloader/scripts/main.py --course "分子生物学"
python pku-downloader/scripts/main.py --skip-analysis  # 只下载不分析
python pku-downloader/scripts/main.py --analysis-only  # 对已下载分析
python pku-downloader/scripts/main.py --force          # 强制重新分析
python pku-downloader/scripts/main.py --concurrency 8  # 调 API 并发
```

### 管道流程

```
PPT/PDF → PyMuPDF / PowerPoint COM 渲染图片
  → Qwen3.7-Plus 逐页解析 (HTML格式)
    → 合并为 Zotero 子笔记
```

| 模型           | 单页均价      | 1028 页总费用 |
| ------------ |:---------:|:---------:|
| Qwen3.7-Plus | ~CNY 0.02 | ~CNY 25   |

---

## 依赖

| 依赖             | 用途                                  |
| -------------- | ----------------------------------- |
| Python 3.10+   | 运行                                  |
| ffmpeg         | recorder 音频 (仓库自带)                  |
| PyTorch        | recorder Whisper                    |
| PowerPoint COM | pku-downloader PPT→PDF (Windows 预装) |
| Zotero 9.x     | pku-downloader 笔记写入                 |

## FAQ

- **Cookie 过期**：重新复制，更新根 `.env`
- **Zotero 找不到**：`.env` 设 `ZOTERO_DB_PATH=F:/文献/zotero.sqlite`
- **PyMuPDF 装不上**：包名 `pymupdf`，不是 `fitz`
