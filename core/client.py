"""
TTS服务器 API 客户端
通过API获取角色、参考音频，并提交推理任务
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from astrbot.api import logger


@dataclass
class TTSRequestResult:
    """TTS请求结果"""
    ok: bool
    data: bytes | None = None
    error: str = ""
    text: str = ""
    file_path: str = ""

    @property
    def size(self) -> int:
        """音频数据大小（字节）"""
        return len(self.data) if self.data else 0

    @property
    def is_empty(self) -> bool:
        """是否无数据"""
        return self.size == 0

    def __bool__(self) -> bool:
        return self.ok and not self.is_empty


@dataclass
class RoleInfo:
    """角色信息"""
    id: str
    name: str
    description: str = ""


@dataclass
class ReferenceAudioInfo:
    """参考音频信息"""
    id: str
    name: str
    file_name: str


class TTSServerClient:
    """TTS服务器 API 客户端"""

    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = ClientSession(timeout=ClientTimeout(total=timeout))
        
        # 缓存角色和参考音频列表
        self._roles_cache: Optional[List[RoleInfo]] = None
        self._references_cache: Dict[str, List[ReferenceAudioInfo]] = {}

    async def close(self):
        """关闭会话"""
        if self.session:
            await self.session.close()

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_roles(self, force_refresh: bool = False) -> List[RoleInfo]:
        """
        获取角色列表
        
        Args:
            force_refresh: 是否强制刷新缓存
            
        Returns:
            角色信息列表
        """
        if self._roles_cache is not None and not force_refresh:
            return self._roles_cache

        try:
            url = f"{self.base_url}/roles"
            async with self.session.get(url, headers=self._get_headers()) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[TTS Client] 获取角色列表失败: HTTP {resp.status}, {error_text}")
                    return []

                data = await resp.json()
                roles = []
                for role_data in data.get("roles", []):
                    # 优先使用role_id和role_name，兼容旧格式的id和name
                    role_id = role_data.get("role_id") or role_data.get("id", "")
                    role_name = role_data.get("role_name") or role_data.get("name", "")
                    roles.append(RoleInfo(
                        id=role_id,
                        name=role_name,
                        description=role_data.get("description", "")
                    ))
                
                self._roles_cache = roles
                logger.info(f"[TTS Client] 获取到 {len(roles)} 个角色")
                return roles

        except ClientError as e:
            logger.error(f"[TTS Client] 获取角色列表请求失败: {e}")
            return []
        except Exception as e:
            logger.exception(f"[TTS Client] 获取角色列表异常")
            return []

    async def get_role_references(self, role_name: str, force_refresh: bool = False) -> List[ReferenceAudioInfo]:
        """
        获取角色的参考音频列表
        
        Args:
            role_name: 角色名称
            force_refresh: 是否强制刷新缓存
            
        Returns:
            参考音频信息列表
        """
        if role_name in self._references_cache and not force_refresh:
            return self._references_cache[role_name]

        try:
            # 获取角色详情，包含参考音频
            url = f"{self.base_url}/roles"
            async with self.session.get(url, headers=self._get_headers()) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[TTS Client] 获取角色参考音频失败: HTTP {resp.status}, {error_text}")
                    return []

                data = await resp.json()
                references = []
                
                # 查找指定角色的参考音频
                for role_data in data.get("roles", []):
                    # 使用与get_roles()相同的逻辑获取角色名
                    current_role_name = role_data.get("role_name") or role_data.get("name", "")
                    if current_role_name == role_name:
                        for ref_data in role_data.get("references", []):
                            # 优先使用reference_id，兼容旧格式的id
                            ref_id = ref_data.get("reference_id") or ref_data.get("id", "")
                            # file_name字段可能不存在，使用name作为file_name
                            file_name = ref_data.get("file_name") or ref_data.get("name", "")
                            references.append(ReferenceAudioInfo(
                                id=ref_id,
                                name=ref_data.get("name", ""),
                                file_name=file_name
                            ))
                        break
                
                self._references_cache[role_name] = references
                logger.info(f"[TTS Client] 角色 '{role_name}' 有 {len(references)} 个参考音频")
                return references

        except ClientError as e:
            logger.error(f"[TTS Client] 获取角色参考音频请求失败: {e}")
            return []
        except Exception as e:
            logger.exception(f"[TTS Client] 获取角色参考音频异常")
            return []

    async def submit_infer_task(
        self,
        text: str,
        role: str,
        reference: str,
        language: str = "zh",
        speed_factor: float = 1.0,
        streaming_mode: bool = False,
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
        text_split_method: str = "cut2",
        repetition_penalty: float = 1.35,
        sample_steps: int = 32,
        seed: int = -1
    ) -> TTSRequestResult:
        """
        提交推理任务
        
        Args:
            text: 要转换的文本
            role: 角色名称
            reference: 参考音频文件名
            language: 语言
            speed_factor: 语速倍数
            streaming_mode: 是否流式模式
            top_k: top_k采样
            top_p: top_p采样
            temperature: 温度参数
            text_split_method: 文本分割方法
            repetition_penalty: 重复惩罚
            sample_steps: 采样步数
            seed: 随机种子
            
        Returns:
            包含task_id的结果
        """
        try:
            url = f"{self.base_url}/infer"
            payload = {
                "role": role,
                "text": text,
                "reference": reference,
                "language": language,
                "speed_factor": speed_factor,
                "streaming_mode": streaming_mode,
                "top_k": top_k,
                "top_p": top_p,
                "temperature": temperature,
                "text_split_method": text_split_method,
                "repetition_penalty": repetition_penalty,
                "sample_steps": sample_steps,
                "seed": seed
            }
            
            logger.info(f"[TTS Client] 提交推理任务: url={url}, role={role}, reference={reference}")

            async with self.session.post(url, headers=self._get_headers(), json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[TTS Client] 提交推理任务失败: HTTP {resp.status}, {error_text}")
                    return TTSRequestResult(ok=False, error=f"HTTP {resp.status}: {error_text}", text=text)

                data = await resp.json()
                task_id = data.get("task_id")
                
                logger.info(f"[TTS Client] 提交推理任务响应: {data}")
                
                if not task_id:
                    logger.error(f"[TTS Client] 未获取到task_id, 响应: {data}")
                    return TTSRequestResult(ok=False, error=f"未获取到task_id, 响应: {data}", text=text)

                logger.info(f"[TTS Client] 获取到task_id: {task_id}")
                return TTSRequestResult(ok=True, text=text, error=task_id)  # 用error字段临时存储task_id

        except ClientError as e:
            logger.error(f"[TTS Client] 提交推理任务请求失败: {e}")
            return TTSRequestResult(ok=False, error=str(e), text=text)
        except Exception as e:
            logger.exception(f"[TTS Client] 提交推理任务异常")
            return TTSRequestResult(ok=False, error=str(e), text=text)

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务状态信息
        """
        try:
            url = f"{self.base_url}/task_status/{task_id}"
            async with self.session.get(url, headers=self._get_headers()) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[TTS Client] 获取任务状态失败: HTTP {resp.status}, {error_text}")
                    return {"status": "error", "message": error_text}

                return await resp.json()

        except ClientError as e:
            logger.error(f"[TTS Client] 获取任务状态请求失败: {e}")
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.exception(f"[TTS Client] 获取任务状态异常")
            return {"status": "error", "message": str(e)}

    async def download_audio(self, task_id: str) -> TTSRequestResult:
        """
        下载音频文件
        
        Args:
            task_id: 任务ID
            
        Returns:
            包含音频数据的结果
        """
        try:
            url = f"{self.base_url}/task_audio/{task_id}"
            async with self.session.get(url, headers=self._get_headers()) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"[TTS Client] 下载音频失败: HTTP {resp.status}, {error_text}")
                    return TTSRequestResult(ok=False, error=f"HTTP {resp.status}: {error_text}")

                data = await resp.read()
                return TTSRequestResult(ok=True, data=data)

        except ClientError as e:
            logger.error(f"[TTS Client] 下载音频请求失败: {e}")
            return TTSRequestResult(ok=False, error=str(e))
        except Exception as e:
            logger.exception(f"[TTS Client] 下载音频异常")
            return TTSRequestResult(ok=False, error=str(e))

    async def infer_and_download(
        self,
        text: str,
        role: str,
        reference: str,
        language: str = "zh",
        speed_factor: float = 1.0,
        streaming_mode: bool = False,
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
        text_split_method: str = "cut2",
        repetition_penalty: float = 1.35,
        sample_steps: int = 32,
        seed: int = -1,
        max_retries: int = 60,
        retry_interval: float = 2.0
    ) -> TTSRequestResult:
        """
        提交推理任务并等待下载音频（完整流程）
        
        Args:
            text: 要转换的文本
            role: 角色名称
            reference: 参考音频文件名
            language: 语言
            speed_factor: 语速倍数
            streaming_mode: 是否流式模式
            top_k: top_k采样
            top_p: top_p采样
            temperature: 温度参数
            text_split_method: 文本分割方法
            repetition_penalty: 重复惩罚
            sample_steps: 采样步数
            seed: 随机种子
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）
            
        Returns:
            包含音频数据的结果
        """
        import asyncio
        
        logger.info(f"[TTS Client] infer_and_download 开始: role={role}, reference={reference}")
        
        # 提交任务
        submit_result = await self.submit_infer_task(
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
        
        if not submit_result.ok:
            logger.error(f"[TTS Client] 提交任务失败: {submit_result.error}")
            return submit_result
        
        task_id = submit_result.error  # task_id存储在error字段中
        logger.info(f"[TTS Client] 任务提交成功, task_id={task_id}")
        
        # 轮询任务状态
        for i in range(max_retries):
            await asyncio.sleep(retry_interval)
            
            status = await self.get_task_status(task_id)
            status_code = status.get("status")
            
            logger.info(f"[TTS Client] 轮询任务状态 [{i+1}/{max_retries}]: {status_code}")
            
            if status_code == "completed":
                # 任务完成，下载音频
                logger.info(f"[TTS Client] 任务完成，开始下载音频")
                return await self.download_audio(task_id)
            elif status_code == "failed":
                error_msg = status.get("message", "任务执行失败")
                logger.error(f"[TTS Client] 任务失败: {error_msg}")
                return TTSRequestResult(
                    ok=False,
                    error=error_msg,
                    text=text
                )
            # 继续轮询
        
        # 超时
        logger.error(f"[TTS Client] 等待任务完成超时")
        return TTSRequestResult(
            ok=False,
            error="等待任务完成超时",
            text=text
        )
