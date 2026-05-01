import os
import sys
import requests
import json
import time
import re
from pathlib import Path

# -----------------------------
# 配置与全局变量
# -----------------------------
API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not API_KEY:
    raise RuntimeError("请设置 DEEPSEEK_API_KEY 环境变量")

CHUNK_SIZE = 300000  
OVERLAP_SIZE = 10000
RETRIES = 3
MAX_CONTEXT_TOKENS_LIMIT = 900000 

# 1. 一次性处理模式 (One-shot) - 优先使用
FULL_SUMMARY_PROMPT = (
    "你是一位深耕生物化学与分子生物学领域的资深学术专家。请对以下整堂分子生物学课的录音转录文本进行系统性建模。\n\n"
    "任务要求：\n"
    "1. 【逻辑建模】：不要简单列举，请梳理出知识点的演进逻辑（例如：从实验矛盾出发，引出机制 A，再到调控机制 B 的发现），同时尽可能按照讲课顺序组织内容。\n"
    "2. 【深度提取】：保留核心机制、关键酶名称、蛋白质复合体及重要的动力学/结构参数。\n"
    "3. 【重点标记】：突出老师在讲解中反复提及或明确指出的难点和重点（Exam Points）。\n"
    "4. 【格式规约】：使用 Markdown 标题层级，专业术语首次出现请保留英文原文。\n"
    "5. 【语言要求】：全文使用精准、专业的学术中文输出。不要加入无关的开场白、礼貌性回复。\n\n"
    "待处理文本内容：\n{content}"
)

# 2. 多块处理模式 (Multi-chunk) - 备用方案
SECTION_PROMPT = (
    "你是一位生物化学助教。请对以下讲义片段进行精炼总结。\n"
    "要求：仅提取核心机制与逻辑推导，术语保留英文缩写，即使输入是英文也请使用中文总结，字数控制在原片段 10%-15%。\n\n"
    "待总结文本：\n{content}"
)

GLOBAL_PROMPT = (
    "你是一位专业的生物医学分析专家。请根据各段摘要，构建整堂课的【逻辑脉络图】。\n"
    "要求：使用中文梳理知识点递进关系，字数控制在 800 字以内。\n\n"
    "段落摘要列表：\n{content}"
)

REFINE_PROMPT = (
    "【全局逻辑】：{global_summary}\n"
    "【上文简述】：{prev_summary}\n\n"
    "任务：结合全局逻辑将当前草稿修整为【极简复习笔记】。要求：去重优先，严禁扩充，Markdown 列表形式，单段限 400 字内，统一中文。"
)

# -----------------------------
# 核心功能函数
# -----------------------------

def call_deepseek(prompt, max_tokens=3000):
    """调用 DeepSeek V4-Pro 接口"""
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "reasoning_effort": "max",  # 确保键名有引号，使用冒号
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
            # V4 处理长文本时计算耗时较长，增加 timeout
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"API 请求失败，重试 ({i+1}/{RETRIES}): {e}")
            time.sleep(5)
    return "[此部分处理失败]"

def split_text_with_overlap(text, chunk_size, overlap):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return chunks

# -----------------------------
# 主程序逻辑
# -----------------------------

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
    
    # 估算 Tokens (V4 编码器下中文约 0.6 字符/token，英文约 4 字符/token，取保守中间值)
    estimated_tokens = len(content) * 1.5 
    print(f"预估 Token 数: ~{int(estimated_tokens):,}")

    # --- 策略 A：一键全量总结 (One-shot) ---
    if estimated_tokens < MAX_CONTEXT_TOKENS_LIMIT:
        print("💡 文本在 V4-Pro 上下文范围内，启动『上帝视角』全量总结模式...")
        
        final_result = call_deepseek(FULL_SUMMARY_PROMPT.format(content=content), max_tokens=8000)
        
        output_header = "="*50 + "\n深度学术总结 (DeepSeek V4-Pro)\n" + "="*50 + "\n\n"
        output_path = input_path.with_suffix(".summary.txt")
        output_path.write_text(output_header + final_result, encoding="utf-8")
        print(f"总结完成！已保存至: {output_path}")
        return

    # --- 策略 B：多块级联处理 (当文本异常巨大时) ---
    print(f"⚠️ 文本量过大，正在进行分块处理 (每块 {CHUNK_SIZE} 字符)...")
    chunks = split_text_with_overlap(content, CHUNK_SIZE, OVERLAP_SIZE)
    
    # 1. 分段摘要
    initial_summaries = []
    for i, chunk in enumerate(chunks, 1):
        print(f"正在处理第 {i}/{len(chunks)} 个片段...")
        s = call_deepseek(SECTION_PROMPT.format(content=chunk), max_tokens=2000)
        initial_summaries.append(s)

    # 2. 生成全局脉络
    print("正在构建全局逻辑地图...")
    combined_notes = "\n".join([f"【片段 {idx+1}】\n{txt}" for idx, txt in enumerate(initial_summaries)])
    global_context = call_deepseek(GLOBAL_PROMPT.format(content=combined_notes), max_tokens=2000)

    # 3. 循环精炼
    print("正在根据全局逻辑进行最终精炼...")
    final_summaries = []
    prev_s = "开头部分"
    for i, s_draft in enumerate(initial_summaries, 1):
        print(f"正在精炼第 {i}/{len(initial_summaries)} 段...")
        refined = call_deepseek(REFINE_PROMPT.format(
            global_summary=global_context,
            prev_summary=prev_s,
            section=s_draft
        ), max_tokens=1500)
        final_summaries.append(refined)
        prev_s = refined[:300]

    # 保存分块总结结果
    output_path = input_path.with_suffix(".summary.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("="*50 + "\n课程全局逻辑脉络\n" + "="*50 + "\n")
        f.write(global_context + "\n\n")
        f.write("="*50 + "\n详细分段笔记\n" + "="*50 + "\n")
        f.write("\n\n".join([f"## 部分 {i}\n{s}" for i, s in enumerate(final_summaries, 1)]))
    
    print(f"多级总结完成！结果已保存至: {output_path}")

if __name__ == "__main__":
    main()