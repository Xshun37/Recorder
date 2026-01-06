import os
import sys
import requests
import json
import time
from pathlib import Path

# -----------------------------
# 配置
# -----------------------------
API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    raise RuntimeError("Please set DEEPSEEK_API_KEY environment variable")

CHUNK_SIZE = 3000
MIN_CHUNK_SIZE = 500

INITIAL_MAX_TOKENS = 1200
GROUP_MAX_TOKENS = 1300
FINAL_MAX_TOKENS = 1500
REFINE_MAX_TOKENS = 1500

GROUP_SIZE = 4
RETRIES = 3
RETRY_DELAY = 2

# -----------------------------
# 输入文件
# -----------------------------
if len(sys.argv) >= 2:
    txt_path = Path(sys.argv[1]).resolve()
else:
    txt_path = Path("test.s.txt").resolve()

if not txt_path.exists():
    print(f"File not found: {txt_path}")
    sys.exit(1)

text_content = txt_path.read_text(encoding="utf-8")

# -----------------------------
# 分段
# -----------------------------
def split_text(text, chunk_size=CHUNK_SIZE):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            newline_pos = text.rfind("\n", start, end)
            if newline_pos != -1:
                end = newline_pos
        chunks.append(text[start:end].strip())
        start = end
    return chunks

# -----------------------------
# API 调用
# -----------------------------
def call_deepseek(prompt, max_tokens):
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-reasoner",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()

def call_with_retry(prompt, max_tokens):
    for attempt in range(1, RETRIES + 1):
        try:
            return call_deepseek(prompt, max_tokens)
        except requests.HTTPError as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                raise

def summarize_smart(prompt, max_tokens):
    prompt = prompt.encode("utf-8", errors="ignore").decode("utf-8")
    try:
        return call_with_retry(prompt, max_tokens)
    except requests.HTTPError as e:
        if e.response.status_code == 400:
            if len(prompt) <= MIN_CHUNK_SIZE:
                return "[Error in this chunk]"
            mid = len(prompt) // 2
            left = summarize_smart(prompt[:mid], max_tokens)
            right = summarize_smart(prompt[mid:], max_tokens)
            return left + "\n\n" + right
        else:
            raise

# -----------------------------
# 通用 Prompt 模板（安全写法）
# -----------------------------

SECTION_PROMPT = (
    "You are a domain-agnostic expert reader and technical summarizer.\n\n"
    "Task:\n"
    "Summarize the following text in clear, accurate Chinese.\n\n"
    "Requirements:\n"
    "- Preserve all key concepts, definitions, mechanisms, and logical relationships\n"
    "- Do NOT oversimplify technical content\n"
    "- Do NOT introduce information not present in the text\n"
    "- Maintain the original structure and emphasis\n"
    "- Use precise terminology; keep specialized terms unchanged\n"
    "- Focus strictly on this section only\n\n"
    "Text:\n"
    "{content}"
)

MERGE_PROMPT = (
    "You are a domain-agnostic expert summarizer.\n\n"
    "Task:\n"
    "Merge the following section summaries into a coherent Chinese summary.\n\n"
    "Requirements:\n"
    "- Retain all important points and technical terminology\n"
    "- Preserve logical structure\n"
    "- Do NOT add external knowledge\n\n"
    "Summaries:\n"
    "{content}"
)

GLOBAL_PROMPT = (
    "You are a domain-agnostic expert analyst.\n\n"
    "Task:\n"
    "Produce a comprehensive global overview of the following summaries.\n\n"
    "Requirements:\n"
    "- Capture overall structure and themes\n"
    "- Identify key mechanisms and conceptual relations\n"
    "- Do NOT add external information\n\n"
    "Content:\n"
    "{content}"
)

REFINE_PROMPT = (
    "You are a domain-agnostic expert editor.\n\n"
    "GLOBAL OVERVIEW (context):\n"
    "{global_summary}\n\n"
    "SECTION SUMMARY:\n"
    "{section}\n\n"
    "Task:\n"
    "Rewrite and expand the section summary in Chinese so that it is:\n"
    "- More detailed and complete\n"
    "- Consistent with the global overview\n"
    "- Focused ONLY on this section\n"
    "- Clear in logical structure\n\n"
    "Do NOT summarize the entire text."
)


# -----------------------------
# 1. 初步 chunk 总结
# -----------------------------
chunks = split_text(text_content)
initial_summaries = []

for i, chunk in enumerate(chunks, 1):
    print(f"Summarizing chunk {i}/{len(chunks)}...")
    lines = chunk.split("\n")
    head = "\n".join(lines[:2]) if len(lines) >= 2 else chunk

    prompt = SECTION_PROMPT.format(
        content=f"[Section preview]\n{head}\n\n{chunk}"
    )

    s = summarize_smart(prompt, INITIAL_MAX_TOKENS)
    initial_summaries.append(s)

# -----------------------------
# 2. 小组汇总
# -----------------------------
def group_summarize(summaries):
    result = []
    total = (len(summaries) + GROUP_SIZE - 1) // GROUP_SIZE
    for i in range(0, len(summaries), GROUP_SIZE):
        print(f"Summarizing group {i//GROUP_SIZE + 1}/{total}...")
        group_text = "\n\n".join(summaries[i:i + GROUP_SIZE])
        prompt = MERGE_PROMPT.format(content=group_text)
        s = summarize_smart(prompt, GROUP_MAX_TOKENS)
        result.append(s)
    return result

group_summaries = group_summarize(initial_summaries)

# -----------------------------
# 3. 全局总结（仅作背景）
# -----------------------------
print("Generating global overview (context only)...")
global_prompt = GLOBAL_PROMPT.format(content="\n\n".join(group_summaries))
global_summary = summarize_smart(global_prompt, FINAL_MAX_TOKENS)

# -----------------------------
# 4. 回写增强
# -----------------------------
def refine_with_global(chunks, global_summary):
    refined = []
    for i, chunk_summary in enumerate(chunks, 1):
        print(f"Refining chunk {i}/{len(chunks)}...")
        prompt = REFINE_PROMPT.format(
            global_summary=global_summary,
            section=chunk_summary
        )
        s = summarize_smart(prompt, REFINE_MAX_TOKENS)
        refined.append(s)
    return refined

refined_summaries = refine_with_global(initial_summaries, global_summary)

# -----------------------------
# 5. 输出
# -----------------------------
out_file = txt_path.with_suffix(".s.summary.txt")
out_text = "\n\n".join(refined_summaries)
out_file.write_text(out_text, encoding="utf-8")

print(f"Summary completed. Output file: {out_file}")
