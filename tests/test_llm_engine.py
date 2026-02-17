#!/usr/bin/env python3
"""
LLM Engine test script.
Tests the GistEngine's ability to extract structured data from email content.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gistflow.config import get_settings
from gistflow.core import GistEngine
from gistflow.models import Gist
from gistflow.utils import get_logger, setup_logger


# Sample email content for testing
SAMPLE_NEWSLETTER = """
# Weekly AI Newsletter - Issue #42

## Top Stories This Week

### OpenAI Releases GPT-5 Preview
OpenAI has announced a preview of GPT-5, their next-generation language model. Key improvements include:
- 10x better reasoning capabilities
- Native multimodal understanding (text, image, audio, video)
- 1M token context window
- 50% cost reduction compared to GPT-4

### Google DeepMind's AlphaFold 3
DeepMind released AlphaFold 3, which can now predict protein interactions with small molecules. This breakthrough could accelerate drug discovery by years.

## Tools & Resources

- **LangChain v0.3**: Major update with improved agent capabilities
- **Ollama**: Run LLMs locally with one command - https://ollama.ai
- **Cursor AI**: AI-powered code editor that actually works

## Quick Links

- [OpenAI Blog](https://openai.com/blog)
- [DeepMind Paper](https://deepmind.com/research)
- [LangChain Docs](https://python.langchain.com/docs)

## Job Board

Senior ML Engineer at Anthropic - $300-500K
AI Researcher at Google DeepMind - Competitive

---

Want to unsubscribe? Click here.
Copyright 2024 AI Newsletter Inc.
"""


def test_gist_engine_dry_run() -> None:
    """Test GistEngine initialization and model info (without API call)."""
    print("\n" + "=" * 60)
    print("Testing GistEngine Initialization")
    print("=" * 60)

    try:
        settings = get_settings()
        engine = GistEngine(settings)

        # Print model info
        model_info = engine.get_model_info()
        print("\n🤖 LLM Configuration:")
        for key, value in model_info.items():
            if "key" in key.lower() or "token" in key.lower():
                print(f"  {key}: ****")
            else:
                print(f"  {key}: {value}")

        print("\n✅ GistEngine initialized successfully!")

    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        raise


def test_llm_connection() -> None:
    """Test LLM API connection."""
    print("\n" + "=" * 60)
    print("Testing LLM Connection")
    print("=" * 60)

    try:
        settings = get_settings()
        setup_logger(log_level=settings.LOG_LEVEL)

        # Check for placeholder API key
        if "sk-xxx" in settings.OPENAI_API_KEY or len(settings.OPENAI_API_KEY) < 20:
            print("\n⚠️  LLM API key not configured. Skipping connection test.")
            print("   Please update your .env file with a real API key.")
            return

        engine = GistEngine(settings)

        print("\n🔌 Testing LLM connection...")
        success = engine.test_connection()

        if success:
            print("✅ LLM connection successful!")
        else:
            print("❌ LLM connection failed!")

    except Exception as e:
        print(f"\n❌ Connection test error: {e}")
        print("\nTroubleshooting tips:")
        print("  1. Check that your API key is valid")
        print("  2. Verify the base_url is correct (especially for non-OpenAI providers)")
        print("  3. Ensure you have sufficient API credits")


def test_extract_gist() -> None:
    """Test gist extraction from sample content."""
    print("\n" + "=" * 60)
    print("Testing Gist Extraction")
    print("=" * 60)

    try:
        settings = get_settings()
        setup_logger(log_level=settings.LOG_LEVEL)
        logger = get_logger("test_llm")

        # Check for placeholder API key
        if "sk-xxx" in settings.OPENAI_API_KEY or len(settings.OPENAI_API_KEY) < 20:
            print("\n⚠️  LLM API key not configured. Skipping extraction test.")
            print("   Using fallback mode for demonstration...")

            # Create engine anyway (won't be used)
            engine = GistEngine(settings)

            # Create a mock gist to show expected output format
            mock_gist = Gist(
                title="Weekly AI Newsletter - Issue #42 (AI Optimized)",
                summary="OpenAI发布GPT-5预览版，推理能力提升10倍；DeepMind推出AlphaFold 3加速药物发现；LangChain更新至v0.3版本。",
                score=88,
                tags=["AI", "LLM", "Research", "Tools"],
                key_insights=[
                    "GPT-5带来10倍推理能力提升，支持百万token上下文",
                    "AlphaFold 3可预测蛋白质与小分子相互作用，推动药物研发",
                    "LangChain v0.3大幅改进Agent能力",
                    "多个实用AI工具发布：Ollama本地运行LLM，Cursor AI辅助编程",
                ],
                mentioned_links=[
                    "https://ollama.ai",
                    "https://openai.com/blog",
                    "https://deepmind.com/research",
                    "https://python.langchain.com/docs",
                ],
                is_spam_or_irrelevant=False,
            )

            print("\n📝 Mock Gist Output (format demonstration):")
            _print_gist(mock_gist)
            return

        # Real extraction test
        engine = GistEngine(settings)

        print("\n📧 Processing sample newsletter...")
        gist = engine.extract_gist(
            content=SAMPLE_NEWSLETTER,
            sender="AI Newsletter Team",
            subject="Weekly AI Newsletter - Issue #42",
            date="2024-05-20",
            original_id="test-email-001",
        )

        if gist:
            print("\n✅ Gist extracted successfully!")
            _print_gist(gist)
        else:
            print("\n❌ Gist extraction failed!")

    except Exception as e:
        print(f"\n❌ Extraction test error: {e}")
        raise


def test_fallback_gist() -> None:
    """Test fallback gist generation."""
    print("\n" + "=" * 60)
    print("Testing Fallback Gist Generation")
    print("=" * 60)

    try:
        settings = get_settings()
        engine = GistEngine(settings)

        print("\n🔄 Testing fallback (guaranteed valid Gist)...")

        gist = engine.extract_gist_with_fallback(
            content="This is a minimal test content.",
            sender="Test Sender",
            subject="Test Subject",
            date="2024-05-20",
            original_id="test-fallback-001",
        )

        print("\n✅ Fallback gist generated:")
        _print_gist(gist)

    except Exception as e:
        print(f"\n❌ Fallback test error: {e}")
        raise


def _print_gist(gist: Gist) -> None:
    """Pretty print a Gist object."""
    print("\n" + "-" * 40)
    print(f"📌 Title: {gist.title}")
    print(f"📊 Score: {gist.score}/100")
    print(f"🏷️  Tags: {', '.join(gist.tags)}")
    print(f"🗑️  Is Spam: {gist.is_spam_or_irrelevant}")
    print(f"\n📝 Summary:")
    print(f"   {gist.summary}")
    print(f"\n💡 Key Insights ({len(gist.key_insights)}):")
    for i, insight in enumerate(gist.key_insights, 1):
        print(f"   {i}. {insight}")
    if gist.mentioned_links:
        print(f"\n🔗 Mentioned Links ({len(gist.mentioned_links)}):")
        for link in gist.mentioned_links[:5]:  # Show first 5
            print(f"   - {link}")
    print("-" * 40)


def main() -> None:
    """Run all tests."""
    print("=" * 60)
    print("GistFlow LLM Engine Tests")
    print("=" * 60)

    # Test 1: Initialization
    test_gist_engine_dry_run()

    # Test 2: Connection
    test_llm_connection()

    # Test 3: Gist Extraction
    test_extract_gist()

    # Test 4: Fallback
    test_fallback_gist()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Configure your .env file with real LLM API key")
    print("  2. Run this script again to test real extraction")
    print("  3. Proceed to Step 4: Notion Publisher")
    print("=" * 60)


if __name__ == "__main__":
    main()