"""
Blackboard Learn scraper
课程列表 → 课程主页(announcement) → listContent.jsp 文件夹递归 → bbcswebdav 文件提取
"""

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, unquote
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from auth import get_session

BASE_URL = "https://course.pku.edu.cn"
COURSE_LIST_URL = f"{BASE_URL}/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"


@dataclass
class PDFResource:
    course_name: str
    course_id: str
    resource_name: str
    pdf_url: str
    folder_path: str = ""


@dataclass
class Course:
    name: str
    course_id: str
    url: str


# ============================================================
# Course list parsing
# ============================================================

def _parse_course_list(html: str):
    soup = BeautifulSoup(html, "lxml")
    courses = []
    seen = set()

    for link in soup.select("a[href*='launcher?type=Course']"):
        href = link.get("href", "")
        name = link.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        course_id = _extract_course_id(href)
        if course_id and course_id not in seen:
            seen.add(course_id)
            url = urljoin(BASE_URL, href) if not href.startswith("http") else href
            courses.append(Course(name=name, course_id=course_id, url=url))

    return courses


def _extract_course_id(url: str) -> str:
    m = re.search(r"PkId\{key=_(\d+_\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(?:course_?)?[iI][dD]=_?(\d+_\d+)", url)
    if m:
        return m.group(1)
    return ""


def get_courses(session=None):
    if session is None:
        session = get_session()

    print("[Scraper] Fetching course list...")
    resp = session.get(COURSE_LIST_URL, timeout=30, verify=False)
    resp.raise_for_status()
    courses = _parse_course_list(resp.text)
    print(f"[Scraper] Found {len(courses)} courses")
    for c in courses:
        print(f"  - {c.name[:80]} ({c.course_id})")
    return courses


# ============================================================
# Content scraping
# ============================================================

def _extract_content_id(url: str) -> str:
    """Extract content_id from listContent.jsp or file?cmd=view URL."""
    m = re.search(r"content_id=_(\d+_\d+)", url)
    return m.group(1) if m else ""


def _extract_filename(link, href: str) -> str:
    """Get human-readable filename from link text or URL path."""
    # 1. Try link text first
    text = link.get_text(strip=True)
    if text and len(text) >= 2 and not text.startswith("http"):
        # Clean up common BB suffixes
        text = re.sub(r"\s*\(\d+\s*[kKMG]B\)", "", text)  # remove "(123 KB)"
        if len(text) >= 2:
            return text

    # 2. Try parent element
    parent = link.find_parent(["li", "div", "tr"])
    if parent:
        for selector in ["h3", ".item-title", ".resource-title", "span.itemName"]:
            elem = parent.select_one(selector)
            if elem:
                t = elem.get_text(strip=True)
                if t and len(t) >= 2:
                    return t

    # 3. Extract from URL
    try:
        clean = unquote(href.split("?")[0].split("/")[-1])
        if "." in clean:
            return Path(clean).stem
        return clean
    except Exception:
        return href.split("/")[-1][:60]


