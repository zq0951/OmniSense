import threading
import queue
import logging

logger = logging.getLogger("OmniSenseAudio")

# 全局插话队列
GLOBAL_TEXT_QUEUE = queue.Queue()
GLOBAL_AUDIO_QUEUE = queue.Queue()

# 运行状态控制
_silent_mode_lock = threading.Lock()
SILENT_MODE = False

def get_silent_mode():
    with _silent_mode_lock:
        return SILENT_MODE

def set_silent_mode(value):
    global SILENT_MODE
    with _silent_mode_lock:
        SILENT_MODE = value

# 播放状态标识
_playing_lock = threading.Lock()
IS_PLAYING = False

def get_is_playing():
    with _playing_lock:
        return IS_PLAYING

def set_is_playing(value):
    global IS_PLAYING
    with _playing_lock:
        IS_PLAYING = value


# 会话初始化标记：用于记录哪些 Session 已发送过 voice_system_hint
INITIALIZED_SESSIONS = set()

# 用户情绪状态
_emotion_lock = threading.Lock()
USER_EMOTION = "NEUTRAL"

def get_user_emotion():
    with _emotion_lock:
        return USER_EMOTION

def set_user_emotion(value):
    global USER_EMOTION
    with _emotion_lock:
        USER_EMOTION = value
