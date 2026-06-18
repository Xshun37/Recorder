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
    "--initial_prompt", (
        "Academic lecture, biochemistry and molecular biology, "
        "professor explaining concepts in English with occasional Chinese terminology."
    ),
    "--no_speech_threshold", "0.5",        # 低于默认 0.6，更积极地过滤静音
    "--condition_on_previous_text", "True",
    "--output_format", "txt",
    "--output_dir", str(out_dir)
]
subprocess.run(cmd, check=True)

# 2. Whisper 输出文件名 = {output_dir}/{audio_stem}.txt
txt_file = out_dir / (audio.stem + ".txt")

if not txt_file.exists():
    raise FileNotFoundError(f"Whisper output not found: {txt_file}")

# 3. 后处理：去掉开头/结尾的无意义噪音片段
#    Whisper 在静音或杂音时容易输出重复短词 (you, thank等)
filler_pattern = re.compile(
    r'^\s*('
    r'You\b|Thank you\b|Thanks\b|um\b|uh\b|ah\b|hmm\b|'
    r'好了?\b|那个\b|嗯\b|啊\b|哦\b|这个\b|就是\b|然后\b'
    r')\s*$',
    re.IGNORECASE
)
lines = txt_file.read_text(encoding="utf-8").strip().splitlines()

# 从头部砍掉连续的无意义行
start = 0
while start < len(lines) and filler_pattern.search(lines[start]):
    start += 1

# 从尾部砍掉连续的无意义行
end = len(lines)
while end > start and filler_pattern.search(lines[end - 1]):
    end -= 1

text = "\n".join(lines[start:end]).strip()
if not text:
    text = "\n".join(lines)  # 防止全砍没了
txt_file.write_text(text, encoding="utf-8")

# 检测中文字符（包括CJK统一表意文字）
chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

if chinese_pattern.search(text):
    # 包含中文，进行繁转简
    out_file = out_dir / (audio.stem + ".s.txt")
    cc = OpenCC("t2s")
    out_file.write_text(cc.convert(text), encoding="utf-8")
    print(f"Done (Chinese detected): {out_file}")
else:
    # 不包含中文（英文等其他语言），直接复制
    out_file = out_dir / (audio.stem + ".s.txt")
    out_file.write_text(text, encoding="utf-8")
    print(f"Done (English/Other language detected): {out_file}")
