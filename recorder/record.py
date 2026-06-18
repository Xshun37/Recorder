import subprocess
import sys

if len(sys.argv) < 2:
    print("Usage: python record.py <output.wav> [duration_sec]")
    sys.exit(1)

from pathlib import Path

output_wav = Path(sys.argv[1]).resolve()
output_wav.parent.mkdir(parents=True, exist_ok=True)

duration = None

if len(sys.argv) >= 3:
    try:
        duration = int(sys.argv[2])
    except ValueError:
        print("Duration must be an integer (seconds)")
        sys.exit(1)

cmd = [
    "ffmpeg",
    "-y",
    "-f", "dshow",
    "-i", "audio=CABLE Output (VB-Audio Virtual Cable)",
]

if duration:
    cmd += ["-t", str(duration)]

cmd += [output_wav]

if duration:
    print(f"Recording to {output_wav} for {duration} seconds...")
else:
    print(f"Recording to {output_wav} until Ctrl+C...")

subprocess.run(cmd)
print("Recording finished!")
