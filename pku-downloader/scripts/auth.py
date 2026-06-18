"""
PKU 教学网认证模块 - Cookie 手动注入模式

获取方式（一次操作）:
  1. Edge 打开 https://course.pku.edu.cn 并登录
  2. F12 -> 应用程序 -> Cookie -> course.pku.edu.cn
  3. 复制 JSESSIONID、s_session_id
  4. Cookie -> .pku.edu.cn -> 复制 JWTUser
  5. 写入 .env（3 个值）
"""

import os
import urllib3
from pathlib import Path

import requests
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Find .env: check recorder/ sibling dir, then walk up
_env_dir = Path(__file__).resolve().parent
for _ in range(5):
    for _name in (".env", "../recorder/.env"):
        env_path = (_env_dir / _name).resolve()
        if env_path.exists():
            load_dotenv(env_path)
            break
    if env_path.exists():
        break
    _env_dir = _env_dir.parent

BASE_URL = "https://course.pku.edu.cn"
PORTAL_URL = f"{BASE_URL}/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"

COOKIES = {
    "JSESSIONID": (os.getenv("COOKIE_JSESSIONID", ""), "course.pku.edu.cn"),
    "s_session_id": (os.getenv("COOKIE_s_session_id", ""), "course.pku.edu.cn"),
    "JWTUser": (os.getenv("COOKIE_JWTUser", ""), ".pku.edu.cn"),
}


def get_session():
    """Create authenticated session from .env cookies."""
    missing = [k for k, (v, _) in COOKIES.items() if not v]
    if missing:
        print(f"[Auth] Missing cookies: {missing}")
        _print_guide()
        raise SystemExit(1)

    session = requests.Session()
    session.verify = False

    for name, (value, domain) in COOKIES.items():
        session.cookies.set(name, value, domain=domain)

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    try:
        resp = session.get(PORTAL_URL, allow_redirects=False, timeout=15)
    except requests.RequestException as e:
        print(f"[Auth] FAIL  connection error: {e}")
        raise SystemExit(1)

    # 302 to SSO = cookie expired
    if resp.status_code in (301, 302):
        loc = resp.headers.get("Location", "").lower()
        if any(k in loc for k in ("sso", "login", "iaaa")):
            print("[Auth] FAIL  cookie expired, please re-acquire")
            _print_guide()
            raise SystemExit(1)

    # 200 but not logged in
    if "courseListing" in resp.text or "Course" in resp.text or "portal" in resp.text.lower():
        print("[Auth] OK  cookie valid")
        return session

    print(f"[Auth] WARN  status={resp.status_code} len={len(resp.text)}")
    print("[Auth]       page may have changed; proceeding anyway")
    return session


def _print_guide():
    print("""
+==================================================================+
|  Get Cookies for PKU Course                                      |
+------------------------------------------------------------------+
|  1. Edge -> https://course.pku.edu.cn -> login via SSO           |
|  2. F12 -> Application -> Cookies -> course.pku.edu.cn           |
|  3. Copy: JSESSIONID  (path: /)                                  |
|          s_session_id (path: /)                                  |
|  4. Cookies -> .pku.edu.cn -> copy: JWTUser                      |
|  5. Write to .env (in project root):                              |
|       COOKIE_JSESSIONID=<value>                                   |
|       COOKIE_s_session_id=<value>                                 |
|       COOKIE_JWTUser=<value>                                      |
+==================================================================+
""")


if __name__ == "__main__":
    get_session()
