#!/usr/bin/env python3
"""
动态生成配置schema脚本
根据API Key从TTS服务器获取角色列表，并注入到配置schema中
"""
import json
import os
import sys
import argparse
import requests
from pathlib import Path
from typing import Optional, List, Dict

# 路径配置
BASE_DIR = Path(__file__).parent.parent
BASE_SCHEMA_PATH = BASE_DIR / "base_schema.json"
OUTPUT_SCHEMA_PATH = BASE_DIR / "_conf_schema.json"
CACHE_PATH = BASE_DIR / "data" / "roles_cache.json"

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
    
    def fetch_roles(self) -> List[str]:
        """
        从TTS服务器获取角色列表
        
        Returns:
            角色名称列表
        """
        if not self.api_key:
            self.log_warning("未提供API Key，无法获取角色列表")
            return []
        
        url = f"{self.base_url}/roles"
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            self.log_info(f"正在请求角色列表: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            roles_data = data.get("roles", [])
            
            # 提取角色名称
            role_names = []
            for role in roles_data:
                if isinstance(role, dict):
                    role_name = role.get("name", "")
                    if role_name:
                        role_names.append(role_name)
                elif isinstance(role, str):
                    role_names.append(role)
            
            self.log_info(f"成功获取 {len(role_names)} 个角色")
            return role_names
            
        except requests.exceptions.Timeout:
            self.log_error("请求超时，无法获取角色列表")
            return []
        except requests.exceptions.ConnectionError:
            self.log_error("连接错误，无法连接到TTS服务器")
            return []
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else '未知'
            self.log_error(f"HTTP错误: {status_code}")
            if e.response and status_code == 401:
                self.log_error("API Key无效或已过期")
            return []
        except Exception as e:
            self.log_error(f"获取角色列表时发生未知错误: {e}")
            return []
    
    def load_cache(self) -> Dict:
        """加载角色缓存"""
        if CACHE_PATH.exists():
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    self.log_info(f"从缓存加载了 {len(cache_data.get('roles', []))} 个角色")
                    return cache_data
            except Exception as e:
                self.log_warning(f"加载缓存失败: {e}")
        return {"roles": [], "timestamp": 0}
    
    def save_cache(self, roles: List[str]):
        """保存角色到缓存"""
        try:
            cache_data = {
                "roles": roles,
                "timestamp": os.path.getmtime(__file__) if roles else 0
            }
            
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            self.log_info(f"已缓存 {len(roles)} 个角色")
        except Exception as e:
            self.log_warning(f"保存缓存失败: {e}")
    
    def get_roles(self, use_cache: bool = True) -> List[str]:
        """获取角色列表（优先使用缓存）"""
        roles = []
        
        if not self.api_key:
            self.log_warning("未提供API Key，无法获取角色列表")
            return []
        
        # 先尝试从缓存加载
        if use_cache:
            cache_data = self.load_cache()
            cached_roles = cache_data.get("roles", [])
            
            if cached_roles:
                self.log_info(f"使用缓存的 {len(cached_roles)} 个角色")
                roles = cached_roles
        
        # 如果缓存为空，从API获取
        if not roles:
            roles = self.fetch_roles()
            
            # 保存到缓存
            if roles:
                self.save_cache(roles)
        
        return roles
    
    def generate_schema(self, roles: Optional[List[str]] = None):
        """生成配置schema"""
        self.log_info("开始生成配置schema")
        
        # 获取角色列表
        if roles is None:
            roles = self.get_roles()
        
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
        
        # 注入角色到schema
        self.inject_roles_to_schema(schema, roles)
        
        # 写入最终schema
        try:
            with open(OUTPUT_SCHEMA_PATH, "w", encoding="utf-8") as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            
            self.log_info(f"已生成配置schema，包含 {len(roles)} 个角色")
            self.log_info(f"输出文件: {OUTPUT_SCHEMA_PATH}")
            return True
            
        except Exception as e:
            self.log_error(f"写入schema失败: {e}")
            return False
    
    def inject_roles_to_schema(self, schema: Dict, roles: List[str]):
        """将角色列表注入到schema中"""
        # 更新主角色字段
        if "default_params" in schema and "items" in schema["default_params"]:
            items = schema["default_params"]["items"]
            if "role" in items:
                items["role"]["options"] = roles
                items["role"]["labels"] = roles  # 使用相同的标签
                # 更新提示信息
                hint = f"从网站获取的角色名称（已加载 {len(roles)} 个角色，修改API Key后需重启插件刷新）"
                items["role"]["hint"] = hint
        
        # 更新情绪配置中的角色字段（如果有）
        if "emotion" in schema and "templates" in schema["emotion"]:
            templates = schema["emotion"]["templates"]
            if "default" in templates and "items" in templates["default"]:
                emotion_items = templates["default"]["items"]
                if "role" in emotion_items:
                    emotion_items["role"]["options"] = roles
                    emotion_items["role"]["labels"] = roles

def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(description="动态生成AstrBot TTS插件配置schema")
    parser.add_argument("--api-key", help="TTS服务器API Key")
    parser.add_argument("--base-url", default="https://benxianhenl.cn/api/proxy", 
                       help="TTS服务器基础URL，默认: https://benxianhenl.cn/api/proxy")
    parser.add_argument("--no-cache", action="store_true", 
                       help="不使用缓存，强制从API获取角色列表")
    
    args = parser.parse_args()
    
    # 如果没有提供API Key，尝试从环境变量获取
    api_key = args.api_key or os.environ.get("TTS_API_KEY")
    base_url = args.base_url or os.environ.get("TTS_BASE_URL", "https://benxianhenl.cn/api/proxy")
    
    if not api_key:
        print("错误: 未提供API Key。请通过--api-key参数或TTS_API_KEY环境变量提供。")
        print("提示: 如果已配置插件，可以在插件初始化后自动运行此脚本。")
        sys.exit(1)
    
    # 创建生成器并生成schema
    generator = SchemaGenerator(base_url=base_url, api_key=api_key)
    success = generator.generate_schema()
    
    if success:
        print("✅ schema生成成功")
        sys.exit(0)
    else:
        print("❌ schema生成失败")
        sys.exit(1)

if __name__ == "__main__":
    main()