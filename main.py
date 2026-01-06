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

subprocess.run(cmd, check=True)

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
