#!/usr/bin/env python3
"""
简单的API测试工具，用于验证TTS服务器API连接和数据格式
"""
import json
import requests
import sys
import argparse
from typing import Dict, Any

def test_api_connection(api_key: str, base_url: str = "https://benxianhenl.cn/api/proxy"):
    """
    测试API连接并获取角色数据
    
    Args:
        api_key: API密钥
        base_url: 服务器基础URL
        
    Returns:
        是否成功，以及获取到的数据（如果成功）
    """
    url = f"{base_url}/roles"
    
    print(f"正在测试API连接...")
    print(f"URL: {url}")
    print(f"API Key: {api_key[:10]}...{api_key[-4:] if len(api_key) > 14 else ''}")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"\n发送请求到 {url}...")
        response = requests.get(url, headers=headers, timeout=30)
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"请求失败: HTTP {response.status_code}")
            print(f"响应内容: {response.text}")
            return False, None
        
        # 尝试解析JSON
        try:
            data = response.json()
            print(f"\n✅ 成功获取数据！")
            print(f"数据格式: {type(data)}")
            
            # 检查数据结构
            if isinstance(data, dict):
                print(f"数据包含的键: {list(data.keys())}")
                
                # 检查roles字段
                if "roles" in data:
                    roles_data = data["roles"]
                    print(f"找到 {len(roles_data)} 个角色")
                    
                    # 详细显示前几个角色
                    for i, role in enumerate(roles_data[:3]):  # 只显示前3个
                        print(f"\n--- 角色 {i+1} ---")
                        if isinstance(role, dict):
                            print(f"  角色名: {role.get('name', '未命名')}")
                            print(f"  角色ID: {role.get('id', '无')}")
                            
                            references = role.get('references', [])
                            print(f"  参考音频数量: {len(references)}")
                            
                            for j, ref in enumerate(references[:3]):  # 只显示前3个参考音频
                                if isinstance(ref, dict):
                                    print(f"    音频 {j+1}: {ref.get('file_name', '未命名')} (ID: {ref.get('id', '无')})")
                                else:
                                    print(f"    音频 {j+1}: 非字典类型: {type(ref)}")
                        else:
                            print(f"  角色 {i+1}: 非字典类型: {type(role)}")
                    
                    if len(roles_data) > 3:
                        print(f"\n... 还有 {len(roles_data) - 3} 个角色未显示")
                else:
                    print(f"⚠️ 数据中没有'roles'字段")
                    print(f"完整数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
            else:
                print(f"⚠️ 数据不是字典类型: {type(data)}")
                print(f"完整数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            return True, data
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            print(f"原始响应内容: {response.text[:500]}...")
            return False, None
            
    except requests.exceptions.Timeout:
        print(f"❌ 请求超时")
        return False, None
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 连接错误: {e}")
        return False, None
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        import traceback
        traceback.print_exc()
        return False, None

def test_schema_update(api_key: str, base_url: str = "https://benxianhenl.cn/api/proxy"):
    """
    测试并直接更新_conf_schema.json
    
    Args:
        api_key: API密钥
        base_url: 服务器基础URL
    """
    print("=" * 60)
    print("开始测试并更新_conf_schema.json")
    print("=" * 60)
    
    # 1. 测试API连接
    success, data = test_api_connection(api_key, base_url)
    
    if not success or not data:
        print("\n❌ API测试失败，无法更新schema")
        return False
    
    # 2. 解析数据
    roles_data = data.get("roles", [])
    if not roles_data:
        print("\n⚠️ 警告：API返回的角色列表为空")
    
    # 3. 构建选项
    options = []
    for role in roles_data:
        if isinstance(role, dict):
            role_name = role.get("name", "")
            if not role_name:
                continue
            
            references = role.get("references", [])
            if references:
                for ref in references:
                    if isinstance(ref, dict):
                        file_name = ref.get("file_name", "")
                        if file_name:
                            options.append(f"{role_name} | {file_name}")
                        else:
                            # 如果没有file_name，使用name或其他字段
                            ref_name = ref.get("name", "默认音频")
                            options.append(f"{role_name} | {ref_name}")
                    else:
                        options.append(f"{role_name} | 未知音频")
            else:
                options.append(f"{role_name} | 默认音频")
    
    if not options:
        print("\n⚠️ 警告：无法从数据中构建任何选项，使用默认选项")
        options = ["默认角色 | 默认音频"]
    
    print(f"\n✅ 成功构建 {len(options)} 个选项:")
    for i, option in enumerate(options[:10]):  # 只显示前10个
        print(f"  {i+1}. {option}")
    
    if len(options) > 10:
        print(f"  ... 还有 {len(options) - 10} 个选项未显示")
    
    # 4. 读取当前schema
    schema_path = "_conf_schema.json"
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        
        print(f"\n读取schema文件: {schema_path}")
    except Exception as e:
        print(f"\n❌ 无法读取schema文件: {e}")
        return False
    
    # 5. 更新schema
    try:
        # 更新默认参数中的voice字段
        if "default_params" in schema and "items" in schema["default_params"]:
            items = schema["default_params"]["items"]
            if "voice" in items:
                items["voice"]["options"] = options
                items["voice"]["labels"] = options
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
        
        # 写入文件
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 成功更新 {schema_path}")
        print(f"  已添加 {len(options)} 个选项到voice字段")
        
        # 显示更新后的部分内容
        print(f"\n更新后的voice字段预览:")
        if "default_params" in schema and "items" in schema["default_params"]:
            voice_field = schema["default_params"]["items"].get("voice", {})
            print(f"  描述: {voice_field.get('description', '')}")
            print(f"  提示: {voice_field.get('hint', '')}")
            print(f"  选项数量: {len(voice_field.get('options', []))}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 更新schema文件失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(description="TTS服务器API测试和schema更新工具")
    parser.add_argument("--api-key", required=True, help="TTS服务器API Key")
    parser.add_argument("--base-url", default="https://benxianhenl.cn/api/proxy", 
                       help="TTS服务器基础URL，默认: https://benxianhenl.cn/api/proxy")
    parser.add_argument("--update", action="store_true", 
                       help="直接更新_conf_schema.json文件")
    parser.add_argument("--test-only", action="