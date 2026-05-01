# Recorder

轻量录音、转写与自动总结工具（Windows 友好）。

适用人群
- 面向不熟悉 Python、环境配置或模型安装的办公本用户。
- 目标是「无需改代码」，按步骤运行即可完成录音→转写→自动总结→生成 Markdown。

快速上手（推荐，不懂命令行也可完成）

1) 获取代码
- 从 GitHub 下载 ZIP 并解压，或在会用 Git 的情况下：
  ```powershell
  git clone <repo-url>
  cd Recorder
  ```

2) 安装 Python（如果电脑没有）
- 访问 https://www.python.org/downloads/windows/ 下载 Windows Installer（3.10+），运行安装程序并勾选“Add Python to PATH”。
- 安装后在开始菜单打开“命令提示符（Command Prompt）”，输入 `python --version` 验证。

3) 一键准备环境（推荐）
- 在资源管理器中进入仓库根目录，双击 `setup_env.bat`，按屏幕提示操作。
  - 该脚本会创建虚拟环境并通过 pip 安装项目依赖。
  - 如果脚本提示找不到 Python，请先完成第 2 步。

4) 安装 PyTorch（必要，影响 Whisper 性能）
- 如果只用 CPU（办公本）：在仓库目录打开命令提示符，运行：
  ```powershell
  .venv\Scripts\activate
  pip install torch --index-url https://download.pytorch.org/whl/cpu
  ```
- 如果有 NVIDIA GPU，请参照 https://pytorch.org/get-started/locally/ 选择合适的安装命令。

5) 安装 VB-Audio Virtual Cable（用于录音输入）
- 下载地址：https://vb-audio.com/Cable/
- 解压后以管理员身份运行 `VBCABLE_Setup_x64.exe`，安装完成后建议重启。
- 安装成功后，系统的录音设备列表应出现：`CABLE Output (VB-Audio Virtual Cable)`。

6) 检查 ffmpeg
- 仓库中一般包含 `ffmpeg.exe`，无需额外安装。如果没有，可从 https://ffmpeg.org/ 下载并放在仓库根目录或加入 PATH。
- 验证：在命令行运行 `ffmpeg -version`。

7) 设置 DeepSeek API Key（用于自动总结）
- Windows GUI：开始 → 输入“环境变量” → 编辑用户变量 → 新建 `DEEPSEEK_API_KEY`，填入你的 Key。
- 命令行（永久）：
  ```powershell
  setx DEEPSEEK_API_KEY "your_key"
  ```
- PowerShell 临时（本次会话有效）：
  ```powershell
  $env:DEEPSEEK_API_KEY = "your_key"
  ```

8) 预下载 Whisper 模型（可减少首次运行等待）
- 录一段短音频或使用已有音频文件，在仓库根目录激活虚拟环境并运行：
  ```powershell
  .venv\Scripts\activate
  python -m whisper sample.wav --model small --output_format txt --output_dir .
  ```
- 建议在办公本上优先使用 `small`、`tiny` 或 `base` 模型以降低资源占用；`medium/large` 需较强硬件。

运行程序（两种方式）

- 推荐（图形化）：双击 `record.bat`，按提示输入录音时长（秒），或留空采用手动停止（Ctrl+C）。
- 命令行：在仓库目录中：
  ```powershell
  .venv\Scripts\activate
  python main.py
  ```

程序会完成：录音 → 转写（whisper）→ 自动总结（DeepSeek）→ 生成 Markdown（make_md）。
输出文件位于 `records\YYYY-MM-DD_HH-MM\` 下，包含：
- `audio.wav`（录音文件）
- `audio.txt`（whisper 原始转写）
- `audio.s.txt`（繁体转简体或清洗后文本）
- `audio.summary.txt`（AI 总结）
- `audio.md`（生成的 Markdown）

核心文件与架构概览
- `record.py`：调用 ffmpeg 从 dshow 设备（默认 `CABLE Output (VB-Audio Virtual Cable)`）录音。
- `main.py`：主流程，串联录音/转写/总结/生成 Markdown。
- `transcribe_s.py`：使用 whisper（通过 `python -m whisper`）转写，若检测到中文会用 opencc 将繁体转为简体。
- `summarize.py`：调用 DeepSeek API 做深度学术风格总结（需要 `DEEPSEEK_API_KEY`）。
- `make_md.py`：将总结写入 Markdown 文件。

常见问题（FAQ）
- 找不到录音设备或报 I/O error：确认 VB-Cable 已安装并在“录音设备”列表中可见，若名称不同请在 `record.py` 中修改 `-i` 参数（高级用户）。
- Whisper 下载/运行缓慢：建议先预下载模型（见上文）或使用更小的模型（tiny/base/small）。
- 若遇到 GPU/ CUDA 错误：请改为 CPU 版 PyTorch（见第 4 步），或在 `transcribe_s.py` 中将设备改为 `cpu`（高级用户）。
- 未设置 API Key：运行 summarize.py 时会报错，请先设置 `DEEPSEEK_API_KEY`。

隐私与存储
- 所有录音与文本保存在本地 `records/` 文件夹，请自行妥善管理或删除敏感内容。

更多帮助
- 仍有问题请把错误截图和 `records/` 下产生的日志文件发给维护者，或在仓库 Issues 里提问。

---
只需按上面的“快速上手”步骤操作，办公本用户通常能在 20–30 分钟内完成环境配置并开始使用。祝顺利！
