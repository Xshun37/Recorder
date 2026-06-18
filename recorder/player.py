"""教学网视频 — Selenium 播放 (stream 模式) + HLS 直下 (download 模式)"""
import time
import re
import json
import base64
import subprocess
import requests
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import urllib3; urllib3.disable_warnings()

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE = Path(__file__).resolve().parent
COURSE_HOST = "https://course.pku.edu.cn"
FFMPEG = str(BASE.parent / "ffmpeg.exe")
if not Path(FFMPEG).exists():
    FFMPEG = "ffmpeg"  # fallback to PATH


def _load_cookies():
    """加载 Cookie，返回 [(name, value, domain), ...]"""
    env_file = BASE.parent / ".env"
    cookies = []
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k.startswith("COOKIE_"):
                    name = k.replace("COOKIE_", "")
                    domain = ".pku.edu.cn" if "jwt" in name.lower() else "course.pku.edu.cn"
                    cookies.append((name, v, domain))
    return cookies


def play_video(token, headless=False, timeout_sec=7200, speed=2.0):
    """
    Selenium 自动播放视频，阻塞直到结束。中途卡顿自动刷新恢复。

    参数:
        token:       playVideo.action 的 JWT token
        headless:    无头模式（不输出音频，慎用）
        timeout_sec: 最长等待时间（秒），默认 2 小时
        speed:       播放倍速，默认 2.0

    返回:
        bool: True=正常结束, False=超时
    """
    options = Options()
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-gesture-requirement-for-media-playback")
    options.add_argument("--ignore-certificate-errors")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    if headless:
        options.add_argument("--headless")

    driver = webdriver.Edge(options=options)
    driver.set_window_size(1280, 720)
    driver.minimize_window()

    try:
        # ---- Step 1: CDP 注入 Cookie ----
        driver.get("about:blank")
        for name, value, domain in _load_cookies():
            try:
                driver.execute_cdp_cmd("Network.setCookie", {
                    "name": name, "value": value, "domain": domain,
                    "path": "/", "secure": True, "sameSite": "Lax",
                })
            except Exception:
                pass

        play_url = (
            f"{COURSE_HOST}/webapps/bb-streammedia-hqy-BBLEARN/"
            f"playVideo.action?token={token}"
        )

        # ---- Step 2: 加载播放页（带重试） ----
        for attempt in range(5):
            if attempt > 0:
                print(f"[Player] 页面加载重试 {attempt}/{4}...")
                time.sleep(2)

            driver.get(play_url)
            print(f"[Player] 加载播放页面 (第{attempt+1}次)...")

            wait = WebDriverWait(driver, 20)
            try:
                iframe = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='yjapise']"))
                )
            except TimeoutException:
                print("[Player] 未找到 CAS iframe")
                continue

            time.sleep(2)
            driver.switch_to.frame(iframe)

            # 等待 video 元素出现
            video = _find_video(driver, timeout=60)
            if video is not None:
                break
            print("[Player] 视频元素未出现，将刷新页面重试...")
        else:
            raise RuntimeError("播放器加载失败：已重试 5 次")

        # ---- Step 3: 播放 + 监控（带卡顿恢复） ----
        last_position = _start_playing(driver, video, speed)
        return _monitor_with_stall_recovery(driver, play_url, speed,
                                            timeout_sec, last_position)

    finally:
        driver.quit()


