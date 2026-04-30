import re


def parse_funasr_tags(text):
    """
    Parses SenseVoiceSmall tags from the recognition result.
    Example: <|zh|><|ANGRY|><|Speech|>你好 -> text: "你好", emotion: "ANGRY", lang: "zh", event: "Speech"
    """
    if not text:
        return {"text": "", "emotion": None, "lang": None, "event": None, "is_speech": False}

    # Extract all tags like <|TAG|>
    tags = re.findall(r'<\|(.*?)\|>', text)

    # Remove all tags to get the clean text
    clean_text = re.sub(r'<\|.*?\|>', '', text).strip()

    emotion = None
    lang = None
    event = None

    # Common emotions in SenseVoice: HAPPY, SAD, ANGRY, NEUTRAL, EMO_UNKNOWN
    emotions_map = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "EMO_UNKNOWN"}

    # Common languages: zh, en, jp, ko
    langs_map = {"zh", "en", "jp", "ko", "yue", "auto"}

    # Event tags (VAD/Environment)
    events_map = {"Speech", "Music", "Laughter", "Applause"}

    for tag in tags:
        if tag in emotions_map:
            # 优先保留非 NEUTRAL/UNKNOWN 的情绪标签
            if not emotion or emotion in ["NEUTRAL", "EMO_UNKNOWN"]:
                emotion = tag
        elif tag in langs_map:
            lang = tag
        elif tag in events_map:
            event = tag

    # VAD Logic: Is it actually speech?
    # 1. Has <|Speech|> tag
    # 2. Or has no event tag but has valid text (fallback)
    # 3. Exclude cases that are only Music/Laughter/Applause
    is_speech = False
    if event == "Speech":
        is_speech = True
    elif not event and clean_text:
        is_speech = True
    
    # 特殊过滤：如果文本包含 [IGNORE] 或者为空，则不是有效语音
    if "[IGNORE]" in clean_text or not clean_text:
        is_speech = False

    return {
        "text": clean_text,
        "emotion": emotion,
        "lang": lang,
        "event": event,
        "is_speech": is_speech
    }


if __name__ == "__main__":
    test_cases = [
        "<|zh|><|ANGRY|><|Speech|>什么都行啊，全给你套上了吧",
        "<|en|><|HAPPY|><|Speech|>Hello world!",
        "<|zh|><|NEUTRAL|><|Music|>",
        "<|zh|><|NEUTRAL|><|Laughter|>哈哈",
        "<|zh|><|NEUTRAL|><|Speech|>[IGNORE]",
        "No tags here but some text"
    ]
    for tc in test_cases:
        print(f"Input: {tc}")
        res = parse_funasr_tags(tc)
        print(f"Output: {res}")
        print(f"VAD Decision (is_speech): {res['is_speech']}")
        print("-" * 20)
