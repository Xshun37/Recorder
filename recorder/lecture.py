"""教学网视频 + 自动笔记 — 全自动流水线 (HLS 直下 + Stream fallback)

用法:
    python lecture.py                          # 交互式选择，默认 HLS 直下
    python lecture.py --mode stream            # 原流式录制 (VB-Cable)
    python lecture.py --course-id _95474_1     # 直接指定课程
    python lecture.py --token <JWT>            # 直接播放指定 token
    python lecture.py --speed 2.0              # stream 模式倍速
    python lecture.py --list --course-id <id>  # 仅列出视频
    python lecture.py --workers 8              # HLS 下载并发数 (默认 4)
    python lecture.py --m3u8-workers 2         # m3u8 抓取并发数 (默认 1)
    python lecture.py --transcribe-workers 2   # 转录并发数 (默认 1，多=GPU爆显存)
    python lecture.py --summarize-workers 8   # 摘要并发数 (默认 4)

HLS 模式: capture m3u8(10s/视频) → 并行下载(ffmpeg) → 串行转录 → 串行摘要
"""
import subprocess
import sys
import os
import warnings
import threading
from pathlib import Path
from datetime import datetime

# 抑制 SSL 警告
warnings.filterwarnings("ignore")
import urllib3
urllib3.disable_warnings()

BASE = Path(__file__).resolve().parent
RECORDS = BASE / "records"
RECORDS.mkdir(exist_ok=True)

# 复用项目内 ffmpeg
FFMPEG = str(BASE.parent / "ffmpeg.exe")
if not Path(FFMPEG).exists():
    FFMPEG = "ffmpeg"  # fallback to PATH


def sanitize_filename(name):
    """去除文件名中的非法字符"""
    forbidden = '<>:"/\\|?*'
    for ch in forbidden:
        name = name.replace(ch, "_")
    return name.strip()[:80]


