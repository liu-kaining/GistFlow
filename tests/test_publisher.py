#!/usr/bin/env python3
"""
Notion Publisher test script.
Tests the ability to create pages in Notion database.
"""

import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gistflow.config import get_settings
from gistflow.core import NotionPublisher
from gistflow.models import Gist
from gistflow.utils import get_logger, setup_logger


def create_test_gist() -> Gist:
    """Create a test Gist object for testing."""
    return Gist(
        title="[测试] GistFlow 功能验证",
        summary="这是一条测试消息，用于验证 GistFlow 的 Notion 发布功能是否正常工作。",
        score=75,
        tags=["测试", "GistFlow", "验证"],
        key_insights=[
            "GistFlow 可以成功提取邮件中的关键信息",
            "支持自动生成标签和评分",
            "内容会被格式化后存入 Notion",
        ],
        mentioned_links=[
            "https://github.com/example/gistflow",
            "https://notion.so",
        ],
        is_spam_or_irrelevant=False,
        original_id="test-email-001",
        sender="GistFlow Test",
        sender_email="test@gistflow.local",
        received_at=datetime.now(),
        original_url="https://example.com/test",
        raw_markdown="""
# 测试邮件内容

这是一封测试邮件，用于验证 GistFlow 的完整处理流程。

## 主要特性

1. **自动摘要**: AI 自动提取关键信息
2. **智能评分**: 根据内容质量打分
3. **标签分类**: 自动识别内容类型

## 技术栈

- Python 3.11+
- LangChain
- Notion API
- Gmail IMAP

---

*此邮件由 GistFlow 测试脚本生成*
""",
    )


def test_notion_connection() -> None:
    """Test Notion API connection."""
    print("\n" + "=" * 60)
    print("Testing Notion Connection")
    print("=" * 60)

    try:
        settings = get_settings()
        setup_logger(log_level=settings.LOG_LEVEL)

        # Check for placeholder values
        if "secret_xxx" in settings.NOTION_API_KEY or len(settings.NOTION_API_KEY) < 20:
            print("\n⚠️  Notion API key not configured. Skipping connection test.")
            print("   Please update your .env file with a real Notion integration key.")
            return

        if len(settings.NOTION_DATABASE_ID) < 30:
            print("\n⚠️  Notion Database ID not configured. Skipping connection test.")
            print("   Please update your .env file with your Notion database ID.")
            return

        publisher = NotionPublisher(settings)

        print("\n🔌 Testing Notion connection...")
        success = publisher.test_connection()

        if success:
            print("✅ Notion connection successful!")

            # Show database properties
            properties = publisher.get_database_properties()
            print(f"\n📊 Database Properties: {len(properties)} defined")
            for name, prop in properties.items():
                print(f"  - {name}: {prop.get('type', 'unknown')}")
        else:
            print("❌ Notion connection failed!")

    except Exception as e:
        print(f"\n❌ Connection test error: {e}")
        print("\nTroubleshooting tips:")
        print("  1. Check that your Notion integration has access to the database")
        print("  2. Share the database with your integration in Notion")
        print("  3. Verify the database ID is correct (from URL)")


def test_build_properties() -> None:
    """Test property building from Gist."""
    print("\n" + "=" * 60)
    print("Testing Property Building")
    print("=" * 60)

    try:
        settings = get_settings()
        publisher = NotionPublisher(settings)
        gist = create_test_gist()

        properties = publisher._build_properties(gist)

        print("\n📦 Built Properties:")
        for key, value in properties.items():
            if key == "Summary":
                print(f"  {key}: {value['rich_text'][0]['text']['content'][:50]}...")
            elif key == "Tags":
                tags = [t['name'] for t in value['multi_select']]
                print(f"  {key}: {tags}")
            else:
                print(f"  {key}: {value}")

        print("\n✅ Property building test passed!")

    except Exception as e:
        print(f"\n❌ Property building test error: {e}")


def test_build_content_blocks() -> None:
    """Test content block generation."""
    print("\n" + "=" * 60)
    print("Testing Content Block Generation")
    print("=" * 60)

    try:
        settings = get_settings()
        publisher = NotionPublisher(settings)
        gist = create_test_gist()

        blocks = publisher._build_content_blocks(gist)

        print(f"\n📝 Generated {len(blocks)} content blocks:")
        for i, block in enumerate(blocks, 1):
            block_type = block.get("type", "unknown")
            print(f"  {i}. {block_type}")

        print("\n✅ Content block generation test passed!")

    except Exception as e:
        print(f"\n❌ Content block generation test error: {e}")


