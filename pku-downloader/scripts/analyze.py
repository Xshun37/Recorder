#!/usr/bin/env python3
"""
课件 AI 解析（独立模块）

用法:
  python analyze.py                    # 交互式：从 Zotero 子分类选课程
  python analyze.py --course "遗传学"  # 按关键词筛选
  python analyze.py --all              # 全部课程
  python analyze.py --force            # 重分析已有 .analysis.json
  python analyze.py --concurrency 8    # 并发数 (默认 12)
"""

import os, sys, json, random, sqlite3, argparse, base64, tempfile, threading, shutil
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import fitz
from PIL import Image
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env
for _i in range(5):
    _dp = Path(__file__).resolve().parent
    for _ in range(_i):
        _dp = _dp.parent
    _env = _dp / ".env"
    if _env.exists():
        for _ln in _env.read_text(encoding="utf-8").splitlines():
            if "=" in _ln and not _ln.strip().startswith("#"):
                _k, _v = _ln.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                # 跳过占位符，优先用系统环境变量
                if "xxx" in _v or "你的" in _v:
                    if _k not in os.environ:
                        continue
                    _v = os.environ[_k]
                os.environ.setdefault(_k, _v)
        break
    if _dp.parent == _dp:
        break

# ==================== config ====================
API_KEY = os.getenv("QWEN_API_KEY", "")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.7-plus"
PRICE_INPUT = 1.6
PRICE_OUTPUT = 6.4
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


# ==================== Zotero lookup ====================
def _find_zotero_db():
    candidates = []
    env = os.getenv("ZOTERO_DB_PATH", "")
    if env:
        p = Path(env)
        if p.exists() and p.stat().st_size > 0:
            return p

    appdata = os.getenv("APPDATA", "")
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

    zotero_dirs = ["Zotero", "文献/Zotero", "Documents/Zotero"]
    for drive in "DEFG":
        for dd in zotero_dirs:
            profiles = Path(f"{drive}:\\{dd}") / "Profiles"
            if profiles.exists():
                for p in profiles.glob("*.default*"):
                    db = p / "zotero.sqlite"
                    if db.exists():
                        candidates.append(db)
            db = Path(f"{drive}:\\{dd}") / "zotero.sqlite"
            if db.exists():
                candidates.append(db)
        db = Path(f"{drive}:\\文献\\zotero.sqlite")
        if db.exists():
            candidates.append(db)

    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return None


ZOTERO_DB = _find_zotero_db()


def _db_get_keys(cur):
    cur.execute("SELECT key FROM items")
    return set(r[0] for r in cur.fetchall())


def _db_gen_key(existing):
    while True:
        k = ''.join(random.choices(KEY_CHARS, k=8))
        if k not in existing:
            return k


def _open_zotero_db():
    """打开 Zotero DB，若被锁则报错提示。"""
    if not ZOTERO_DB:
        print("[ERROR] Zotero DB 未找到。请设置 ZOTERO_DB_PATH 或安装 Zotero。")
        sys.exit(1)
    try:
        return sqlite3.connect(str(ZOTERO_DB))
    except sqlite3.OperationalError:
        print("[ERROR] Zotero DB 被锁定。请先关闭 Zotero，再运行此脚本。")
        sys.exit(1)


def get_collections_from_zotero():
    """扫描 Zotero 中所有包含附件的分类，返回 [(collection_name, pdf_count), ...]"""
    db = _open_zotero_db()
    cur = db.cursor()

    cur.execute("""
        SELECT C.collectionName, COUNT(DISTINCT CI.itemID)
        FROM collections C
        JOIN collectionItems CI ON C.collectionID = CI.collectionID
        JOIN itemAttachments IA ON IA.parentItemID = CI.itemID
        WHERE IA.contentType = 'application/pdf'
        GROUP BY C.collectionID
        ORDER BY C.collectionName
    """)
    result = [(name, count) for name, count in cur.fetchall()]
    db.close()
    return result