def start_recording(output_wav):
    """启动 ffmpeg 录音子进程，返回 Popen 对象"""
    cmd = [
        FFMPEG, "-y",
        "-f", "dshow",
        "-i", "audio=CABLE Output (VB-Audio Virtual Cable)",
        str(output_wav),
    ]
    print(f"[Record] 开始录音 → {output_wav.name}")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def stop_recording(proc):
    """优雅停止 ffmpeg（通过 stdin 发送 'q'）"""
    if proc and proc.poll() is None:
        try:
            proc.stdin.write(b"q\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait()
    print("[Record] 录音已停止")


def slowdown_audio(input_wav, output_wav, speed):
    """
    用 ffmpeg atempo 将加速录音降回正常速度。
    atempo 单次支持 0.5~2.0，多次串联以支持更高倍速。
    例: speed=3.0 → atempo=0.5,atempo=0.6667 → 0.5*0.6667≈0.3333
    """
    target = 1.0 / speed  # 例如 3x → 0.333x

    filters = []
    remaining = target
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    if remaining > 0.001:  # 接近 1.0 就跳过
        filters.append(f"atempo={remaining:.4f}")

    filter_chain = ",".join(filters)
    cmd = [
        FFMPEG, "-y", "-i", str(input_wav),
        "-filter:a", filter_chain,
        "-q:a", "2",
        str(output_wav),
    ]
    print(f"[Slowdown] {speed}x -> 1x (filter: {filter_chain})")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_transcribe(audio_wav):
    """运行转录"""
    print("\n===== Transcribing =====")
    subprocess.run(
        [sys.executable, str(BASE / "transcribe_s.py"), str(audio_wav)],
        check=True,
    )


def run_summarize(txt_file):
    """运行摘要"""
    print("\n===== Summarizing =====")
    subprocess.run(
        [sys.executable, str(BASE / "summarize.py"), str(txt_file)],
        check=True,
    )


def run_make_md(txt_file, course_name, video_time):
    """生成带有课程元数据的 Markdown"""
    print("\n===== Generating Markdown =====")
    txt_path = Path(txt_file)
    s_txt = txt_path.with_suffix(".s.txt")
    summary = txt_path.with_suffix(".s.summary.txt")
    md = txt_path.with_suffix(".md")

    # 构建 Markdown
    header = f"# {course_name}\n\n"
    header += f"**录制时间**: {video_time}\n\n"
    header += f"**处理时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    header += "---\n\n"

    content = ""
    if summary.exists():
        content += summary.read_text(encoding="utf-8")
    elif s_txt.exists():
        content += s_txt.read_text(encoding="utf-8")
    elif txt_path.exists():
        content += txt_path.read_text(encoding="utf-8")

    md.write_text(header + content, encoding="utf-8")
    print(f"[Markdown] 已生成: {md}")


def process_audio_hls(wav, txt, course_name, video_time):
    """转录 → 摘要 → Markdown（全部串行，HLS 原速音频无需降速）"""
    print(f"\n[Proc] 处理: {wav.name}")
    try:
        run_transcribe(wav)
        run_summarize(txt)
        run_make_md(txt, course_name, video_time)
        print(f"[Proc] 完成: {wav.name}")
    except Exception as e:
        print(f"[Proc] 失败 ({wav.name}): {e}")


def transcribe_only(wav):
    """仅转录，不含摘要"""
    print(f"  [TR] {wav.name}...")
    try:
        run_transcribe(wav)
        return True
    except Exception as e:
        print(f"  [TR] 失败: {e}")
        return False


def parse_selection(choice, max_n):
    """
    解析选择字符串，返回去重后的索引列表。

    支持: 单个 '3', 逗号 '0,2,4', 范围 '0-4', 混合 '0,3-5,9', 'all', 'a'
    """
    choice = choice.strip().lower()
    if choice in ("all", "a"):
        return list(range(max_n))

    result = set()
    parts = choice.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                a, b = int(a.strip()), int(b.strip())
                if a > b:
                    a, b = b, a
                for i in range(a, b + 1):
                    if 0 <= i < max_n:
                        result.add(i)
            except ValueError:
                return None
        else:
            try:
                i = int(part)
                if 0 <= i < max_n:
                    result.add(i)
            except ValueError:
                return None
    return sorted(result) if result else None


def interactive_select():
    """二级交互：批量选课程 → 批量选视频"""
    from scraper import (
        get_course_list, print_course_list,
        get_video_list, print_video_list,
    )

    # ---- Level 1: 批量选择课程 ----
    courses = get_course_list()
    print_course_list(courses)

    if not courses:
        print("未找到课程")
        sys.exit(1)

    # 支持命令行传 --course-id / --course-ids
    selected_courses = []
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv):
            if arg in ("--course-id", "--course-ids") and i + 1 < len(sys.argv):
                raw = sys.argv[i + 1]
                # 先尝试逗号/范围解析
                indices = parse_selection(raw, len(courses))
                if indices:
                    selected_courses = [courses[j] for j in indices]
                else:
                    # 尝试直接匹配 course_id
                    for cid in raw.split(","):
                        c = next((c for c in courses if c["course_id"] == cid.strip()), None)
                        if c:
                            selected_courses.append(c)
                break

    if selected_courses:
        print(f"\n已选择 {len(selected_courses)} 门课程:")
        for c in selected_courses:
            print(f"  {c['course_id']}  {c['name']}")
    else:
        while True:
            choice = input(
                f"\n选择课程 (0-{len(courses)-1}, 逗号/范围/all/course_id) [q退出]: "
            ).strip()
            if choice.lower() == "q":
                sys.exit(0)
            # 直接 course_id 匹配
            c = next((c for c in courses if c["course_id"] == choice), None)
            if c:
                selected_courses = [c]
                break
            indices = parse_selection(choice, len(courses))
            if indices:
                selected_courses = [courses[j] for j in indices]
                break
            print("无效选择")

    print(f"\n已选择 {len(selected_courses)} 门课程")

    # ---- Level 2: 为每门课独立选择视频 ----
    plans = []  # [(course_name, [video_dict])]

    for ci, course in enumerate(selected_courses):
        try:
            cn, videos = get_video_list(course_id=course["course_id"])
        except Exception as e:
            print(f"\n{course['name']}: 无法获取视频列表 ({e})")
            continue

        if not videos:
            print(f"\n{course['name']}: 暂无视频")
            continue

        print_video_list(cn, videos)

        while True:
            choice = input(
                f"[{ci+1}/{len(selected_courses)}] {cn}\n"
                f"  选视频 (逗号/范围/all/s=跳过/q=退出): "
            ).strip()
            if choice.lower() == "q":
                sys.exit(0)
            if choice.lower() == "s":
                break
            indices = parse_selection(choice, len(videos))
            if indices:
                selected_videos = [videos[i] for i in indices]
                plans.append((cn, selected_videos))
                print(f"  -> {len(selected_videos)} 个视频加入队列")
                break
            print("  无效选择")

    if not plans:
        print("未选择任何视频")
        sys.exit(0)

    if not plans:
        print("未选择任何视频")
        sys.exit(0)

    total_videos = sum(len(v) for _, v in plans)
    print(f"\n{'='*50}")
    print(f"汇总: {len(plans)} 门课程, 共 {total_videos} 个视频")
    for cn, vids in plans:
        print(f"  {cn}: {len(vids)} 个")
    print(f"{'='*50}")

    return plans


