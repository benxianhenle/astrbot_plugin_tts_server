"""
缓存管理
"""
import hashlib
import base64
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from astrbot.api import logger


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, cache_dir: Path, enabled: bool = True, expire_hours: int = 0):
        self.cache_dir = cache_dir
        self.enabled = enabled
        self.expire_hours = expire_hours
        
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _generate_key(self, text: str, role: str, reference: str, **kwargs) -> str:
        """生成缓存键"""
        # 组合所有参数
        params = f"{text}|{role}|{reference}"
        for k, v in sorted(kwargs.items()):
            params += f"|{k}={v}"
        
        # 使用MD5生成短键
        return hashlib.md5(params.encode()).hexdigest()
    
    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{key}.wav"
    
    def get(self, text: str, role: str, reference: str, **kwargs) -> Optional[bytes]:
        """
        获取缓存的音频数据
        
        Returns:
            音频数据或None（未命中）
        """
        if not self.enabled:
            return None
        
        key = self._generate_key(text, role, reference, **kwargs)
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            return None
        
        # 检查是否过期
        if self.expire_hours > 0:
            mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
            if datetime.now() - mtime > timedelta(hours=self.expire_hours):
                logger.debug(f"[Cache] 缓存已过期: {key}")
                cache_path.unlink(missing_ok=True)
                return None
        
        try:
            data = cache_path.read_bytes()
            logger.debug(f"[Cache] 命中: {key}, 大小: {len(data)} bytes")
            return data
        except Exception as e:
            logger.warning(f"[Cache] 读取缓存失败: {e}")
            return None
    
    def set(self, data: bytes, text: str, role: str, reference: str, **kwargs) -> bool:
        """
        设置缓存
        
        Returns:
            是否成功
        """
        if not self.enabled:
            return False
        
        key = self._generate_key(text, role, reference, **kwargs)
        cache_path = self._get_cache_path(key)
        
        try:
            cache_path.write_bytes(data)
            logger.debug(f"[Cache] 已保存: {key}, 大小: {len(data)} bytes")
            return True
        except Exception as e:
            logger.warning(f"[Cache] 保存缓存失败: {e}")
            return False
    
    def clear(self) -> int:
        """
        清除所有缓存
        
        Returns:
            清除的文件数量
        """
        count = 0
        try:
            for f in self.cache_dir.glob("*.wav"):
                f.unlink()
                count += 1
            logger.info(f"[Cache] 已清除 {count} 个缓存文件")
        except Exception as e:
            logger.error(f"[Cache] 清除缓存失败: {e}")
        return count
    
    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        try:
            files = list(self.cache_dir.glob("*.wav"))
            total_size = sum(f.stat().st_size for f in files)
            return {
                "file_count": len(files),
                "total_size": total_size,
                "cache_dir": str(self.cache_dir)
            }
        except Exception as e:
            logger.error(f"[Cache] 获取统计信息失败: {e}")
            return {"file_count": 0, "total_size": 0, "cache_dir": str(self.cache_dir)}
