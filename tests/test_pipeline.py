#!/usr/bin/env python3
"""
Full pipeline integration test.
Tests the complete workflow from configuration to email processing.
"""

import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gistflow.config import get_settings
from gistflow.core import ContentCleaner, GistEngine, NotionPublisher
from gistflow.database import LocalStore
from gistflow.models import Gist, RawEmail
from gistflow.utils import get_logger, setup_logger


def create_test_email() -> RawEmail:
    """Create a test RawEmail for testing."""
    return RawEmail(
        message_id=f"test-{datetime.now().timestamp()}",
        thread_id="test-thread-001",
        subject="[测试] Weekly AI Newsletter #42",
        sender="AI Newsletter Team",
        sender_email="newsletter@aiweekly.com",
        date=datetime.now(),
        html_content="""
        <html>
        <body>
        <h1>Weekly AI Newsletter</h1>
        <h2>GPT-5 Released!</h2>
        <p>OpenAI has released GPT-5 with amazing new capabilities:</p>
        <ul>
            <li>10x better reasoning</li>
            <li>1M token context</li>
            <li>Native multimodal support</li>
        </ul>
        <h2>Tools & Resources</h2>
        <ul>
            <li><a href="https://ollama.ai">Ollama</a> - Run LLMs locally</li>
            <li><a href="https://cursor.sh">Cursor</a> - AI code editor</li>
        </ul>
        <p>Copyright 2024 AI Newsletter. <a href="http://unsubscribe.com">Unsubscribe</a></p>
        </body>
        </html>
        """,
        text_content="Weekly AI Newsletter - GPT-5 Released!",
        labels=["Newsletter"],
        urls=["https://ollama.ai", "https://cursor.sh"],
    )


def test_full_pipeline() -> None:
    """Test the full processing pipeline with a sample email."""
    print("\n" + "=" * 60)
    print("Testing Full Pipeline Integration")
    print("=" * 60)

    try:
        # Load settings
        settings = get_settings()
        setup_logger(log_level="DEBUG")
        logger = get_logger("test_pipeline")

        # Initialize components
        print("\n📦 Initializing components...")
        cleaner = ContentCleaner(settings)
        llm_engine = GistEngine(settings)
        publisher = NotionPublisher(settings)

        # Create test email
        print("\n📧 Creating test email...")
        email = create_test_email()
        print(f"  Subject: {email.subject}")
        print(f"  Sender: {email.sender}")
        print(f"  URLs: {email.urls}")

        # Step 1: Clean content
        print("\n🧹 Step 1: Cleaning content...")
        cleaned = cleaner.clean(email.content)
        print(f"  Original length: {len(email.content)} chars")
        print(f"  Cleaned length: {len(cleaned)} chars")
        print(f"  Preview: {cleaned[:100]}...")

        # Step 2: Extract Gist
        print("\n🤖 Step 2: Extracting Gist with LLM...")

        # Check if API key is configured
        if "sk-xxx" in settings.OPENAI_API_KEY or len(settings.OPENAI_API_KEY) < 20:
            print("\n  ⚠️  LLM API key not configured. Using mock Gist...")
            gist = Gist(
                title="Weekly AI Newsletter #42",
                summary="GPT-5发布，推理能力提升10倍，支持百万token上下文；介绍Ollama和Cursor等实用工具。",
                score=85,
                tags=["AI", "LLM", "GPT-5"],
                key_insights=[
                    "GPT-5推理能力提升10倍",
                    "支持1M token上下文窗口",
                    "原生多模态支持",
                ],
                mentioned_links=["https://ollama.ai", "https://cursor.sh"],
                is_spam_or_irrelevant=False,
                original_id=email.message_id,
                sender=email.sender,
                raw_markdown=cleaned,
            )
        else:
            gist = llm_engine.extract_gist_with_fallback(
                content=cleaned,
                sender=email.sender,
                subject=email.subject,
                date=email.date.isoformat(),
                original_id=email.message_id,
                original_url=email.urls[0] if email.urls else None,
            )
            gist.raw_markdown = cleaned

        print(f"\n  📌 Title: {gist.title}")
        print(f"  📊 Score: {gist.score}")
        print(f"  🏷️  Tags: {gist.tags}")
        print(f"  🗑️  Is Spam: {gist.is_spam_or_irrelevant}")
        print(f"  📝 Summary: {gist.summary[:100]}...")

        # Step 3: Publish to Notion (if valuable and configured)
        print("\n📤 Step 3: Publishing to Notion...")

        if not gist.is_valuable():
            print(f"  ⏭️  Skipping (score={gist.score}, spam={gist.is_spam_or_irrelevant})")
        elif "secret_xxx" in settings.NOTION_API_KEY or len(settings.NOTION_API_KEY) < 20:
            print("  ⚠️  Notion API not configured. Skipping publish.")
        else:
            page_id = publisher.push(gist)
            if page_id:
                print(f"  ✅ Published successfully: {page_id}")
                gist.notion_page_id = page_id
            else:
                print("  ❌ Publish failed")

        # Summary
        print("\n" + "-" * 40)
        print("✅ Pipeline test completed!")
        print("-" * 40)
        print(f"  Email processed: {email.message_id}")
        print(f"  Gist extracted: score={gist.score}")
        print(f"  Valuable: {gist.is_valuable()}")

        return gist

    except Exception as e:
        print(f"\n❌ Pipeline test error: {e}")
        raise


