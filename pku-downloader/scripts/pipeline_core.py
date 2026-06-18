#!/usr/bin/env python3
"""
统一管道核心：PPT→PDF / RIS生成 / Zotero导入 / Qwen分析 / 笔记注入。
所有子功能收敛到此文件。
"""

import os, sys, json, sqlite3, random, string, re, base64, threading, tempfile, io
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import fitz
import pythoncom, win32com.client
from openai import OpenAI
from PIL import Image

# ==================== 配置 ====================
from dotenv import load_dotenv
_env_dir = Path(__file__).resolve().parent
for _ in range(5):
    for _name in (".env", "../recorder/.env"):
        _env_path = (_env_dir / _name).resolve()
        if _env_path.exists():
            load_dotenv(_env_path)
            break
    if _env_path.exists():
        break
    _env_dir = _env_dir.parent

def _find_zotero_db():
    """Auto-detect Zotero database. Returns None if not found."""
    candidates = []

    # 1. Env var (highest priority)
    env = os.getenv("ZOTERO_DB_PATH", "")
    if env:
        p = Path(env)
        if p.exists() and p.stat().st_size > 0:
            return p

    appdata = os.getenv("APPDATA", "")

    # 2. Standard profile dir under APPDATA
    if appdata:
        profiles = Path(appdata) / "Zotero" / "Zotero" / "Profiles"
        if profiles.exists():
            for p in profiles.glob("*.default*"):
                db = p / "zotero.sqlite"
                if db.exists():
                    candidates.append(db)

        direct = Path(appdata) / "Zotero" / "zotero.sqlite"
        if direct.exists():
            candidates.append(direct)

    # 3. Scan drives D: through G: for common Zotero data dirs
    import string
    zotero_data_dirs = [
        "Zotero",
        "文献/Zotero",
        "Documents/Zotero",
    ]
    for drive_letter in "DEFG":
        for data_dir in zotero_data_dirs:
            # Profile -> zotero.sqlite
            profiles = Path(f"{drive_letter}:\\{data_dir}") / "Profiles"
            if profiles.exists():
                for p in profiles.glob("*.default*"):
                    db = p / "zotero.sqlite"
                    if db.exists():
                        candidates.append(db)
            # Direct zotero.sqlite
            db = Path(f"{drive_letter}:\\{data_dir}") / "zotero.sqlite"
            if db.exists():
                candidates.append(db)
        # Also F:\文献\zotero.sqlite (bare, no Zotero wrapper)
        db = Path(f"{drive_letter}:\\文献\\zotero.sqlite")
        if db.exists():
            candidates.append(db)

    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return None

ZOTERO_DB = _find_zotero_db()
if ZOTERO_DB:
    # 验证 DB 确实有 Zotero 表结构
    try:
        db = sqlite3.connect(str(ZOTERO_DB))
        db.execute("SELECT 1 FROM items LIMIT 1")
        db.close()
    except sqlite3.OperationalError:
        print("[WARN] Found file at Zotero path but it is not a valid Zotero DB. Ignoring.")
        ZOTERO_DB = None
else:
    print("[WARN] Zotero DB not found. Zotero integration disabled.")
API_KEY = os.getenv("QWEN_API_KEY", "")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.7-plus"
PRICE_INPUT = 1.6
PRICE_OUTPUT = 6.4
CONCURRENCY = 12
KEY_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_print_lock = threading.Lock()

SYSTEM_PROMPT = """You are an expert in biochemistry, genomics and molecular biology. The user will show you a slide from a lecture.

Your response MUST follow this structure:

<h2>图片内容翻译与解析</h2>
- Identify every biological term, label, and concept shown on this slide
- Translate them into Chinese and explain what each element means
- Do NOT describe visual layout — focus on the scientific meaning of the content

<h2>知识拓展</h2>
- Extend with foundational biological knowledge a student needs to understand this topic
- Explain underlying principles, mechanisms, and biological significance
- Include comparisons, examples, or context that help learning
- Use <table> tags for comparison tables

CRITICAL: Output raw HTML directly. Use <b>bold</b>, <h2>, <h3>, <p>, <ul>, <li>, <table>, <thead>, <tbody>, <tr>, <th>, <td>, <sup>, <sub>. Do NOT use markdown. Output in Simplified Chinese.
"""

# ==================== DB helpers ====================
def db_get_keys(cur):
    cur.execute("SELECT key FROM items")
    return set(r[0] for r in cur.fetchall())

def db_gen_key(existing):
    while True:
        k = ''.join(random.choices(KEY_CHARS, k=8))
        if k not in existing: return k

