#!/usr/bin/env python3
"""
简单粗暴的API测试和配置更新脚本
直接获取角色和参考音频，更新_conf_schema.json

使用方法:
1. 命令行参数: python test_and_update.py --api-key YOUR_KEY --base-url https://benxianhenl.cn/api/proxy
2. 配置文件: python test_and_update.py --config config.json
3. 交互模式: python test_and_update.py (会提示输入API信息)
"""
import json
import requests
import os
import sys
import argparse

def test_api(api_key, base_url):
    """测试API连接并获取数据"""
    print(f"测试API连接...")
    print(f"API地址: {base_url}")
    print(f"API Key: {api_key[:10]}...{api_key[-5:] if len(api_key) > 15 else ''}")
    
    url = f"{base_url}/roles"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"发送请求到: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"[成功] API连接成功！状态码: {response.status_code}")
        
        return data
        
    except requests.exceptions.Timeout:
        print("[失败] 请求超时，无法连接到服务器")
        return None
    except requests.exceptions.ConnectionError:
        print("[失败] 连接错误，无法连接到服务器")
        return None
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else '未知'
        print(f"[失败] HTTP错误: {status_code}")
        if e.response and status_code == 401:
            print("[失败] API Key无效或已过期")
        return None
    except Exception as e:
        print(f"[失败] 未知错误: {e}")
        return None

def load_config_from_file(config_path):
    """从配置文件加载API配置"""
    try:
        if not os.path.exists(config_path):
            print(f"[失败] 配置文件不存在: {config_path}")
            return None, None
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # 尝试从不同位置获取API Key和base_url
        api_key = None
        base_url = None
        
        # 1. 尝试从client对象获取
        if "client" in config:
            client_config = config["client"]
            api_key = client_config.get("api_key", "")
            base_url = client_config.get("base_url", "https://benxianhenl.cn/api/proxy")
        
        # 2. 尝试直接从根获取
        if not api_key:
            api_key = config.get("api_key", "")
        
        if not base_url:
            base_url = config.get("base_url", "https://benxianhenl.cn/api/proxy")
        
        if api_key:
            print(f"[成功] 从配置文件加载API配置")
            print(f"  API Key: {api_key[:10]}...{api_key[-5:] if len(api_key) > 15 else ''}")
            print(f"  Base URL: {base_url}")
            return api_key, base_url
        else:
            print("[失败] 配置文件中未找到API Key")
            return None, None
            
    except Exception as e:
        print(f"[失败] 读取配置文件失败: {e}")
        return None, None

def parse_roles_and_refs(data):
    """解析角色和参考音频数据"""
    if not data:
        return {}
    
    roles_data = data.get("roles", [])
    print(f"找到 {len(roles_data)} 个角色")
    
    result = {}
    for role in roles_data:
        if isinstance(role, dict):
            # 实际API返回的是role_name字段
            role_name = role.get("role_name", "")
            if not role_name:
                # 如果没有role_name，尝试name字段
                role_name = role.get("name", "")
                if not role_name:
                    print(f"  [!] 角色数据缺少name/role_name字段: {role}")
                    continue
            
            refs = []
            for ref in role.get("references", []):
                if isinstance(ref, dict):
                    # 实际API返回的是name字段
                    file_name = ref.get("name", "")
                    if file_name:
                        refs.append(file_name)
            
            if refs:
                result[role_name] = refs
                print(f"  [+] {role_name}: {len(refs)} 个参考音频")
                for i, ref in enumerate(refs):
                    print(f"      {i+1}. {ref[:50]}..." if len(ref) > 50 else f"      {i+1}. {ref}")
            else:
                result[role_name] = []
                print(f"  [!] {role_name}: 无参考音频")
    
    return result

def build_options(data):
    """构建选项列表：角色 | 参考音频文件名"""
    options = []
    
    for role, audios in data.items():
        if audios:
            for audio in audios:
                options.append(f"{role} | {audio}")
        else:
            options.append(f"{role} | 默认音频")
    
    print(f"共生成 {len(options)} 个选项")
    return options

