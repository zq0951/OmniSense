import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "logs/stt_history.jsonl")
FILTER_FILE = os.path.join(BASE_DIR, "hallucination_data/filter_list.json")

def analyze():
    if not os.path.exists(LOG_FILE):
        print("未找到 STT 历史日志。")
        return

    print("\n--- 最近 20 条识别记录 ---")
    with open(LOG_FILE, 'r') as f:
        lines = f.readlines()
        for line in lines[-20:]:
            data = json.loads(line)
            status = "[幻觉]" if data['is_hallucination'] else "[正常]"
            print(f"{data['timestamp']} {status}: {data['text']} (录音: {data['audio_file']})")

    # 统计高频非正常词汇
    print("\n--- 幻觉词补充建议 ---")
    hallucinations = []
    with open(LOG_FILE, 'r') as f:
        for line in f:
            data = json.loads(line)
            if not data['is_hallucination'] and len(data['text']) < 5:
                # 记录那些长度短但没被过滤的，可能有漏网之鱼
                hallucinations.append(data['text'].lower())
    
    if hallucinations:
        from collections import Counter
        most_common = Counter(hallucinations).most_common(5)
        print("以下关键词识别频率高且短，建议考虑加入 filter_list.json:")
        for word, count in most_common:
            print(f"- {word} (出现 {count} 次)")

if __name__ == "__main__":
    analyze()