# ==================== DB lookup ====================
def db_find_parent_by_file(file_path):
    """
    在 Zotero DB 中查找引用指定文件的条目（RIS 导入后创建）。
    返回 parentItemID 或 None。
    """
    if not ZOTERO_DB:
        return None
    fname = Path(file_path).name
    db = sqlite3.connect(str(ZOTERO_DB))
    cur = db.cursor()
    # 附件 path 可能是 "storage:xxx" 或绝对路径
    cur.execute("""
        SELECT IA.parentItemID FROM itemAttachments IA
        WHERE IA.path LIKE ? OR IA.path = ?
    """, (f"%{fname}", f"storage:{fname}"))
    row = cur.fetchone()
    db.close()
    return row[0] if row else None


def db_ensure_collections(file_path, course_name):
    """
    确保 Zotero 中存在 'PKU教学网 → 课程名' 子分类，并把匹配到的条目归入。
    （仅在 db_find_parent_by_file 找到条目时调用，避免空条目）
    """
    if not ZOTERO_DB or not course_name:
        return
    pid = db_find_parent_by_file(file_path)
    if not pid:
        return
    db = sqlite3.connect(str(ZOTERO_DB))
    cur = db.cursor()
    cur.execute("SELECT libraryID FROM items LIMIT 1")
    lib_id = cur.fetchone()[0]

    # 查找或创建 "PKU教学网" 父 collection
    cur.execute("SELECT collectionID FROM collections WHERE collectionName = 'PKU教学网' AND libraryID = ?", (lib_id,))
    r = cur.fetchone()
    if r:
        parent_col_id = r[0]
    else:
        k = ''.join(random.choices(KEY_CHARS, k=8))
        cur.execute("INSERT INTO collections (collectionName, libraryID, key, version, synced) VALUES ('PKU教学网', ?, ?, 0, 0)", (lib_id, k))
        parent_col_id = cur.lastrowid

    # 查找或创建课程子 collection
    cur.execute("SELECT collectionID FROM collections WHERE collectionName = ? AND parentCollectionID = ?", (course_name, parent_col_id))
    r = cur.fetchone()
    if r:
        col_id = r[0]
    else:
        k = ''.join(random.choices(KEY_CHARS, k=8))
        cur.execute("INSERT INTO collections (collectionName, parentCollectionID, libraryID, key, version, synced) VALUES (?, ?, ?, ?, 0, 0)",
                    (course_name, parent_col_id, lib_id, k))
        col_id = cur.lastrowid

    cur.execute("INSERT OR IGNORE INTO collectionItems (collectionID, itemID) VALUES (?, ?)", (col_id, pid))
    db.commit()
    db.close()


# 替换旧 db_import_file，保持 main.py 兼容
def db_import_file(file_path, course_name, folder_path=""):
    """
    兼容接口：不再创建 Zotero 条目。仅确保 collection 存在并返回已导入的 pid。
    """
    if not ZOTERO_DB:
        return None
    db_ensure_collections(file_path, course_name)
    return db_find_parent_by_file(file_path)

# ==================== PPT -> PDF ====================
def ppt_to_pdf(ppt_path, out_dir):
    """Convert a single PPT/PPTX to PDF. Returns Path to output PDF."""
    out_pdf = out_dir / (Path(ppt_path).stem + ".pdf")
    if out_pdf.exists(): return out_pdf

    pythoncom.CoInitialize()
    ppt = pres = None
    try:
        ppt = win32com.client.Dispatch("PowerPoint.Application")
        pres = ppt.Presentations.Open(str(Path(ppt_path).resolve()), WithWindow=False)
        pres.ExportAsFixedFormat(str(out_pdf.resolve()), 32)  # 32 = ppFixedFormatTypePDF
        pres.Close()
        return out_pdf
    finally:
        if pres: pres.Close()
        if ppt: ppt.Quit()
        pythoncom.CoUninitialize()

def convert_all_ppts(root_dir):
    """Recursively convert all PPT/PPTX files under root_dir to PDF."""
    converted = []
    for ext in ("*.ppt", "*.pptx"):
        for f in Path(root_dir).rglob(ext):
            if ".analysis" in f.name: continue
            try:
                pdf = ppt_to_pdf(f, f.parent)
                converted.append((f, pdf))
                print(f"  PPT->PDF: {f.name} -> {pdf.name}")
            except Exception as e:
                print(f"  [FAIL] {f.name}: {e}")
    return converted

# ==================== PDF -> images ====================
def pdf_to_images(pdf_path, max_pages=200):
    doc = fitz.open(pdf_path)
    n = min(doc.page_count, max_pages)
    tmp = tempfile.mkdtemp(prefix="pdf_")
    paths = []
    for i in range(n):
        pix = doc[i].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        w, h = img.size
        if max(w, h) > 2048:
            scale = 2048 / max(w, h)
            img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
        p = os.path.join(tmp, f"{i+1:04d}.png")
        img.save(p, "PNG")
        paths.append((i+1, p))
    doc.close()
    return paths