def test_full_publish() -> None:
    """Test full publishing workflow (creates real page)."""
    print("\n" + "=" * 60)
    print("Testing Full Publish Workflow")
    print("=" * 60)

    try:
        settings = get_settings()
        setup_logger(log_level=settings.LOG_LEVEL)
        logger = get_logger("test_publisher")

        # Check for placeholder values
        if "secret_xxx" in settings.NOTION_API_KEY or len(settings.NOTION_API_KEY) < 20:
            print("\n⚠️  Notion API key not configured. Skipping full publish test.")
            print("   Please update your .env file with real credentials.")
            _show_mock_result()
            return

        if len(settings.NOTION_DATABASE_ID) < 30:
            print("\n⚠️  Notion Database ID not configured. Skipping full publish test.")
            _show_mock_result()
            return

        publisher = NotionPublisher(settings)
        gist = create_test_gist()

        print("\n🚀 Publishing test Gist to Notion...")
        print(f"  Title: {gist.title}")
        print(f"  Score: {gist.score}")
        print(f"  Tags: {gist.tags}")

        page_id = publisher.push(gist)

        if page_id:
            print(f"\n✅ Successfully published to Notion!")
            print(f"  Page ID: {page_id}")
            print(f"\n  View at: https://notion.so/{page_id.replace('-', '')}")
        else:
            print("\n❌ Failed to publish Gist")

    except Exception as e:
        print(f"\n❌ Full publish test error: {e}")
        raise


def _show_mock_result() -> None:
    """Show mock result for unconfigured tests."""
    print("\n📋 Expected output (when configured):")
    print("=" * 40)
    print("✅ Successfully published to Notion!")
    print("  Page ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    print()
    print("  Page contents:")
    print("  - 💡 Key Insights (callout)")
    print("  - ─── (divider)")
    print("  - 📎 相关链接 (heading)")
    print("  - ─── (divider)")
    print("  - 📄 原文内容 (toggle)")
    print("  - ─── (divider)")
    print("  - Metadata footer")
    print("=" * 40)


def test_spam_filtering() -> None:
    """Test that spam/irrelevant emails are filtered."""
    print("\n" + "=" * 60)
    print("Testing Spam Filtering")
    print("=" * 60)

    try:
        settings = get_settings()
        publisher = NotionPublisher(settings)

        # Test spam gist
        spam_gist = Gist(
            title="Buy Now! Limited Offer!!!",
            summary="This is spam content.",
            score=10,
            tags=["spam"],
            key_insights=[],
            mentioned_links=[],
            is_spam_or_irrelevant=True,
        )

        result = publisher.push(spam_gist)
        print(f"\n  Spam gist publish result: {result}")
        assert result is None, "Spam should return None"
        print("  ✅ Spam correctly filtered")

        # Test low-value gist
        low_value_gist = Gist(
            title="Low Value Content",
            summary="This has low value.",
            score=20,
            tags=["low-value"],
            key_insights=["Not much here"],
            mentioned_links=[],
            is_spam_or_irrelevant=False,
        )

        result = publisher.push(low_value_gist)
        print(f"\n  Low-value gist publish result: {result}")
        assert result is None, "Low-value should return None"
        print("  ✅ Low-value content correctly filtered")

        print("\n✅ Spam filtering test passed!")

    except Exception as e:
        print(f"\n❌ Spam filtering test error: {e}")


def main() -> None:
    """Run all tests."""
    print("=" * 60)
    print("GistFlow Notion Publisher Tests")
    print("=" * 60)

    # Test 1: Connection
    test_notion_connection()

    # Test 2: Property building
    test_build_properties()

    # Test 3: Content blocks
    test_build_content_blocks()

    # Test 4: Spam filtering
    test_spam_filtering()

    # Test 5: Full publish (requires real credentials)
    test_full_publish()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
    print("\nNotion Database Setup Checklist:")
    print("  □ Create a new database in Notion")
    print("  □ Add properties with correct names and types:")
    print("    - Name (Title)")
    print("    - Score (Number)")
    print("    - Summary (Text)")
    print("    - Tags (Multi-select)")
    print("    - Sender (Select)")
    print("    - Date (Date)")
    print("    - Link (URL)")
    print("  □ Create integration at https://www.notion.so/my-integrations")
    print("  □ Share database with the integration")
    print("  □ Copy database ID to .env")
    print("=" * 60)


if __name__ == "__main__":
    main()