def main():
    # ---- 解析模式 ----
    mode = "download"  # 默认 HLS 直下
    for i, arg in enumerate(sys.argv):
        if arg == "--mode" and i + 1 < len(sys.argv):
            mode = sys.argv[i + 1]
            if mode not in ("download", "stream"):
                print(f"无效模式: {mode}，可选 download / stream")
                sys.exit(1)

    # ---- Resume 模式：跳过所有交互，直接扫描 records/ ----
    if "--resume" in sys.argv:
        # 解析并发参数
        tr_workers = 1
        sum_workers = 4
        for i, arg in enumerate(sys.argv):
            if arg == "--transcribe-workers" and i + 1 < len(sys.argv):
                try: tr_workers = max(1, int(sys.argv[i + 1]))
                except ValueError: pass
            if arg == "--summarize-workers" and i + 1 < len(sys.argv):
                try: sum_workers = max(1, int(sys.argv[i + 1]))
                except ValueError: pass
        _run_hls_pipeline([], 0, dl_workers=0, m3u8_workers=0,
                          tr_workers=tr_workers, sum_workers=sum_workers, resume=True)
        return

    # ---- 命令行模式 ----
    if "--list" in sys.argv:
        from scraper import get_video_list, print_video_list
        course_id = None
        for i, arg in enumerate(sys.argv):
            if arg == "--course-id" and i + 1 < len(sys.argv):
                course_id = sys.argv[i + 1]
                break
        if not course_id:
            print("请用 --course-id 指定课程（先 python scraper.py --courses 查看课程列表）")
            sys.exit(1)
        cn, vids = get_video_list(course_id=course_id)
        print_video_list(cn, vids)
        return

    if "--token" in sys.argv:
        from scraper import get_video_list, decode_jwt
        token = None; course_id = None
        for i, arg in enumerate(sys.argv):
            if arg == "--token" and i + 1 < len(sys.argv): token = sys.argv[i + 1]
            if arg == "--course-id" and i + 1 < len(sys.argv): course_id = sys.argv[i + 1]
        if not token:
            print("需要 --token 参数"); sys.exit(1)
        cn, videos = get_video_list(course_id=course_id)
        if not videos:
            print(f"课程 {course_id or '未知'} 无视频")
            sys.exit(1)
        v_info = next((v for v in videos if v["token"] == token), None)
        if v_info is None:
            payload = decode_jwt(token)
            v_info = {"token": token, "record_time": payload.get("recordTime", "未知"),
                       "sub_id": payload.get("hqySubId", ""), "section": ""}
        plans = [(cn, [v_info])]
    else:
        plans = interactive_select()

    # 展平
    all_videos = []
    for cn, vids in plans:
        for v in vids:
            v["_course_name"] = cn
            all_videos.append(v)

    total = len(all_videos)
    print(f"\n{'='*50}")
    print(f"模式: {mode} | 共 {total} 个视频")
    print(f"{'='*50}")

    # 解析并发参数
    dl_workers = 4
    m3u8_workers = 1
    transcribe_workers = 1
    summarize_workers = 4
    for i, arg in enumerate(sys.argv):
        if arg == "--workers" and i + 1 < len(sys.argv):
            try:
                dl_workers = max(1, int(sys.argv[i + 1]))
            except ValueError:
                print(f"Invalid --workers: {sys.argv[i + 1]}"); sys.exit(1)
        if arg == "--m3u8-workers" and i + 1 < len(sys.argv):
            try:
                m3u8_workers = max(1, int(sys.argv[i + 1]))
            except ValueError:
                print(f"Invalid --m3u8-workers: {sys.argv[i + 1]}"); sys.exit(1)
        if arg == "--transcribe-workers" and i + 1 < len(sys.argv):
            try:
                transcribe_workers = max(1, int(sys.argv[i + 1]))
            except ValueError:
                print(f"Invalid --transcribe-workers: {sys.argv[i + 1]}"); sys.exit(1)
        if arg == "--summarize-workers" and i + 1 < len(sys.argv):
            try:
                summarize_workers = max(1, int(sys.argv[i + 1]))
            except ValueError:
                print(f"Invalid --summarize-workers: {sys.argv[i + 1]}"); sys.exit(1)

    if mode == "stream":
        _run_stream_pipeline(all_videos, total)
    else:
        resume = "--resume" in sys.argv
        _run_hls_pipeline(all_videos, total, dl_workers, m3u8_workers, transcribe_workers, summarize_workers, resume)


