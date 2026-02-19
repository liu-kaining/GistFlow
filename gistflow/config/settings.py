"""
Configuration management using Pydantic Settings.
Loads environment variables and provides type-safe configuration access.
"""

from pathlib import Path
from shutil import copyfile

from loguru import logger
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def ensure_env_file() -> None:
    """
    Ensure .env file exists. If not, create it from .env.example.
    This is called before loading settings to ensure configuration is available.
    Note: In Docker environments, .env is typically provided via env_file mount,
    so this function will skip creation if the file already exists or if we don't
    have write permissions.
    """
    env_path = Path(".env")
    
    # Check if .env already exists and is readable
    if env_path.exists():
        # Check if we can read it
        try:
            env_path.read_text(encoding="utf-8")
            logger.debug(".env file already exists and is readable")
            return
        except PermissionError:
            logger.warning(".env file exists but is not readable, skipping auto-creation")
            return
        except Exception as e:
            logger.debug(f".env file exists but has issues: {e}, will try to create new one")

    # Try multiple possible locations for .env.example
    possible_paths = [
        Path(".env.example"),  # Current directory
        Path(__file__).parent.parent.parent / ".env.example",  # Project root
        Path("/app/.env.example"),  # Docker container path
    ]
    
    env_example_path = None
    for path in possible_paths:
        if path.exists():
            env_example_path = path
            logger.debug(f"Found .env.example at {path}")
            break

    if env_example_path is None:
        logger.debug(".env.example file not found in any expected location")
        logger.debug(f"Searched paths: {[str(p) for p in possible_paths]}")
        # In Docker, .env is usually provided via env_file, so this is not an error
        return

    # Try to create .env file, but handle permission errors gracefully
    try:
        # Check if we have write permission to the directory
        env_dir = env_path.parent
        if not env_dir.exists():
            env_dir.mkdir(parents=True, exist_ok=True)
        
        # Try to create the file
        copyfile(env_example_path, env_path)
        logger.info(f"Created .env file from .env.example at {env_path.absolute()}")
        logger.info("Please edit .env file with your actual configuration values")
    except PermissionError:
        # In Docker, .env is often mounted read-only or provided via env_file
        logger.debug(f"Permission denied creating .env file (likely mounted via docker-compose env_file)")
        logger.debug("This is normal in Docker environments where .env is provided via env_file")
    except Exception as e:
        logger.warning(f"Failed to create .env file from .env.example: {e}")
        # Don't raise - allow the application to continue
        # Settings will load from environment variables if .env is not available


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    All configuration values are type-safe and validated.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Gmail Configuration
    GMAIL_USER: str = Field(..., description="Gmail account email address")
    GMAIL_APP_PASSWORD: str = Field(..., description="Gmail App Password for IMAP access")
    GMAIL_FOLDER: str = Field(
        default="INBOX",
        description="Gmail folder to search for emails",
    )
    TARGET_LABEL: str = Field(
        default="Newsletter",
        description="Gmail label to filter newsletter emails (case-insensitive, supports variants like newsletter, News, news)",
    )

    # LLM Configuration
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key (or compatible service)")
    OPENAI_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI API base URL (change for OneAPI, DeepSeek, etc.)",
    )
    LLM_MODEL_NAME: str = Field(
        default="gpt-4o",
        description="LLM model name (e.g., gpt-4o, gemini-1.5-pro, deepseek-chat)",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.3,
        description="LLM temperature for response consistency",
        ge=0.0,
        le=2.0,
    )
    LLM_MAX_TOKENS: int = Field(
        default=2000,
        description="Maximum tokens for LLM response",
        gt=0,
    )

    # Notion Configuration
    NOTION_API_KEY: str = Field(..., description="Notion integration API key")
    NOTION_DATABASE_ID: str = Field(..., description="Notion database ID for storing gists")

    # Local Storage Configuration
    ENABLE_LOCAL_STORAGE: bool = Field(
        default=True,
        description="Enable saving gists to local Markdown files",
    )
    LOCAL_STORAGE_PATH: str = Field(
        default="./gists",
        description="Directory path for local Markdown storage",
    )
    LOCAL_STORAGE_FORMAT: str = Field(
        default="markdown",
        description="Storage format: 'markdown' or 'json'",
    )
    DATA_DIR: str = Field(
        default="./data",
        description="Directory for SQLite database and runtime data. In Docker set to /app/data so volume persists.",
    )

    # System Configuration
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    CHECK_INTERVAL_MINUTES: int = Field(
        default=30,
        description="Interval in minutes between email checks",
        gt=0,
    )
    MAX_EMAILS_PER_RUN: int = Field(
        default=10,
        description="Maximum emails to process per run (prevent rate limits)",
        gt=0,
        le=100,
    )

    # Content Processing Configuration
    MAX_CONTENT_LENGTH: int = Field(
        default=20000,
        description="Maximum characters for LLM processing (before truncation)",
        gt=0,
    )
    CONTENT_TRUNCATION_HEAD: int = Field(
        default=15000,
        description="Characters to keep from the start when truncating",
    )
    CONTENT_TRUNCATION_TAIL: int = Field(
        default=2000,
        description="Characters to keep from the end when truncating",
    )

    # Retry Configuration
    LLM_MAX_RETRIES: int = Field(
        default=3,
        description="Maximum retries for LLM API calls",
        gt=0,
        le=10,
    )
    LLM_RETRY_DELAY_SECONDS: float = Field(
        default=2.0,
        description="Initial delay between retries (exponential backoff)",
        gt=0,
    )

    # Value Scoring Configuration
    MIN_VALUE_SCORE: int = Field(
        default=30,
        description="Minimum score (0-100) for a gist to be considered valuable and worth saving",
        ge=0,
        le=100,
    )

    # Prompt Configuration
    PROMPT_SYSTEM_PATH: str = Field(
        default="./prompts/system_prompt.txt",
        description="Path to system prompt template file",
    )
    PROMPT_USER_PATH: str = Field(
        default="./prompts/user_prompt_template.txt",
        description="Path to user prompt template file",
    )

    # Web Server Configuration
    WEB_SERVER_PORT: int = Field(
        default=5800,
        description="Port for web management interface",
        gt=0,
        lt=65536,
    )
    WEB_SERVER_HOST: str = Field(
        default="0.0.0.0",
        description="Host for web management interface (0.0.0.0 for Docker/external access, 127.0.0.1 for local only)",
    )

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Validate that LOG_LEVEL is a valid logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_value = value.upper()
        if upper_value not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}, got {value}")
        return upper_value

    @field_validator("OPENAI_BASE_URL")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """Remove trailing slash from base URL if present."""
        return value.rstrip("/")


# Global settings instance (singleton pattern)
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get the global settings instance.
    Uses lazy initialization to allow for environment variable changes.
    Ensures .env file exists before loading settings.
    """
    global _settings
    if _settings is None:
        # Ensure .env file exists before loading settings
        ensure_env_file()
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """
    Force reload settings from environment variables.
    Useful for testing or when environment changes.
    """
    global _settings
    _settings = Settings()
    return _settings