def update_schema_file(options):
    """直接更新_conf_schema.json文件"""
    schema_file = "_conf_schema.json"
    
    if not os.path.exists(schema_file):
        print(f"[失败] 找不到schema文件: {schema_file}")
        return False
    
    try:
        # 读取现有schema
        with open(schema_file, "r", encoding="utf-8") as f:
            schema = json.load(f)
        
        print(f"读取schema文件成功")
        
        # 更新voice字段
        if "default_params" in schema and "items" in schema["default_params"]:
            items = schema["default_params"]["items"]
            if "voice" in items:
                items["voice"]["options"] = options
                items["voice"]["labels"] = options
                hint = f"从网站获取的角色和参考音频组合（已加载 {len(options)} 个组合，修改API Key后需重启插件刷新）"
                items["voice"]["hint"] = hint
                print(f"更新了default_params中的voice字段")
        
        # 更新情绪配置中的voice字段
        if "emotion" in schema and "templates" in schema["emotion"]:
            templates = schema["emotion"]["templates"]
            if "default" in templates and "items" in templates["default"]:
                emotion_items = templates["default"]["items"]
                if "voice" in emotion_items:
                    emotion_items["voice"]["options"] = options
                    emotion_items["voice"]["labels"] = options
                    print(f"更新了emotion中的voice字段")
        
        # 写回文件
        with open(schema_file, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        
        print(f"[成功] 成功更新 {schema_file}")
        return True
        
    except Exception as e:
        print(f"[失败] 更新schema文件失败: {e}")
        return False

def main():
    """主函数 - 解析命令行参数并执行更新"""
    parser = argparse.ArgumentParser(
        description="简单粗暴的TTS插件配置更新工具 - 动态获取角色和参考音频并更新配置文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 1. 使用命令行参数
  python test_and_update.py --api-key "your-api-key" --base-url "https://benxianhenl.cn/api/proxy"
  
  # 2. 使用配置文件
  python test_and_update.py --config config.json
  
  # 3. 从插件配置读取
  python test_and_update.py --plugin-config
  
  # 4. 交互模式 (会提示输入)
  python test_and_update.py
  
默认base_url: https://benxianhenl.cn/api/proxy
        """
    )
    
    parser.add_argument("--api-key", help="TTS服务器API Key")
    parser.add_argument("--base-url", default="https://benxianhenl.cn/api/proxy", 
                       help="TTS服务器基础URL (默认: https://benxianhenl.cn/api/proxy)")
    parser.add_argument("--config", help="配置文件路径 (JSON格式)")
    parser.add_argument("--plugin-config", action="store_true", 
                       help="从插件配置文件读取API配置")
    parser.add_argument("--quiet", action="store_true", 
                       help="安静模式，只输出关键信息")
    
    args = parser.parse_args()
    
    # 初始化变量
    api_key = None
    base_url = args.base_url
    
    print("=" * 50)
    print("简单粗暴的TTS插件配置更新工具")
    print("=" * 50)
    
    # 1. 确定API Key来源
    if args.api_key:
        # 从命令行参数获取
        api_key = args.api_key
        print(f"[信息] 使用命令行参数提供的API Key")
        
    elif args.config:
        # 从配置文件获取
        print(f"[信息] 从配置文件读取: {args.config}")
        api_key, config_base_url = load_config_from_file(args.config)
        if config_base_url:
            base_url = config_base_url
            
    elif args.plugin_config:
        # 从插件配置文件获取
        print(f"[信息] 从插件配置文件读取")
        # 尝试查找插件配置文件
        config_files = ["config.json", "../config.json", "data/config.json"]
        for config_file in config_files:
            if os.path.exists(config_file):
                api_key, config_base_url = load_config_from_file(config_file)
                if api_key:
                    if config_base_url:
                        base_url = config_base_url
                    break
        
        if not api_key:
            print("[失败] 未找到插件配置文件或其中没有API Key")
            return
    
    else:
        # 交互模式：提示用户输入
        print("[信息] 进入交互模式")
        print(f"Base URL (按Enter使用默认值: {base_url}): ")
        user_input = input().strip()
        if user_input:
            base_url = user_input
        
        print("请输入API Key (输入后按Enter): ")
        api_key = input().strip()
    
    # 2. 验证API Key
    if not api_key:
        print("[失败] 未提供API Key，请通过以下方式之一提供:")
        print("  1. --api-key 参数")
        print("  2. --config 配置文件")
        print("  3. --plugin-config 从插件配置读取")
        print("  4. 交互模式输入")
        return
    
    if args.quiet:
        print(f"[信息] API Key: {api_key[:10]}...{api_key[-5:] if len(api_key) > 15 else ''}")
        print(f"[信息] Base URL: {base_url}")
    else:
        print(f"[信息] 使用配置:")
        print(f"  Base URL: {base_url}")
        print(f"  API Key: {api_key[:10]}...{api_key[-5:] if len(api_key) > 15 else ''}")
    
    # 3. 测试API连接
    data = test_api(api_key, base_url)
    if not data:
        print("[失败] API测试失败，退出")
        return
    
    # 显示原始数据（前500字符）
    if not args.quiet:
        data_str = json.dumps(data, ensure_ascii=False)
        print(f"\n原始响应数据（前500字符）:")
        print(data_str[:500] + ("..." if len(data_str) > 500 else ""))
    
    # 4. 解析数据
    print(f"\n解析角色和参考音频...")
    roles_data = parse_roles_and_refs(data)
    
    if not roles_data:
        print("[失败] 没有找到角色数据")
        return
    
    # 5. 构建选项
    print(f"\n构建选项列表...")
    options = build_options(roles_data)
    
    # 显示前几个选项
    if not args.quiet:
        print(f"\n前5个选项示例:")
        for i, option in enumerate(options[:5]):
            print(f"  {i+1}. {option}")
        if len(options) > 5:
            print(f"  ... 还有 {len(options)-5} 个选项")
    
    # 6. 更新schema文件
    print(f"\n更新配置文件...")
    success = update_schema_file(options)
    
    if success:
        print(f"\n[成功] 完成！")
        print(f"  1. 已在 {len(options)} 个选项")
        print(f"  2. 配置文件已更新")
        print(f"  3. 请重启AstrBot插件以生效")
    else:
        print(f"\n[失败] 更新失败")

if __name__ == "__main__":
    main()