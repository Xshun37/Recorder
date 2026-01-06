# /record.py
from pathlib import Path
import subprocess

def record_audio(output_wav: str, duration: int | None = None):
    """
    傻瓜式录音函数，使用 ffmpeg 录制音频。

    :param output_wav: 输出 WAV 文件路径
    :param duration: 可选，录音时长（秒），None 表示手动停止 Ctrl+C
    """
    output_wav_ = Path(output_wav).resolve()
    output_wav_.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "dshow",
        "-i", "audio=CABLE Output (VB-Audio Virtual Cable)",
    ]

    if duration:
        cmd += ["-t", str(duration)]

    cmd += [str(output_wav_)]

    if duration:
        print(f"Recording to {output_wav_} for {duration} seconds...")
    else:
        print(f"Recording to {output_wav_} until Ctrl+C...")

    subprocess.run(cmd, check=True)
    print("Recording finished!")


# -----------------------------
# 兼容命令行调用
# -----------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python record.py <output.wav> [duration_sec]")
        sys.exit(1)

    wav_path = sys.argv[1]
    dur = None
    if len(sys.argv) >= 3:
        try:
            dur = int(sys.argv[2])
        except ValueError:
            print("Duration must be an integer (seconds)")
            sys.exit(1)

    record_audio(wav_path, dur)