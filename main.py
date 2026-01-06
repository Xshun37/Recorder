# /main.py
from pathlib import Path
from datetime import datetime
from record import record_audio
from transcribe_s import transcribe
from summarize import summarize_file
from make_md import generate_md

BASE = Path(__file__).resolve().parent
RECORDS = BASE / "records"
RECORDS.mkdir(exist_ok=True)

ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
out_dir = RECORDS / ts
out_dir.mkdir(exist_ok=True)

wav_file = out_dir / "audio.wav"

dur = input("Enter recording duration in seconds (blank = manual stop): ").strip()
duration = int(dur) if dur else None

print("===== Recording =====")
record_audio(str(wav_file), duration=duration)

print("===== Transcribing =====")
txt_file = transcribe(str(wav_file))
if not txt_file:
    print("Transcription failed.")
    exit(1)

print("===== Summarizing =====")
summary_file = summarize_file(str(txt_file))
if not summary_file:
    print("Summarization failed.")
    exit(1)

print("===== Generating Markdown =====")
md_file = generate_md(str(txt_file))
if not md_file:
    print("Markdown generation failed.")
    exit(1)

print("===== All done =====")
print(f"WAV: {wav_file}")
print(f"TXT: {txt_file}")
print(f"SUMMARY: {summary_file}")
print(f"Markdown: {md_file}")