def _find_video(driver, timeout=60):
    """在 iframe 中等待 <video> 元素出现，返回 element 或 None"""
    for _ in range(timeout // 2):
        for sel in ("video", "video, .video-player video, #player video"):
            try:
                return driver.find_element(By.CSS_SELECTOR, sel)
            except NoSuchElementException:
                pass
        time.sleep(2)
    return None


def _start_playing(driver, video, speed):
    """点击/JS 播放，设倍速，返回 currentTime"""
    is_playing = driver.execute_script("return !arguments[0].paused;", video)
    if not is_playing:
        try:
            video.click()
        except Exception:
            pass
        driver.execute_script("arguments[0].play();", video)
        for _ in range(10):
            if driver.execute_script("return !arguments[0].paused;", video):
                break
            time.sleep(0.5)

    driver.execute_script(f"arguments[0].playbackRate = {speed};", video)
    rate = driver.execute_script("return arguments[0].playbackRate;", video)
    pos = driver.execute_script("return arguments[0].currentTime;", video)

    state = "playing" if driver.execute_script("return !arguments[0].paused;", video) else "paused"
    print(f"[Player] 视频 {state}, 速度 {rate}x, 位置 {pos:.0f}s")
    return pos


def _monitor_with_stall_recovery(driver, play_url, speed, timeout_sec, pos):
    """监控播放进度。卡顿 >30s 则刷新页面跳到断点继续。"""
    from selenium.webdriver.common.by import By

    start_time = time.time()
    last_report = 0
    stall_begin = None
    stall_recovered = 0

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_sec:
            print(f"[Player] 超时 ({timeout_sec}s)")
            return False

        try:
            video = driver.find_element(By.TAG_NAME, "video")

            # 检查是否结束
            ended = driver.execute_script("return arguments[0].ended;", video)
            if ended:
                print("[Player] 视频播放完毕")
                return True

            # 检查是否卡顿（paused 但没 ended，也不在 seeking）
            paused = driver.execute_script("return arguments[0].paused;", video)
            ready = driver.execute_script(
                "return arguments[0].readyState >= 3;", video
            )
            pos = driver.execute_script("return arguments[0].currentTime;", video)

            if paused and not ended:
                if stall_begin is None:
                    stall_begin = time.time()
                stall_dur = time.time() - stall_begin

                # 保留最新位置用于恢复
                if pos > 0:
                    _recovery_seek_pos = pos

                if stall_dur > 30:
                    stall_recovered += 1
                    print(f"[Player] 卡顿 {stall_dur:.0f}s，刷新恢复 "
                          f"(#{stall_recovered}, 跳至 {pos:.0f}s)...")

                    # 刷新页面并恢复
                    driver.get(play_url)
                    time.sleep(3)

                    # 重新走 CAS → iframe → video
                    try:
                        iframe = WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "iframe[src*='yjapise']"))
                        )
                        driver.switch_to.frame(iframe)
                    except TimeoutException:
                        print("[Player] 刷新后未找到 CAS iframe")
                        return False

                    video2 = _find_video(driver, timeout=30)
                    if video2 is None:
                        print("[Player] 刷新后未找到视频元素")
                        return False

                    # 跳到之前位置
                    seek_target = pos + 2  # 往前 2 秒，跳过卡住的那段
                    driver.execute_script(
                        f"arguments[0].currentTime = {seek_target};", video2
                    )
                    driver.execute_script(
                        f"arguments[0].playbackRate = {speed};", video2
                    )
                    driver.execute_script("arguments[0].play();", video2)

                    time.sleep(2)
                    new_pos = driver.execute_script(
                        "return arguments[0].currentTime;", video2
                    )
                    print(f"[Player] 恢复播放，位置 {new_pos:.0f}s")

                    stall_begin = None  # 重置卡顿计时
                    video = video2
                else:
                    # 还没到 30s 阈值：如果 buffer 不够了就什么都不做，等它加载
                    pass
            else:
                stall_begin = None  # 正常播放，清除卡顿标记

        except NoSuchElementException:
            pass  # stale element，下一轮重新找
        except Exception:
            pass

        # 每分钟汇报
        if elapsed - last_report >= 60:
            minutes = int(elapsed / 60)
            try:
                pos = driver.execute_script(
                    "return Math.floor(arguments[0].currentTime);", video
                )
            except Exception:
                pos = "?"
            print(f"[Player] 已播放 {minutes} 分钟 (currentTime={pos}s)")
            last_report = elapsed

        try:
            driver.current_url
        except Exception:
            print("[Player] 页面已关闭")
            return True

        time.sleep(1)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python player.py <token>")
        sys.exit(1)
    play_video(sys.argv[1])


# ---- HLS 直下模式 ----

