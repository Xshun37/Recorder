# Recorder

轻量录音转写与自动总结工具。

环境准备（Windows）:

1. 安装 Python 3.10+
2. 克隆仓库: git clone <repo-url>
3. 进入目录: cd Recorder
4. 运行: setup_env.bat （或手动创建虚拟环境并 `pip install -r requirements.txt`）
   - PyTorch 请根据你的 GPU/CPU 手动安装，参考 https://pytorch.org/get-started/locally/
5. 设置环境变量: DEEPSEEK_API_KEY（用于 DeepSeek API）
   - PowerShell 临时: $env:DEEPSEEK_API_KEY="your_key"
   - Windows 永久: setx DEEPSEEK_API_KEY "your_key"
6. 安装 VB-Audio Virtual Cable（用于录音）: https://vb-audio.com/Cable/
7. 确保 ffmpeg.exe 在仓库根目录或已加入 PATH（仓库内提供了 ffmpeg.exe）

使用:
- 运行: `python main.py` 或 双击 `record.bat` 按提示操作。
- 录音文件与输出保存在 `records/` 下。

更多细节见 readme.txt。
