import subprocess
import time
import wave
import logging
import os
from config import SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH, CHUNK_SIZE, ENERGY_THRESHOLD, SILENCE_TIMEOUT, MAX_RECORD_SECONDS, PRE_SPEECH_BUFFER, CHUNK_DURATION_MS
from utils.audio import calc_rms

logger = logging.getLogger("OmniSenseAudio")

# 跨次录音持久化的动态底噪状态
_global_noise_floor = 0.0
_global_calibrated_threshold = 0.0

def record_audio_until_silence(output_filename="temp_audio.wav"):
    from config import ENERGY_THRESHOLD, MIN_ENERGY_THRESHOLD, VAD_MULTIPLIER, SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH, CHUNK_SIZE, SILENCE_TIMEOUT, MAX_RECORD_SECONDS, PRE_SPEECH_BUFFER, CHUNK_DURATION_MS, AUDIO_DUPLEX_MODE
    from core.shared import get_is_playing
    
    logger.info(f"🎧 等待人声输入... (模式: {AUDIO_DUPLEX_MODE}, 环境音自动校准中)")
    proc = subprocess.Popen(
        ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", str(CHANNELS), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    
    frames = []
    pre_buffer = []
    is_speaking = False
    trigger_rms = 0
    silence_start = None
    record_start = None
    bytes_per_chunk = CHUNK_SIZE * SAMPLE_WIDTH
    
    global _global_noise_floor, _global_calibrated_threshold
    
    # 动态阈值状态 (复用全局状态)
    noise_floor = _global_noise_floor
    alpha = 0.05 # 更平滑的系数
    calibrated_threshold = _global_calibrated_threshold if _global_calibrated_threshold > 0 else ENERGY_THRESHOLD

    try:
        while True:
            data = proc.stdout.read(bytes_per_chunk)
            if not data or len(data) < bytes_per_chunk:
                break
            rms = calc_rms(data, SAMPLE_WIDTH)
            
            # --- 动态阈值抑制 (Ducking) ---
            # 如果 AI 正在说话，我们临时大幅提高灵敏度要求，防止自触发回声
            # 只有当用户说话声音远大于 AI 回声时才触发打断
            current_multiplier = VAD_MULTIPLIER
            if get_is_playing():
                current_multiplier = VAD_MULTIPLIER * 2.5 # 提高 2.5 倍门槛

            if not is_speaking:
                # 背景噪音平滑估计
                if noise_floor == 0:
                    noise_floor = rms
                else:
                    noise_floor = (1 - alpha) * noise_floor + alpha * rms
                
                # 动态计算触发阈值
                calibrated_threshold = max(MIN_ENERGY_THRESHOLD, noise_floor * current_multiplier)
                
                pre_buffer.append(data)
                if len(pre_buffer) > PRE_SPEECH_BUFFER:
                    pre_buffer.pop(0)
                
                if rms > calibrated_threshold and rms > MIN_ENERGY_THRESHOLD:
                    # 如果是半双工模式且正在播放，即便过了阈值也强行拦截（main.py 已有拦截，这里作为双重保险）
                    if AUDIO_DUPLEX_MODE == "half" and get_is_playing():
                        continue

                    is_speaking = True
                    trigger_rms = rms
                    record_start = time.time()
                    silence_start = None
                    frames.extend(pre_buffer)
                    pre_buffer = []
                    logger.info(f"🎤 检测到人声 (RMS={int(rms)} > Threshold={int(calibrated_threshold)})，开始录制!")
            else:
                frames.append(data)
                # 停止阈值通常可以略低于触发阈值以保持连贯性
                if rms < (calibrated_threshold * 0.8):
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > SILENCE_TIMEOUT:
                        logger.info(f"🛑 静默 {SILENCE_TIMEOUT}s，录音结束 (共 {len(frames)} 帧)")
                        break
                else:
                    silence_start = None
                
                if time.time() - record_start > MAX_RECORD_SECONDS:
                    logger.info(f"⏰ 达到最大录音时长 {MAX_RECORD_SECONDS}s，强制结束")
                    break
    finally:
        _global_noise_floor = noise_floor
        _global_calibrated_threshold = calibrated_threshold
        proc.terminate()
        proc.wait()

    if not frames:
        logger.info("(未检测到有效人声)")
        return None, 0

    with wave.open(output_filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(frames))

    duration = len(frames) * CHUNK_DURATION_MS / 1000
    logger.info(f"✅ 录音已保存: {output_filename} ({duration:.1f}s), Trigger RMS: {int(trigger_rms)}")
    return output_filename, trigger_rms
