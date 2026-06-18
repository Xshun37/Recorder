#!/usr/bin/env python3
"""
PKU 教学网 课件下载 + AI 解析 + Zotero 导入

用法:
  python main.py                    # 交互式选课程
  python main.py --course "分子生物学"  # 直接指定
  python main.py --all              # 全部课程
  python main.py --skip-analysis    # 只下载导入，不分析
  python main.py --analysis-only    # 对已下载文件直接分析
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_selection(choice, max_n):
    """解析用户选择: '1,2,5-8' -> set of 0-based indices"""
    if not choice.strip():
        return set(range(max_n))
    result = set()
    for part in choice.replace(" ", "").split(","):
        if "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit():
                result.update(range(int(a) - 1, min(int(b), max_n)))
        elif part.isdigit():
            n = int(part) - 1
            if 0 <= n < max_n:
                result.add(n)
    return result


def interactive_select_courses():
    """显示课程列表，让用户选择"""
    from scraper import get_courses

    courses = get_courses()
    if not courses:
        print("[ERROR] No courses found")
        return []

    print(f"\n{'='*60}")
    print(f"  PKU 教学网 — 课件下载与分析")
    print(f"{'='*60}")
    print(f"  共 {len(courses)} 门课程\n")

    for i, c in enumerate(courses, 1):
        print(f"  [{i:2d}] {c.name}")

    print(f"\n  输入序号选择课程 (如: 1,3,5-8 或 留空全选)")
    choice = input("  > ").strip()

    indices = parse_selection(choice, len(courses))
    selected = [courses[i] for i in sorted(indices)]

    if selected:
        print(f"\n  已选择 {len(selected)} 门课程:")
        for c in selected:
            print(f"    - {c.name}")
        input("\n  按 Enter 开始下载...")

    return selected


def scan_pdfs(force=False):
    """扫描 downloads/ 下所有 PDF，跳过已有 .analysis.json 的（除非 force）。"""
    import os
    from zotero_sync import DOWNLOAD_DIR
    from pipeline_core import db_import_file

    result = []
    for root, dirs, files in os.walk(DOWNLOAD_DIR):
        for f in files:
            if not f.lower().endswith('.pdf'): continue
            if "annotated" in f.lower(): continue
            fp = Path(root) / f
            if not force and fp.with_suffix('.analysis.json').exists():
                continue
            rel = fp.relative_to(DOWNLOAD_DIR)
            parts = rel.parts
            course = parts[0] if len(parts) > 1 else ""
            folder = "/".join(parts[1:-1]) if len(parts) > 2 else ""
            pid = db_import_file(fp, course, folder)
            result.append((fp, pid, f))
    return result


def download_course(course):
    """下载单个课程的所有资源。只下载新增/更新的文件。"""
    from auth import get_session
    from scraper import get_pdfs
    from zotero_sync import sync_to_zotero

    session = get_session()
    pdfs = get_pdfs(session, [course], delay=1.0)
    if not pdfs:
        print(f"  [SKIP] No resources found")
        return 0, 0

    stats = sync_to_zotero(pdfs, session=session, delay=1.0, skip_existing=True)
    return stats["downloaded"], stats["failed"]


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--course", type=str, help="课程名关键词")
    p.add_argument("--all", action="store_true", help="全部课程")
    p.add_argument("--skip-analysis", action="store_true", help="只下载，不分析")
    p.add_argument("--analysis-only", action="store_true", help="对已下载 PDF 直接分析")
    p.add_argument("--force", action="store_true", help="重新分析已有 analysis.json 的文件")
    p.add_argument("--concurrency", type=int, default=12, help="Qwen API 并发数")
    args = p.parse_args()

    # ---- 选课程 ----
    if args.analysis_only:
        print("=" * 60)
        print("Analysis-only mode: scanning downloads/ for PDFs...")
        print("=" * 60)

        pdfs_to_analyze = scan_pdfs(force=args.force)
        for fp, pid, fname in pdfs_to_analyze:
            print(f"  [{pid}] {fname}")
    else:
        from scraper import get_courses, Course

        all_courses = get_courses()

        if args.all:
            selected = all_courses
        elif args.course:
            selected = [c for c in all_courses if args.course in c.name]
            if not selected:
                print(f"[ERROR] No course matching '{args.course}'")
                return
        else:
            selected = interactive_select_courses()

        if not selected:
            print("No courses selected. Exiting.")
            return

        # ---- Step 1: 下载 ----
        print(f"\n{'='*60}")
        print(f"Step 1: Download ({len(selected)} courses)")
        print(f"{'='*60}")
        total_dl, total_fail = 0, 0
        for c in selected:
            print(f"\n  [{c.name}]")
            dl, fail = download_course(c)
            total_dl += dl
            total_fail += fail
        print(f"\n  Downloaded: {total_dl}, Failed: {total_fail}")

        # ---- Step 2: PPT -> PDF ----
        print(f"\n{'='*60}")
        print(f"Step 2: Convert PPT/PPTX -> PDF")
        print(f"{'='*60}")
        from zotero_sync import DOWNLOAD_DIR
        from pipeline_core import convert_all_ppts
        converted = convert_all_ppts(DOWNLOAD_DIR)
        print(f"  Converted: {len(converted)} files")

        # ---- Step 3: Import into Zotero ----
        print(f"\n{'='*60}")
        print(f"Step 3: Import PDFs into Zotero")
        print(f"{'='*60}")
        pdfs_to_analyze = scan_pdfs(force=args.force)
        for fp, pid, fname in pdfs_to_analyze:
            print(f"  [{pid}] {fname}")
        print(f"  To analyze: {len(pdfs_to_analyze)} PDFs")

        if args.skip_analysis:
            print("\n[SKIP] Analysis.")
            return

    # ---- Step 4-5: 分析 + 写入 Zotero ----
    if not pdfs_to_analyze:
        print("No PDFs to analyze.")
        return

    print(f"\n{'='*60}")
    print(f"Step 4: Qwen3.7-Plus AI Analysis")
    print(f"{'='*60}")

    from pipeline_core import analyze_pdf, write_note_to_zotero
    import json, pipeline_core as pc
    from datetime import datetime

    pc.CONCURRENCY = args.concurrency

    total_cost = 0.0
    for i, (fp, pid, fname) in enumerate(pdfs_to_analyze, 1):
        print(f"\n[{i}/{len(pdfs_to_analyze)}] {fname}")
        results, cost = analyze_pdf(fp)
        total_cost += cost
        print(f"  Cost: CNY{cost:.4f}")

        with open(fp.with_suffix(".analysis.json"), "w", encoding="utf-8") as jf:
            json.dump({
                "file": str(fp.resolve()), "model": pc.MODEL,
                "timestamp": datetime.now().isoformat(), "total_pages": len(results),
                "summary": {"cost_yuan": round(cost, 6)}, "slides": results,
            }, jf, ensure_ascii=False, indent=2)

        write_note_to_zotero(pid, fname, results)

    print(f"\n{'='*60}")
    print(f"Complete! {len(pdfs_to_analyze)} PDFs, total cost: CNY{total_cost:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
