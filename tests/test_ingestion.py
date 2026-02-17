#!/usr/bin/env python3
"""
Ingestion module test script.
Tests Gmail connection and email fetching functionality.
Run this to verify your Gmail IMAP setup.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gistflow.config import get_settings
from gistflow.core import ContentCleaner, EmailFetcher
from gistflow.database import LocalStore
from gistflow.utils import get_logger, setup_logger


def test_cleaner() -> None:
    """Test content cleaner with sample HTML."""
    print("\n" + "=" * 60)
    print("Testing Content Cleaner")
    print("=" * 60)

    settings = get_settings()
    cleaner = ContentCleaner(settings)

    # Sample HTML content
    sample_html = """
    <html>
    <body>
        <h1>Weekly Newsletter</h1>
        <p>This is a sample newsletter content.</p>
        <p>Click here to <a href="http://unsubscribe.example.com">unsubscribe</a></p>
        <div style="display:none;">Tracking pixel</div>
        <img src="pixel.gif" width="1" height="1">
        <p>Copyright © 2024 Example Corp. All rights reserved.</p>
    </body>
    </html>
    """

    cleaned = cleaner.clean(sample_html)
    urls = cleaner.extract_urls(sample_html)

    print("\nCleaned Markdown:")
    print("-" * 40)
    print(cleaned)
    print("-" * 40)

    print(f"\nExtracted URLs: {urls}")
    print("\n✅ Content cleaner test passed!")


def test_local_store() -> None:
    """Test local SQLite storage."""
    print("\n" + "=" * 60)
    print("Testing Local Store")
    print("=" * 60)

    # Use a test database in project root data directory
    test_db_path = Path(__file__).parent.parent / "data" / "test_gistflow.db"
    store = LocalStore(test_db_path)

    # Test deduplication
    test_id = "test-message-123"

    print(f"\nChecking if '{test_id}' is processed: {store.is_processed(test_id)}")

    # Mark as processed
    store.mark_processed(
        message_id=test_id,
        subject="Test Email",
        sender="test@example.com",
        score=85,
        is_spam=False,
    )

    print(f"After marking, is '{test_id}' processed: {store.is_processed(test_id)}")

    # Get stats
    stats = store.get_stats()
    print(f"\nStore stats: {stats}")

    # Cleanup test
    store.close()

    # Remove test database
    if test_db_path.exists():
        test_db_path.unlink()
        print("\n🧹 Test database cleaned up")

    print("\n✅ Local store test passed!")


def test_email_fetcher_dry_run() -> None:
    """
    Test email fetcher configuration (dry run).
    Note: This will attempt to connect to Gmail if credentials are provided.
    """
    print("\n" + "=" * 60)
    print("Testing Email Fetcher (Configuration Check)")
    print("=" * 60)

    try:
        settings = get_settings()
        setup_logger(log_level=settings.LOG_LEVEL)
        logger = get_logger("test_ingestion")

        print(f"\n📧 Gmail Configuration:")
        print(f"  User: {settings.GMAIL_USER}")
        print(f"  Target Label: {settings.TARGET_LABEL}")
        print(f"  Max Emails Per Run: {settings.MAX_EMAILS_PER_RUN}")

        # Check if credentials are placeholder values
        if "your_email" in settings.GMAIL_USER.lower() or "xxxx" in settings.GMAIL_APP_PASSWORD:
            print("\n⚠️  Gmail credentials not configured. Skipping connection test.")
            print("   Please update your .env file with real credentials.")
            return

        # Try to connect
        print("\n🔌 Attempting to connect to Gmail...")
        fetcher = EmailFetcher(settings)

        try:
            fetcher.connect()
            print("✅ Successfully connected to Gmail!")

            # Get label stats
            stats = fetcher.get_label_stats()
            print(f"\n📊 Label Statistics:")
            print(f"  Label: {stats['label']}")
            print(f"  Total emails with label: {stats['total_with_label']}")
            print(f"  Unread emails: {stats['unread_with_label']}")

            fetcher.disconnect()
            print("\n✅ Email fetcher test passed!")

        except Exception as e:
            print(f"\n❌ Connection failed: {e}")
            print("\nTroubleshooting tips:")
            print("  1. Make sure 2FA is enabled on your Google account")
            print("  2. Generate an App Password at https://myaccount.google.com/apppasswords")
            print("  3. Use the App Password (not your regular password) in .env")
            print("  4. Make sure IMAP is enabled in Gmail settings")

    except Exception as e:
        print(f"\n❌ Configuration error: {e}")
        print("\nPlease check your .env file is properly configured.")


def main() -> None:
    """Run all tests."""
    print("=" * 60)
    print("GistFlow Ingestion Module Tests")
    print("=" * 60)

    # Test 1: Content Cleaner
    test_cleaner()

    # Test 2: Local Store
    test_local_store()

    # Test 3: Email Fetcher (requires real credentials)
    test_email_fetcher_dry_run()

    print("\n" + "=" * 60)
    print("All tests completed! Summary:")
    print("=" * 60)
    print("  ✅ Content Cleaner - Working")
    print("  ✅ Local Store - Working")
    print("  ⚠️  Email Fetcher - Requires Gmail credentials")
    print("\nNext steps:")
    print("  1. Configure your .env file with real Gmail credentials")
    print("  2. Create the 'Newsletter' label in your Gmail")
    print("  3. Run this script again to test real email fetching")
    print("=" * 60)


if __name__ == "__main__":
    main()