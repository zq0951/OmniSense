import io
import logging
import threading
import torchaudio
from fastapi import FastAPI, Body
from fastapi.responses import Response
from core.tts import MOSS_SERVICE
from core.shared import GLOBAL_TEXT_QUEUE
from core.orchestrator import stream_and_speak
from utils.text import filter_symbols

logger = logging.getLogger("OmniSenseAudio")
app = FastAPI()

@app.post("/v1/audio/speech")
async def tts_speech_api(input: str = Body(..., embed=True), voice: str = Body("zm_yunxi", embed=True)):
    """兼容 Kokoro 格式的 TTS 接口"""
    if not MOSS_SERVICE:
        return Response(status_code=500, content="MOSS Service 不可用")
    
    clean_text = filter_symbols(input)
    if not clean_text:
        return Response(status_code=400, content="无效文本")

    logger.info(f"🛰️ [API 请求] 外部组件请求合成: {clean_text}")
    try:
        result = MOSS_SERVICE.synthesize(text=clean_text)
        waveform = result["waveform"]
        sr = result["sample_rate"]

        if sr != 44100:
            waveform = torchaudio.functional.resample(waveform, sr, 44100)
            sr = 44100
        if waveform.shape[0] == 1:
            waveform = waveform.repeat(2, 1)

        buffer = io.BytesIO()
        torchaudio.save(buffer, waveform.cpu(), sr, format="wav", encoding="PCM_S", bits_per_sample=16)
        return Response(content=buffer.getvalue(), media_type="audio/wav")
    except Exception as e:
        logger.error(f"TTS API Error: {e}")
        return Response(status_code=500, content=str(e))

@app.post("/v1/audio/speak")
async def tts_speak_play(input: str = Body(..., embed=True)):
    """主动播报接口"""
    logger.info(f"📣 [外部插话]: {input}")
    GLOBAL_TEXT_QUEUE.put(input)
    GLOBAL_TEXT_QUEUE.put(None)
    return {"status": "queued"}

@app.post("/v1/audio/proactive")
async def proactive_brain_trigger(input: str = Body(..., embed=True)):
    """主动思考接口"""
    logger.info(f"🧠 [主动触发感官]: {input}")
    import asyncio
    # 在后台线程运行异步任务
    threading.Thread(target=lambda: asyncio.run(stream_and_speak(input)), daemon=True).start()
    return {"status": "processing"}
