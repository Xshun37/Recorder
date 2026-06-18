"""教学网视频列表抓取 — 从课程URL提取所有视频元数据"""
import os, sys, json, base64, re, urllib.parse
import requests
from bs4 import BeautifulSoup
from pathlib import Path

BASE = Path(__file__).resolve().parent
COURSE_HOST = "https://course.pku.edu.cn"


def load_cookies():
    """从 .env 加载 Cookie，返回 {name: value}"""
    env_file = BASE.parent / ".env"
    cookies = {}

    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k.startswith("COOKIE_"):
                    cookies[k.replace("COOKIE_", "")] = v
    elif os.getenv("COURSE_JSESSIONID"):
        cookies = {
            "JSESSIONID": os.getenv("COURSE_JSESSIONID"),
            "s_session_id": os.getenv("COURSE_SESSION_ID"),
            "JWTUser": os.getenv("COURSE_JWTUSER"),
        }

    return cookies


def make_session(cookies):
    """创建带 Cookie 的 requests Session"""
    s = requests.Session()
    s.verify = False
    for name, value in cookies.items():
        domain = ".pku.edu.cn" if "jwt" in name.lower() else "course.pku.edu.cn"
        s.cookies.set(name, value, domain=domain)
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    )
    return s


def decode_jwt(token):
    """解码 JWT payload（不验证签名）"""
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        pass
    return {}


def get_course_list():
    """
    从门户"我的主页"抓取所有课程列表

    返回:
        list[dict]: [{"course_id": "_95474_1", "name": "分子生物学(25-26学年第2学期)"}, ...]
    """
    cookies = load_cookies()
    s = make_session(cookies)

    url = "https://course.pku.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"
    resp = s.get(url, timeout=30)

    soup = BeautifulSoup(resp.text, "lxml")
    courses = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"PkId\{key=(_\d+_\d+)", href)
        if not m:
            continue
        cid = m.group(1)
        if cid in seen:
            continue
        seen.add(cid)

        # 文本格式: "课程编码: 课程名(学期)"，取冒号后的课程名
        raw = a.text.strip()
        name = raw
        if ":" in raw:
            name = raw.split(":", 1)[1].strip()
        courses.append({"course_id": cid, "name": name})

    return courses


def get_video_list(course_id=None, url=None):
    """
    抓取视频列表页，返回 (course_name, videos)

    参数:
        course_id: Blackboard course_id（如 _95474_1），优先于 url
        url:       完整的视频列表页 URL（fallback）

    返回:
        course_name: str 课程名
        videos: list[dict]
            - token, record_time, sub_id, course_id_hqy, index, section
    """
    cookies = load_cookies()
    if not cookies:
        raise RuntimeError(
            "未找到 Cookie 配置。请创建 .env 文件:\n"
            "  COOKIE_JSESSIONID=...\n"
            "  COOKIE_s_session_id=...\n"
            "  COOKIE_JWTUser=..."
        )

    if course_id is not None:
        url = (
            "https://course.pku.edu.cn/webapps/bb-streammedia-hqy-BBLEARN/"
            f"videoList.action?course_id={course_id}&mode=view"
        )
    elif url is None:
        raise ValueError("必须提供 course_id 或 url")

    # 自动补全协议
    if not url.startswith("http"):
        url = COURSE_HOST + url if url.startswith("/") else url

    s = make_session(cookies)

    # 测试连通性
    resp = s.get(url, timeout=30, allow_redirects=False)
    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", "")
        if "sso" in location.lower() or "login" in location.lower():
            raise RuntimeError("Cookie 已过期，请重新获取并更新 .env")
        resp = s.get(url, timeout=30)

    soup = BeautifulSoup(resp.text, "lxml")

    # 提取课程名
    course_name = None
    for sel in ["h3", "[class*='pageTitle']", "h1", "h2"]:
        el = soup.select_one(sel)
        if el and el.text.strip():
            course_name = el.text.strip()
            break

    # 提取视频列表
    # 跟踪当前所属章节
    current_section = ""
    videos = []
    seen_tokens = set()

    # 找到所有相关链接，按DOM顺序遍历
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.text.strip()

        # 章节/文件夹链接
        if "listContent.jsp" in href and "content_id" in href:
            if text and text not in ("", "观看", "前一个", "后一个"):
                current_section = text

        # 视频链接
        if "playVideo.action" in href:
            token_match = re.search(r"token=([^&]+)", href)
            if not token_match:
                continue
            token = token_match.group(1)

            if token in seen_tokens:
                continue
            seen_tokens.add(token)

            payload = decode_jwt(token)
            videos.append({
                "token": token,
                "record_time": payload.get("recordTime", "未知"),
                "sub_id": payload.get("hqySubId", ""),
                "course_id_hqy": payload.get("hqyCourseId", ""),
                "section": current_section,
                "index": len(videos),
            })

    return course_name, videos


def get_player_url(token):
    """
    通过 CAS 认证链获取 onlineroomse 播放器 URL

    参数:
        token: playVideo.action 的 JWT token

    返回:
        str: onlineroomse.pku.edu.cn/player?... 完整 URL
    """
    cookies = load_cookies()
    s = make_session(cookies)

    # Step 1: 访问 playVideo.action 页面，提取 CAS iframe URL
    play_url = (
        f"{COURSE_HOST}/webapps/bb-streammedia-hqy-BBLEARN/"
        f"playVideo.action?token={token}"
    )
    resp = s.get(play_url, timeout=30)
    soup = BeautifulSoup(resp.text, "lxml")
    iframe = soup.find("iframe", src=re.compile("yjapise"))
    if not iframe:
        raise RuntimeError("未找到 CAS 认证 iframe，页面结构可能已变化")

    cas_url = iframe["src"]
    if cas_url.startswith("/"):
        cas_url = COURSE_HOST + cas_url

    # Step 2: 跟随 CAS 重定向到播放器
    resp = s.get(cas_url, timeout=30, allow_redirects=True)

    if "onlineroomse.pku.edu.cn" not in resp.url:
        raise RuntimeError(f"CAS 认证后未到达播放器: {resp.url}")

    return resp.url


def print_video_list(course_name, videos):
    """打印格式化的视频列表"""
    print(f"\n课程: {course_name}")
    print(f"共 {len(videos)} 个视频\n")
    print(f"{'#':<4} {'录制时间':<22} {'章节':<20} {'sub_id':<12}")
    print("-" * 62)

    for v in videos:
        section = v["section"][:18] if v["section"] else "-"
        print(f"{v['index']:<4} {v['record_time']:<22} {section:<20} {v['sub_id']:<12}")


def print_course_list(courses):
    """打印格式化的课程列表"""
    print(f"\n共 {len(courses)} 门课程\n")
    print(f"{'#':<4} {'course_id':<14} {'课程名'}")
    print("-" * 70)
    for i, c in enumerate(courses):
        print(f"{i:<4} {c['course_id']:<14} {c['name']}")


if __name__ == "__main__":
    if "--courses" in sys.argv:
        courses = get_course_list()
        print_course_list(courses)
    elif len(sys.argv) > 1 and sys.argv[1].startswith("_"):
        # 传入 course_id
        cn, vids = get_video_list(course_id=sys.argv[1])
        print_video_list(cn, vids)
    else:
        # 兼容旧用法：传入完整 URL 或默认
        url = sys.argv[1] if len(sys.argv) > 1 else None
        cn, vids = get_video_list(url=url)
        print_video_list(cn, vids)
