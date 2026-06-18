#!/usr/bin/env python3
"""
PKU 教学网 → 全流程自动化

下载 → PPT转PDF → 导入Zotero → Qwen分析 → 笔记注入

用法:
  python main.py --all                   # 全部课程
  python main.py --course "分子生物学"    # 按关键词筛选
  python main.py --dry-run               # 仅预览
  python main.py --skip-analysis         # 只下载+导入, 不分析
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import get_session
from scraper import get_courses, get_pdfs
from zotero_sync import sync_to_zotero, DOWNLOAD_DIR


def main():
    parser = argparse.ArgumentParser(description="PKU 教学网 全流程自动化")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--all", action="store_true")
    action.add_argument("--course", type=str)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--skip-analysis", action="store_true")
    args = parser.parse_args()

    # Step 1: Download
    print("=" * 60)
    print("Step 1: Download course materials")
    print("=" * 60)
    session = get_session()
    courses = get_courses(session)
    if not courses:
        print("[ERROR] No courses found"); return

    course_filter = args.course if args.course else None
    pdfs = get_pdfs(session, courses, course_filter=course_filter, delay=args.delay)
    if not pdfs:
        print("[INFO] No resources found"); return

    print(f"\n  Found: {len(pdfs)} resources")
    for p in pdfs:
        folder = f" [{p.folder_path}]" if p.folder_path else ""
        print(f"    {p.course_name}{folder} > {p.resource_name}")

    if args.dry_run:
        print("\n[DRY-RUN] Done."); return

    stats = sync_to_zotero(pdfs, session=session, delay=args.delay, skip_existing=not args.no_dedup)
    print(f"  Downloaded: {stats['downloaded']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")

    # Step 2: PPT → PDF
    print("\n" + "=" * 60)
    print("Step 2: Convert PPT/PPTX → PDF")
    print("=" * 60)
    from pipeline_core import convert_all_ppts
    converted = convert_all_ppts(DOWNLOAD_DIR)
    print(f"  Converted: {len(converted)} files")

    # Step 3: Import all PDFs into Zotero
    print("\n" + "=" * 60)
    print("Step 3: Import PDFs into Zotero")
    print("=" * 60)
    from pipeline_core import db_import_file
    import os
    pdfs_to_analyze = []
    for root, dirs, files in os.walk(DOWNLOAD_DIR):
        for f in files:
            if not f.lower().endswith('.pdf'): continue
            if "annotated" in f.lower(): continue
            fp = Path(root) / f
            rel = fp.relative_to(DOWNLOAD_DIR)
            parts = rel.parts
            course = parts[0] if len(parts) > 1 else ""
            folder = "/".join(parts[1:-1]) if len(parts) > 2 else ""
            pid = db_import_file(fp, course, folder)
            pdfs_to_analyze.append((fp, pid, f))
            print(f"  [{pid}] {f}")
    print(f"  Imported: {len(pdfs_to_analyze)} PDFs")

    if args.skip_analysis:
        print("\n[SKIP] Analysis. Open Zotero and run:")
        print("  python -c \"from pipeline_core import run_full_pipeline; run_full_pipeline(skip_download=True)\"")
        return

    # Step 4-5: Analyze + Write notes
    print("\n" + "=" * 60)
    print("Step 4: Qwen3.7-Plus AI Analysis")
    print("=" * 60)
    from pipeline_core import analyze_pdf, write_note_to_zotero
    import json
    from datetime import datetime

    total_cost = 0.0
    for i, (fp, pid, fname) in enumerate(pdfs_to_analyze, 1):
        print(f"\n[{i}/{len(pdfs_to_analyze)}] {fname}")
        results, cost = analyze_pdf(fp)
        total_cost += cost
        print(f"  Cost: CNY{cost:.4f}")

        # Save analysis.json
        with open(fp.with_suffix(".analysis.json"), "w", encoding="utf-8") as jf:
            json.dump({
                "file": str(fp.resolve()), "model": "qwen3.7-plus",
                "timestamp": datetime.now().isoformat(), "total_pages": len(results),
                "summary": {"cost_yuan": round(cost, 6)}, "slides": results,
            }, jf, ensure_ascii=False, indent=2)

        # Write Zotero note
        write_note_to_zotero(pid, fname, results)

    print(f"\n{'='*60}")
    print(f"Complete! {len(pdfs_to_analyze)} PDFs, total cost: CNY{total_cost:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
