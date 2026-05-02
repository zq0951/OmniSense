import logging
import httpx
import json
import queue
import threading
import time
import re
import asyncio
from core.shared import get_silent_mode, set_silent_mode, get_user_emotion
from core.actions import GLOBAL_ACTION_MGR
from core.controller import TASK_CTRL
from core.tts import synthesis_worker, playback_worker
from config import AGENT_URL, AGENT_TOKEN, SENTENCE_DELIMITERS, MIN_SENTENCE_LEN, MAX_SENTENCE_LEN, SECONDARY_DELIMITERS

logger = logging.getLogger("OmniSenseAudio")

_llm_client = None


def get_llm_client():
    global _llm_client
    if _llm_client is None:
        _llm_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=5.0))
    return _llm_client


def handle_immediate_actions(text):
    """处理不需要经过 LLM 的本地紧急指令"""
    if not text:
        return False

    actions = GLOBAL_ACTION_MGR.process_chunk(text, use_semantic=True)
    if not actions:
        return False

    # 本地直接执行关键指令（如闭嘴、重置）
    for aid in actions:
        GLOBAL_ACTION_MGR.execute_action(aid)
    return True


async def stream_and_speak(user_text):
    """异步流式请求 LLM 并分句推入 TTS 队列"""
    if not user_text:
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AGENT_TOKEN}",
        # Hermes 兼容头
        "X-Hermes-Session-Id": GLOBAL_ACTION_MGR.session_key,
        "X-Hermes-Strategy": "yolo",
        "X-Hermes-Execution-Policy": "bypass",
        "X-Hermes-Allow-Danger": "true",
        # OpenClaw 兼容头
        "X-OpenClaw-Session-Key": GLOBAL_ACTION_MGR.session_key,
        "X-OpenClaw-Strategy": "yolo",
        "X-OpenClaw-Execution-Policy": "bypass",
        "X-OpenClaw-Allow-Danger": "true"
    }

    voice_system_hint = (
        "（当前为语音通话场景，请直接使用口语化的纯文本进行回复，避免使用表格、复杂的Markdown列表、表情符号、标签。"
        "所有的数值单位请转换为中文读音文字，如：将 15℃ 写作'15度'，将 95% 写作'百分之九十五'，将 10~20 写作'10到20'。）\n\n"
        "【环境感知指令】：请先分析捕捉到的文本。如果你判断这并非是对你说的有效指令（例如是视频背景音、嘈杂环境下的碎片语音、或明显的误触），"
        "请直接回复 `[IGNORE]`（必须完全匹配该字符串），不要产生任何其他输出。只有当你确信是在与你交流时才正常回复。"
    )

    from core.shared import INITIALIZED_SESSIONS

    current_session = GLOBAL_ACTION_MGR.session_key
    user_emotion = get_user_emotion()
    if user_emotion and user_emotion != "NEUTRAL":
        # 针对特定情绪添加感知提示
        emotion_hints = {
            "ANGRY": "（检测到用户语气愤怒，请用安抚、理智且温和的语气回复，不要火上浇油。）",
            "HAPPY": "（检测到用户心情愉悦，可以适当表现得轻松、热情一些。）",
            "SAD": "（检测到用户情绪低落，请表现出同情心和关怀，使用治愈系的语气。）"
        }
        hint = emotion_hints.get(user_emotion, f"（用户当前情绪：{user_emotion}）")
        user_text = hint + "\n" + user_text

    # 只有当 Session 未被初始化过时，才附加系统提示词
    if current_session not in INITIALIZED_SESSIONS:
        user_text += "\n\n" + voice_system_hint
        INITIALIZED_SESSIONS.add(current_session)

    payload = {
        "model": "openclaw:main",
        "messages": [{"role": "user", "content": user_text}],
        "stream": True,
        "execution_mode": "yolo",
        "session_id": current_session
    }

    logger.info(f"🚀 [LLM 请求]: {user_text}")
    from core.shared import GLOBAL_TEXT_QUEUE

    full_response = ""
    current_sentence = ""
    is_thinking = False

    try:
        # 复用全局连接池
        client = get_llm_client()
        async with client.stream("POST", f"{AGENT_URL}/v1/chat/completions", headers=headers, json=payload) as response:
            if response.status_code != 200:
                err_text = await response.aread()
                logger.error(
                    f"LLM 接口报错 [{response.status_code}]: {err_text.decode()[:200]}")
                GLOBAL_TEXT_QUEUE.put("对不起，系统暂时无法处理您的请求。")
                GLOBAL_TEXT_QUEUE.put(None)
                return

            async for line in response.aiter_lines():
                if TASK_CTRL.is_stopped():
                    logger.info("🚫 [LLM 停止]: 收到打断信号")
                    break

                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    chunk = data.get("choices", [{}])[0].get(
                        "delta", {}).get("content", "")
                    if not chunk:
                        continue

                    full_response += chunk

                    # 拦截幻觉/噪音判定：如果 LLM 回复了 [IGNORE]，立即中止本次处理
                    if "[IGNORE]" in full_response:
                        logger.info(f">> 拦截幻觉/噪音: {full_response.strip()}")
                        # 确保清理可能已经入队的任何残余数据（理论上 [IGNORE] 会是第一个词）
                        TASK_CTRL.request_stop(reason="reset")
                        return

                    # 处理中间标签拦截
                    actions = GLOBAL_ACTION_MGR.process_chunk(chunk)
                    for aid in actions:
                        GLOBAL_ACTION_MGR.execute_action(
                            aid, context={"url": AGENT_URL, "headers": headers, "payload": payload})

                    # 这里可以加入简单的标签过滤逻辑
                    if "<think>" in chunk:
                        is_thinking = True
                    if "</think>" in chunk:
                        is_thinking = False

                    if not is_thinking:
                        current_sentence += chunk
                        # 分句逻辑：使用 config 中定义的正则分句器
                        last_match = None
                        for m in SENTENCE_DELIMITERS.finditer(current_sentence):
                            last_match = m

                        if last_match and len(current_sentence) >= MIN_SENTENCE_LEN:
                            split_idx = last_match.end()
                            sentence_to_send = current_sentence[:split_idx].strip(
                            )
                            current_sentence = current_sentence[split_idx:]
                            if sentence_to_send and not get_silent_mode():
                                GLOBAL_TEXT_QUEUE.put(sentence_to_send)
                        elif len(current_sentence) >= MAX_SENTENCE_LEN:
                            # 超长句强制分割：优先在逗号处切分
                            sec_match = None
                            for m in SECONDARY_DELIMITERS.finditer(current_sentence):
                                sec_match = m
                            if sec_match:
                                split_idx = sec_match.end()
                            else:
                                split_idx = MAX_SENTENCE_LEN
                            sentence_to_send = current_sentence[:split_idx].strip(
                            )
                            current_sentence = current_sentence[split_idx:]
                            if sentence_to_send and not get_silent_mode():
                                GLOBAL_TEXT_QUEUE.put(sentence_to_send)

                except json.JSONDecodeError:
                    continue

        # 处理剩余文本
        if current_sentence.strip() and not TASK_CTRL.is_stopped():
            if not get_silent_mode():
                GLOBAL_TEXT_QUEUE.put(current_sentence.strip())

        # 结束标志
        GLOBAL_TEXT_QUEUE.put(None)
        logger.info(f"✅ [LLM 回答完成]: {full_response[:50]}...")

    except Exception as e:
        logger.error(f"LLM Stream Error: {e}")
        GLOBAL_TEXT_QUEUE.put(None)
