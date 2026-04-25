import httpx
import time
import os
import json
import re
import logging
import shutil
from config import WHISPER_STT_URL, LOG_STT_DIR, HALLUCINATION_FILE, BASE_DIR, STT_HISTORY_FILE
from utils.text import simple_t2s

logger = logging.getLogger("OmniSenseAudio")

def load_hallucinations():
    try:
        if os.path.exists(HALLUCINATION_FILE):
            with open(HALLUCINATION_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return ["i'm sorry", "thank you", "you", "谢谢", "...", "。", "bye bye"]

async def speech_to_text(audio_file, trigger_rms=0):
    logger.info("Requesting Faster-Whisper (Async)...")
    try:
        if not os.path.exists(audio_file):
            return ""
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        archive_wav = os.path.join(LOG_STT_DIR, f"{timestamp}.wav")
        
        async with httpx.AsyncClient() as client:
            with open(audio_file, 'rb') as f:
                files = {'file': (audio_file, f, 'audio/wav')}
                data = {
                    'model': 'small',
                    'vad_filter': 'true',
                    'language': 'zh',
                    'temperature': '0',
                    'initial_prompt': '这是一段关于智能家居控制的简体中文对话，包含指令如：查询天气、开启静默模式、重置上下文、闭嘴、停止、没事了。全部输出应为简体中文，禁止输出繁体字。'
                }
                resp = await client.post(WHISPER_STT_URL, files=files, data=data, timeout=30)
            
            if resp.status_code == 200:
                text = resp.json().get('text', '').strip()
                lower_text = text.lower()
                hallucinations = load_hallucinations()
                
                is_hallucination = False
                if not text:
                    is_hallucination = True
                
                STOP_WORDS = {"嗯", "谢谢", "謝謝", "哦", "啊", "唉", "嗯哦", "好吧", "呃", "哎", "嗨", "嘿", "哈"}
                if text in STOP_WORDS:
                    is_hallucination = True
                elif re.match(r'^[呃嗯啊哦唉哎嘿哈]+$', text):
                    is_hallucination = True
                elif any(h in lower_text for h in hallucinations if (len(h) > 2 or (len(h) > 1 and re.search(r'[\u4e00-\u9fa5]', h)))):
                    is_hallucination = True
                elif len(text) < 3 and not re.search(r'[\u4e00-\u9fa5]', text):
                    is_hallucination = True
                
                log_entry = {
                    "timestamp": timestamp,
                    "text": text,
                    "trigger_rms": int(trigger_rms),
                    "is_hallucination": is_hallucination,
                    "audio_file": f"{timestamp}.wav"
                }
                with open(STT_HISTORY_FILE, "a") as log_f:
                    log_f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

                if is_hallucination:
                    logger.info(f">> 拦截幻觉/噪音: [{text}]")
                    return ""
                
                shutil.copy(audio_file, archive_wav)
                text = simple_t2s(text)
                logger.info(f"👂 >> [STT 透写结果]: {text}")
                return text
            else:
                logger.error(f"STT Service Error: {resp.status_code}")
    except Exception as e:
        logger.error(f"STT Error: {e}")
    return ""
