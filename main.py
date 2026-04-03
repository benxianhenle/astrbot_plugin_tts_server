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

# Schema生成使用subprocess执行，避免import路径问题


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

    async def _generate_schema_via_subprocess(self):
        """使用subprocess执行schema生成脚本"""
        import subprocess
        import os
        import asyncio
        
        plugin_dir = os.path.dirname(__file__)
        script_path = os.path.join(plugin_dir, "scripts", "generate_schema.py")
        
        if not os.path.exists(script_path):
            logger.warning(f"[TTS Plugin] Schema生成脚本不存在: {script_path}")
            return False
        
        # 构建命令行参数
        cmd = ["python", script_path]
        if self.cfg.client.api_key:
            cmd.extend(["--api-key", self.cfg.client.api_key])
        if self.cfg.client.base_url:
            cmd.extend(["--base-url", self.cfg.client.base_url])
        
        try:
            logger.info(f"[TTS Plugin] 正在执行schema生成脚本: {' '.join(cmd[:2])}...")
            
            # 在后台线程中运行subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info("[TTS Plugin] Schema生成成功")
                if stdout:
                    logger.debug(f"[TTS Plugin] 脚本输出: {stdout.decode('utf-8', errors='ignore')}")
                return True
            else:
                logger.warning(f"[TTS Plugin] Schema生成失败，退出码: {process.returncode}")
                if stderr:
                    error_msg = stderr.decode('utf-8', errors='ignore')
                    logger.warning(f"[TTS Plugin] 脚本错误: {error_msg}")
                return False
                
        except Exception as e:
            logger.warning(f"[TTS Plugin] 执行schema生成脚本时出错: {e}")
            return False

    async def initialize(self):
        """插件初始化"""
        if self.cfg.enabled:
            logger.info("[TTS Plugin] 插件已初始化，正在尝试获取角色列表...")
            
            # 1. 尝试动态生成配置schema
            if self.cfg.client.api_key:
                try:
                    logger.info("[TTS Plugin] 正在生成动态配置schema...")
                    success = await self._generate_schema_via_subprocess()
                    
                    if success:
                        logger.info("[TTS Plugin] 动态配置schema生成成功")
                    else:
                        logger.warning("[TTS Plugin] 动态配置schema生成失败，将使用静态schema")
                except Exception as e:
                    logger.warning(f"[TTS Plugin] 生成动态schema时出错: {e}")
            
            # 2. 预加载角色列表（用于插件内部验证）
            if self.cfg.client.api_key:
                try:
                    # 预加载角色列表
                    self._roles_cache = await self.client.get_roles()
                    logger.info(f"[TTS Plugin] 已加载 {len(self._roles_cache)} 个角色")
                except Exception as e:
                    logger.warning(f"[TTS Plugin] 初始化时获取角色列表失败: {e}")
                    logger.info("[TTS Plugin] 角色列表将在需要时获取")
            else:
                logger.info("[TTS Plugin] API Key未配置，角色列表将在需要时获取")

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
        speed_factor: float = None,
        voice: str = None
    ) -> TTSRequestResult:
        """
        执行TTS
        
        Args:
            text: 要转换的文本
            role: 角色名称（可选，使用默认配置）
            reference: 参考音频文件名（可选，使用默认配置）
            language: 语言（可选，使用默认配置）
            speed_factor: 语速倍数（可选，使用默认配置）
            voice: 角色和参考音频组合，格式"角色 | 参考音频文件名"（可选，优先级高于role和reference）
            
        Returns:
            TTS请求结果
        """
        # 使用默认配置
        if not language:
            language = self.cfg.default_params.language
        if speed_factor is None:
            speed_factor = self.cfg.default_params.speed_factor
        
        # 处理voice字段（优先级最高）
        if voice is not None and voice != "":
            # 解析voice字段
            try:
                if " | " in voice:
                    role_from_voice, reference_from_voice = voice.split(" | ", 1)
                    role = role_from_voice
                    reference = reference_from_voice
                else:
                    # 格式不正确，清空role和reference
                    role = ""
                    reference = ""
            except Exception:
                role = ""
                reference = ""
        else:
            # 如果没有提供voice，使用默认配置中的voice字段
            default_voice = self.cfg.default_params.voice
            if default_voice:
                try:
                    if " | " in default_voice:
                        role_from_default, reference_from_default = default_voice.split(" | ", 1)
                        if not role:
                            role = role_from_default
                        if not reference:
                            reference = reference_from_default
                    else:
                        # 格式不正确，清空role和reference
                        if not role:
                            role = ""
                        if not reference:
                            reference = ""
                except Exception:
                    if not role:
                        role = ""
                    if not reference:
                        reference = ""
        
        # 如果role和reference仍未设置，设置为空字符串
        if role is None:
            role = ""
        if reference is None:
            reference = ""
            
        # 验证角色是否存在
        if role:
            # 如果缓存为空，尝试获取角色列表
            if not self._roles_cache:
                try:
                    self._roles_cache = await self.client.get_roles(force_refresh=False)
                except Exception:
                    self._roles_cache = []
            
            # 检查角色是否在缓存中
            role_exists = any(r.name == role for r in self._roles_cache) if self._roles_cache else False
            
            if not role_exists and self._roles_cache is not None:
                # 尝试刷新角色列表
                try:
                    self._roles_cache = await self.client.get_roles(force_refresh=True)
                    role_exists = any(r.name == role for r in self._roles_cache) if self._roles_cache else False
                except Exception:
                    role_exists = False
                    
            if not role_exists:
                # 获取可用角色列表
                role_names = [r.name for r in self._roles_cache] if self._roles_cache else []
                error_msg = f"角色 '{role}' 不存在。"
                if role_names:
                    error_msg += f" 可用角色: {', '.join(role_names)}"
                else:
                    error_msg += " 无法获取角色列表，请检查API Key配置或使用 /角色列表 命令查看可用角色。"
                return TTSRequestResult(ok=False, error=error_msg, text=text)

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
            yield event.plain_result("插件未启用，请在配置中启用插件")
            return
            
        # 检查API Key是否配置
        if not self.cfg.client.api_key:
            yield event.plain_result("API Key未配置，请先在插件配置中填写API Key")
            return
            
        try:
            # 刷新角色列表
            self._roles_cache = await self.client.get_roles(force_refresh=True)
            
            if not self._roles_cache:
                yield event.plain_result("无法获取角色列表，可能原因：\n1. API Key无效或已过期\n2. 网络连接问题\n3. 服务器暂时不可用\n请检查配置后重试")
                return

            role_names = [f"• {role.name}" for role in self._roles_cache]
            text = f"可用角色列表（共{len(self._roles_cache)}个角色）:\n" + "\n".join(role_names)
            yield event.plain_result(text)
            
        except Exception as e:
            logger.error(f"[TTS Plugin] 获取角色列表异常: {e}")
            yield event.plain_result(f"获取角色列表时发生错误: {str(e)}")

    @filter.command("参考音频", alias={"refs", "音频"})
    async def on_refs_command(self, event: AstrMessageEvent):
        """
        参考音频 <角色名> - 显示角色的参考音频列表
        用法: /参考音频 霄宫
        """
        if not self.cfg.enabled:
            yield event.plain_result("插件未启用，请在配置中启用插件")
            return
            
        # 检查API Key是否配置
        if not self.cfg.client.api_key:
            yield event.plain_result("API Key未配置，请先在插件配置中填写API Key")
            return

        role_name = event.message_str.partition(" ")[2].strip()
        if not role_name:
            yield event.plain_result("请提供角色名称，例如：/参考音频 霄宫")
            return
            
        try:
            # 获取参考音频列表
            refs = await self.client.get_role_references(role_name, force_refresh=True)

            if not refs:
                yield event.plain_result(f"角色 '{role_name}' 没有可用的参考音频，或角色名称不正确")
                return

            ref_names = [f"• {ref.name} ({ref.file_name})" for ref in refs]
            text = f"角色 '{role_name}' 的参考音频（共{len(refs)}个）:\n" + "\n".join(ref_names)
            yield event.plain_result(text)
            
        except Exception as e:
            logger.error(f"[TTS Plugin] 获取参考音频列表异常: {e}")
            yield event.plain_result(f"获取参考音频列表时发生错误: {str(e)}")

    @filter.command("测试TTS连接", alias={"test-tts", "tts-test"})
    async def on_test_connection(self, event: AstrMessageEvent):
        """
        测试TTS连接 - 测试API Key有效性并获取角色列表
        用法: /测试TTS连接
        """
        if not self.cfg.enabled:
            yield event.plain_result("插件未启用，请在配置中启用插件")
            return
            
        # 检查API Key是否配置
        if not self.cfg.client.api_key:
            yield event.plain_result("API Key未配置，请先在插件配置中填写API Key")
            return
            
        try:
            yield event.plain_result("正在测试TTS服务器连接...")
            
            # 测试获取角色列表
            roles = await self.client.get_roles(force_refresh=True)
            
            if roles:
                self._roles_cache = roles
                role_names = [f"• {role.name}" for role in roles]
                text = f"✅ 连接成功！\n已获取到 {len(roles)} 个角色：\n" + "\n".join(role_names)
                yield event.plain_result(text)
                
                # 可选：获取第一个角色的参考音频作为进一步测试
                if roles:
                    first_role = roles[0]
                    refs = await self.client.get_role_references(first_role.name, force_refresh=True)
                    if refs:
                        yield event.plain_result(f"角色 '{first_role.name}' 有 {len(refs)} 个参考音频，连接完全正常。")
                    else:
                        yield event.plain_result(f"角色 '{first_role.name}' 暂无参考音频，但基本连接正常。")
            else:
                yield event.plain_result("❌ 连接失败：无法获取角色列表\n可能原因：\n1. API Key无效或已过期\n2. 网络连接问题\n3. 服务器暂时不可用\n请检查配置后重试")
                
        except Exception as e:
            logger.error(f"[TTS Plugin] 测试连接异常: {e}")
            yield event.plain_result(f"❌ 连接测试失败: {str(e)}")

    @filter.command("TTS缓存")
    async def on_cache_command(self, event: AstrMessageEvent):
        """
        TTS缓存 - 显示缓存统计信息
        """
        if not self.cfg.enabled:
            yield event.plain_result("插件未启用，请在配置中启用插件")
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
            yield event.plain_result("插件未启用，请在配置中启用插件")
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
