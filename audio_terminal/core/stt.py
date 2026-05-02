import httpx
import time
import os
import json
import re
import logging
import shutil
import ssl
import asyncio
import websockets
from config import FUNASR_STT_URL, LOG_STT_DIR, HALLUCINATION_FILE, STT_HISTORY_FILE
from utils.text import simple_t2s
from utils.funasr_parser import parse_funasr_tags
from core.shared import set_user_emotion

logger = logging.getLogger("OmniSenseAudio")


def load_hallucinations():
    try:
        if os.path.exists(HALLUCINATION_FILE):
            with open(HALLUCINATION_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return ["i'm sorry", "thank you", "you", "谢谢", "...", "。", "bye bye"]


async def funasr_stt(audio_file):
    logger.info("Requesting FunASR (SenseVoiceSmall via WSS)...")

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        async with websockets.connect(FUNASR_STT_URL, ssl=ssl_context) as websocket:
            # Send config
            config = {
                "mode": "offline",
                "chunk_size": [5, 10, 5],
                "chunk_interval": 10,
                "wav_name": "stt_request",
                "is_speaking": True,
                "hotwords": ""
            }
            await websocket.send(json.dumps(config))

            # Send audio data
            with open(audio_file, "rb") as f:
                audio_data = f.read()
                await websocket.send(audio_data)

            # Send end flag
            await websocket.send(json.dumps({"is_speaking": False}))

            # Receive result
            raw_text = ""
            try:
                # FunASR offline mode only sends ONE message back.
                # We use a timeout to prevent infinite hanging.
                response = await asyncio.wait_for(websocket.recv(), timeout=15.0)
                result = json.loads(response)
                raw_text = result.get('text', '')
            except asyncio.TimeoutError:
                logger.error("FunASR STT WebSocket recv timeout!")
            except Exception as e:
                logger.error(f"FunASR STT WebSocket recv error: {e}")

            # Parse tags
            parsed = parse_funasr_tags(raw_text)
            text = parsed['text']
            emotion = parsed['emotion']
            is_speech = parsed.get('is_speech', True)
            event = parsed.get('event')

            if event and event != "Speech":
                logger.info(f"🔊 [SenseVoice Event]: {event}")

            if emotion:
                logger.info(f"🎭 [SenseVoice Emotion]: {emotion}")
                set_user_emotion(emotion)

            # VAD Integration: If not speech (e.g. only Music/Noise/Ignore)
            if not is_speech:
                if text or event:
                    logger.info(
                        f"🔇 [VAD] Detected non-speech event ({event or 'Noise'}) with text: [{text}], filtering out.")
                return ""

            return text

    except Exception as e:
        logger.error(f"FunASR STT Error: {e}")
        return ""


async def speech_to_text(audio_file, trigger_rms=0):
    try:
        if not os.path.exists(audio_file):
            return ""

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        archive_wav = os.path.join(LOG_STT_DIR, f"{timestamp}.wav")

        # 强制仅使用 FunASR
        text = await funasr_stt(audio_file)

        if text:
            lower_text = text.lower()
            hallucinations = load_hallucinations()

            is_hallucination = False

            STOP_WORDS = {"嗯", "谢谢", "謝謝", "哦", "啊",
                          "唉", "嗯哦", "好吧", "呃", "哎", "嗨", "嘿", "哈"}
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
            logger.info(f"👂 >> [STT 透写结果] : {text}")
            return text
        else:
            # Log empty result
            log_entry = {
                "timestamp": timestamp,
                "text": "",
                "trigger_rms": int(trigger_rms),
                "is_hallucination": True,
                "audio_file": f"{timestamp}.wav"
            }
            with open(STT_HISTORY_FILE, "a") as log_f:
                log_f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    except Exception as e:
        logger.error(f"STT Error: {e}")
    return ""
