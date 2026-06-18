"""
Zotero 同步模块 - 文件导入模式 (零配置，无需 API)
下载文件 + 生成 RIS 导入文件，拖入 Zotero 即可完成入库。

输出:
  downloads/<课程名>/  <- 文件（自动检测扩展名）
  downloads/import.ris  <- 拖入 Zotero 完成导入
"""

import re
import time
from datetime import datetime
from pathlib import Path

import requests

from scraper import PDFResource

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"

# 已处理记录
SEEN_FILE = DOWNLOAD_DIR / ".seen.txt"

# Content-Type → 扩展名映射
CT_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/zip": ".zip",
}


def _sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def _sanitize_path(path_str: str) -> Path:
    parts = path_str.replace("\\", "/").split("/")
    safe_parts = [_sanitize(p) for p in parts if _sanitize(p)]
    return Path(*safe_parts) if safe_parts else Path()


def _ext_from_content_type(ct: str) -> str:
    """从 Content-Type 获取文件扩展名"""
    ct_lower = ct.split(";")[0].strip().lower()
    return CT_MAP.get(ct_lower, "")


def _load_seen() -> set:
    if not SEEN_FILE.exists():
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def _mark_seen(title: str):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "a", encoding="utf-8") as f:
        f.write(title.strip() + "\n")


def _download_file(session, pdf: PDFResource, folder_base: Path, safe_name: str) -> tuple:
    """下载文件，返回 (success, final_path)。根据 Content-Type 自动确定扩展名。"""
    # 先 HEAD 获取 Content-Type 确定扩展名
    try:
        head = session.head(pdf.pdf_url, timeout=30, allow_redirects=True)
        ct = head.headers.get("Content-Type", "")
        ext = _ext_from_content_type(ct)
    except requests.RequestException:
        ext = ""

    # 没有匹配的 Content-Type，尝试从 URL 推断
    if not ext:
        url_ext = Path(pdf.pdf_url.split("?")[0]).suffix.lower()
        if url_ext in (".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".txt", ".zip"):
            ext = url_ext

    # 避免双后缀：如果 safe_name 已经以 ext 结尾就不要再加
    if safe_name.lower().endswith(ext.lower()):
        file_path = folder_base / safe_name
    else:
        file_path = folder_base / f"{safe_name}{ext}"

    if file_path.exists():
        print(f"    [OK] already exists")
        return True, file_path

    folder_base.mkdir(parents=True, exist_ok=True)
    resp = session.get(pdf.pdf_url, timeout=120, stream=True)
    resp.raise_for_status()

    ct = resp.headers.get("Content-Type", "")
    if "html" in ct:
        sample = resp.text[:500].lower()
        if any(k in sample for k in ("login", "sso", "unauthorized", "error")):
            print("    [FAIL] response is login page, not a file")
            return False, None

    with open(file_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    print(f"    [OK] downloaded ({ext})")
    return True, file_path


def _ris_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", " ").replace("\r", "")


def rebuild_ris():
    """从 downloads/ 下所有已有文件重建 import.ris"""
    files = sorted(DOWNLOAD_DIR.rglob("*"))
    ris_lines = []
    count = 0

    for f in files:
        if not f.is_file() or f.name.startswith(".") or f.suffix.lower() not in (
            ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptm", ".potx",
        ):
            continue

        rel = f.relative_to(DOWNLOAD_DIR)
        parts = rel.parts
        course_name = parts[0]
        folder = "/".join(parts[1:-1]) if len(parts) > 2 else ""
        filename = f.stem

        ris_lines.append("TY  - GEN")
        ris_lines.append(f"TI  - {_ris_escape(filename)}")
        ris_lines.append("KW  - PKU教学网")
        ris_lines.append(f"KW  - {_ris_escape(course_name)}")
        info = f"来源: PKU 教学网 (Blackboard) | 课程: {course_name}"
        if folder:
            info += f" | 文件夹: {folder}"
        ris_lines.append(f"N1  - {info}")
        ris_lines.append(f"L1  - file:///{f.resolve().as_posix()}")
        ris_lines.append(f"DA  - {datetime.now().strftime('%Y/%m/%d')}")
        ris_lines.append("ER  - ")
        ris_lines.append("")
        count += 1

    ris_path = DOWNLOAD_DIR / "import.ris"
    with open(ris_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ris_lines))
    print(f"[OK] RIS regenerated: {count} items")
    return count


def sync_to_zotero(
    pdfs: list,
    session=None,
    delay: float = 1.0,
    skip_existing: bool = True,
) -> dict:
    """Download files and generate RIS import file."""
    if session is None:
        from auth import get_session
        session = get_session()

    seen = _load_seen() if skip_existing else set()
    downloaded_files = []
    stats = {"downloaded": 0, "skipped": 0, "failed": 0}

    for i, pdf in enumerate(pdfs, 1):
        tag = f"[{i}/{len(pdfs)}]"
        print(f"\n{tag} {pdf.course_name} > {pdf.resource_name[:60]}")

        if skip_existing and pdf.resource_name.strip() in seen:
            print("    [SKIP] already seen")
            stats["skipped"] += 1
            continue

        safe_name = _sanitize(pdf.resource_name)
        safe_course = _sanitize(pdf.course_name)
        folder_base = DOWNLOAD_DIR / safe_course
        if pdf.folder_path:
            folder_base = folder_base / _sanitize_path(pdf.folder_path)

        ok, file_path = _download_file(session, pdf, folder_base, safe_name)
        if ok and file_path:
            downloaded_files.append((pdf, file_path))
            _mark_seen(pdf.resource_name)
            stats["downloaded"] += 1
        else:
            stats["failed"] += 1

        if delay and i < len(pdfs):
            time.sleep(delay)

    if downloaded_files:
        rebuild_ris()

    return stats


if __name__ == "__main__":
    print(f"Download dir: {DOWNLOAD_DIR}")
    print(f"Seen records: {len(_load_seen())}")
