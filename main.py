"""
TTS服务器插件 - AstrBot
通过API调用远程TTS服务器进行语音合成
"""
import base64
import random

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import Plain, Record
from astrbot.core.platform import AstrMessageEvent

from .core.client import TTSServerClient, TTSRequestResult, RoleInfo, ReferenceAudioInfo
from .core.config import PluginConfig
from .core.emotion import EmotionManager
from .core.cache import CacheManager


class TTSServerPlugin(Star):
    """TTS服务器插件主类"""
    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self.client = TTSServerClient(
            base_url=self.cfg.client.base_url,
            api_key=self.cfg.client.api_key,
            timeout=self.cfg.client.timeout
        )
        self.emotion_mgr = EmotionManager(self.cfg.emotion)
        self.cache = CacheManager(
            cache_dir=self.cfg.audio_dir,
            enabled=self.cfg.cache.enabled,
            expire_hours=self.cfg.cache.expire_hours
        )
        
        # 缓存角色和参考音频列表
        self._roles_cache: list[RoleInfo] = []
        self._references_cache: dict[str, list[ReferenceAudioInfo]] = {}

    async def initialize(self):
        """插件初始化"""
        if self.cfg.enabled:
            # 预加载角色列表
            self._roles_cache = await self.client.get_roles()
            logger.info(f"[TTS Plugin] 已加载 {len(self._roles_cache)} 个角色")

    async def terminate(self):
        """插件终止"""
        await self.client.close()

    @staticmethod
    def _to_record(res: TTSRequestResult) -> Record:
        """将结果转换为 Record 组件"""
        if not res.data:
            raise ValueError("无法获取结果数据")

        b64 = base64.urlsafe_b64encode(res.data).decode()
        return Record.fromBase64(b64)

    def _get_emotion_params(self, text: str) -> dict:
        """获取情绪参数"""
        entry = self.emotion_mgr.match_entry(text)
        if entry:
            return entry.to_params()
        return {}

    async def _do_tts(
        self,
        text: str,
        role: str = None,
        reference: str = None,
        language: str = None,
        speed_factor: float = None
    ) -> TTSRequestResult:
        """
        执行TTS
        
        Args:
            text: 要转换的文本
            role: 角色名称（可选，使用默认配置）
            reference: 参考音频文件名（可选，使用默认配置）
            language: 语言（可选，使用默认配置）
            speed_factor: 语速倍数（可选，使用默认配置）
            
        Returns:
            TTS请求结果
        """
        # 使用默认配置
        if not role:
            role = self.cfg.default_params.role
        if not reference:
            reference = self.cfg.default_params.reference
        if not language:
            language = self.cfg.default_params.language
        if speed_factor is None:
            speed_factor = self.cfg.default_params.speed_factor

        # 检查缓存
        cached_data = self.cache.get(
            text=text,
            role=role,
            reference=reference,
            language=language,
            speed_factor=speed_factor
        )
        if cached_data:
            return TTSRequestResult(ok=True, data=cached_data, text=text)

        # 提交推理任务并等待结果
        result = await self.client.infer_and_download(
            text=text,
            role=role,
            reference=reference,
            language=language,
            speed_factor=speed_factor
        )

        # 保存缓存
        if result.ok:
            self.cache.set(
                data=result.data,
                text=text,
                role=role,
                reference=reference,
                language=language,
                speed_factor=speed_factor
            )

        return result

    @filter.on_decorating_result(priority=14)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """消息装饰器 - 自动将文本转为语音"""
        if not self.cfg.enabled:
            return

        cfg = self.cfg.auto
        result = event.get_result()
        if not result:
            return

        chain = result.chain
        if not chain:
            return

        # 只处理LLM结果
        if cfg.only_llm_result and not result.is_llm_result():
            return

        # 按概率触发
        if random.random() > cfg.tts_prob:
            return

        # 收集所有Plain文本片段
        plain_texts = []
        for seg in chain:
            if isinstance(seg, Plain):
                plain_texts.append(seg.text)

        # 仅允许只含有Plain的消息链通过
        if len(plain_texts) != len(chain):
            return

        # 合并所有Plain文本
        combined_text = "\n".join(plain_texts)

        # 仅允许一定长度以下的文本通过
        if len(combined_text) > cfg.max_msg_len:
            return

        # 获取情绪参数
        emotion_params = self._get_emotion_params(combined_text)
        
        # 执行TTS
        res = await self._do_tts(combined_text, **emotion_params)
        
        if not bool(res):
            logger.warning(f"[TTS Plugin] TTS失败: {res.error}")
            return

        # 替换消息链为语音
        chain.clear()
        chain.append(self._to_record(res))

    @filter.command("说", alias={"tts", "TTS"})
    async def on_say_command(self, event: AstrMessageEvent):
        """
        说 <内容> - 直接调用TTS合成语音
        用法: /说 你好世界
        """
        if not self.cfg.enabled:
            return

        text = event.message_str.partition(" ")[2].strip()
        if not text:
            yield event.plain_result("请提供要转换的文本，例如：/说 你好世界")
            return

        # 获取情绪参数
        emotion_params = self._get_emotion_params(text)
        
        # 执行TTS
        res = await self._do_tts(text, **emotion_params)

        if not bool(res):
            yield event.plain_result(f"TTS失败: {res.error}")
            return

        yield event.chain_result([self._to_record(res)])

    @filter.command("角色列表", alias={"roles", "角色"})
    async def on_roles_command(self, event: AstrMessageEvent):
        """
        角色列表 - 显示可用角色列表
        """
        if not self.cfg.enabled:
            return

        # 刷新角色列表
        self._roles_cache = await self.client.get_roles(force_refresh=True)

        if not self._roles_cache:
            yield event.plain_result("无法获取角色列表，请检查配置")
            return

        role_names = [f"• {role.name}" for role in self._roles_cache]
        text = "可用角色列表（从API获取）:\n" + "\n".join(role_names)
        yield event.plain_result(text)

    @filter.command("参考音频", alias={"refs", "音频"})
    async def on_refs_command(self, event: AstrMessageEvent):
        """
        参考音频 <角色名> - 显示角色的参考音频列表
        用法: /参考音频 霄宫
        """
        if not self.cfg.enabled:
            return

        role_name = event.message_str.partition(" ")[2].strip()
        if not role_name:
            yield event.plain_result("请提供角色名称，例如：/参考音频 霄宫")
            return

        # 获取参考音频列表
        refs = await self.client.get_role_references(role_name, force_refresh=True)

        if not refs:
            yield event.plain_result(f"角色 '{role_name}' 没有可用的参考音频")
            return

        ref_names = [f"• {ref.name} ({ref.file_name})" for ref in refs]
        text = f"角色 '{role_name}' 的参考音频:\n" + "\n".join(ref_names)
        yield event.plain_result(text)

    @filter.command("TTS缓存")
    async def on_cache_command(self, event: AstrMessageEvent):
        """
        TTS缓存 - 显示缓存统计信息
        """
        if not self.cfg.enabled:
            return

        stats = self.cache.get_stats()
        text = (
            f"TTS缓存统计:\n"
            f"• 缓存文件数: {stats['file_count']}\n"
            f"• 总大小: {stats['total_size'] / 1024 / 1024:.2f} MB\n"
            f"• 缓存目录: {stats['cache_dir']}"
        )
        yield event.plain_result(text)

    @filter.command("清除TTS缓存")
    async def on_clear_cache_command(self, event: AstrMessageEvent):
        """
        清除TTS缓存 - 清除所有缓存文件
        """
        if not self.cfg.enabled:
            return

        count = self.cache.clear()
        yield event.plain_result(f"已清除 {count} 个缓存文件")

    @filter.llm_tool()
    async def tts_tool(self, event: AstrMessageEvent, message: str = ""):
        """
        用语音输出要讲的话
        
        Args:
            message(str): 要讲的话
        """
        try:
            if not message:
                return "请提供要讲的话"

            # 获取情绪参数
            emotion_params = self._get_emotion_params(message)
            
            # 执行TTS
            res = await self._do_tts(message, **emotion_params)
            
            if not bool(res):
                return f"语音合成失败: {res.error}"

            seg = self._to_record(res)
            await event.send(event.chain_result([seg]))
            return "语音已发送"
        except Exception as e:
            return f"语音合成出错: {str(e)}"
