#!/usr/bin/env python3
"""
PPT 识别结果可视化报告生成器
输入 PPT + analysis.json，输出单文件 HTML 对比报告。
"""

import sys
import json
import base64
import argparse
import tempfile
from pathlib import Path
from io import BytesIO
from datetime import datetime

import pythoncom
import win32com.client
from PIL import Image


def ppt_to_images(ppt_path: str, slide_nums: list[int], out_dir: Path) -> dict[int, Path]:
    """导出指定页为 PNG"""
    pythoncom.CoInitialize()
    ppt = None
    presentation = None
    result = {}

    try:
        ppt = win32com.client.Dispatch("PowerPoint.Application")
        abs_path = str(Path(ppt_path).resolve())
        presentation = ppt.Presentations.Open(abs_path, WithWindow=False)

        for num in slide_nums:
            out_path = out_dir / f"slide_{num:03d}.png"
            if not out_path.exists():
                presentation.Slides(num).Export(str(out_path), "PNG", 1920, 1080)
            result[num] = out_path
        return result
    finally:
        if presentation:
            presentation.Close()
        if ppt:
            ppt.Quit()
        pythoncom.CoUninitialize()


def img_to_b64_data_uri(img_path: Path, max_size: int = 1024) -> str:
    """图片转 data URI (缩略图)"""
    img = Image.open(img_path)
    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=75)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


def build_html(analysis_data: dict, image_map: dict[int, Path]) -> str:
    """生成单文件 HTML"""
    slides = analysis_data["slides"]
    summary = analysis_data["summary"]
    model = analysis_data["model"]
    filename = Path(analysis_data["file"]).name

    # 按 slide 编号排序
    slides.sort(key=lambda s: s["slide"])

    slide_cards = []
    for s in slides:
        num = s["slide"]
        img_path = image_map.get(num)
        img_html = ""
        if img_path and img_path.exists():
            data_uri = img_to_b64_data_uri(img_path)
            img_html = f'<div class="slide-img"><img src="{data_uri}" alt="Slide {num}" onclick="this.classList.toggle(\'zoomed\')" title="Click to zoom"></div>'
        else:
            img_html = '<div class="slide-img missing">[Image not found]</div>'

        content = s.get("content", "[No analysis]")
        # 简单的 markdown -> html
        content_html = (
            content
            .replace("## 关键元素", '<h3 class="section-title">关键元素</h3>')
            .replace("## 内容概括", '<h3 class="section-title">内容概括</h3>')
            .replace("\n\n", "</p><p>")
            .replace("\n", "<br>")
        )
        content_html = f"<p>{content_html}</p>"

        cost_info = f"in={s['tokens_in']} out={s['tokens_out']} CNY{s['cost_yuan']:.4f}"

        slide_cards.append(f"""
        <div class="slide-card" id="slide-{num}">
            <div class="slide-header">
                <span class="slide-num">Slide {num}</span>
                <span class="slide-cost">{cost_info}</span>
            </div>
            <div class="slide-body">
                {img_html}
                <div class="slide-analysis">{content_html}</div>
            </div>
        </div>""")

    # 统计
    cost_per_slide = [s["cost_yuan"] for s in slides if s["cost_yuan"] > 0]
    out_tokens = [s["tokens_out"] for s in slides if s["tokens_out"] > 0]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PPT 识别报告 - {filename}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; }}