def encode_image(path):
    img = Image.open(path)
    w, h = img.size; s = 2048 / max(w, h)
    img = img.resize((int(w*s), int(h*s)), Image.LANCZOS)
    buf = BytesIO()
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()

# ==================== Qwen analysis ====================
def analyze_page(page_num, total, b64):
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                    {"type": "text", "text": f"Page {page_num}/{total}. 讲解本页知识。"},
                ]}
            ],
            max_tokens=2500, temperature=0.1,
        )
        c = r.choices[0].message.content
        ti, to = r.usage.prompt_tokens, r.usage.completion_tokens
        cost = ti/1e6*PRICE_INPUT + to/1e6*PRICE_OUTPUT
        return {"slide": page_num, "content": c, "tokens_in": ti, "tokens_out": to, "cost_yuan": round(cost, 6)}
    except Exception as e:
        return {"slide": page_num, "content": f"[ERROR] {e}", "tokens_in": 0, "tokens_out": 0, "cost_yuan": 0.0}

def analyze_pdf(pdf_path):
    """Analyze entire PDF. Returns (results, total_cost)."""
    name = Path(pdf_path).name
    images = pdf_to_images(pdf_path)
    total = len(images)
    encoded = [(num, encode_image(p)) for num, p in images]

    results = []
    total_cost = 0.0
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futs = {pool.submit(analyze_page, num, total, b64): num for num, b64 in encoded}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            total_cost += r["cost_yuan"]
            if len(results) % 10 == 0:
                with _print_lock:
                    print(f"  [{len(results)}/{total}] CNY{total_cost:.4f}")
    results.sort(key=lambda x: x["slide"])
    return results, total_cost

# ==================== content -> HTML ====================
def content_to_html(c):
    c = c.strip()
    if c.startswith("<"): return c
    return _md_to_html(c)

def _md_to_html(md):
    html = md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    while "**" in html:
        html = html.replace("**", "<b>", 1)
        if "**" in html: html = html.replace("**", "</b>", 1)
    lines = html.split('\n')
    parts, in_list, in_table, header_used = [], False, False, False
    table_header = None
    for line in lines:
        t = line.strip()
        if t.startswith('|') and t.endswith('|') and '---' in t: continue
        if t.startswith('|') and t.endswith('|'):
            if in_list: parts.append('</ul>'); in_list = False
            cells = [c.strip() for c in t.split('|')[1:-1]]
            if not header_used:
                table_header = cells; header_used = True; continue
            if not in_table:
                parts.append('<table style="border-collapse:collapse;margin:8px 0;width:100%;font-size:13px"><thead><tr>')
                for h in table_header: parts.append(f'<th style="background:#f0ecf9;padding:6px 10px;border:1px solid #ddd;text-align:left;font-weight:700">{h}</th>')
                parts.append('</tr></thead><tbody>'); in_table = True
            parts.append('<tr>')
            for c in cells: parts.append(f'<td style="padding:6px 10px;border:1px solid #ddd;vertical-align:top">{c}</td>')
            parts.append('</tr>'); continue
        if in_table: parts.append('</tbody></table>'); in_table = False; header_used = False
        if not t:
            if in_list: parts.append('</ul>'); in_list = False; continue
        if t.startswith('#'):
            if in_list: parts.append('</ul>'); in_list = False
            lvl = min(len(t)-len(t.lstrip('#')), 3)
            parts.append(f'<h{lvl} style="color:#5b3cc4;margin:10px 0 4px">{t.lstrip("#").strip()}</h{lvl}>'); continue
        if t.startswith('- ') or t.startswith('* '):
            if not in_list: parts.append('<ul style="margin:2px 0;padding-left:16px">'); in_list = True
            parts.append(f'<li style="margin:2px 0">{t[2:]}</li>'); continue
        if in_list: parts.append('</ul>'); in_list = False
        parts.append(f'<p style="margin:2px 0 4px">{t}</p>')
    if in_list: parts.append('</ul>')
    if in_table: parts.append('</tbody></table>')
    return '\n'.join(parts)

