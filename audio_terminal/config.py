import os
import re

# 基础目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Endpoints
KOKORO_TTS_URL = os.getenv("KOKORO_TTS_URL", "http://localhost:8000/v1/audio/speech")
WHISPER_STT_URL = os.getenv("WHISPER_STT_URL", "http://localhost:8081/v1/audio/transcriptions")
AGENT_URL = os.getenv("AGENT_API_URL", "http://localhost:8642")
AGENT_TOKEN = os.getenv("API_SERVER_KEY", "your_token_here")


# 日志与数据目录
LOG_STT_DIR = os.path.join(BASE_DIR, "logs/stt")
LOG_TTS_DIR = os.path.join(BASE_DIR, "logs/tts")
STT_HISTORY_FILE = os.path.join(BASE_DIR, "logs/stt_history.jsonl")
HALLUCINATION_FILE = os.path.join(BASE_DIR, "hallucination_data/filter_list.json")

# 音频配置
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
CHUNK_DURATION_MS = 30
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)

# 音频模式：'full' (全双工，支持打断) 或 'half' (半双工，播放时禁止录音)
AUDIO_DUPLEX_MODE = os.getenv("AUDIO_DUPLEX_MODE", "full")


# VAD 配置
ENERGY_THRESHOLD = 500
MIN_ENERGY_THRESHOLD = 250 # 允许降到的最低阈值
VAD_MULTIPLIER = 1.5       # 灵敏度倍率 (noise_floor * multiplier)
SILENCE_TIMEOUT = 1.5
MAX_RECORD_SECONDS = 30
PRE_SPEECH_BUFFER = 10

# 语音配置
ZH_VOICE = "zm_yunxi"
EN_VOICE = "am_adam"

# 断句逻辑
SENTENCE_DELIMITERS = re.compile(r'[\n]|(?<=[。！？])|(?<=[!?])')
SECONDARY_DELIMITERS = re.compile(r'(?<=[，,])')
MIN_SENTENCE_LEN = 5
MAX_SENTENCE_LEN = 25

# 硬件补丁
HW_SAMPLE_RATE = 44100
PLAYBACK_CHANNELS = 2
SILENCE_PADDING_DURATION = 0.15 # 150ms 静默注入

# MOSS-TTS-Nano 离线补丁配置
MOSS_PATH = os.path.join(PROJECT_ROOT, "MOSS-TTS-Nano")
# 具体的 .model 文件路径，用于触发 main.py 中的猴子补丁
# 默认指向 Docker 容器内的路径，可通过 .env 覆盖
DEFAULT_MOSS_MODEL = "/app/MOSS-TTS-Nano/hf_cache/hub/models--OpenMOSS-Team--MOSS-TTS-Nano/snapshots/44502f80dbf9743528fa921cc544d662c685ebec/tokenizer.model"
MOSS_CHECKPOINT_PATH = os.getenv("MOSS_CHECKPOINT_PATH", DEFAULT_MOSS_MODEL)
