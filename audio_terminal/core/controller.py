import threading
import logging
import subprocess
from .shared import GLOBAL_TEXT_QUEUE, GLOBAL_AUDIO_QUEUE

logger = logging.getLogger("OmniSenseAudio")

class GlobalTaskController:
    def __init__(self):
        self.stop_event = threading.Event()
        self.active_aplay = None
        self.current_thread = None
        self.lock = threading.Lock()
        self.speaker_lock = threading.Lock() # 实际用于同步 aplay 的锁

    def request_stop(self, reason="reset"):
        """物理打断：杀掉进程、设置信号、清空状态"""
        has_active = False
        with self.lock:
            if self.active_aplay:
                has_active = True

        if reason == "user_command":
            logger.warning("🛑 [语音打断]: 收到 '停止' 指令，正在强行终止任务...")
        elif has_active:
            logger.info("🔄 [播放重置]: 检测到新输入，正在打断旧有的语音输出...")
        
        self.stop_event.set()
        
        if reason in ["user_command", "reset"]:
            logger.info("🧹 正在清空待任务队列...")
            while not GLOBAL_TEXT_QUEUE.empty():
                try: GLOBAL_TEXT_QUEUE.get_nowait(); GLOBAL_TEXT_QUEUE.task_done()
                except: break
            
            # 无论是重置还是用户命令，都清空音频队列
            while not GLOBAL_AUDIO_QUEUE.empty():
                try: GLOBAL_AUDIO_QUEUE.get_nowait(); GLOBAL_AUDIO_QUEUE.task_done()
                except: break

        with self.lock:
            if self.active_aplay:
                try:
                    self.active_aplay.kill()
                    logger.info("🔪 物理播放进程已终止")
                except (ProcessLookupError, OSError):
                    pass
                self.active_aplay = None

    def reset(self):
        self.stop_event.clear()
        with self.lock:
            self.active_aplay = None

    def set_aplay(self, proc):
        with self.lock:
            self.active_aplay = proc

    def is_stopped(self):
        return self.stop_event.is_set()

# 单例
TASK_CTRL = GlobalTaskController()
SPEAKER_LOCK = TASK_CTRL.speaker_lock
