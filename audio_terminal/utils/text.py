import re

def simple_t2s(text):
    """极其轻量级的常见繁简转换，用于处理 STT 偶发的繁体输出"""
    mapping = {
        '閉': '闭', '嘴': '嘴', '說': '说', '別': '别', '講': '讲',
        '停': '停', '止': '止', '安': '安', '靜': '静', '為': '为',
        '聽': '听', '開': '开', '關': '关', '燈': '灯', '溫': '温',
        '氣': '气', '天': '天', '預': '预', '報': '报', '啟': '启',
        '處': '处', '理': '理', '現': '现', '場': '场', '機': '机'
    }
    for t_char, s_char in mapping.items():
        text = text.replace(t_char, s_char)
    return text

def filter_symbols(text):
    """极强力过滤：剔除所有可能导致 MOSS 产生“外星语”的干扰项"""
    if not text: return ""

    # 1. 移除思维链标签及其内容 (加强版正则)
    tags = ["think", "thinking", "reasoning", "thought", "REASONING_SCRATCHPAD"]
    for tag in tags:
        text = re.sub(rf'<{tag}>.*?</{tag}>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(rf'</?{tag}>', '', text, flags=re.IGNORECASE)

    # 2. 符号口语化预处理 (扩充库)
    symbol_map = {
        '℃': '度',
        '~': '到',
        '～': '到',
        '%': '百分之',
        ':': '：',
        '：': '：',
        '+': '加',
        '-': '减',
        '*': '乘',
        '/': '除',
        '=': '等于',
        '>': '大于',
        '<': '小于'
    }
    for k, v in symbol_map.items():
        text = text.replace(k, v)

    # 3. 移除 Markdown 装饰符
    text = text.replace('**', '')
    text = text.replace('__', '')
    text = re.sub(r'^[-\*\#]\s*', '', text, flags=re.MULTILINE) 
    
    # 4. 移除注释风格的括号内容
    text = re.sub(r'[\(\uff08](思考|动作|笑|哭|叹气|语气|暂停|停顿|背景音).*?[\uff09\)]', '', text)
    # 特殊：如果括号内是普通文字，只剥离括号
    text = text.replace('(', '').replace(')', '').replace('（', '').replace('）', '')
    
    # 5. 保留核心标点及中英文数字
    text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9，。！？.,!?]', '', text)
    
    text = text.strip()
    if not text: return ""
    
    # 6. [核心优化] 强力 EOS 注入
    # MOSS-TTS 如果没有标点结尾，会产生极长噪音
    if not re.search(r'[，。！？.,!?]$', text):
        text += "。"
    
    # 将弱标点标准化为强标点，有助于结句
    weak_to_strong = {
        '，': '。',
        ',': '。',
        '：': '。',
        ':': '。',
        '；': '。',
        ';': '。'
    }
    if text[-1] in weak_to_strong:
        text = text[:-1] + weak_to_strong[text[-1]]
        
    return text

def split_text(text, zh_voice="zm_yunxi", en_voice="am_adam"):
    """根据语种切分中英文字段，数字跟随上下文语种"""
    pattern = r'([a-zA-Z][a-zA-Z\s.,!?\'";\-:]+)'
    segments = []
    last_end = 0
    for match in re.finditer(pattern, text):
        start, end = match.start(), match.end()
        if start > last_end:
            zh_part = text[last_end:start].strip()
            if zh_part:
                segments.append({"text": zh_part, "voice": zh_voice})
        en_part = match.group().strip()
        if en_part:
            segments.append({"text": en_part, "voice": en_voice})
        last_end = end
    if last_end < len(text):
        zh_part = text[last_end:].strip()
        if zh_part:
            segments.append({"text": zh_part, "voice": zh_voice})
    
    if not segments:
        segments.append({"text": text.strip(), "voice": zh_voice})

    # 碎片吸附逻辑
    processed = []
    for s in segments:
        if not processed:
            processed.append(s)
        else:
            if len(s["text"]) <= 1 and not re.search(r'[\u4e00-\u9fa5a-zA-Z0-9]', s["text"]):
                processed[-1]["text"] += s["text"]
            else:
                processed.append(s)
    return processed