.header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; padding: 24px 32px; position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,.15); }}
.header h1 {{ font-size: 20px; margin-bottom: 8px; }}
.header .meta {{ font-size: 13px; opacity: .85; display: flex; gap: 24px; flex-wrap: wrap; }}
.header .meta span {{ white-space: nowrap; }}
.stats-bar {{ display: flex; gap: 16px; padding: 16px 32px; background: #fff; border-bottom: 1px solid #e0e0e0; flex-wrap: wrap; }}
.stat {{ background: #f8f9fa; border-radius: 8px; padding: 12px 18px; min-width: 120px; }}
.stat .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .5px; }}
.stat .value {{ font-size: 22px; font-weight: 700; color: #333; margin-top: 2px; }}
.stat .value.big {{ color: #667eea; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px 32px; }}
.nav {{ position: fixed; right: 16px; top: 50%; transform: translateY(-50%); z-index: 99; display: flex; flex-direction: column; gap: 2px; background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,.1); padding: 6px; max-height: 70vh; overflow-y: auto; }}
.nav a {{ display: block; padding: 4px 10px; font-size: 11px; color: #999; text-decoration: none; border-radius: 4px; text-align: center; }}
.nav a:hover {{ background: #667eea; color: #fff; }}
.slide-card {{ background: #fff; border-radius: 12px; margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
.slide-header {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; background: #fafafa; border-bottom: 1px solid #eee; }}
.slide-num {{ font-weight: 700; font-size: 15px; color: #667eea; }}
.slide-cost {{ font-size: 12px; color: #999; font-family: "SF Mono", "Cascadia Code", monospace; }}
.slide-body {{ display: flex; gap: 0; }}
.slide-img {{ flex: 0 0 50%; max-width: 50%; padding: 12px; display: flex; align-items: flex-start; justify-content: center; background: #f8f8f8; }}
.slide-img img {{ width: 100%; height: auto; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,.1); cursor: pointer; transition: transform .2s; }}
.slide-img img.zoomed {{ transform: scale(1.8); box-shadow: 0 8px 32px rgba(0,0,0,.3); position: relative; z-index: 200; }}
.slide-img.missing {{ color: #ccc; font-style: italic; display: flex; align-items: center; justify-content: center; min-height: 200px; }}
.slide-analysis {{ flex: 0 0 50%; max-width: 50%; padding: 16px 20px; font-size: 14px; line-height: 1.7; overflow-y: auto; max-height: 600px; }}
.slide-analysis p {{ margin-bottom: 8px; }}
.section-title {{ font-size: 15px; color: #667eea; margin: 12px 0 6px; padding-bottom: 4px; border-bottom: 2px solid #667eea; display: inline-block; }}
.footer {{ text-align: center; padding: 32px; color: #aaa; font-size: 12px; }}
@media (max-width: 900px) {{
    .slide-body {{ flex-direction: column; }}
    .slide-img, .slide-analysis {{ flex: 1 1 100%; max-width: 100%; }}
    .slide-analysis {{ max-height: none; }}
    .nav {{ display: none; }}
    .stats-bar {{ padding: 12px 16px; gap: 8px; }}
    .stat {{ min-width: 80px; padding: 8px 12px; }}
    .stat .value {{ font-size: 18px; }}
}}
</style>
</head>
<body>

<div class="header">
    <h1>PPT Recognition Report</h1>
    <div class="meta">
        <span>File: {filename}</span>
        <span>Model: {model}</span>
        <span>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
    </div>
</div>

<div class="stats-bar">
    <div class="stat">
        <div class="label">Slides</div>
        <div class="value">{analysis_data["total_slides"]}</div>
    </div>
    <div class="stat">
        <div class="label">Total Tokens</div>
        <div class="value">{summary["tokens_in"] + summary["tokens_out"]:,}</div>
    </div>
    <div class="stat">
        <div class="label">Total Cost</div>
        <div class="value big">CNY{summary["cost_yuan"]:.4f}</div>
    </div>
    <div class="stat">
        <div class="label">Avg / Slide</div>
        <div class="value">CNY{summary["cost_yuan"] / analysis_data["total_slides"]:.4f}</div>
    </div>
    <div class="stat">
        <div class="label">Elapsed</div>
        <div class="value">{summary.get("elapsed_seconds", "?")}s</div>
    </div>
    <div class="stat">
        <div class="label">Avg Out Tokens/Slide</div>
        <div class="value">{sum(out_tokens) // max(len(out_tokens), 1):,}</div>
    </div>
    <div class="stat">
        <div class="label">Cheapest/Dearest</div>
        <div class="value">CNY{min(cost_per_slide):.3f} ~ {max(cost_per_slide):.3f}</div>
    </div>
</div>

<nav class="nav">
    {''.join(f'<a href="#slide-{s["slide"]}">{s["slide"]}</a>' for s in slides)}
</nav>

<div class="container">
    {''.join(slide_cards)}
</div>

<div class="footer">
    Generated by ppt_vision_test.py + Qwen3.6-Plus
</div>

</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML visualization report")
    parser.add_argument("analysis_json", help="Path to analysis.json")
    parser.add_argument("--ppt", default=None, help="PPT file path (auto-detected from JSON if omitted)")
    parser.add_argument("--output", default=None, help="Output HTML path (default: next to JSON)")
    parser.add_argument("--image-dir", default=None, help="Reuse existing slide images dir")
    args = parser.parse_args()

    # 读 JSON
    json_path = Path(args.analysis_json)
    if not json_path.exists():
        print(f"[ERROR] JSON not found: {json_path}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 确定 PPT 路径
    ppt_path = args.ppt or data.get("file", "")
    if not ppt_path or not Path(ppt_path).exists():
        # 尝试从 JSON 同目录推断
        ppt_path = json_path.with_suffix(".pptx")
        if not ppt_path.exists():
            ppt_path = json_path.with_suffix(".ppt")
        if not ppt_path.exists():
            print(f"[ERROR] Cannot find PPT file. Use --ppt to specify.")
            sys.exit(1)

    print(f"PPT: {ppt_path}")
    print(f"JSON: {json_path}")
    print(f"Slides: {data['total_slides']}")

    # 获取需要的页码
    slide_nums = [s["slide"] for s in data["slides"]]

    # 导出图片
    img_dir = None
    if args.image_dir:
        img_dir = Path(args.image_dir)
        print(f"Using existing images: {img_dir}")
        image_map = {num: img_dir / f"slide_{num:03d}.png" for num in slide_nums}
    else:
        img_dir = Path(tempfile.mkdtemp(prefix="ppt_report_"))
        print(f"Exporting {len(slide_nums)} slides to {img_dir} ...")
        image_map = ppt_to_images(ppt_path, slide_nums, img_dir)
        print(f"  Done: {len(image_map)} images")

    # 生成 HTML
    html = build_html(data, image_map)

    out_path = Path(args.output) if args.output else json_path.with_suffix(".html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[OK] Report saved: {out_path}")
    print(f"      Size: {len(html):,} bytes")
    print(f"\n  Open in browser: file:///{out_path.resolve().as_posix()}")


if __name__ == "__main__":
    main()
