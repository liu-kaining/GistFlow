"""
Local Publisher module for writing processed gists to local Markdown/JSON files.
Provides an alternative to Notion for users who prefer local file storage.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from loguru import logger

from gistflow.config import Settings
from gistflow.models import Gist

if TYPE_CHECKING:
    from gistflow.core.publisher import NotionPublisher


class LocalPublisher:
    """
    Local file publisher for creating Markdown/JSON files from Gist objects.
    Provides local storage as an alternative or supplement to Notion.
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the local publisher.

        Args:
            settings: Application settings containing storage configuration.
        """
        self.settings = settings
        self.storage_path = Path(settings.LOCAL_STORAGE_PATH)
        self.format = settings.LOCAL_STORAGE_FORMAT.lower()
        self.enabled = settings.ENABLE_LOCAL_STORAGE

        if self.enabled:
            self._ensure_storage_path()
            logger.info(f"LocalPublisher initialized: {self.storage_path} (format: {self.format})")

    def _ensure_storage_path(self) -> None:
        """Create storage directory if it doesn't exist."""
        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Fallback: try to use /app/data/gists if in Docker
            fallback_path = Path("/app/data/gists")
            try:
                fallback_path.mkdir(parents=True, exist_ok=True)
                self.storage_path = fallback_path
                logger.warning(
                    f"Permission denied for {self.settings.LOCAL_STORAGE_PATH}, "
                    f"using fallback path: {fallback_path}"
                )
            except (PermissionError, OSError) as e:
                logger.error(
                    f"Failed to create storage directory: {self.storage_path} "
                    f"and fallback: {fallback_path}. Error: {e}"
                )
                raise

    def push(self, gist: Gist) -> Optional[str]:
        """
        Save a Gist to local file.

        Args:
            gist: The Gist object to save.

        Returns:
            File path if successful, None otherwise.
        """
        if not self.enabled:
            logger.debug("Local storage is disabled, skipping")
            return None

        if gist.is_spam_or_irrelevant:
            logger.info(f"Skipping spam/irrelevant email: {gist.title}")
            return None

        if not gist.is_valuable():
            logger.info(f"Skipping low-value email (score={gist.score}): {gist.title}")
            return None

        try:
            # Generate safe filename
            safe_title = self._sanitize_filename(gist.title)
            date_prefix = datetime.now().strftime("%Y-%m-%d")

            if self.format == "json":
                file_path = self._save_as_json(gist, safe_title, date_prefix)
            else:
                file_path = self._save_as_markdown(gist, safe_title, date_prefix)

            logger.info(f"Saved gist to: {file_path}")
            return str(file_path)

        except OSError as e:
            logger.error(f"Failed to save gist locally: {e}")
            return None
        except ValueError as e:
            logger.error(f"Data serialization error: {e}")
            return None

    def _sanitize_filename(self, title: str) -> str:
        """
        Create a safe filename from title.

        Args:
            title: Original title string.

        Returns:
            Sanitized filename-safe string.
        """
        # Replace invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        safe_title = title
        for char in invalid_chars:
            safe_title = safe_title.replace(char, '_')

        # Remove extra spaces and limit length
        safe_title = '_'.join(safe_title.split())
        return safe_title[:100]  # Limit filename length

    def _save_as_markdown(self, gist: Gist, safe_title: str, date_prefix: str) -> Path:
        """
        Save Gist as a Markdown file.

        Args:
            gist: The Gist object to save.
            safe_title: Sanitized title for filename.
            date_prefix: Date prefix for filename.

        Returns:
            Path to the created file.
        """
        filename = f"{date_prefix}_{safe_title}.md"
        file_path = self.storage_path / filename

        # Build Markdown content
        content = self._build_markdown_content(gist)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return file_path

    def _build_markdown_content(self, gist: Gist) -> str:
        """
        Build Markdown content from Gist.

        Args:
            gist: The Gist object.

        Returns:
            Markdown formatted string.
        """
        lines = []

        # Front matter (YAML style for compatibility with static site generators)
        lines.append("---")
        lines.append(f"title: \"{gist.title}\"")
        lines.append(f"score: {gist.score}")
        lines.append(f"date: {gist.received_at.isoformat() if gist.received_at else datetime.now().isoformat()}")
        if gist.tags:
            lines.append(f"tags: {json.dumps(gist.tags)}")
        if gist.sender:
            lines.append(f"sender: \"{gist.sender}\"")
        if gist.original_url:
            lines.append(f"source: \"{gist.original_url}\"")
        lines.append("---")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(gist.summary)
        lines.append("")

        # Key Insights
        if gist.key_insights:
            lines.append("## Key Insights")
            lines.append("")
            for insight in gist.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        # Mentioned Links
        if gist.mentioned_links:
            lines.append("## Links")
            lines.append("")
            for link in gist.mentioned_links:
                lines.append(f"- [{link}]({link})")
            lines.append("")

        # Raw Content (collapsible)
        if gist.raw_markdown:
            lines.append("<details>")
            lines.append("<summary>📄 原文内容</summary>")
            lines.append("")
            lines.append(gist.raw_markdown)
            lines.append("")
            lines.append("</details>")
            lines.append("")

        # Metadata
        lines.append("---")
        lines.append("")
        lines.append(f"*Processed by GistFlow | Score: {gist.score}/100*")
        if gist.original_id:
            lines.append(f"*Message ID: {gist.original_id}*")

        return '\n'.join(lines)

    def _save_as_json(self, gist: Gist, safe_title: str, date_prefix: str) -> Path:
        """
        Save Gist as a JSON file.

        Args:
            gist: The Gist object to save.
            safe_title: Sanitized title for filename.
            date_prefix: Date prefix for filename.

        Returns:
            Path to the created file.
        """
        filename = f"{date_prefix}_{safe_title}.json"
        file_path = self.storage_path / filename

        # Build JSON content
        data = self._build_json_content(gist)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        return file_path

    def _build_json_content(self, gist: Gist) -> dict:
        """
        Build JSON-compatible dictionary from Gist.

        Args:
            gist: The Gist object.

        Returns:
            Dictionary ready for JSON serialization.
        """
        return {
            "title": gist.title,
            "summary": gist.summary,
            "score": gist.score,
            "tags": gist.tags,
            "key_insights": gist.key_insights,
            "mentioned_links": gist.mentioned_links,
            "metadata": {
                "sender": gist.sender,
                "sender_email": gist.sender_email,
                "received_at": gist.received_at.isoformat() if gist.received_at else None,
                "original_id": gist.original_id,
                "original_url": gist.original_url,
            },
            "content": gist.raw_markdown,
        }

    def get_storage_stats(self) -> dict:
        """
        Get statistics about local storage.

        Returns:
            Dictionary with storage statistics.
        """
        if not self.enabled:
            return {"enabled": False}

        try:
            files = list(self.storage_path.glob("*.md")) + list(self.storage_path.glob("*.json"))
            total_size = sum(f.stat().st_size for f in files if f.is_file())

            return {
                "enabled": True,
                "path": str(self.storage_path),
                "format": self.format,
                "total_files": len(files),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
            }
        except OSError as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {
                "enabled": True,
                "error": str(e),
            }


# Publisher factory function
def get_publishers(settings: Settings) -> tuple:
    """
    Get configured publishers based on settings.

    Args:
        settings: Application settings.

    Returns:
        Tuple of (notion_publisher, local_publisher) - either can be None if disabled.
    """
    notion_publisher = None
    local_publisher = None

    # Notion publisher (always initialized if credentials are provided)
    try:
        if settings.NOTION_API_KEY and settings.NOTION_DATABASE_ID:
            from gistflow.core.publisher import NotionPublisher
            notion_publisher = NotionPublisher(settings)
    except Exception as e:
        logger.warning(f"Failed to initialize Notion publisher: {e}")

    # Local publisher
    if settings.ENABLE_LOCAL_STORAGE:
        local_publisher = LocalPublisher(settings)

    return notion_publisher, local_publisher