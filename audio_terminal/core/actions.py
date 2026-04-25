import logging
import threading
import requests
import uuid
import torch
from .shared import set_silent_mode, GLOBAL_TEXT_QUEUE
from .controller import TASK_CTRL

logger = logging.getLogger("OmniSenseAudio")

class SemanticMatcher:
    def __init__(self, model_name='/app/audio_terminal/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', threshold=0.82):
        import os
        if not os.path.exists(model_name):
            # 回退到 HuggingFace 名称（如果本地挂载失败）
            model_name = 'paraphrase-multilingual-MiniLM-L12-v2'
            
        from sentence_transformers import SentenceTransformer
        logger.info(f"🧬 正在加载语义模型: {model_name} ...")
        self.model = SentenceTransformer(model_name)
        self.threshold = threshold
        self.intents = {} # {intent_id: prototype_vector}

    def add_intent(self, intent_id, reference_phrases):
        if not reference_phrases: return
        vectors = self.model.encode(reference_phrases, convert_to_tensor=True)
        self.intents[intent_id] = torch.mean(vectors, dim=0)
        logger.info(f"📚 意图库已注册: {intent_id} ({len(reference_phrases)} 参考句)")

    def match(self, text):
        if not text or not self.intents: return None
        query_vector = self.model.encode(text, convert_to_tensor=True)
        best_score = -1
        best_intent = None
        for intent_id, proto_vector in self.intents.items():
            score = torch.cosine_similarity(query_vector.unsqueeze(0), proto_vector.unsqueeze(0)).item()
            if score > best_score:
                best_score = score
                best_intent = intent_id
        if best_score >= self.threshold:
            logger.info(f"🎯 [VCD 语义匹配]: {best_intent} (相似度: {best_score:.4f})")
            return best_intent
        return None

def generate_session_key():
    return f"agent:main:jarvis-voice-terminal-{uuid.uuid4().hex[:8]}"

class ActionManager:
    ACTIONS = {
        "NEW_SESSION": {
            "tags": ["[ACTION_NEW]"],
            "keywords": ["开启新对话", "重新开始", "清空对话", "重置对话", "忘记之前的"],
            "log": "🧹 触发重置意图 (New Session)"
        },
        "COMPRESS": {
            "tags": ["[ACTION_COMPRESS]"],
            "keywords": ["压缩上下文", "压缩记忆", "精简对话", "清理冗余"],
            "log": "🗜️ 触发压缩意图 (Compress)"
        },
        "STOP_DIALOGUE": {
            "tags": ["[ACTION_STOP]"],
            "keywords": ["闭嘴", "别说了", "停止说话", "安静点", "别说话了", "停"],
            "log": "🛑 触发停止意图 (Stop Dialogue)"
        },
        "SILENT_ON": {
            "tags": ["[ACTION_SILENT]"],
            "keywords": ["进入静默模式", "开启静默模式", "开启静默", "不要说话", "保持静默"],
            "log": "🔇 状态切换: 进入静默模式"
        },
        "SILENT_OFF": {
            "tags": ["[ACTION_ACTIVE]"],
            "keywords": ["退出静默模式", "恢复对话", "关闭静默模式", "关闭静默", "可以说话了", "解除静默"],
            "log": "🔊 状态切换: 恢复正常模式"
        }
    }

    def __init__(self, has_semantic=True):
        self.buffer = ""
        self.max_buffer_len = 100
        self.semantic_matcher = None
        self.is_ready = False
        self.session_key = generate_session_key()
        
        if has_semantic:
            threading.Thread(target=self._lazy_init_semantic, daemon=True).start()
        else:
            logger.warning("⚠️ VCD 将降级为关键词模式")

    def _lazy_init_semantic(self):
        try:
            self.semantic_matcher = SemanticMatcher()
            for action_id, config in self.ACTIONS.items():
                self.semantic_matcher.add_intent(action_id, config["keywords"])
            self.is_ready = True
            logger.info("✅ ActionManager 语义引擎预热完成")
        except Exception as e:
            logger.error(f"❌ 语义引擎加载失败: {e}")

    def process_chunk(self, chunk_text, use_semantic=False):
        """处理流式数据块，主要识别显式标签和关键词"""
        self.buffer += chunk_text
        if len(self.buffer) > self.max_buffer_len:
            self.buffer = self.buffer[-self.max_buffer_len:]
        
        triggered = []
        temp_text = self.buffer
        
        # 1. 优先匹配显式标签 (Tags) - 性能最高
        for action_id, config in self.ACTIONS.items():
            for tag in config["tags"]:
                if tag in temp_text:
                    triggered.append(action_id)
                    self.buffer = self.buffer.replace(tag, "")
                    break
        
        # 2. 只有在明确要求或可能是完整意图时才进行语义匹配
        if not triggered and use_semantic and self.semantic_matcher and self.is_ready:
            if len(self.buffer) > 2:
                action_id = self.semantic_matcher.match(self.buffer)
                if action_id:
                    triggered.append(action_id)
                    self.buffer = ""
        
        # 3. 关键词后备匹配
        if not triggered:
            for action_id, config in self.ACTIONS.items():
                for kw in config["keywords"]:
                    if kw in temp_text:
                        triggered.append(action_id)
                        # 匹配后清理 buffer 防止重复触发
                        self.buffer = "" 
                        break
        return triggered

    def execute_action(self, action_id, context=None):
        config = self.ACTIONS.get(action_id)
        if not config: return
        logger.info(config["log"])
        
        if action_id == "NEW_SESSION":
            self.session_key = generate_session_key()
            logger.info(f"🔄 已本地轮换 Session ID: {self.session_key}")
            GLOBAL_TEXT_QUEUE.put("好的，已为您重置对话。")
            if context and 'url' in context:
                threading.Thread(target=requests.post, args=(context['url'],), kwargs={
                    "headers": context.get('headers'), 
                    "json": {**context.get('payload', {}), "messages": [{"role": "user", "content": "/new"}], "stream": False}
                }, daemon=True).start()
        elif action_id == "COMPRESS":
            GLOBAL_TEXT_QUEUE.put("正在为您压缩对话记忆。")
            if context and 'url' in context:
                threading.Thread(target=requests.post, args=(context['url'],), kwargs={
                    "headers": context.get('headers'), 
                    "json": {**context.get('payload', {}), "messages": [{"role": "user", "content": "/compress"}], "stream": False}
                }, daemon=True).start()
        elif action_id == "SILENT_ON":
            set_silent_mode(True)
            GLOBAL_TEXT_QUEUE.put("好的，已为您开启静默模式。")
        elif action_id == "SILENT_OFF":
            set_silent_mode(False)
            GLOBAL_TEXT_QUEUE.put("好的，已为您恢复语音回复。")
        elif action_id == "STOP_DIALOGUE":
            TASK_CTRL.request_stop(reason="user_command")

# 单例
GLOBAL_ACTION_MGR = ActionManager()
