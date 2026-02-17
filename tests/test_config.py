#!/usr/bin/env python3
"""
Configuration validation script.
Tests if environment variables are loaded correctly.
Run this to verify your .env setup before running the main application.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gistflow.config import get_settings
from gistflow.utils import setup_logger, get_logger


def main() -> None:
    """Validate configuration and print loaded values."""
    try:
        # Try to load settings
        settings = get_settings()

        # Setup logger with configured level
        setup_logger(log_level=settings.LOG_LEVEL)
        logger = get_logger("config_test")

        logger.info("=" * 60)
        logger.info("GistFlow Configuration Validation")
        logger.info("=" * 60)

        # Print masked configuration values
        print("\n📧 Gmail Configuration:")
        print(f"  GMAIL_USER: {settings.GMAIL_USER}")
        print(f"  GMAIL_FOLDER: {settings.GMAIL_FOLDER}")
        print(f"  TARGET_LABEL: {settings.TARGET_LABEL}")
        print(f"  GMAIL_APP_PASSWORD: {'*' * 8}...{'*' * 4}")

        print("\n🤖 LLM Configuration:")
        print(f"  OPENAI_BASE_URL: {settings.OPENAI_BASE_URL}")
        print(f"  LLM_MODEL_NAME: {settings.LLM_MODEL_NAME}")
        print(f"  LLM_TEMPERATURE: {settings.LLM_TEMPERATURE}")
        print(f"  LLM_MAX_TOKENS: {settings.LLM_MAX_TOKENS}")
        print(f"  OPENAI_API_KEY: {'*' * 8}...{'*' * 4}")

        print("\n📝 Notion Configuration:")
        print(f"  NOTION_DATABASE_ID: {settings.NOTION_DATABASE_ID[:8]}...{settings.NOTION_DATABASE_ID[-4:]}")
        print(f"  NOTION_API_KEY: {'*' * 8}...{'*' * 4}")

        print("\n⚙️  System Configuration:")
        print(f"  LOG_LEVEL: {settings.LOG_LEVEL}")
        print(f"  CHECK_INTERVAL_MINUTES: {settings.CHECK_INTERVAL_MINUTES}")
        print(f"  MAX_EMAILS_PER_RUN: {settings.MAX_EMAILS_PER_RUN}")
        print(f"  MAX_CONTENT_LENGTH: {settings.MAX_CONTENT_LENGTH}")

        print("\n🔄 Retry Configuration:")
        print(f"  LLM_MAX_RETRIES: {settings.LLM_MAX_RETRIES}")
        print(f"  LLM_RETRY_DELAY_SECONDS: {settings.LLM_RETRY_DELAY_SECONDS}")

        logger.info("=" * 60)
        logger.success("✅ Configuration loaded successfully!")
        logger.info("=" * 60)

        print("\n💡 Next steps:")
        print("  1. Implement core/ingestion.py (Gmail fetching)")
        print("  2. Implement core/llm_engine.py (AI processing)")
        print("  3. Implement core/publisher.py (Notion publishing)")
        print("  4. Implement main.py with scheduler")

    except Exception as e:
        print(f"\n❌ Configuration validation failed!")
        print(f"Error: {e}")
        print("\nPlease check:")
        print("  1. .env file exists in the project root")
        print("  2. All required environment variables are set")
        print("  3. Environment variable values are correct")
        sys.exit(1)


if __name__ == "__main__":
    main()