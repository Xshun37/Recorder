import sys
import subprocess
from pathlib import Path
from opencc import OpenCC

if len(sys.argv) < 2:
    print("Usage: python transcribe_s.py <audio_file>")
    sys.exit(1)

audio = Path(sys.argv[1]).resolve()
out_dir = audio.parent

# 1. 调用 whisper
cmd = [
    sys.executable, "-m", "whisper",
    str(audio),
    "--language", "zh",
    "--device", "cuda",
    "--model", "medium",
    "--output_format", "txt",
    "--output_dir", str(out_dir)
]
subprocess.run(cmd, check=True)

# 2. Whisper 实际输出文件名（你这里就是 audio.txt）
txt_file = out_dir / "audio.txt"

if not txt_file.exists():
    raise FileNotFoundError(f"Whisper output not found: {txt_file}")

# 3. 繁转简
out_file = out_dir / "audio.s.txt"

cc = OpenCC("t2s")
text = txt_file.read_text(encoding="utf-8")
out_file.write_text(cc.convert(text), encoding="utf-8")

print(f"Done: {out_file}")
