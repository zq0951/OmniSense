import os
import sys
from pathlib import Path
import logging
import threading
import time
import uvicorn
import asyncio

# ==============================================================================
# 🧩 CPU 离线环境深度优化 (CPU-Only & Offline Enforcement)
# ==============================================================================
# 1. 物理屏蔽 GPU：强制让所有库认为系统没有显卡，避免任何显存分配尝试
os.environ["CUDA_VISIBLE_DEVICES"] = ""
# 2. 强制离线模式
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("OmniSenseAudio")

def apply_offline_patches():
    """针对 CPU 离线环境的精准补丁 (V5.3 纯净版)"""
    from config import MOSS_PATH
    
    if MOSS_PATH not in sys.path:
        sys.path.append(MOSS_PATH)

    try:
        import transformers
        # 🧩 劫持 transformers 工厂类：
        # 在 CPU 环境下，加载 MOSS 必须强制关闭 low_cpu_mem_usage，否则会触发 torch-cpu 不支持的 meta 设备路径
        # 🧩 劫持 transformers 工厂类 (V5.4 终极强化版)：
        # 该项目必须运行在 CPU 上。我们强制关闭一切可能导致进入 meta 设备的内存优化逻辑。
        for auto_cls in [transformers.AutoModel, transformers.AutoModelForCausalLM]:
            if not hasattr(auto_cls, "_is_patched"):
                _orig_fp = auto_cls.from_pretrained
                @classmethod
                def _patched_fp(cls, *args, **kwargs):
                    # 强力重置：无论加载什么模型，在 CPU 上都必须禁用 low_cpu_mem_usage
                    # 因为 torch-cpu 环境下 meta tensor 的 copy 操作是不支持的
                    kwargs["low_cpu_mem_usage"] = False
                    kwargs["device_map"] = None
                    if "device" in kwargs: del kwargs["device"]
                    
                    # 打印一条日志方便确认补丁生效
                    model_id = args[0] if len(args) > 0 else kwargs.get("pretrained_model_name_or_path", "unknown")
                    logging.getLogger("OmniSenseAudio").info(f"🛠️ [CPU-Patch] Loading model {model_id} with low_cpu_mem_usage=False")
                    
                    return _orig_fp.__func__(cls, *args, **kwargs)
                auto_cls.from_pretrained = _patched_fp
                auto_cls._is_patched = True

        # 🧩 注入 MOSS 虚拟模块支持
        import types
        for m in ["configuration_moss_audio_tokenizer", "configuration_moss_tts_nano", "modeling_moss_audio_tokenizer", "modeling_moss_tts_nano"]:
            if m not in sys.modules: sys.modules[m] = types.ModuleType(m)

        # 🧩 拦截 C: MOSS 路径适配
        try:
            import moss_tts_nano_runtime
            if not hasattr(moss_tts_nano_runtime.NanoTTSService, "_is_patched"):
                _orig_load = moss_tts_nano_runtime.NanoTTSService._load_model_locked
                def _p_load(self):
                    if self.checkpoint_path and str(self.checkpoint_path).endswith(".model"):
                        self.checkpoint_path = os.path.dirname(str(self.checkpoint_path))
                    return _orig_load(self)
                moss_tts_nano_runtime.NanoTTSService._load_model_locked = _p_load
                moss_tts_nano_runtime.NanoTTSService._is_patched = True
        except: pass

        # 🧩 拦截 D: 屏蔽加速库与设备重定向
        try:
            import torch
            # 1. 禁用 accelerate 探测：这是防止 transformers 自动进入 meta 加载逻辑的最优雅方式
            import transformers.utils.import_utils as import_utils
            import_utils.is_accelerate_available = lambda: False
            
            # 2. 劫持 torch.load (保持原有 CPU 重定向)
            _orig_torch_load = torch.load
            def _patched_torch_load(*args, **kwargs):
                ml = kwargs.get("map_location")
                if ml == "meta" or getattr(ml, "type", "") == "meta": kwargs["map_location"] = "cpu"
                return _orig_torch_load(*args, **kwargs)
            torch.load = _patched_torch_load
            
        except Exception as e:
            print(f"底层屏蔽失败: {e}")

        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"
        print("🛠️ [Patch] V5.2 补丁已激活 (已恢复语义匹配兼容性)")
    except Exception as e:
        print(f"补丁应用失败: {e}")

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
import queue

LLM_QUEUE = queue.Queue()

def llm_worker_thread():
    """专用的 LLM 工作线程，维护单一持久事件循环，避免高并发下过多事件循环导致泄露"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try:
            text = LLM_QUEUE.get()
            if text is None: break
            loop.run_until_complete(stream_and_speak(text))
        except Exception as e:
            logger.error(f"LLM Worker Error: {e}")


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

def main():
    logger.info("--- OmniSense Audio Terminal Started (Modular Refactored) ---")
    cleanup_old_audio(days=3)
    
    # 创建持久事件循环，避免反复创建/销毁导致资源泄漏
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 启动 API 服务
    threading.Thread(target=run_api_server, daemon=True).start()

    # 启动全局 TTS 管线与 LLM 队列消费
    threading.Thread(target=persistent_worker, args=(synthesis_worker, GLOBAL_TEXT_QUEUE, GLOBAL_AUDIO_QUEUE), daemon=True).start()
    threading.Thread(target=persistent_worker, args=(playback_worker, GLOBAL_AUDIO_QUEUE), daemon=True).start()
    threading.Thread(target=llm_worker_thread, daemon=True).start()
    
    logger.info("🎧 系统就绪，随时等待你开口说话...")
    while True:
        try:
            if AUDIO_DUPLEX_MODE == "half" and get_is_playing():
                time.sleep(0.1)
                continue
            audio_file, trigger_rms = record_audio_until_silence()
            if audio_file is None: continue
            user_text = loop.run_until_complete(speech_to_text(audio_file, trigger_rms))
            if user_text and user_text.strip():
                if handle_immediate_actions(user_text): continue
                if get_silent_mode():
                    logger.info(f"🤫 [静默模式]: 忽略用户输入: {user_text}")
                    continue
                TASK_CTRL.request_stop(reason="reset")
                time.sleep(0.05) 
                TASK_CTRL.reset()
                
                # 清空队列中积压的旧任务
                while not LLM_QUEUE.empty():
                    try:
                        LLM_QUEUE.get_nowait()
                    except queue.Empty:
                        break
                
                # 将新任务推入队列，由固定 Worker 处理
                LLM_QUEUE.put(user_text)
        except KeyboardInterrupt:
            logger.info("👋 用户中断，退出程序")
            break
        except Exception as e:
            logger.error(f"Main Loop Error: {e}")
    
    loop.close()

if __name__ == "__main__":
    main()