def get_pdfs_for_collections(keywords, force=False):
    """
    按关键词匹配 Zotero 分类，反查 downloads/ 里的 PDF。
    返回 [(pdf_path, parent_item_id, filename), ...]
    """
    db = _open_zotero_db()
    cur = db.cursor()

    # 从 zotero_sync 取 DOWNLOAD_DIR
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zotero_sync import DOWNLOAD_DIR

    # 查找匹配的 collection（按关键词）
    selected_col_ids = []
    cur.execute("""
        SELECT C.collectionID, C.collectionName, COUNT(CI.itemID)
        FROM collections C
        JOIN collectionItems CI ON C.collectionID = CI.collectionID
        GROUP BY C.collectionID
    """)
    for cid, name, count in cur.fetchall():
        match = not keywords
        for kw in keywords:
            if kw in name:
                match = True
                break
        if match:
            selected_col_ids.append(cid)

    if not selected_col_ids:
        print("[ERROR] 未找到匹配的分类")
        db.close()
        return []

    # 收集这些 collection 的所有 itemID
    item_ids = set()
    for cid in selected_col_ids:
        cur.execute("SELECT itemID FROM collectionItems WHERE collectionID = ?", (cid,))
        for (iid,) in cur:
            item_ids.add(iid)

    # 对每个 item，找附件 PDF 路径
    result = []
    for iid in item_ids:
        cur.execute("SELECT path FROM itemAttachments WHERE parentItemID = ? AND contentType = 'application/pdf'", (iid,))
        for (path_val,) in cur:
            fname = Path(path_val).name
            # 在 downloads/ 下匹配
            matches = list(DOWNLOAD_DIR.rglob(fname))
            if matches:
                pdf_path = matches[0]
                if force or not pdf_path.with_suffix('.analysis.json').exists():
                    result.append((pdf_path, iid, fname))

    db.close()
    return result


# ==================== PDF → images ====================
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
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        p = os.path.join(tmp, f"{i + 1:04d}.png")
        img.save(p, "PNG")
        paths.append((i + 1, p))
    doc.close()
    return paths


def encode_image(path):
    img = Image.open(path)
    w, h = img.size
    s = 2048 / max(w, h)
    img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


# ==================== Qwen analysis ====================
def analyze_page(page_num, total, b64):
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": f"Page {page_num}/{total}. 讲解本页知识。"},
            ]},
        ],
        max_tokens=2048,
    )
    choice = resp.choices[0]
    usage = resp.usage
    ti, to = usage.input_tokens or 0, usage.output_tokens or 0
    cost = ti / 1e6 * PRICE_INPUT + to / 1e6 * PRICE_OUTPUT
    return {
        "slide": page_num,
        "content": choice.message.content.strip(),
        "tokens_in": ti,
        "tokens_out": to,
        "cost_yuan": round(cost, 6),
    }


def analyze_pdf(pdf_path, concurrency=12):
    pages = pdf_to_images(pdf_path)
    results = [None] * len(pages)
    total_cost = 0.0

    def _task(idx, pn, b64):
        try:
            r = analyze_page(pn, len(pages), b64)
            results[idx] = r
            with _print_lock:
                print(f"    [{pn}/{len(pages)}] cost=CNY{r['cost_yuan']:.4f}")
            return r["cost_yuan"]
        except Exception as e:
            with _print_lock:
                print(f"    [{pn}/{len(pages)}] FAIL: {e}")
            return 0.0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for idx, (pn, img_path) in enumerate(pages):
            b64 = encode_image(img_path)
            futures[pool.submit(_task, idx, pn, b64)] = pn
        for fut in as_completed(futures):
            total_cost += fut.result()

    shutil.rmtree(os.path.dirname(pages[0][1]), ignore_errors=True)
    return [r for r in results if r], total_cost


# ==================== Content → HTML ====================
def content_to_html(raw):
    html = raw
    if html.startswith("<"):
        pass
    else:
        html = html.replace("**", "<b>", 1)
        if "**" in html:
            html = html.replace("**", "</b>", 1)
    lines = html.split('\n')
    parts, in_list, in_table, header_used = [], False, False, False
    table_header = None
    for line in lines:
        t = line.strip()
        if t.startswith('|') and t.endswith('|') and '---' in t:
            continue
        if t.startswith('|') and t.endswith('|'):
            if in_list:
                parts.append('</ul>')
                in_list = False
            cells = [c.strip() for c in t.split('|')[1:-1]]
            if not header_used:
                table_header = cells
                header_used = True
                continue
            if not in_table:
                parts.append(
                    '<table style="border-collapse:collapse;margin:8px 0;width:100%;font-size:13px"><thead><tr>')
                for h in table_header:
                    parts.append(
                        f'<th style="background:#f0ecf9;padding:6px 10px;border:1px solid #ddd;text-align:left;font-weight:700">{h}</th>')
                parts.append('</tr></thead><tbody>')
                in_table = True
            parts.append('<tr>')
            for c in cells:
                parts.append(f'<td style="padding:6px 10px;border:1px solid #ddd;vertical-align:top">{c}</td>')
            parts.append('</tr>')
            continue
        if in_table:
            parts.append('</tbody></table>')
            in_table = False
            header_used = False
        if t.startswith('- ') or t.startswith('* '):
            if not in_list:
                parts.append('<ul style="margin:4px 0;padding-left:20px">')
                in_list = True
            parts.append(f'<li style="margin:2px 0">{t[2:]}</li>')
            continue
        if in_list:
            parts.append('</ul>')
            in_list = False
        if t:
            parts.append(f'<p style="margin:2px 0 4px">{t}</p>')
    if in_list:
        parts.append('</ul>')
    if in_table:
        parts.append('</tbody></table>')
    return '\n'.join(parts)