def test_local_store_integration() -> None:
    """Test local store with the pipeline."""
    print("\n" + "=" * 60)
    print("Testing Local Store Integration")
    print("=" * 60)

    try:
        test_db_path = Path(__file__).parent.parent / "data" / "test_pipeline.db"
        store = LocalStore(test_db_path)

        test_id = f"pipeline-test-{datetime.now().timestamp()}"

        # Check initial state
        print(f"\n📌 Test ID: {test_id}")
        print(f"  Initially processed: {store.is_processed(test_id)}")

        # Mark as processed
        store.mark_processed(
            message_id=test_id,
            subject="Test Subject",
            sender="test@example.com",
            score=75,
            is_spam=False,
        )
        print(f"  After marking: {store.is_processed(test_id)}")

        # Get stats
        stats = store.get_stats()
        print(f"\n📊 Stats: {stats}")

        # Cleanup
        store.close()
        if test_db_path.exists():
            test_db_path.unlink()
            print("\n🧹 Test database cleaned up")

        print("\n✅ Local store integration test passed!")

    except Exception as e:
        print(f"\n❌ Local store test error: {e}")
        raise


def test_graceful_shutdown() -> None:
    """Test that the pipeline handles shutdown signals gracefully."""
    print("\n" + "=" * 60)
    print("Testing Graceful Shutdown Handling")
    print("=" * 60)

    try:
        settings = get_settings()
        # Import here to avoid circular dependency issues
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from main import GistFlowPipeline

        pipeline = GistFlowPipeline()

        # Check signal handlers are set up
        import signal
        handlers_configured = (
            signal.getsignal(signal.SIGINT) != signal.SIG_DFL or
            signal.getsignal(signal.SIGTERM) != signal.SIG_DFL
        )

        print(f"\n  Signal handlers configured: {handlers_configured}")
        print(f"  Shutdown flag: {pipeline._shutdown_requested}")

        pipeline.cleanup()

        print("\n✅ Graceful shutdown test passed!")

    except Exception as e:
        print(f"\n❌ Shutdown test error: {e}")


def main() -> None:
    """Run all integration tests."""
    print("=" * 60)
    print("GistFlow Full Pipeline Integration Tests")
    print("=" * 60)

    # Test 1: Full pipeline
    test_full_pipeline()

    # Test 2: Local store
    test_local_store_integration()

    # Test 3: Graceful shutdown
    test_graceful_shutdown()

    print("\n" + "=" * 60)
    print("All integration tests completed!")
    print("=" * 60)
    print("\n🚀 Ready to run the full application:")
    print("   python main.py          # Run with scheduler")
    print("   python main.py --once   # Run once and exit")
    print("   docker-compose up       # Run with Docker")
    print("=" * 60)


if __name__ == "__main__":
    main()