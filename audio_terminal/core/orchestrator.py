import logging
import httpx
import json
import queue
import threading
import time
import re
import asyncio
from core.shared import get_silent_mode, set_silent_mode
from core.actions import GLOBAL_ACTION_MGR
from core.controller import TASK_CTRL
from core.tts import synthesis_worker, playback_worker
from config import AGENT_URL, AGENT_TOKEN, SENTENCE_DELIMITERS, MIN_SENTENCE_LEN, MAX_SENTENCE_LEN, SECONDARY_DELIMITERS

logger = logging.getLogger("OmniSenseAudio")

def handle_immediate_actions(text):
    """处理不需要经过 LLM 的本地紧急指令"""
    if not text: return False
    
    actions = GLOBAL_ACTION_MGR.process_chunk(text, use_semantic=True)
    if not actions: return False
    
    # 本地直接执行关键指令（如闭嘴、重置）
    for aid in actions:
        GLOBAL_ACTION_MGR.execute_action(aid)
    return True

async def stream_and_speak(user_text):
    """异步流式请求 LLM 并分句推入 TTS 队列"""
    if not user_text: return
    
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
        "所有的数值单位请转换为中文读音文字，如：将 15℃ 写作'15度'，将 95% 写作'百分之九十五'，将 10~20 写作'10到20'。）"
    )
    
    from core.shared import INITIALIZED_SESSIONS
    
    current_session = GLOBAL_ACTION_MGR.session_key
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
        # 使用超时时间更长的 AsyncClient
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            async with client.stream("POST", f"{AGENT_URL}/v1/chat/completions", headers=headers, json=payload) as response:
                if response.status_code != 200:
                    err_text = await response.aread()
                    logger.error(f"LLM 接口报错 [{response.status_code}]: {err_text.decode()[:200]}")
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
                        chunk = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if not chunk: continue
                        
                        full_response += chunk
                        
                        # 处理中间标签拦截
                        actions = GLOBAL_ACTION_MGR.process_chunk(chunk)
                        for aid in actions:
                            GLOBAL_ACTION_MGR.execute_action(aid, context={"url": AGENT_URL, "headers": headers, "payload": payload})

                        # 这里可以加入简单的标签过滤逻辑
                        if "<think>" in chunk: is_thinking = True
                        if "</think>" in chunk: is_thinking = False
                        
                        if not is_thinking:
                            current_sentence += chunk
                            # 分句逻辑：寻找结束标点
                            if any(d in current_sentence for d in [".", "!", "?", "。", "！", "？", "\n"]):
                                if len(current_sentence) >= MIN_SENTENCE_LEN:
                                    # 寻找最后一个标点进行切分
                                    split_idx = -1
                                    for i in range(len(current_sentence)-1, -1, -1):
                                        if current_sentence[i] in [".", "!", "?", "。", "！", "？", "\n"]:
                                            split_idx = i + 1
                                            break
                                    
                                    if split_idx != -1:
                                        sentence_to_send = current_sentence[:split_idx].strip()
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