def _scan_records_for_resume():
    """扫描 records/ 下所有目录，找已下载但未转录/未摘要的 WAV。返回 [(wav, txt, cn, rt), ...]"""
    from pathlib import Path
    pending = []
    for wav_file in RECORDS.rglob("audio.wav"):
        out_dir = wav_file.parent
        if (out_dir / "audio.md").exists():
            continue  # 已完成
        txt = out_dir / "audio.txt"
        s_txt = out_dir / "audio.s.txt"

        # 从路径推导课程名（父目录名）
        cn = out_dir.parent.name
        rt = out_dir.name

        status = "need_all"
        if (s_txt.exists() and s_txt.stat().st_size > 0) or \
           (txt.exists() and txt.stat().st_size > 0):
            status = "need_summary"

        pending.append((wav_file, txt, cn, rt, status))
    return pending


def _run_hls_pipeline(all_videos, total, dl_workers=4, m3u8_workers=1, tr_workers=1, sum_workers=4, resume=False):
    """Phase 1: capture m3u8 → Phase 2: parallel download → Phase 3: transcribe → Phase 4: summarize"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from player import capture_m3u8_url, download_hls_audio

    # ---- Resume 模式：跳过 Phase 1-2，扫描已有文件 ----
    if resume:
        pending = _scan_records_for_resume()
        print(f"\n[Resume] 扫描到 {len(pending)} 个待处理")
        need_tr = [(w, t, cn, rt) for w, t, cn, rt, s in pending if s == "need_all"]
        need_sum = [(w, t, cn, rt) for w, t, cn, rt, s in pending if s == "need_summary"]
        print(f"  需转录+摘要: {len(need_tr)}")
        print(f"  仅需摘要(已有转录): {len(need_sum)}")

        # Phase 3: 转录
        if need_tr:
            print(f"\n{'='*50}")
            print(f"Phase 3: 并行转录 ({len(need_tr)} 个, {tr_workers} 并发)")
            print(f"{'='*50}")
            tr_ok = []
            with ThreadPoolExecutor(max_workers=min(tr_workers, len(need_tr))) as pool:
                futures = {pool.submit(transcribe_only, w): (w, t, cn, rt) for w, t, cn, rt in need_tr}
                for fut in as_completed(futures):
                    ok = fut.result()
                    meta = futures[fut]
                    tr_ok.append((*meta, ok))
            # 转录完的也加入摘要队列
            need_sum += [(w, t, cn, rt) for w, t, cn, rt, ok in tr_ok if ok]

        # Phase 4: 并行摘要
        if need_sum:
            print(f"\n{'='*50}")
            print(f"Phase 4: 并行摘要 ({len(need_sum)} 个, {sum_workers} 并发)")
            print(f"{'='*50}")

            def _resume_summarize(wav, txt, cn, rt):
                try:
                    run_summarize(txt)
                    run_make_md(txt, cn, rt)
                    return (cn, rt, True, "OK")
                except Exception as e:
                    return (cn, rt, False, str(e))

            with ThreadPoolExecutor(max_workers=min(sum_workers, len(need_sum))) as pool:
                futures = {pool.submit(_resume_summarize, w, t, c, r): (c, r) for w, t, c, r in need_sum}
                for i, fut in enumerate(as_completed(futures)):
                    cn, rt, ok, msg = fut.result()
                    print(f"  [{i+1}/{len(need_sum)}] {cn}/{rt}: {msg}")

        print(f"\n{'='*50}")
        print(f"续传完成！转录: {len(need_tr)}, 摘要: {len(need_sum)}")
        print(f"{'='*50}")
        return

    # ---- 正常流水线 ----
    # ---- Phase 1: 抓取所有 m3u8 URL ----
    print(f"\n{'='*50}")
    print(f"Phase 1: 抓取 m3u8 URL ({total} 个视频)")
    print(f"{'='*50}")

    tasks = []
    for vi, video_info in enumerate(all_videos):
        course_name = video_info["_course_name"]
        record_time = video_info.get("record_time", datetime.now().strftime("%Y-%m-%d_%H-%M"))
        safe_course = sanitize_filename(course_name)
        safe_ts = sanitize_filename(record_time)
        out_dir = RECORDS / safe_course / safe_ts
        out_dir.mkdir(parents=True, exist_ok=True)

        wav = out_dir / "audio.wav"
        txt = out_dir / "audio.txt"

        print(f"\n[{vi+1}/{total}] {course_name} / {record_time}")

        if (out_dir / "audio.md").exists():
            print("  [Skip] 已有笔记")
            continue
        if (out_dir / "audio.s.txt").exists() or (out_dir / "audio.txt").exists():
            print("  [Skip] 已有转录(等待摘要)，用 --resume 续传")
            continue

        try:
            m3u8_url = capture_m3u8_url(video_info["token"])
            print(f"  m3u8: {m3u8_url[:100]}...")
            tasks.append((wav, txt, course_name, m3u8_url, record_time))
        except Exception as e:
            print(f"  [FAIL] 抓取失败: {e}")

    if not tasks:
        print("\n没有待下载的视频（如有已下载未转录的，用 --resume 续传）")
        return

    # ---- Phase 2: 并行下载音频 ----
    workers = min(dl_workers, len(tasks))
    print(f"\n{'='*50}")
    print(f"Phase 2: 并行下载音频 ({len(tasks)} 个, {workers} 并发)")
    print(f"{'='*50}")

    def _download_one(wav, txt, cn, m3u8_url, rt):
        print(f"  [DL] {wav.parent.name}...")
        ok = download_hls_audio(m3u8_url, wav)
        if ok:
            return (wav, txt, cn, rt, True)
        else:
            return (wav, txt, cn, rt, False)

    completed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, *t): t for t in tasks}
        for fut in as_completed(futures):
            result = fut.result()
            completed.append(result)
            print(f"  [OK] {result[0].parent.name}" if result[4] else f"  [FAIL] {result[0].parent.name}")

    # ---- Phase 3: 并行转录（GPU 显存够就多开，默认 1） ----
    success = [c for c in completed if c[4]]
    print(f"\n{'='*50}")
    print(f"Phase 3: 并行转录 ({len(success)} 个视频, {tr_workers} 并发)")
    print(f"{'='*50}")

    tr_results = []
    with ThreadPoolExecutor(max_workers=min(tr_workers, len(success))) as pool:
        futures = {pool.submit(transcribe_only, wav): (wav, txt, cn, rt) for wav, txt, cn, rt, _ in success}
        for fut in as_completed(futures):
            result = fut.result()
            meta = futures[fut]
            tr_results.append((*meta, result))

    # ---- Phase 4: 并行摘要 ----
    print(f"\n{'='*50}")
    print(f"Phase 4: 并行摘要 ({len(tr_results)} 个, {sum_workers} 并发)")
    print(f"{'='*50}")

    def _summarize_one(wav, txt, cn, rt, ok):
        if not ok:
            return (cn, rt, False, "转录失败")
        if (wav.parent / "audio.md").exists():
            return (cn, rt, True, "已有笔记(skip)")
        try:
            run_summarize(txt)
            run_make_md(txt, cn, rt)
            return (cn, rt, True, "OK")
        except Exception as e:
            return (cn, rt, False, str(e))

    with ThreadPoolExecutor(max_workers=min(sum_workers, len(tr_results))) as pool:
        futures = {pool.submit(_summarize_one, *s): s for s in tr_results}
        for i, fut in enumerate(as_completed(futures)):
            cn, rt, ok, msg = fut.result()
            print(f"  [{i+1}/{len(tr_results)}] {cn}/{rt}: {msg}")

    print(f"\n{'='*50}")
    print(f"全部完成！成功: {len(success)}/{total}")
    print(f"笔记在: {RECORDS}")
    print(f"{'='*50}")


def _run_stream_pipeline(all_videos, total):
    """原流式录制模式（VB-Cable + 实时播放），保留作为 fallback"""
    import threading

    speed = 2.0
    for i, arg in enumerate(sys.argv):
        if arg == "--speed" and i + 1 < len(sys.argv):
            try: speed = float(sys.argv[i + 1])
            except ValueError: pass

    print(f"播放速度: {speed}x")

    bg_threads = []
    for vi, video_info in enumerate(all_videos):
        course_name = video_info["_course_name"]
        ts = video_info.get("record_time", datetime.now().strftime("%Y-%m-%d_%H-%M"))
        safe_course = sanitize_filename(course_name)
        safe_ts = sanitize_filename(ts)
        out_dir = RECORDS / safe_course / safe_ts
        out_dir.mkdir(parents=True, exist_ok=True)

        wav = out_dir / "audio.wav"
        txt = out_dir / "audio.txt"

        print(f"\n{'='*50}")
        print(f"[{vi+1}/{total}] {course_name} / {ts}")
        print(f"输出: {out_dir}")
        print(f"{'='*50}")

        if (out_dir / "audio.md").exists():
            print("[Skip] 已有笔记"); continue

        rec_proc = start_recording(wav)
        from player import play_video
        print(f"\n===== Auto-playing ({speed}x) =====")
        play_video(video_info["token"], speed=speed)
        stop_recording(rec_proc)

        if not wav.exists() or wav.stat().st_size == 0:
            print("错误: 录音文件为空"); continue

        print(f"音频: {wav} ({wav.stat().st_size:,} bytes)")

        t = threading.Thread(
            target=_process_audio_stream,
            args=(wav, txt, course_name, video_info["record_time"], speed),
            daemon=True,
        )
        t.start(); bg_threads.append(t)
        print(f"[{vi+1}/{total}] 转录已提交后台")

    for i, t in enumerate(bg_threads):
        t.join(); print(f"后台 [{i+1}/{len(bg_threads)}] 完成")

    print(f"\n{'='*50}")
    print(f"全部完成！共 {total} 个视频")
    print(f"笔记在: {RECORDS}")
    print(f"{'='*50}")


def _process_audio_stream(wav, txt, course_name, video_time, speed):
    """stream 模式后台处理: 降速 → 转录 → 摘要"""
    if speed != 1.0:
        slow_wav = wav.with_stem(wav.stem + "_1x")
        try: slowdown_audio(wav, slow_wav, speed)
        except: slow_wav = wav
    else:
        slow_wav = wav
    try:
        run_transcribe(slow_wav)
        run_summarize(txt)
        run_make_md(txt, course_name, video_time)
    except Exception as e:
        print(f"处理失败: {e}")


if __name__ == "__main__":
    main()
