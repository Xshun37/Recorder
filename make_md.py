# /make_md.py
from pathlib import Path
from datetime import datetime

def generate_md(wav_path: str):
    """
    生成 Markdown 文件，基于 .s.txt 和 .s.summary.txt 文件
    :param wav_path: 原始音频文件路径（.wav）
    """
    wav_path_ = Path(wav_path)
    txt_path = wav_path_.with_suffix(".s.txt")            # 繁转简后的文本
    summary_path = wav_path_.with_suffix(".s.summary.txt")  # AI 总结文件

    if not txt_path.exists():
        raise FileNotFoundError(f"文本文件不存在: {txt_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"总结文件不存在: {summary_path}")

    summary = summary_path.read_text(encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    md_path = txt_path.with_suffix(".md")
    md_path.write_text(f"""# 录音摘要（{now}）

## AI 总结

{summary}
""", encoding="utf-8")

    print(f"Markdown 已生成: {md_path}")
    return md_path


# -----------------------------
# CLI 兼容
# -----------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python make_md.py 原文.wav")
        sys.exit(1)

    generate_md(sys.argv[1])