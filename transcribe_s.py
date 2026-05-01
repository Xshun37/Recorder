import os
import sys
import subprocess
from pathlib import Path
from opencc import OpenCC
import re

if len(sys.argv) < 2:
    print("Usage: python transcribe_s.py <audio_file>")
    sys.exit(1)

audio = Path(sys.argv[1]).resolve()
out_dir = audio.parent

# 1. 调用 whisper（自动检测语言）
device = os.getenv("WHISPER_DEVICE")
if not device:
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

cmd = [
    sys.executable, "-m", "whisper",
    str(audio),
    "--device", device,
    "--model", "medium",
    "--language", "English",
    "--initial_prompt", "English lesson, some Chinese explanation, grammar, vocabulary.",
    "--output_format", "txt",
    "--output_dir", str(out_dir)
]
subprocess.run(cmd, check=True)

# 2. Whisper 实际输出文件名（你这里就是 audio.txt）
txt_file = out_dir / "audio.txt"

if not txt_file.exists():
    raise FileNotFoundError(f"Whisper output not found: {txt_file}")

# 3. 检测是否包含中文字符，如果包含则进行繁转简
text = txt_file.read_text(encoding="utf-8")

# 检测中文字符（包括CJK统一表意文字）
chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

if chinese_pattern.search(text):
    # 包含中文，进行繁转简
    out_file = out_dir / "audio.s.txt"
    cc = OpenCC("t2s")
    out_file.write_text(cc.convert(text), encoding="utf-8")
    print(f"Done (Chinese detected): {out_file}")
else:
    # 不包含中文（英文等其他语言），直接复制
    out_file = out_dir / "audio.s.txt"
    out_file.write_text(text, encoding="utf-8")
    print(f"Done (English/Other language detected): {out_file}")