# ==================== Zotero note write ====================
def write_note_to_zotero(parent_id, title, results):
    """Write merged analysis note to a Zotero item."""
    if not ZOTERO_DB or not parent_id:
        return
    db = sqlite3.connect(str(ZOTERO_DB))
    cur = db.cursor()

    # Kill old notes
    cur.execute("DELETE FROM items WHERE itemID IN (SELECT itemID FROM itemNotes WHERE parentItemID = ?)", (parent_id,))
    cur.execute("DELETE FROM itemNotes WHERE parentItemID = ?", (parent_id,))

    keys = db_get_keys(cur)
    header = f'<h1>{title} - AI 解析</h1><p style="color:#999;font-size:11px">{len(results)} 页 | {MODEL}</p><hr>'
    body = ""
    for r in sorted(results, key=lambda x: x["slide"]):
        body += f'<h2 style="color:#5b3cc4;margin-top:16px">Page {r["slide"]}</h2>'
        body += content_to_html(r.get("content", ""))

    html = '<div class="zotero-note znv1">' + header + body + '</div>'
    k = db_gen_key(keys); keys.add(k)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO items (itemTypeID,dateAdded,dateModified,clientDateModified,libraryID,key,version,synced) VALUES (28,?,?,?,?,?,0,0)", (now,now,now,1,k))
    cur.execute("INSERT INTO itemNotes (itemID,parentItemID,note,title) VALUES (?,?,?,?)", (cur.lastrowid, parent_id, html, f"AI 解析 - {title}"))
    cur.execute("UPDATE items SET dateModified=?,clientDateModified=? WHERE itemID=?", (now,now,parent_id))
    db.commit(); db.close()
    print(f"  [OK] Note written to item {parent_id}")

# ==================== Unified pipeline ====================
def run_full_pipeline(course_filter=None, skip_download=False, skip_analysis=False):
    """
    核心管道:
      下载 → PPT转PDF → 导入Zotero → Qwen分析 → 笔记注入
    """
    from zotero_sync import DOWNLOAD_DIR, sync_to_zotero as sz_sync

    # Step 1: Download
    if not skip_download:
        print("=" * 60)
        print("Step 1: Download course materials")
        print("=" * 60)
        from auth import get_session
        from scraper import get_courses, get_pdfs

        session = get_session()
        courses = get_courses(session)
        if not courses:
            print("[ERROR] No courses"); return

        pdfs = get_pdfs(session, courses, course_filter=course_filter, delay=1.5)
        print(f"Found {len(pdfs)} resources")

        stats = sz_sync(pdfs, session=session, delay=1.5, skip_existing=True)
        print(f"Downloaded: {stats['downloaded']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")

    # Step 2: PPT -> PDF
    print("\n" + "=" * 60)
    print("Step 2: Convert PPT -> PDF")
    print("=" * 60)
    converted = convert_all_ppts(DOWNLOAD_DIR)
    print(f"Converted: {len(converted)} files")

    # Step 3: Import all PDFs into Zotero
    print("\n" + "=" * 60)
    print("Step 3: Import into Zotero")
    print("=" * 60)
    pdfs_to_analyze = []
    for root, dirs, files in os.walk(DOWNLOAD_DIR):
        for f in files:
            if not f.lower().endswith('.pdf'): continue
            if "annotated" in f: continue
            fp = Path(root) / f
            rel = fp.relative_to(DOWNLOAD_DIR)
            parts = rel.parts
            course = parts[0] if len(parts) > 1 else ""
            folder = "/".join(parts[1:-1]) if len(parts) > 2 else ""
            pid = db_import_file(fp, course, folder)
            pdfs_to_analyze.append((fp, pid, f))
            print(f"  [{pid}] {f}")

    print(f"\n  Imported: {len(pdfs_to_analyze)} PDFs")

    if skip_analysis:
        print("\n[SKIP] Analysis step skipped")
        return

    # Step 4: Analyze
    print("\n" + "=" * 60)
    print("Step 4: Qwen analysis")
    print("=" * 60)
    total_cost = 0.0
    for fp, pid, fname in pdfs_to_analyze:
        print(f"\n  Analyzing: {fname}")
        results, cost = analyze_pdf(fp)
        total_cost += cost
        print(f"    Cost: CNY{cost:.4f}")

        # Save analysis.json
        analysis_path = fp.with_suffix(".analysis.json")
        summary = {"tokens_in": sum(r["tokens_in"] for r in results),
                   "tokens_out": sum(r["tokens_out"] for r in results),
                   "cost_yuan": round(cost, 6)}
        with open(analysis_path, "w", encoding="utf-8") as jf:
            json.dump({"file": str(fp.resolve()), "model": MODEL, "timestamp": datetime.now().isoformat(),
                        "total_pages": len(results), "summary": summary, "slides": results}, jf, ensure_ascii=False, indent=2)

        # Step 5: Write Zotero note
        print("    Writing note...")
        write_note_to_zotero(pid, fname, results)

    print(f"\n{'='*60}")
    print(f"Pipeline complete! {len(pdfs_to_analyze)} PDFs analyzed, total cost: CNY{total_cost:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--course", type=str, help="Course keyword filter")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--skip-analysis", action="store_true")
    args = p.parse_args()
    run_full_pipeline(args.course, args.skip_download, args.skip_analysis)
