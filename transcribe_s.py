# /transcribe_s.py
from pathlib import Path
from opencc import OpenCC
import whisper
import torch
import sys

def transcribe(audio_file: str, device: str = "cuda", model: str = "medium"):
    """
    傻瓜式转录音频文件并生成繁转简文本。
    
    :param audio_file: 音频文件路径
    :param device: whisper 运行设备，可选 'cuda' 或 'cpu'
    :param model: whisper 模型大小，例如 'tiny', 'base', 'small', 'medium', 'large'
    """
    audio = Path(audio_file).resolve()
    out_dir = audio.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Transcribing {audio} with whisper model {model} on {device}...")

    if device == "cuda" and not torch.cuda.is_available():
        print("CUDA is not available, switching to CPU.")
        device = "cpu"

    # 1️⃣ 加载模型
    model_obj = whisper.load_model(model, device=device)

    # 2️⃣ 转录
    result = model_obj.transcribe(str(audio), language="zh")
    text = result.get("text", "")

    # 如果 text 可能是列表，统一转换成 str
    if isinstance(text, list):
        text = "".join(text)  # 合并所有段落

    # 3️⃣ 写原文 txt 文件（可选保留）
    txt_file = out_dir / f"{audio.stem}.txt"
    txt_file.write_text(text, encoding="utf-8")

    # 4️⃣ 繁体转简体
    out_file = out_dir / f"{audio.stem}.s.txt"
    cc = OpenCC("t2s")
    out_file.write_text(cc.convert(text), encoding="utf-8")

    print(f"Transcription and conversion done: {out_file}")
    return out_file

# -----------------------------
# CLI 兼容
# -----------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe_s.py <audio_file>")
        sys.exit(1)

    transcribe(sys.argv[1])