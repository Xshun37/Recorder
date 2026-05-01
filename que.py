import os
from openai import OpenAI

# 从环境变量获取
raw_key = os.getenv("DEEPSEEK_API_KEY", "").strip()

print(f"检查：API Key 已读取，长度为 {len(raw_key)} 位")

client = OpenAI(
    api_key=raw_key,
    base_url="https://api.deepseek.com"
)

def load_notes(directory="."):
    all_content = ""
    file_count = 0
    # 使用 os.walk 遍历所有子目录
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".md"):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        all_content += f"\n--- 文件: {filename} ---\n{content}"
                        file_count += 1
                        print(f"已读取: {filename}")
                except Exception as e:
                    print(f"读取 {filename} 失败: {e}")
    
    print(f"读取完毕，共计 {file_count} 个文件。")
    return all_content

# 1. 加载笔记
print("正在读取 Markdown 笔记...")
knowledge_base = load_notes()

# 2. 设置系统 Prompt
system_prompt = (
    "你是一个分子生物学教授。我为你提供了我所有的课堂笔记。\n"
    "你的任务是：\n"
    "1. 深入分析笔记中的逻辑细节。\n"
    "2. 每次只出一道题（多选、简答或机制分析题）。\n"
    "3. 在我回答后，给出评价和正确的原理解释，然后出下一道题。\n"
    "4. 请优先考察核小体表观遗传、重组及转座。"
)

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": f"这是我的笔记内容，请开始出题：\n\n{knowledge_base}"}
]

print("--- DeepSeek V4-Pro (Think Max 模式) 已就绪 ---")

# 3. 循环对话（模拟考试）
while True:
    # 开启推理最大化模式 (Think Max)
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=messages,
        reasoning_effort="max",  # 开启最高推理强度
        stream=True
    )

    print("\n教授:", end=" ", flush=True)
    full_reply = ""
    for chunk in response:
        if chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            print(content, end="", flush=True)
            full_reply += content
    print("\n")
    
    messages.append({"role": "assistant", "content": full_reply})
    
    user_answer = input("你的回答 (输入 exit 退出): ")
    if user_answer.lower() in ["exit", "quit"]:
        break
    messages.append({"role": "user", "content": user_answer})