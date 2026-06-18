#!/usr/bin/env python3
"""
PKU 教学网 课件下载 + RIS 生成

用法:
  python main.py                    # 交互式选课程
  python main.py --course "分子生物学"  # 直接指定
  python main.py --all              # 全部课程
  python main.py --skip-ppt         # 跳过 PPT→PDF 转换

下载完成后：
  ① 关闭 Zotero
  ② 把 downloads/import.ris 拖入 Zotero 窗口
  ③ 关闭 Zotero
  ④ python analyze.py              # AI 解析
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_selection(choice, max_n):
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
    from scraper import get_courses

    courses = get_courses()
    if not courses:
        print("[ERROR] No courses found")
        return []

    print(f"\n{'='*60}")
    print(f"  PKU 教学网 — 课件下载")
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


def download_course(course):
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
    p = argparse.ArgumentParser(description="PKU 教学网课件下载")
    p.add_argument("--course", type=str, help="课程名关键词")
    p.add_argument("--all", action="store_true", help="全部课程")
    p.add_argument("--skip-ppt", action="store_true", help="跳过 PPT→PDF 转换")
    args = p.parse_args()

    from scraper import get_courses

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

    # ---- Step 1: Download ----
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
    if not args.skip_ppt:
        print(f"\n{'='*60}")
        print(f"Step 2: Convert PPT/PPTX -> PDF")
        print(f"{'='*60}")
        from zotero_sync import DOWNLOAD_DIR
        from pipeline_core import convert_all_ppts
        converted = convert_all_ppts(DOWNLOAD_DIR)
        print(f"  Converted: {len(converted)} files")

    # ---- Step 3: RIS export ----
    print(f"\n{'='*60}")
    print(f"Step 3: RIS import file")
    print(f"{'='*60}")
    from zotero_sync import rebuild_ris
    count = rebuild_ris()
    print(f"  Exported: {count} items → downloads/import.ris")

    # ---- Next steps ----
    print(f"\n{'='*60}")
    print(f"下一步:")
    print(f"  ① 关闭 Zotero")
    print(f"  ② 拖入 downloads/import.ris 到 Zotero")
    print(f"  ③ 关闭 Zotero")
    print(f"  ④ python analyze.py  # AI 解析")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