def capture_m3u8_url(token):
    """
    Selenium 打开播放页，等 video 加载，从 JS performance API 提取 m3u8 URL。

    参数:
        token: playVideo.action 的 JWT token

    返回:
        str: m3u8 URL，失败抛异常
    """
    options = Options()
    options.add_argument("--mute-audio")
    options.add_argument("--ignore-certificate-errors")

    driver = webdriver.Edge(options=options)
    driver.set_window_size(1280, 720)

    try:
        driver.get("about:blank")
        for name, value, domain in _load_cookies():
            try:
                driver.execute_cdp_cmd("Network.setCookie", {
                    "name": name, "value": value, "domain": domain,
                    "path": "/", "secure": True, "sameSite": "Lax",
                })
            except Exception:
                pass

        play_url = f"{COURSE_HOST}/webapps/bb-streammedia-hqy-BBLEARN/playVideo.action?token={token}"
        driver.get(play_url)
        time.sleep(3)

        for f in driver.find_elements(By.TAG_NAME, "iframe"):
            if "yjapise" in (f.get_attribute("src") or ""):
                driver.switch_to.frame(f)
                break
        time.sleep(5)

        for _ in range(10):
            try:
                driver.find_element(By.TAG_NAME, "video")
                break
            except NoSuchElementException:
                time.sleep(2)
        time.sleep(3)

        entries = driver.execute_script("""
            return performance.getEntriesByType('resource').filter(function(e) {
                return e.name.indexOf('.m3u8') >= 0;
            }).map(function(e) { return e.name; });
        """)
        if not entries:
            raise RuntimeError("未捕获到 m3u8 URL")
        return entries[0]
    finally:
        driver.quit()


def download_hls_audio(m3u8_url, output_wav, timeout=1800):
    """
    下载 HLS 流音频（AES-128 解密 + ffmpeg 提取音轨）。

    参数:
        m3u8_url:  远程 m3u8 地址
        output_wav: 输出 WAV 路径
        timeout:   ffmpeg 超时（秒）

    返回:
        bool: 成功/失败
    """
    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    # 获取 m3u8 内容
    s = requests.Session()
    s.verify = False
    s.headers["Referer"] = "https://onlineroomse.pku.edu.cn/"
    m3u8_text = s.get(m3u8_url, timeout=30).text

    # 提取并下载 AES key（需要 _token cookie）
    key_match = re.search(r'URI="([^"]+)"', m3u8_text)
    if not key_match:
        raise RuntimeError("m3u8 中未找到 AES key URI")

    key_url = key_match.group(1)
    # 加载 cookie 获取 _token
    token_cookie = None
    env_file = BASE.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("COOKIE__token="):
                token_cookie = line.split("=", 1)[1].strip().strip('"').strip("'")

    if token_cookie:
        s.cookies.set("_token", token_cookie, domain=".pku.edu.cn")
    key_data = s.get(key_url, timeout=15).content

    # 构建 data URI 内嵌 key 的本地 m3u8
    key_b64 = base64.b64encode(key_data).decode()
    data_uri = f"data:text/plain;base64,{key_b64}"
    m3u8_base = m3u8_url.rsplit("/", 1)[0] + "/"

    local_lines = []
    for line in m3u8_text.splitlines():
        if line.startswith("#EXT-X-KEY"):
            line = line.replace(key_url, data_uri)
        elif not line.startswith("#") and line.strip():
            line = m3u8_base + line
        local_lines.append(line)

    tmp_m3u8 = output_wav.with_suffix(".tmp.m3u8")
    tmp_m3u8.write_text("\n".join(local_lines), encoding="utf-8")

    # ffmpeg 下载
    cmd = [
        FFMPEG, "-y",
        "-protocol_whitelist", "file,https,tls,crypto,data,tcp",
        "-allowed_extensions", "ALL",
        "-i", str(tmp_m3u8),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
        str(output_wav),
    ]

    print(f"[HLS] ffmpeg downloading...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    tmp_m3u8.unlink(missing_ok=True)

    if output_wav.exists() and output_wav.stat().st_size > 0:
        print(f"[HLS] Done: {output_wav.stat().st_size:,} bytes")
        return True
    else:
        print(f"[HLS] Failed: {result.stderr[-500:]}")
        return False
