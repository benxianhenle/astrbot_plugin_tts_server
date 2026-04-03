"""
情绪管理
处理情绪匹配和参数获取
"""
from typing import Optional, Dict, Any
from astrbot.api import logger


class EmotionEntry:
    """情绪条目"""
    
    def __init__(self, data: Dict[str, Any]):
        self.name = data.get("name", "")
        self.keywords = data.get("keywords", [])
        self.speed_factor = data.get("speed_factor", 1.0)
        
        # 处理voice字段（新格式）或role/reference字段（旧格式）
        voice = data.get("voice", "")
        if voice and " | " in voice:
            try:
                role_from_voice, reference_from_voice = voice.split(" | ", 1)
                self.role = role_from_voice
                self.reference = reference_from_voice
            except Exception:
                self.role = data.get("role", "")
                self.reference = data.get("reference", "")
        else:
            self.role = data.get("role", "")
            self.reference = data.get("reference", "")
    
    def to_params(self) -> Dict[str, Any]:
        """转换为API参数"""
        return {
            "voice": f"{self.role} | {self.reference}" if self.role and self.reference else "",
            "speed_factor": self.speed_factor
        }
    
    def match(self, text: str) -> bool:
        """检查文本是否匹配该情绪"""
        text_lower = text.lower()
        for keyword in self.keywords:
            if keyword.lower() in text_lower:
                return True
        return False


class EmotionManager:
    """情绪管理器"""
    
    def __init__(self, emotion_list: list):
        self.entries: list[EmotionEntry] = []
        for data in emotion_list:
            try:
                entry = EmotionEntry(data)
                if entry.name:
                    self.entries.append(entry)
            except Exception as e:
                logger.warning(f"[EmotionManager] 加载情绪条目失败: {e}")
    
    def get_entry(self, name: str) -> Optional[EmotionEntry]:
        """根据名称获取情绪条目"""
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None
    
    def match_entry(self, text: str) -> Optional[EmotionEntry]:
        """根据文本匹配情绪条目"""
        for entry in self.entries:
            if entry.match(text):
                return entry
        return None
    
    def get_names(self) -> list[str]:
        """获取所有情绪名称"""
        return [entry.name for entry in self.entries]
