import sys
from pathlib import Path
from datetime import datetime

if len(sys.argv) < 2:
    print("用法: python make_md.py 原文.txt")
    sys.exit(1)

wav_path = Path(sys.argv[1])
txt_path = wav_path.with_suffix(".s.txt")           # 注意读取 .s.txt 文件
summary_path = wav_path.with_suffix(".s.summary.txt")  # AI 总结文件

raw = txt_path.read_text(encoding="utf-8")
summary = summary_path.read_text(encoding="utf-8")

now = datetime.now().strftime("%Y-%m-%d %H:%M")

md_path = txt_path.with_suffix(".md")
md_path.write_text(f"""# 录音摘要（{now}）

## AI 总结

{summary}
""", encoding="utf-8")

print(f"Markdown 已生成: {md_path}")
