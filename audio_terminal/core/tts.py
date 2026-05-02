import os
import sys
from pathlib import Path
import time
import logging
import queue
import subprocess
import io
import torch
import torchaudio
import soundfile as sf
from config import BASE_DIR, LOG_TTS_DIR, HW_SAMPLE_RATE, SILENCE_PADDING_DURATION, MOSS_CHECKPOINT_PATH
from core.shared import GLOBAL_TEXT_QUEUE, GLOBAL_AUDIO_QUEUE, set_is_playing
from core.controller import TASK_CTRL, SPEAKER_LOCK

from utils.text import filter_symbols

logger = logging.getLogger("OmniSenseAudio")

# 强制使用 soundfile 加载音频的猴子补丁
def patched_load(filepath, **kwargs):
    data, samplerate = sf.read(filepath)
    if len(data.shape) == 1:
        data = data.reshape(-1, 1)
    return torch.from_numpy(data.T).float(), samplerate

torchaudio.load = patched_load

MOSS_SERVICE = None
try:
    from moss_tts_nano_runtime import NanoTTSService
    torch.set_num_threads(int(os.getenv("OMP_NUM_THREADS", "4")))
    try:
        # 🛠️ V5 强制补丁：指定 dtype 和 attn_implementation 以避开 meta 设备加载路径
        MOSS_SERVICE = NanoTTSService(device="cpu", dtype="float32", attn_implementation="sdpa") 
        MOSS_SERVICE.checkpoint_path = MOSS_CHECKPOINT_PATH
        logger.info(f"✅ MOSS TTS 服务初始化成功 (路径: {MOSS_CHECKPOINT_PATH})")
    except Exception as e:
        logger.error(f"Failed to initialize MOSS_SERVICE: {e}")
    # 异步预热
    import threading
    if MOSS_SERVICE:
        threading.Thread(target=MOSS_SERVICE.warmup, daemon=True).start()
except ImportError:
    logger.warning("⚠️ 未找到 MOSS-TTS-Nano 运行时，系统将降级。")

def synthesis_worker(text_queue, audio_queue):
    """合成线程：从文本队列读取，流式合成后放入音频队列"""
    while True:
        if TASK_CTRL.is_stopped():
            time.sleep(0.1)
            continue

        try:
            sentence = text_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if TASK_CTRL.is_stopped():
            text_queue.task_done()
            continue

        if sentence is None:
            audio_queue.put(None)
            text_queue.task_done()
            continue

        clean_text = filter_symbols(sentence)
        if not clean_text:
            text_queue.task_done()
            continue

        ts = time.strftime("%H%M%S")
        debug_wav_path = os.path.join(LOG_TTS_DIR, f"{ts}_tts.wav")
        debug_txt_path = os.path.join(LOG_TTS_DIR, f"{ts}_tts.txt")
        try:
            with open(debug_txt_path, "w") as f: f.write(clean_text)
        except: pass

        logger.info(f"🎙️ [MOSS 合成]: {clean_text}")
        if MOSS_SERVICE:
            try:
                result = MOSS_SERVICE.synthesize(text=clean_text)
                waveform = result["waveform"]
                sr = result["sample_rate"]

                if sr != HW_SAMPLE_RATE:
                    waveform = torchaudio.functional.resample(waveform, sr, HW_SAMPLE_RATE)
                
                if waveform.shape[0] == 1:
                    waveform = waveform.repeat(2, 1)
                
                pcm_data = (torch.clamp(waveform, -1.0, 1.0) * 32767).to(torch.int16).cpu().numpy().T.tobytes()
                audio_queue.put(pcm_data)
                torchaudio.save(debug_wav_path, waveform.cpu(), HW_SAMPLE_RATE, encoding="PCM_S", bits_per_sample=16)
            except Exception as e:
                logger.error(f"MOSS Synthesis Error: {e}")
        else:
            logger.error("MOSS Service not available for synthesis")
        
        text_queue.task_done()

def playback_worker(audio_queue):
    """播放线程：从音频队列读取原始 PCM 字节流并写入 aplay 管道"""
    os.system("amixer -c 0 set Music 80% > /dev/null 2>&1")
    aplay_proc = None
    lock_acquired = False

    try:
        while True:
            if TASK_CTRL.is_stopped():
                set_is_playing(False)
                if lock_acquired:
                    SPEAKER_LOCK.release()
                    lock_acquired = False
                if aplay_proc:
                    try: aplay_proc.kill()
                    except: pass
                    aplay_proc = None
                # 清空音频队列，防止停止后仍有残留
                try:
                    while not audio_queue.empty(): audio_queue.get_nowait()
                except: pass
                time.sleep(0.1)
                continue

            try:
                # 增加等待时间，防止 CPU 空转，同时降低抖动
                chunk = audio_queue.get(timeout=0.1)
            except queue.Empty:
                if aplay_proc and not TASK_CTRL.is_stopped():
                    # 队列暂时空了，说明当前句子已经喂完且没有新句子。
                    # 安全起见关闭 aplay，避免因长时间 underrun 导致 ALSA 驱动卡死
                    set_is_playing(False)
                    try:
                        aplay_proc.stdin.close()
                        aplay_proc.wait(timeout=1)
                    except:
                        try: aplay_proc.kill()
                        except: pass
                    aplay_proc = None
                    TASK_CTRL.set_aplay(None)
                continue
            
            # 只要拿到数据块，就标记为正在播放
            set_is_playing(True)

            if not lock_acquired:
                SPEAKER_LOCK.acquire()
                lock_acquired = True
                if TASK_CTRL.is_stopped():
                    set_is_playing(False)
                    audio_queue.task_done()
                    continue

            if chunk is None:
                # 收到结束标志
                if aplay_proc:
                    try:
                        aplay_proc.stdin.close()
                        aplay_proc.wait(timeout=1)
                    except:
                        aplay_proc.kill()
                    aplay_proc = None
                
                set_is_playing(False)
                TASK_CTRL.set_aplay(None)
                if lock_acquired:
                    SPEAKER_LOCK.release()
                    lock_acquired = False
                audio_queue.task_done()
                continue
            
            if aplay_proc is None:
                try:
                    aplay_proc = subprocess.Popen(
                        ["aplay", "-D", "default", "-f", "S16_LE", "-r", str(HW_SAMPLE_RATE), "-c", "2", "-t", "raw"],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    TASK_CTRL.set_aplay(aplay_proc)
                    
                    silence_padding = b'\x00' * int(HW_SAMPLE_RATE * 2 * 2 * SILENCE_PADDING_DURATION)
                    aplay_proc.stdin.write(silence_padding)
                    aplay_proc.stdin.flush()
                except Exception as e:
                    logger.error(f"Failed to start aplay: {e}")
                    aplay_proc = None
                    TASK_CTRL.set_aplay(None)
                    audio_queue.task_done()
                    continue

            try:
                aplay_proc.stdin.write(chunk)
                aplay_proc.stdin.flush()
            except (BrokenPipeError, ConnectionResetError):
                aplay_proc = None
                TASK_CTRL.set_aplay(None)
            except Exception as e:
                logger.error(f"Playback Write Error: {e}")
                try: aplay_proc.kill()
                except: pass
                aplay_proc = None
                TASK_CTRL.set_aplay(None)
            
            audio_queue.task_done()
    finally:
        set_is_playing(False)
        if lock_acquired:
            SPEAKER_LOCK.release()
        if aplay_proc:
            try: aplay_proc.kill()
            except: pass
        TASK_CTRL.set_aplay(None)
