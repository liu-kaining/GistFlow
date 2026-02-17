#!/usr/bin/env python3
"""
检查 Notion 数据库属性名称
用于诊断属性名称不匹配问题
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gistflow.config import get_settings
from gistflow.core import NotionPublisher
from gistflow.utils import setup_logger, get_logger


def main() -> None:
    """检查 Notion 数据库的实际属性名称"""
    settings = get_settings()
    setup_logger(log_level=settings.LOG_LEVEL)
    logger = get_logger("check_notion_db")

    print("=" * 60)
    print("Notion 数据库属性检查工具")
    print("=" * 60)

    try:
        publisher = NotionPublisher(settings)

        # 先测试连接
        print("\n🔌 测试 Notion 连接...")
        if not publisher.test_connection():
            print("\n❌ Notion 连接失败")
            return
        
        # 获取数据库属性
        print("\n📊 正在获取数据库属性...")
        try:
            # 尝试获取数据库信息
            database = publisher.client.databases.retrieve(database_id=publisher.database_id)
            
            # 检查返回的数据结构
            print(f"   数据库对象键: {list(database.keys())}")
            
            # 尝试不同的方式获取属性
            properties = {}
            if "properties" in database:
                properties = database.get("properties", {})
            else:
                # 如果没有 properties 键，可能是权限问题或 API 版本问题
                # 尝试查询数据库页面来获取属性信息
                print("\n   ⚠️ 数据库对象中没有 'properties' 键")
                print("   尝试通过查询页面来获取属性信息...")
                
                try:
                    # 查询数据库中的页面（即使为空，也能获取 schema）
                    response = publisher.client.databases.query(database_id=publisher.database_id, page_size=1)
                    
                    # 如果查询成功，说明权限正常
                    if response:
                        print("   ✅ 可以查询数据库，权限正常")
                        # 再次尝试获取数据库信息
                        database_full = publisher.client.databases.retrieve(database_id=publisher.database_id)
                        if "properties" in database_full:
                            properties = database_full.get("properties", {})
                            print(f"   ✅ 通过重新获取找到 properties: {len(properties)} 个")
                except Exception as query_error:
                    print(f"   ⚠️ 查询数据库失败: {query_error}")
                    print("   这可能是权限问题")
            
            # 如果还是没有，尝试通过查询页面来获取 schema
            if not properties:
                print("\n   🔍 尝试通过查询数据库页面获取属性信息...")
                try:
                    # 查询数据库（即使为空）
                    response = publisher.client.databases.query(
                        database_id=publisher.database_id,
                        page_size=1
                    )
                    
                    # 如果查询成功，说明权限正常
                    print(f"   ✅ 数据库查询成功")
                    print(f"   - 结果类型: {type(response)}")
                    
                    # 再次尝试获取完整的数据库信息
                    print("\n   🔍 重新获取数据库完整信息...")
                    database_full = publisher.client.databases.retrieve(database_id=publisher.database_id)
                    
                    # 打印完整的数据库对象（用于调试）
                    import json
                    print(f"\n   完整数据库对象（调试）:")
                    db_str = json.dumps(database_full, indent=2, ensure_ascii=False, default=str)
                    # 只显示前 2000 个字符，避免输出过长
                    if len(db_str) > 2000:
                        print(db_str[:2000] + "...")
                    else:
                        print(db_str)
                    
                    # 再次检查 properties
                    if "properties" in database_full:
                        properties = database_full.get("properties", {})
                        print(f"\n   ✅ 找到 properties: {len(properties)} 个属性")
                    else:
                        print(f"\n   ⚠️ 仍然没有找到 properties 键")
                        print(f"   这可能意味着：")
                        print(f"   1. Integration 权限不足（需要 'Full access'）")
                        print(f"   2. 数据库还没有任何行/页面")
                        print(f"   3. Notion API 版本问题")
                        
                except Exception as query_error:
                    print(f"   ❌ 查询失败: {query_error}")
                    import traceback
                    traceback.print_exc()
            
            # 调试信息
            title = database.get('title', [{}])
            title_text = title[0].get('plain_text', 'Unknown') if title else 'Unknown'
            print(f"   ✅ 数据库标题: {title_text}")
            print(f"   ✅ 数据库 ID: {publisher.database_id}")
            
            # 显示数据库的完整信息（用于调试）
            print(f"\n   数据库对象类型: {database.get('object', 'unknown')}")
            print(f"   数据库 URL: https://notion.so/{publisher.database_id.replace('-', '')}")
            
            # 调试：显示完整的 properties 结构
            print(f"\n   调试信息：")
            print(f"   - properties 类型: {type(properties)}")
            print(f"   - properties 长度: {len(properties) if properties else 0}")
            
            # 尝试不同的方式获取属性
            all_keys = list(database.keys())
            print(f"   - 数据库对象的所有键: {all_keys}")
            
            if 'properties' in database:
                props = database['properties']
                print(f"   - properties 键数量: {len(props) if isinstance(props, dict) else 'N/A'}")
                if isinstance(props, dict) and props:
                    print(f"   - properties 键列表: {list(props.keys())}")
                    # 显示每个属性的详细信息
                    print(f"\n   属性详情：")
                    for key, value in props.items():
                        prop_type = value.get('type', 'unknown') if isinstance(value, dict) else type(value).__name__
                        print(f"     • {key}: {prop_type}")
            
            # 如果 properties 为空，尝试其他可能的位置
            if not properties:
                print(f"\n   ⚠️ properties 字典为空，尝试其他方式...")
                # 检查是否有其他字段包含属性信息
                for key in ['schema', 'columns', 'fields']:
                    if key in database:
                        print(f"   - 发现字段 '{key}': {type(database[key])}")
            
            if not properties:
                print("\n⚠️  警告：数据库属性为空")
                print("   这可能意味着：")
                print("   1. 数据库是新创建的，还没有添加任何属性列")
                print("   2. Integration 权限不足")
                print("   3. 这是一个页面而不是数据库")
                print("\n   请检查：")
                print("   - 在 Notion 中打开数据库，确认是否有属性列（列标题）")
                print("   - 确认这是一个 Table 视图的数据库，不是页面")
                print("   - 确认 Integration 有 'Full access' 权限")
                print("   - 确认数据库已分享给 Integration")
                print("\n   如果数据库确实有属性，但这里显示为空，")
                print("   可能是权限问题。请检查 Integration 权限设置。")
                print("\n   提示：数据库必须至少有一个 Title 类型的属性列")
                print("   （通常是第一列，显示页面标题）")
                return
        except Exception as e:
            print(f"\n❌ 错误：无法获取数据库信息")
            print(f"   错误详情: {e}")
            print("\n   请检查：")
            print("   1. NOTION_API_KEY 是否正确")
            print("   2. NOTION_DATABASE_ID 是否正确（32个字符）")
            print("   3. Integration 是否有权限访问数据库")
            print("   4. 数据库是否已分享给 Integration")
            import traceback
            traceback.print_exc()
            return

        print(f"\n✅ 找到 {len(properties)} 个属性：\n")

        # 显示所有属性及其类型
        print("当前数据库中的属性：")
        print("-" * 60)
        for prop_name, prop_info in properties.items():
            prop_type = prop_info.get("type", "unknown")
            print(f"  • {prop_name:20s} ({prop_type})")

        print("\n" + "-" * 60)
        print("\n代码期望的属性：")
        print("-" * 60)
        expected_props = {
            "Name": "Title",
            "Score": "Number",
            "Summary": "Text",
            "Tags": "Multi-select",
            "Sender": "Select",
            "Date": "Date",
            "Link": "URL",
        }

        for prop_name, prop_type in expected_props.items():
            exists = prop_name in properties
            status = "✅" if exists else "❌"
            actual_type = properties.get(prop_name, {}).get("type", "不存在")
            print(f"  {status} {prop_name:20s} ({prop_type:15s}) -> 实际: {actual_type}")

        print("\n" + "=" * 60)
        print("\n💡 解决方案：")
        print("\n如果属性名称不匹配，有两种解决方法：")
        print("\n方法 1：修改 Notion 数据库属性名称（推荐）")
        print("  1. 打开你的 Notion 数据库")
        print("  2. 点击每个属性的 '...' 菜单")
        print("  3. 选择 'Rename' 重命名为代码期望的名称")
        print("  4. 确保属性类型也匹配")
        print("\n方法 2：修改代码中的属性名称")
        print("  编辑 gistflow/core/publisher.py 中的 _build_properties 方法")
        print("  将属性名称改为你数据库中的实际名称")

        print("\n" + "=" * 60)

    except Exception as e:
        print(f"\n❌ 错误：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
