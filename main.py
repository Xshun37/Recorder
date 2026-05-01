import subprocess
import sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
RECORDS = BASE / "records"
RECORDS.mkdir(exist_ok=True)

ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
out_dir = RECORDS / ts
out_dir.mkdir(exist_ok=True)

wav = out_dir / "audio.wav"
txt = out_dir / "audio.txt"

dur = input("Enter recording duration in seconds (blank = manual stop): ").strip()

print("===== Recording =====")
cmd = ["python", str(BASE / "record.py"), str(wav)]
if dur:
    cmd.append(dur)

try:
    # 录音阶段：捕获 Ctrl+C
    subprocess.run(cmd, check=True)
except (subprocess.CalledProcessError, KeyboardInterrupt):
    # 当用户按下 Ctrl+C 时，record.py 停止，这里会捕获到中断
    print("\n[录制已手动停止]")

# 检查文件是否存在，防止录制失败导致后面报错
if not wav.exists():
    print("错误：未找到录音文件，无法继续。")
    sys.exit(1)
print("===== Transcribing =====")
subprocess.run(
    ["python", str(BASE / "transcribe_s.py"), str(wav)],
    check=True
)

print("===== Summarizing =====")
subprocess.run(
    ["python", str(BASE / "summarize.py"), str(txt)],
    check=True
)

print("===== Generating Markdown =====")
subprocess.run(
    ["python", str(BASE / "make_md.py"), str(txt)],
    check=True
)

print("===== All done =====")
