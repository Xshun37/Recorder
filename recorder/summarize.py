import os
import sys
import requests
import time
from pathlib import Path

# 加载项目根 .env
_dp = Path(__file__).resolve().parent
for _ in range(5):
    _e = _dp / ".env"
    if _e.exists():
        for _ln in _e.read_text(encoding="utf-8").splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                _k, _v = _ln.split("=", 1)
                _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                if "xxx" not in _v and "你的" not in _v:
                    os.environ.setdefault(_k, _v)
        break
    _dp = _dp.parent

# -----------------------------
# 配置与全局变量
# -----------------------------
API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    raise RuntimeError("请设置 DEEPSEEK_API_KEY 环境变量")

RETRIES = 3

SYSTEM_PROMPT = """
# Background
You are a senior academic expert specializing in biochemistry, molecular biology, and genetics, with deep insight into structuring lecture content for pedagogical purposes. The user provides a raw lecture transcript for you to organize.

# Objective
Produce a structured, comprehensive set of academic lecture notes based on the transcript. Output in Chinese only.

# Format
1. Use Markdown. Maximum heading level: H3.
2. No word limit. Follow the lecture's original order of presentation.

# Content Requirements
1. **Logical Modeling** — Do not simply enumerate facts. Trace the conceptual progression (e.g., from experimental contradiction → hypothesis → mechanism A → regulatory mechanism B). Expand where helpful to make the content accessible to readers without prior knowledge of the topic.
2. **Deep Extraction** — Preserve core mechanisms, key entities, and their abbreviations (gene names, protein names, acronyms).
3. **Exam Points** — Flag concepts the lecturer repeatedly emphasizes or explicitly identifies as difficult or important.
4. **Language**:
   a. Use precise, professional academic Chinese. No colloquialisms. Do not address or converse with the user.
   b. If a metaphor or analogy appears in the transcript, retain it. Otherwise, do NOT invent any metaphors to explain mechanisms.
   c. No opening pleasantries, closing remarks, or filler text.
"""

USER_PROMPT = """
# Content to Analyze
The following is the lecture transcript. Analyze it according to the requirements above and output a structured Chinese summary.
==========
{content}
==========
"""


def call_deepseek(content, max_tokens=32768):
    """调用 DeepSeek V4-Pro 接口 (system + user 双消息)"""
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-v4-pro",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT.format(content=content)},
        ],
        "max_tokens": max_tokens,
        "reasoning_effort": "max",
        "extra_body": {
            "thinking": {
                "type": "enabled"
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    for i in range(RETRIES):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"API 请求失败，重试 ({i+1}/{RETRIES}): {e}")
            time.sleep(5)
    return "[此部分处理失败]"


def main():
    # 文件读取逻辑
    if len(sys.argv) < 2:
        input_path = Path("audio.s.txt")
    else:
        input_path = Path(sys.argv[1]).with_suffix(".s.txt")

    if not input_path.exists():
        print(f"错误：找不到输入文件 {input_path}")
        return

    print(f"正在读取文件: {input_path.name}")
    content = input_path.read_text(encoding="utf-8")

    estimated_tokens = len(content) * 1.5
    print(f"预估 Token 数: ~{int(estimated_tokens):,}")

    final_result = call_deepseek(content, max_tokens=32768)

    output_header = "=" * 50 + "\n深度学术总结 (DeepSeek V4-Pro)\n" + "=" * 50 + "\n\n"
    output_path = input_path.with_suffix(".summary.txt")
    output_path.write_text(output_header + final_result, encoding="utf-8")
    print(f"总结完成！已保存至: {output_path}")


if __name__ == "__main__":
    main()