def _scrape_page(session, url: str, course_name: str, course_id: str,
                 folder_path: str = "", visited: set = None,
                 seen_urls: set = None,
                 seen_names: set = None):
    """Recursively scrape a listContent.jsp page for files and sub-folders."""
    if visited is None:
        visited = set()
    if seen_urls is None:
        seen_urls = set()
    if seen_names is None:
        seen_names = set()

    current_id = _extract_content_id(url)
    if current_id and current_id in visited:
        return []
    if current_id:
        visited.add(current_id)

    resources = []

    resp = session.get(url, timeout=30, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # --- Files: bbcswebdav links ---
    for link in soup.select("a[href*='bbcswebdav']"):
        href = link.get("href", "")
        if not href:
            continue
        file_url = urljoin(BASE_URL, href)
        # Dedup by URL: same bbcswebdav link = same physical file
        if file_url in seen_urls:
            continue
        seen_urls.add(file_url)
        name = _extract_filename(link, href)
        # Also dedup by name within course
        name_key = f"{course_id}|{name}"
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        resources.append(PDFResource(
            course_name=course_name,
            course_id=course_id,
            resource_name=name,
            pdf_url=file_url,
            folder_path=folder_path,
        ))

    # --- Files: direct .pdf links ---
    for link in soup.select("a[href$='.pdf'], a[href*='.pdf?']"):
        href = link.get("href", "")
        if not href or "bbcswebdav" in href:
            continue
        file_url = urljoin(BASE_URL, href)
        if file_url in seen_urls:
            continue
        seen_urls.add(file_url)
        name = _extract_filename(link, href)
        name_key = f"{course_id}|{name}"
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        resources.append(PDFResource(
            course_name=course_name,
            course_id=course_id,
            resource_name=name,
            pdf_url=file_url,
            folder_path=folder_path,
        ))

    # --- Sub-folders: other listContent.jsp pages ---
    for link in soup.select("a[href*='listContent.jsp']"):
        href = link.get("href", "")
        sub_id = _extract_content_id(href)
        if not sub_id or sub_id in visited:
            continue
        fname = link.get_text(strip=True) or sub_id
        sub_url = urljoin(BASE_URL, href)
        sub_path = f"{folder_path}/{fname}" if folder_path else fname
        try:
            sub_r = _scrape_page(session, sub_url, course_name, course_id,
                                 sub_path, visited, seen_urls, seen_names)
            resources.extend(sub_r)
        except requests.RequestException as e:
            print(f"    [WARN] skip {fname}: {e}")

    return resources


def _get_course_content_links(session, course_id: str):
    """
    Access the course announcement page and extract all listContent.jsp
    entry points (content area navigation items).
    """
    # courseMain redirects to the announcement page which has left-nav content menu
    course_url = f"{BASE_URL}/webapps/blackboard/execute/courseMain?course_id=_{course_id}"
    resp = session.get(course_url, timeout=30, verify=False)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    links = []
    seen = set()

    for link in soup.select("a[href*='listContent.jsp']"):
        href = link.get("href", "")
        content_id = _extract_content_id(href)
        if not content_id or content_id in seen:
            continue
        name = link.get_text(strip=True)
        if not name or name in ("", "首页", "通知", "Announcements"):
            continue
        seen.add(content_id)
        links.append({
            "name": name,
            "url": urljoin(BASE_URL, href),
            "content_id": content_id,
        })

    return links


def get_pdfs(session=None, courses=None, course_filter=None, delay=1.0):
    if session is None:
        session = get_session()
    if courses is None:
        courses = get_courses(session)

    if course_filter:
        courses = [c for c in courses if course_filter.lower() in c.name.lower()]
        print(f"[Scraper] Filter: {len(courses)} courses match '{course_filter}'")

    all_pdfs = []

    for i, course in enumerate(courses, 1):
        print(f"\n[{i}/{len(courses)}] {course.name[:80]} ({course.course_id})")

        # Step A: get content folder links from announcement page
        try:
            content_links = _get_course_content_links(session, course.course_id)
        except requests.RequestException as e:
            print(f"  [WARN] cannot access course: {e}")
            continue

        print(f"  Content folders: {len(content_links)}")
        for cl in content_links:
            print(f"    - {cl['name']}")

        if not content_links:
            # Try direct content page as fallback
            content_links = [{
                "name": "全部内容",
                "url": f"{BASE_URL}/webapps/blackboard/content/listContent.jsp?course_id=_{course.course_id}",
                "content_id": "",
            }]

        # Step B: recursively scrape each folder
        seen_urls = set()
        seen_names = set()
        for cl in content_links:
            print(f"  Scraping: {cl['name']}")
            try:
                pdfs = _scrape_page(
                    session, cl["url"],
                    course.name, course.course_id,
                    folder_path=cl["name"],
                    seen_urls=seen_urls,
                    seen_names=seen_names,
                )
                all_pdfs.extend(pdfs)
                if pdfs:
                    print(f"    -> {len(pdfs)} files")
            except requests.RequestException as e:
                print(f"    [WARN] {e}")

        if delay and i < len(courses):
            time.sleep(delay)

    print(f"\n[Scraper] Total: {len(all_pdfs)} files")
    return all_pdfs


if __name__ == "__main__":
    session = get_session()
    courses = get_courses(session)
    pdfs = get_pdfs(session, courses)
    for p in pdfs:
        print(f"  [{p.course_name}] {p.resource_name}")
        print(f"    {p.pdf_url}")
