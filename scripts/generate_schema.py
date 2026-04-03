#!/usr/bin/env python3
"""
动态生成配置schema脚本
根据API Key从TTS服务器获取角色和参考音频列表，生成组合选项
"""
import json
import os
import sys
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List

# 路径配置
BASE_DIR = Path(__file__).parent.parent
BASE_SCHEMA_PATH = BASE_DIR / "base_schema.json"
OUTPUT_SCHEMA_PATH = BASE_DIR / "_conf_schema.json"
CACHE_PATH = BASE_DIR / "data" / "roles_cache.json"
CONFIG_FILE = BASE_DIR / "config.json"

class SchemaGenerator:
    """配置schema生成器"""
    
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url or "https://benxianhenl.cn/api/proxy"
        self.api_key = api_key
        
    def log_info(self, msg: str):
        print(f"[Schema] INFO: {msg}")
    
    def log_warning(self, msg: str):
        print(f"[Schema] WARNING: {msg}")
    
    def log_error(self, msg: str):
        print(f"[Schema] ERROR: {msg}")
    
    def fetch_roles_and_refs(self) -> Dict[str, List[str]]:
        """
        从TTS服务器获取角色和参考音频列表
        
        Returns:
            字典：{角色名: [参考音频文件名1, 参考音频文件名2, ...]}
        """
        if not self.api_key:
            self.log_warning("未提供API Key，无法获取角色和参考音频列表")
            return {}
        
        url = f"{self.base_url}/roles"
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            self.log_info(f"正在请求角色和参考音频列表: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            roles_data = data.get("roles", [])
            
            # 解析角色和参考音频
            result = {}
            for role in roles_data:
                if isinstance(role, dict):
                    role_name = role.get("name", "")
                    if not role_name:
                        continue
                    
                    refs = []
                    for ref in role.get("references", []):
                        if isinstance(ref, dict):
                            file_name = ref.get("file_name", "")
                            if file_name:
                                refs.append(file_name)
                    
                    if refs:
                        result[role_name] = refs
                    else:
                        # 如果没有参考音频，至少添加角色
                        result[role_name] = []
            
            self.log_info(f"成功获取 {len(result)} 个角色")
            total_refs = sum(len(refs) for refs in result.values())
            self.log_info(f"总计 {total_refs} 个参考音频")
            return result
            
        except requests.exceptions.Timeout:
            self.log_error("请求超时，无法获取角色和参考音频列表")
            return {}
        except requests.exceptions.ConnectionError:
            self.log_error("连接错误，无法连接到TTS服务器")
            return {}
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else '未知'
            self.log_error(f"HTTP错误: {status_code}")
            if e.response and status_code == 401:
                self.log_error("API Key无效或已过期")
            return {}
        except Exception as e:
            self.log_error(f"获取角色和参考音频列表时发生未知错误: {e}")
            return {}
    
    def build_options(self, data: Dict[str, List[str]]) -> List[str]:
        """
        构建组合选项列表
        
        Args:
            data: {角色名: [参考音频文件名1, ...]}
            
        Returns:
            组合选项列表，格式: ["角色A | 音频1", "角色A | 音频2", "角色B | 音频3"]
        """
        options = []
        
        for role, audios in data.items():
            if audios:
                for audio in audios:
                    options.append(f"{role} | {audio}")
            else:
                # 如果没有参考音频，添加角色本身作为选项
                options.append(f"{role} | 默认音频")
        
        return options
    
    def load_cache(self) -> Dict:
        """加载角色缓存"""
        if CACHE_PATH.exists():
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    self.log_info(f"从缓存加载了 {len(cache_data.get('data', {}))} 个角色数据")
                    return cache_data
            except Exception as e:
                self.log_warning(f"加载缓存失败: {e}")
        return {"data": {}, "timestamp": 0}
    
    def save_cache(self, data: Dict[str, List[str]]):
        """保存角色和参考音频数据到缓存"""
        try:
            cache_data = {
                "data": data,
                "timestamp": os.path.getmtime(__file__) if data else 0
            }
            
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            self.log_info(f"已缓存 {len(data)} 个角色的数据")
        except Exception as e:
            self.log_warning(f"保存缓存失败: {e}")
    
    def get_roles_and_refs(self, use_cache: bool = True) -> Dict[str, List[str]]:
        """获取角色和参考音频数据（优先使用缓存）"""
        data = {}
        
        if not self.api_key:
            self.log_warning("未提供API Key，无法获取角色和参考音频列表")
            return {}
        
        # 先尝试从缓存加载
        if use_cache:
            cache_data = self.load_cache()
            cached_data = cache_data.get("data", {})
            
            if cached_data:
                self.log_info(f"使用缓存的 {len(cached_data)} 个角色数据")
                data = cached_data
        
        # 如果缓存为空，从API获取
        if not data:
            data = self.fetch_roles_and_refs()
            
            # 保存到缓存
            if data:
                self.save_cache(data)
        
        return data
    
    def load_config(self) -> Dict:
        """加载插件配置"""
        if not CONFIG_FILE.exists():
            return {}
        
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.log_warning(f"读取配置文件失败: {e}")
            return {}
    
    def generate_schema(self, use_cache: bool = True):
        """生成配置schema"""
        self.log_info("开始生成配置schema")
        
        # 获取角色和参考音频数据
        data = self.get_roles_and_refs(use_cache)
        
        # 构建选项
        options = self.build_options(data)
        
        # API失败 fallback
        if not options:
            self.log_warning("无法获取角色和参考音频列表，使用默认选项")
            options = ["默认角色 | 默认音频"]
        
        # 读取基础schema模板
        if not BASE_SCHEMA_PATH.exists():
            self.log_error(f"基础schema模板不存在: {BASE_SCHEMA_PATH}")
            return False
        
        try:
            with open(BASE_SCHEMA_PATH, "r", encoding="utf-8") as f:
                schema = json.load(f)
        except Exception as e:
            self.log_error(f"读取基础schema失败: {e}")
            return False
        
        # 注入选项到schema
        success = self.inject_options_to_schema(schema, options)
        if not success:
            return False
        
        # 写入最终schema
        try:
            with open(OUTPUT_SCHEMA_PATH, "w", encoding="utf-8") as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            
            self.log_info(f"已生成配置schema，包含 {len(options)} 个组合选项")
            self.log_info(f"输出文件: {OUTPUT_SCHEMA_PATH}")
            return True
            
        except Exception as e:
            self.log_error(f"写入schema失败: {e}")
            return False
    
    def inject_options_to_schema(self, schema: Dict, options: List[str]) -> bool:
        """将组合选项注入到schema中"""
        try:
            # 更新默认参数中的voice字段
            if "default_params" in schema and "items" in schema["default_params"]:
                items = schema["default_params"]["items"]
                if "voice" in items:
                    items["voice"]["options"] = options
                    items["voice"]["labels"] = options  # 使用相同的标签
                    # 更新提示信息
                    hint = f"从网站获取的角色和参考音频组合（已加载 {len(options)} 个组合，修改API Key后需重启插件刷新）"
                    items["voice"]["hint"] = hint
            
            # 更新情绪配置中的voice字段（如果有）
            if "emotion" in schema and "templates" in schema["emotion"]:
                templates = schema["emotion"]["templates"]
                if "default" in templates and "items" in templates["default"]:
                    emotion_items = templates["default"]["items"]
                    if "voice" in emotion_items:
                        emotion_items["voice"]["options"] = options
                        emotion_items["voice"]["labels"] = options
            
            return True
        except Exception as e:
            self.log_error(f"注入选项到schema失败: {e}")
            return False

def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(description="动态生成AstrBot TTS插件配置schema")
    parser.add_argument("--api-key", help="TTS服务器API Key")
    parser.add_argument("--base-url", default="https://benxianhenl.cn/api/proxy", 
                       help="TTS服务器基础URL，默认: https://benxianhenl.cn/api/proxy")
    parser.add_argument("--no-cache", action="store_true", 
                       help="不使用缓存，强制从API获取角色列表")
    
    args = parser.parse_args()
    
    # 如果没有提供API Key，尝试从插件配置获取
    api_key = args.api_key
    if not api_key:
        # 尝试从插件配置加载
        config_file = CONFIG_FILE
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    # 注意：配置中的api_key可能在client对象中
                    if "client" in config and "api_key" in config["client"]:
                        api_key = config["client"]["api_key"]
                    elif "api_key" in config:
                        api_key = config["api_key"]
            except Exception as e:
                print(f"[Schema] 读取配置文件失败: {e}")
    
    # 如果仍然没有API Key，尝试从环境变量获取
    if not api_key:
        api_key = os.environ.get("TTS_API_KEY")
    
    base_url = args.base_url or os.environ.get("TTS_BASE_URL", "https://benxianhenl.cn/api/proxy")
    
    if not api_key:
        print("错误: 未提供API Key。请通过--api-key参数或插件配置提供。")
        print("提示: 如果已配置插件，可以在插件初始化后自动运行此脚本。")
        sys.exit(1)
    
    # 创建生成器并生成schema
    generator = SchemaGenerator(base_url=base_url, api_key=api_key)
    success = generator.generate_schema(use_cache=not args.no_cache)
    
    if success:
        print("[成功] schema生成成功")
        sys.exit(0)
    else:
        print("[失败] schema生成失败")
        sys.exit(1)

if __name__ == "__main__":
    main()