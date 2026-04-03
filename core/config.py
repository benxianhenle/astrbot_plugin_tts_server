"""
配置管理
"""
from __future__ import annotations

import re
import sys
from pathlib import Path, PureWindowsPath
from typing import Any, Union, get_args, get_origin, get_type_hints

# Python 3.10+ 支持 UnionType，低版本需要回退
if sys.version_info >= (3, 10):
    from types import UnionType
else:
    # 对于 Python 3.9 及以下版本，使用 typing.Union 作为替代
    UnionType = type(Union)

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context
from astrbot.core.star.star_tools import StarTools
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_path


class ConfigNode:
    """
    配置节点, 把 dict 变成强类型对象。
    """

    _SCHEMA_CACHE: dict[type, dict[str, type]] = {}
    _FIELDS_CACHE: dict[type, set[str]] = {}

    @classmethod
    def _schema(cls) -> dict[str, type]:
        return cls._SCHEMA_CACHE.setdefault(cls, get_type_hints(cls))

    @classmethod
    def _fields(cls) -> set[str]:
        return cls._FIELDS_CACHE.setdefault(
            cls,
            {k for k in cls._schema() if not k.startswith("_")},
        )

    @staticmethod
    def _is_optional(tp: type) -> bool:
        if get_origin(tp) in (Union, UnionType):
            return type(None) in get_args(tp)
        return False

    def __init__(self, data: dict[str, Any]):
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_children", {})
        for key, tp in self._schema().items():
            if key.startswith("_"):
                continue
            if key in data:
                continue
            if hasattr(self.__class__, key):
                continue
            if self._is_optional(tp):
                continue
            logger.warning(f"[config:{self.__class__.__name__}] 缺少字段: {key}")

    def __getattr__(self, key: str) -> Any:
        if key in self._fields():
            value = self._data.get(key)
            tp = self._schema().get(key)

            if isinstance(tp, type) and issubclass(tp, ConfigNode):
                children: dict[str, ConfigNode] = self.__dict__["_children"]
                if key not in children:
                    if not isinstance(value, dict):
                        raise TypeError(
                            f"[config:{self.__class__.__name__}] "
                            f"字段 {key} 期望 dict，实际是 {type(value).__name__}"
                        )
                    children[key] = tp(value)
                return children[key]

            return value

        if key in self.__dict__:
            return self.__dict__[key]

        raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self._fields():
            self._data[key] = value
            return
        object.__setattr__(self, key, value)

    def raw_data(self) -> dict[str, Any]:
        """底层配置 dict"""
        return self._data


class AutoConfig(ConfigNode):
    only_llm_result: bool
    tts_prob: float
    max_msg_len: int


class ClientConfig(ConfigNode):
    base_url: str
    api_key: str
    timeout: int


class DefaultParamsConfig(ConfigNode):
    voice: str
    language: str
    speed_factor: float
    streaming_mode: bool


class AdvancedParamsConfig(ConfigNode):
    top_k: int
    top_p: float
    temperature: float
    text_split_method: str
    repetition_penalty: float
    sample_steps: int
    seed: int


class CacheConfig(ConfigNode):
    enabled: bool
    expire_hours: int
    path: str


class PluginConfig(ConfigNode):
    enabled: bool
    auto: AutoConfig
    client: ClientConfig
    default_params: DefaultParamsConfig
    advanced_params: AdvancedParamsConfig
    cache: CacheConfig
    emotion: list[dict[str, Any]]

    _plugin_name: str = "astrbot_plugin_tts_server"

    def __init__(self, cfg: AstrBotConfig, context: Context):
        super().__init__(cfg)
        self.context = context

        # 确保advanced_params存在（向后兼容）
        if "advanced_params" not in self._data:
            self._data["advanced_params"] = {}
        
        # 为advanced_params设置默认值（向后兼容）
        advanced_params_data = self._data["advanced_params"]
        advanced_defaults = {
            "top_k": 15,
            "top_p": 1.0,
            "temperature": 1.0,
            "text_split_method": "cut2",
            "repetition_penalty": 1.35,
            "sample_steps": 32,
            "seed": -1
        }
        for key, default_value in advanced_defaults.items():
            if key not in advanced_params_data:
                advanced_params_data[key] = default_value
        
        # 确保default_params中有streaming_mode（向后兼容）
        default_params_data = self._data.get("default_params", {})
        if "streaming_mode" not in default_params_data:
            default_params_data["streaming_mode"] = False
            self._data["default_params"] = default_params_data

        self.data_dir = StarTools.get_data_dir(self._plugin_name)
        self.plugin_dir = Path(get_astrbot_plugin_path()) / self._plugin_name

        # 规范化缓存路径
        self.cache.path = self.normalize_path(self.cache.path)

        self.audio_dir = (
            Path(self.cache.path) if self.cache.path else self.data_dir / "audio"
        )
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalize_path(p: str) -> str:
        """规范化路径"""
        if not p:
            return p
        path_text = p.strip()
        if not path_text:
            return path_text

        match = re.search(r"([A-Za-z]:[\\/].*)$", path_text)
        if match and PureWindowsPath(match.group(1)).is_absolute():
            return match.group(1)

        if PureWindowsPath(path_text).is_absolute():
            return path_text

        path = Path(path_text).expanduser()
        if path.is_absolute():
            return str(path)
        return str(path.resolve())
