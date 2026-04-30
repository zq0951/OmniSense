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
