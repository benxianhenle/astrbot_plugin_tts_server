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
    
    async def _generate_schema_from_cache(self):
        """
        使用已缓存的数据生成schema
        避免重复API调用，使用插件已获取的角色和参考音频数据
        """
        import json
        import os
        
        plugin_dir = os.path.dirname(__file__)
        base_schema_path = os.path.join(plugin_dir, "base_schema.json")
        output_schema_path = os.path.join(plugin_dir, "_conf_schema.json")
        
        if not os.path.exists(base_schema_path):
            logger.warning(f"[TTS Plugin] 基础schema模板不存在: {base_schema_path}")
            return False
        
        try:
            # 读取基础schema模板
            with open(base_schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            
            # 构建选项列表
            options = []
            
            # 如果已有角色缓存，使用缓存数据
            if self._roles_cache:
                logger.info(f"[TTS Plugin] 使用 {len(self._roles_cache)} 个缓存角色生成schema选项")
                
                total_references = 0
                for role in self._roles_cache:
                    role_name = role.name
                    
                    # 获取角色的参考音频
                    try:
                        references = await self.client.get_role_references(role_name)
                        if references:
                            logger.debug(f"[TTS Plugin] 角色 '{role_name}' 有 {len(references)} 个参考音频")
                            for ref in references:
                                # 使用file_name或name作为音频标识
                                audio_name = ref.file_name or ref.name or "默认音频"
                                option = f"{role_name} | {audio_name}"
                                options.append(option)
                                total_references += 1
                                logger.debug(f"[TTS Plugin] 添加选项: {option}")
                        else:
                            # 如果没有参考音频，添加默认选项
                            option = f"{role_name} | 默认音频"
                            options.append(option)
                            logger.debug(f"[TTS Plugin] 角色 '{role_name}' 无参考音频，添加默认选项")
                    except Exception as e:
                        logger.warning(f"[TTS Plugin] 获取角色'{role_name}'的参考音频失败: {e}")
                        option = f"{role_name} | 默认音频"
                        options.append(option)
                
                logger.info(f"[TTS Plugin] 总计生成了 {len(options)} 个选项，来自 {len(self._roles_cache)} 个角色，共 {total_references} 个参考音频")
            else:
                logger.warning("[TTS Plugin] 角色缓存为空，无法生成选项")
                logger.warning("[TTS Plugin] 可能原因: 1) API Key无效 2) 网络连接问题 3) 服务器无角色数据")
                options = ["默认角色 | 默认音频"]
            
            # 如果没有选项，使用默认
            if not options:
                logger.warning("[TTS Plugin] 无法生成角色和参考音频选项，使用默认选项")
                options = ["默认角色 | 默认音频"]
            
            # 更新schema中的voice字段
            if "default_params" in schema and "items" in schema["default_params"]:
                items = schema["default_params"]["items"]
                if "voice" in items:
                    items["voice"]["options"] = options
                    items["voice"]["labels"] = options
                    # 更新提示信息
                    hint = f"从网站获取的角色和参考音频组合（已加载 {len(options)} 个组合，修改API Key后需重启插件刷新）"
                    items["voice"]["hint"] = hint
                    logger.info(f"[TTS Plugin] 已更新default_params.voice字段，{len(options)} 个选项")
                else:
                    logger.warning("[TTS Plugin] schema中未找到default_params.items.voice字段")
            else:
                logger.warning("[TTS Plugin] schema中未找到default_params或default_params.items")
            
            # 更新情绪配置中的voice字段（如果有）
            if "emotion" in schema and "templates" in schema["emotion"]:
                templates = schema["emotion"]["templates"]
                if "default" in templates and "items" in templates["default"]:
                    emotion_items = templates["default"]["items"]
                    if "voice" in emotion_items:
                        emotion_items["voice"]["options"] = options
                        emotion_items["voice"]["labels"] = options
                        logger.info(f"[TTS Plugin] 已更新emotion.templates.default.items.voice字段")
            
            # 写入最终schema
            with open(output_schema_path, "w", encoding="utf-8") as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[TTS Plugin] 已生成配置schema，包含 {len(options)} 个组合选项")
            logger.info(f"[TTS Plugin] 输出文件: {output_schema_path}")
            
            # 记录前几个选项供调试
            for i, option in enumerate(options[:5]):
                logger.debug(f"[TTS Plugin] 选项 {i+1}: {option}")
            if len(options) > 5:
                logger.debug(f"[TTS Plugin] ... 还有 {len(options)-5} 个选项")
            
            return True
            
        except Exception as e:
            logger.error(f"[TTS Plugin] 生成schema失败: {e}")
            import traceback
            logger.error(f"[TTS Plugin] 详细错误: {traceback.format_exc()}")
            return False

    async def initialize(self):
        """插件初始化"""
        if self.cfg.enabled:
            logger.info("[TTS Plugin] 插件已初始化，正在检查配置...")
            
            # 检查API配置
            api_key = self.cfg.client.api_key
            base_url = self.cfg.client.base_url
            
            logger.info(f"[TTS Plugin] 配置检查 - API地址: {base_url}")
            logger.info(f"[TTS Plugin] 配置检查 - API Key: {'已配置' if api_key and api_key.strip() not in ['', '请在此处输入您的API Key'] else '未配置或无效'}")
            
            # 1. 预加载角色列表（用于插件内部验证和schema生成）
            if api_key and api_key.strip() and api_key.strip() != "请在此处输入您的API Key":
                try:
                    logger.info("[TTS Plugin] 正在使用配置的API Key获取角色列表...")
                    # 预加载角色列表
                    self._roles_cache = await self.client.get_roles()
                    
                    if self._roles_cache:
                        logger.info(f"[TTS Plugin] 成功获取到 {len(self._roles_cache)} 个角色")
                        
                        # 记录前几个角色供调试
                        for i, role in enumerate(self._roles_cache[:3]):
                            logger.debug(f"[TTS Plugin] 角色 {i+1}: {role.name}")
                        if len(self._roles_cache) > 3:
                            logger.debug(f"[TTS Plugin] ... 还有 {len(self._roles_cache)-3} 个角色")
                    else:
                        logger.warning("[TTS Plugin] 获取到的角色列表为空，可能API Key无效或服务器无角色数据")
                    
                    # 2. 强制动态生成配置schema（使用已获取的角色数据）
                    logger.info("[TTS Plugin] 正在强制重新生成配置schema...")
                    try:
                        success = await self._generate_schema_from_cache()
                        
                        if success:
                            logger.info("[TTS Plugin] 动态配置schema生成成功，已更新voice选项")
                            logger.info("[TTS Plugin] 注意：修改配置后需要重启插件才能生效")
                        else:
                            logger.warning("[TTS Plugin] 动态配置schema生成失败，尝试备用方法...")
                            # 如果新方法失败，回退到脚本方法
                            script_success = await self._generate_schema_via_subprocess()
                            if script_success:
                                logger.info("[TTS Plugin] 脚本生成schema成功")
                            else:
                                logger.warning("[TTS Plugin] 所有schema生成方法都失败，UI将显示默认选项")
                    except Exception as e:
                        logger.warning(f"[TTS Plugin] 生成动态schema时出错: {e}")
                        # 出错时也尝试使用脚本
                        try:
                            script_success = await self._generate_schema_via_subprocess()
                            if script_success:
                                logger.info("[TTS Plugin] 脚本生成schema成功")
                        except Exception as script_error:
                            logger.warning(f"[TTS Plugin] 脚本生成schema也失败: {script_error}")
                            logger.info("[TTS Plugin] 将使用现有的schema配置")
                        
                except Exception as e:
                    logger.warning(f"[TTS Plugin] 初始化时获取角色列表失败: {e}")
                    logger.info("[TTS Plugin] 角色列表将在需要时获取")
                    
                    # 即使获取角色失败，也尝试生成schema（脚本可能有缓存）
                    logger.info("[TTS Plugin] 尝试使用脚本生成schema...")
                    try:
                        success = await self._generate_schema_via_subprocess()
                        
                        if success:
                            logger.info("[TTS Plugin] 脚本生成schema成功")
                        else:
                            logger.warning("[TTS Plugin] 脚本生成schema失败，将使用现有的schema配置")
                    except Exception as schema_error:
                        logger.warning(f"[TTS Plugin] 生成schema失败: {schema_error}")
            else:
                logger.info("[TTS Plugin] API Key未配置或无效，角色列表将在需要时获取")
                logger.info("[TTS Plugin] 请在配置中填写有效的API Key并重启插件")

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
        voice: str = None,
        streaming_mode: bool = None,
        top_k: int = None,
        top_p: float = None,
        temperature: float = None,
        text_split_method: str = None,
        repetition_penalty: float = None,
        sample_steps: int = None,
        seed: int = None
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
            streaming_mode: 是否流式模式（可选，使用默认配置）
            top_k: top_k采样（可选，使用默认配置）
            top_p: top_p采样（可选，使用默认配置）
            temperature: 温度参数（可选，使用默认配置）
            text_split_method: 文本分割方法（可选，使用默认配置）
            repetition_penalty: 重复惩罚（可选，使用默认配置）
            sample_steps: 采样步数（可选，使用默认配置）
            seed: 随机种子（可选，使用默认配置）
            
        Returns:
            TTS请求结果
        """
        # 使用默认配置
        if not language:
            language = self.cfg.default_params.language
        if speed_factor is None:
            speed_factor = self.cfg.default_params.speed_factor
        
        # 高级参数配置
        if streaming_mode is None:
            streaming_mode = getattr(self.cfg.default_params, "streaming_mode", False)
        if top_k is None:
            top_k = getattr(self.cfg.advanced_params, "top_k", 15)
        if top_p is None:
            top_p = getattr(self.cfg.advanced_params, "top_p", 1.0)
        if temperature is None:
            temperature = getattr(self.cfg.advanced_params, "temperature", 1.0)
        if text_split_method is None:
            text_split_method = getattr(self.cfg.advanced_params, "text_split_method", "cut2")
        if repetition_penalty is None:
            repetition_penalty = getattr(self.cfg.advanced_params, "repetition_penalty", 1.35)
        if sample_steps is None:
            sample_steps = getattr(self.cfg.advanced_params, "sample_steps", 32)
        if seed is None:
            seed = getattr(self.cfg.advanced_params, "seed", -1)
        
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

        # 检查缓存（包含所有微调参数）
        cached_data = self.cache.get(
            text=text,
            role=role,
            reference=reference,
            language=language,
            speed_factor=speed_factor,
            streaming_mode=streaming_mode,
            top_k=top_k,
            top_p=top_p,
            temperature=temperature,
            text_split_method=text_split_method,
            repetition_penalty=repetition_penalty,
            sample_steps=sample_steps,
            seed=seed
        )
        if cached_data:
            logger.debug(f"[TTS Plugin] 缓存命中，参数: role={role}, reference={reference}, language={language}, speed_factor={speed_factor}")
            return TTSRequestResult(ok=True, data=cached_data, text=text)

        # 提交推理任务并等待结果
        result = await self.client.infer_and_download(
            text=text,
            role=role,
            reference=reference,
            language=language,
            speed_factor=speed_factor,
            streaming_mode=streaming_mode,
            top_k=top_k,
            top_p=top_p,
            temperature=temperature,
            text_split_method=text_split_method,
            repetition_penalty=repetition_penalty,
            sample_steps=sample_steps,
            seed=seed
        )

        # 保存缓存（包含所有微调参数）
        if result.ok:
            success = self.cache.set(
                data=result.data,
                text=text,
                role=role,
                reference=reference,
                language=language,
                speed_factor=speed_factor,
                streaming_mode=streaming_mode,
                top_k=top_k,
                top_p=top_p,
                temperature=temperature,
                text_split_method=text_split_method,
                repetition_penalty=repetition_penalty,
                sample_steps=sample_steps,
                seed=seed
            )
            if success:
                logger.debug(f"[TTS Plugin] 已保存缓存，参数: role={role}, reference={reference}, size={len(result.data) if result.data else 0} bytes")
            else:
                logger.warning("[TTS Plugin] 保存缓存失败")

        return result

    @filter.on_decorating_result(priority=14)
    async def on_decorating_result(self, event: AstrMessageEvent):
        """消息装饰器 - 自动将文本转为语音"""
        if not self.cfg.enabled:
            logger.debug("[TTS Plugin] 插件未启用")
            return

        cfg = self.cfg.auto
        logger.debug(f"[TTS Plugin] 装饰器检查: enabled={self.cfg.enabled}, only_llm_result={cfg.only_llm_result}, tts_prob={cfg.tts_prob}, max_msg_len={cfg.max_msg_len}")
        
        result = event.get_result()
        if not result:
            logger.debug("[TTS Plugin] 无结果，跳过")
            return

        chain = result.chain
        if not chain:
            logger.debug("[TTS Plugin] 无消息链，跳过")
            return

        # 只处理LLM结果
        if cfg.only_llm_result and not result.is_llm_result():
            logger.debug(f"[TTS Plugin] 非LLM结果被跳过 (only_llm_result={cfg.only_llm_result}, is_llm_result={result.is_llm_result()})")
            return

        # 按概率触发
        rand_val = random.random()
        if rand_val > cfg.tts_prob:
            logger.debug(f"[TTS Plugin] 概率触发跳过 (random={rand_val:.3f} > tts_prob={cfg.tts_prob})")
            return
        else:
            logger.debug(f"[TTS Plugin] 概率触发通过 (random={rand_val:.3f} <= tts_prob={cfg.tts_prob})")

        # 收集所有Plain文本片段
        plain_texts = []
        for seg in chain:
            if isinstance(seg, Plain):
                plain_texts.append(seg.text)
        
        logger.debug(f"[TTS Plugin] 消息链分析: 总段数={len(chain)}, Plain段数={len(plain_texts)}")

        # 仅允许只含有Plain的消息链通过
        if len(plain_texts) != len(chain):
            logger.debug(f"[TTS Plugin] 消息链包含非Plain内容，跳过 (plain_texts={len(plain_texts)}, chain={len(chain)})")
            return

        # 合并所有Plain文本
        combined_text = "\n".join(plain_texts)
        logger.debug(f"[TTS Plugin] 合并文本: 长度={len(combined_text)}, 内容前50字符: {combined_text[:50]}{'...' if len(combined_text) > 50 else ''}")

        # 仅允许一定长度以下的文本通过
        if len(combined_text) > cfg.max_msg_len:
            logger.debug(f"[TTS Plugin] 文本长度超过限制: {len(combined_text)} > {cfg.max_msg_len}")
            return
        else:
            logger.debug(f"[TTS Plugin] 文本长度检查通过: {len(combined_text)} <= {cfg.max_msg_len}")

        # 获取情绪参数
        emotion_params = self._get_emotion_params(combined_text)
        logger.debug(f"[TTS Plugin] 情绪参数: {emotion_params}")
        
        # 执行TTS
        logger.debug("[TTS Plugin] 开始执行TTS...")
        res = await self._do_tts(combined_text, **emotion_params)
        
        if not bool(res):
            logger.warning(f"[TTS Plugin] TTS失败: {res.error}")
            return
        else:
            logger.debug(f"[TTS Plugin] TTS成功: 音频大小={len(res.data) if res.data else 0} bytes")

        # 替换消息链为语音
        logger.debug("[TTS Plugin] 替换消息链为语音")
        chain.clear()
        chain.append(self._to_record(res))
        logger.debug("[TTS Plugin] 语音转换完成")

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