# ==================== Zotero note write ====================
def write_note_to_zotero(parent_id, title, results):
    if not ZOTERO_DB or not parent_id:
        return
    db = _open_zotero_db()
    cur = db.cursor()

    cur.execute("DELETE FROM items WHERE itemID IN (SELECT itemID FROM itemNotes WHERE parentItemID = ?)",
                (parent_id,))
    cur.execute("DELETE FROM itemNotes WHERE parentItemID = ?", (parent_id,))

    keys = _db_get_keys(cur)
    header = f'<h1>{title} - AI 解析</h1><p style="color:#999;font-size:11px">{len(results)} 页 | {MODEL}</p><hr>'
    body = ""
    for r in sorted(results, key=lambda x: x["slide"]):
        body += f'<h2 style="color:#5b3cc4;margin-top:16px">Page {r["slide"]}</h2>'
        body += content_to_html(r.get("content", ""))

    html = '<div class="zotero-note znv1">' + header + body + '</div>'
    k = _db_gen_key(keys)
    keys.add(k)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO items (itemTypeID,dateAdded,dateModified,clientDateModified,libraryID,key,version,synced) VALUES (28,?,?,?,?,?,0,0)",
        (now, now, now, 1, k))
    cur.execute("INSERT INTO itemNotes (itemID,parentItemID,note,title) VALUES (?,?,?,?)",
                (cur.lastrowid, parent_id, html, f"AI 解析 - {title}"))
    cur.execute("UPDATE items SET dateModified=?,clientDateModified=? WHERE itemID=?", (now, now, parent_id))
    db.commit()
    db.close()
    print(f"  [OK] Note written to item {parent_id}")


# ==================== CLI ====================
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


def main():
    p = argparse.ArgumentParser(description="课件 AI 解析")
    p.add_argument("--course", type=str, help="课程名关键词 (多个逗号分隔)")
    p.add_argument("--all", action="store_true", help="全部课程")
    p.add_argument("--force", action="store_true", help="重新分析已有 analysis.json 的文件")
    p.add_argument("--concurrency", type=int, default=12, help="Qwen API 并发数")
    args = p.parse_args()

    if not API_KEY:
        print("[ERROR] QWEN_API_KEY not set")
        sys.exit(1)
    if not ZOTERO_DB:
        print("[ERROR] Zotero DB not found. 关闭 Zotero 后重试。")
        sys.exit(1)

    print(f"[OK] Zotero DB: {ZOTERO_DB}")

    # ---- 选分类 ----
    collections = get_collections_from_zotero()
    if not collections:
        print("[ERROR] Zotero 中未找到包含 PDF 附件的分类。")
        sys.exit(1)

    if args.all:
        keywords = [c[0] for c in collections]
    elif args.course:
        keywords = [kw.strip() for kw in args.course.split(",") if kw.strip()]
    else:
        print(f"\n{'='*60}")
        print(f"  Zotero 分类 — 课件 AI 解析")
        print(f"{'='*60}")
        for i, (name, count) in enumerate(collections, 1):
            print(f"  [{i:2d}] {name} ({count} 个文件)")
        choice = input(f"\n  选择分类 (如: 1,3,5-8) > ").strip()
        indices = parse_selection(choice, len(collections))
        keywords = [collections[i][0] for i in sorted(indices)]

    if not keywords:
        print("未选择分类。")
        return

    print(f"\n  已选择: {', '.join(keywords)}")

    # ---- 收集 PDFs ----
    pdfs = get_pdfs_for_collections(keywords, force=args.force)
    if not pdfs:
        print("  没有待分析的 PDF。")
        return

    print(f"  共 {len(pdfs)} 个 PDF\n")

    # ---- 分析 ----
    print(f"{'='*60}")
    print(f"AI Analysis ({MODEL}, {args.concurrency} 并发)")
    print(f"{'='*60}")

    total_cost = 0.0
    for i, (fp, pid, fname) in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] {fname}")
        results, cost = analyze_pdf(fp, args.concurrency)
        total_cost += cost
        print(f"  Cost: CNY{cost:.4f}")

        with open(fp.with_suffix(".analysis.json"), "w", encoding="utf-8") as jf:
            json.dump({
                "file": str(fp.resolve()), "model": MODEL,
                "timestamp": datetime.now().isoformat(), "total_pages": len(results),
                "summary": {"cost_yuan": round(cost, 6)}, "slides": results,
            }, jf, ensure_ascii=False, indent=2)

        write_note_to_zotero(pid, fname, results)

    print(f"\n{'='*60}")
    print(f"Complete! {len(pdfs)} PDFs, total cost: CNY{total_cost:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
