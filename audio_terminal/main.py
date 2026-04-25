import os
import sys
from pathlib import Path
import logging
import threading
import time
import uvicorn

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OmniSenseAudio")

# ==============================================================================
# 🧩 离线环境增强补丁 (Offline Environment Enhancements)
# ==============================================================================
def apply_offline_patches():
    """应用针对离线环境和 MOSS-TTS-Nano 的猴子补丁"""
    from config import MOSS_PATH
    
    # 注入 MOSS 搜索路径
    if MOSS_PATH not in sys.path:
        sys.path.append(MOSS_PATH)

    try:
        import transformers.modeling_utils
        import transformers.utils.import_utils
        
        # 🧩 补丁 1: 修复 transformers 在完全离线模式下处理 safetensors 元数据缺失导致的 NoneType 崩溃
        if not hasattr(transformers.modeling_utils, "_is_patched_for_offline"):
            _orig_load_state_dict = transformers.modeling_utils.load_state_dict
            def _patched_load_state_dict(checkpoint_file, map_location=None, **kwargs):
                if checkpoint_file.endswith(".safetensors") and transformers.utils.import_utils.is_safetensors_available():
                    from safetensors.torch import load_file as safe_load_file
                    return safe_load_file(checkpoint_file, device=map_location if map_location else "cpu")
                return _orig_load_state_dict(checkpoint_file, map_location=map_location, **kwargs)
            
            transformers.modeling_utils.load_state_dict = _patched_load_state_dict
            transformers.modeling_utils._is_patched_for_offline = True
            logger.info("🛠️ [Patch] Transformers Safetensors 容错补丁已应用")

        # 🧩 补丁 2: 注入虚拟模块以绕过 transformers 的动态导入静态检查
        import types
        fake_modules = [
            "configuration_moss_audio_tokenizer", "configuration_moss_tts_nano", 
            "modeling_moss_audio_tokenizer", "modeling_moss_tts_nano"
        ]
        for mod_name in fake_modules:
            if mod_name not in sys.modules:
                sys.modules[mod_name] = types.ModuleType(mod_name)

        # 🧩 补丁 3: MOSS 路径死锁拦截 (解决 AutoModel 目录加载 vs Tokenizer 文件加载冲突)
        try:
            import moss_tts_nano_runtime
            if not hasattr(moss_tts_nano_runtime.NanoTTSService, "_is_patched"):
                _orig_load_locked = moss_tts_nano_runtime.NanoTTSService._load_model_locked
                
                def _patched_load_model_locked(self):
                    old_path = self.checkpoint_path
                    is_file = old_path and str(old_path).endswith(".model")
                    if is_file:
                        self.checkpoint_path = os.path.dirname(str(old_path))
                        logger.info(f"🛠️ [Patch] 正在为 AutoModel 切换路径: {self.checkpoint_path}")
                    try:
                        return _orig_load_locked(self)
                    finally:
                        if is_file:
                            self.checkpoint_path = old_path
                
                moss_tts_nano_runtime.NanoTTSService._load_model_locked = _patched_load_model_locked
                moss_tts_nano_runtime.NanoTTSService._is_patched = True
                logger.info("🛠️ [Patch] MOSS 路径死锁补丁已就绪")
        except Exception as e:
            logger.warning(f"无法应用 MOSS 运行时补丁: {e}")

        # 强制开启离线模式
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        
    except ImportError:
        logger.warning("未检测到 transformers，跳过环境补丁")

# 在模块加载时立即应用补丁
apply_offline_patches()
# ==============================================================================

# 确保当前目录在搜索路径中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from config import LOG_STT_DIR, AUDIO_DUPLEX_MODE
from core.shared import GLOBAL_TEXT_QUEUE, GLOBAL_AUDIO_QUEUE, get_silent_mode, get_is_playing

from core.controller import TASK_CTRL
from core.vad import record_audio_until_silence
from core.stt import speech_to_text
from core.tts import synthesis_worker, playback_worker
from core.orchestrator import stream_and_speak, handle_immediate_actions
from api.routes import app

def cleanup_old_audio(days=3):
    """清理旧日志"""
    now = time.time()
    cutoff = now - (days * 86400)
    count = 0
    try:
        if os.path.exists(LOG_STT_DIR):
            for f in os.listdir(LOG_STT_DIR):
                fpath = os.path.join(LOG_STT_DIR, f)
                if os.path.isfile(fpath) and f.endswith(".wav"):
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                        count += 1
        if count > 0:
            logger.info(f"🧹 已自动清理 {count} 个 {days} 天前的旧音频文件")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def run_api_server():
    """在后台线程运行 API 服务"""
    logger.info("📡 TTS API 服务已启动 (端口 8000)")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

def persistent_worker(target, *args):
    """持久化工作线程，异常自动重启"""
    name = target.__name__
    while True:
        try:
            target(*args)
            logger.info(f"线程 {name} 正常退出，1s 后重启")
            time.sleep(1)
        except Exception as e:
            logger.error(f"线程 {name} 异常，5s 后自动重启: {e}")
            time.sleep(5)

import asyncio

def main():
    logger.info("--- OmniSense Audio Terminal Started (Modular Refactored) ---")
    cleanup_old_audio(days=3)
    
    # 启动 API 服务
    threading.Thread(target=run_api_server, daemon=True).start()

    # 启动全局 TTS 管线
    threading.Thread(target=persistent_worker, args=(synthesis_worker, GLOBAL_TEXT_QUEUE, GLOBAL_AUDIO_QUEUE), daemon=True).start()
    threading.Thread(target=persistent_worker, args=(playback_worker, GLOBAL_AUDIO_QUEUE), daemon=True).start()
    
    logger.info("🎧 系统就绪，随时等待你开口说话...")
    while True:
        try:
            # 半双工逻辑：如果正在播放且非全双工模式，则暂时跳过录音识别
            if AUDIO_DUPLEX_MODE == "half" and get_is_playing():
                time.sleep(0.1)
                continue

            audio_file, trigger_rms = record_audio_until_silence()
            if audio_file is None:
                continue

            
            # 异步 STT
            user_text = asyncio.run(speech_to_text(audio_file, trigger_rms))
            
            if user_text and user_text.strip():
                # 指令拦截
                if handle_immediate_actions(user_text):
                    continue

                # 如果当前是静默模式，且不是紧急指令，则不发送给 LLM
                if get_silent_mode():
                    logger.info(f"🤫 [静默模式]: 忽略用户输入: {user_text}")
                    continue

                # 新任务重置
                TASK_CTRL.request_stop(reason="reset")
                time.sleep(0.05) 
                TASK_CTRL.reset()

                # 异步处理对话 (在线程中运行 asyncio.run)
                threading.Thread(target=lambda: asyncio.run(stream_and_speak(user_text)), daemon=True).start()
        except KeyboardInterrupt:
            logger.info("👋 用户中断，退出程序")
            break
        except Exception as e:
            logger.error(f"Main Loop Error: {e}")

if __name__ == "__main__":
    main()
