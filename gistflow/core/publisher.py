"""
Notion Publisher module for writing processed gists to Notion database.
Handles page creation, property mapping, and content block generation.
"""

from typing import Optional

from loguru import logger
from notion_client import Client
from notion_client.errors import APIResponseError, HTTPResponseError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gistflow.config import Settings
from gistflow.models import Gist


class NotionPublisher:
    """
    Notion API publisher for creating pages from Gist objects.
    Maps Gist fields to Notion database properties and page content.
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the Notion publisher.

        Args:
            settings: Application settings containing Notion API credentials.
        """
        self.settings = settings
        self.client = Client(auth=settings.NOTION_API_KEY)
        self.database_id = settings.NOTION_DATABASE_ID

        logger.info(f"NotionPublisher initialized for database: {self.database_id[:8]}...")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((HTTPResponseError, APIResponseError)),
        reraise=True,
    )
    def _create_page_with_retry(self, properties: dict) -> dict:
        """
        Create a Notion page with retry mechanism.

        Args:
            properties: Notion page properties.

        Returns:
            Created page object from Notion API.

        Raises:
            APIResponseError: If all retries fail.
        """
        return self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=properties,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((HTTPResponseError, APIResponseError)),
        reraise=True,
    )
    def _append_blocks_with_retry(self, page_id: str, blocks: list[dict]) -> dict:
        """
        Append content blocks to a Notion page with retry mechanism.

        Args:
            page_id: The Notion page ID.
            blocks: List of block dictionaries to append.

        Returns:
            API response.

        Raises:
            APIResponseError: If all retries fail.
        """
        return self.client.blocks.children.append(
            block_id=page_id,
            children=blocks,
        )

    def push(self, gist: Gist) -> Optional[str]:
        """
        Push a Gist to Notion database.

        Args:
            gist: The Gist object to publish.

        Returns:
            Notion page ID if successful, None otherwise.
        """
        if gist.is_spam_or_irrelevant:
            logger.info(f"Skipping spam/irrelevant email: {gist.title}")
            return None

        if not gist.is_valuable(min_score=self.settings.MIN_VALUE_SCORE):
            logger.info(f"Skipping low-value email (score={gist.score}, threshold={self.settings.MIN_VALUE_SCORE}): {gist.title}")
            return None

        try:
            # Step 1: Create page with properties
            properties = self._build_properties(gist)
            page = self._create_page_with_retry(properties)
            page_id = page["id"]

            logger.info(f"Created Notion page: {page_id}")

            # Step 2: Append content blocks
            blocks = self._build_content_blocks(gist)
            self._append_blocks_in_chunks(page_id, blocks)

            logger.info(f"Successfully published gist to Notion: {gist.title}")
            return page_id

        except APIResponseError as e:
            logger.error(f"Notion API error for gist '{gist.title}': {e}")
            return None
        except HTTPResponseError as e:
            logger.error(f"Notion HTTP error for gist '{gist.title}': {e}")
            return None
        except ValueError as e:
            logger.error(f"Notion property mapping error for gist '{gist.title}': {e}")
            return None
        except (KeyError, TypeError, AttributeError) as e:
            # Handle data structure errors during page/block building
            logger.error(f"Data structure error building Notion page for '{gist.title}': {e}")
            return None
        except ConnectionError as e:
            # Handle network connection errors
            logger.error(f"Connection error publishing to Notion for '{gist.title}': {e}")
            return None

    def _append_blocks_in_chunks(self, page_id: str, blocks: list[dict]) -> None:
        """
        Append content blocks in chunks to avoid Notion's limit.

        Args:
            page_id: The Notion page ID.
            blocks: List of block dictionaries to append.
        """
        if not blocks:
            return

        chunk_size = 100  # Notion has a limit of 100 blocks per request

        for i in range(0, len(blocks), chunk_size):
            chunk = blocks[i:i + chunk_size]
            try:
                self._append_blocks_with_retry(page_id, chunk)
            except (APIResponseError, HTTPResponseError) as e:
                logger.error(f"Failed to append blocks chunk {i//chunk_size + 1} to page {page_id}: {e}")
                # Continue with next chunk even if one fails
                continue
            except (ConnectionError, TimeoutError) as e:
                logger.error(f"Network error appending blocks chunk {i//chunk_size + 1} to page {page_id}: {e}")
                continue

    def _build_properties(self, gist: Gist) -> dict:
        """
        Build Notion page properties from Gist object.

        Args:
            gist: The Gist object to convert.

        Returns:
            Dictionary of Notion properties.
        """
        properties = {
            # Title (required)
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": gist.title[:100] if gist.title else "Untitled"
                        }
                    }
                ]
            },
            # Score (number)
            "Score": {
                "number": gist.score
            },
            # Summary (rich text)
            "Summary": {
                "rich_text": [
                    {
                        "text": {
                            "content": gist.summary[:2000] if gist.summary else ""
                        }
                    }
                ]
            },
            # Tags (multi-select)
            "Tags": {
                "multi_select": [
                    {"name": tag} for tag in gist.tags[:10]
                ]
            },
        }

        # Sender (select or rich_text) - optional
        # Try select first, fallback to rich_text if select fails
        if gist.sender:
            # Use select format (single-select)
            properties["Sender"] = {
                "select": {"name": gist.sender[:100]}
            }

        # Date - optional
        if gist.received_at:
            properties["Date"] = {
                "date": {"start": gist.received_at.isoformat()}
            }

        # Link (URL) - optional
        if gist.original_url:
            properties["Link"] = {
                "url": gist.original_url[:2000]
            }

        return properties

    def _build_content_blocks(self, gist: Gist) -> list[dict]:
        """
        Build Notion block objects for page content.

        Args:
            gist: The Gist object with content to convert.

        Returns:
            List of Notion block dictionaries.
        """
        blocks: list[dict] = []

        # Block 1: Key Insights (Callout)
        if gist.key_insights:
            insights_text = "\n".join([f"• {insight}" for insight in gist.key_insights])
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": insights_text[:2000]}}],
                    "icon": {"emoji": "💡"},
                    "color": "blue_background",
                }
            })

        # Block 2: Divider
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })

        # Block 3: Mentioned Links (if any)
        if gist.mentioned_links:
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": "📎 相关链接"}}],
                }
            })

            for link in gist.mentioned_links[:10]:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{
                            "type": "text",
                            "text": {
                                "content": link[:2000],
                                "link": {"url": link[:2000]} if link.startswith("http") else None,
                            }
                        }]
                    }
                })

        # Block 4: Another Divider
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })

        # Block 5: Raw Markdown Content (in Toggle for readability)
        if gist.raw_markdown:
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": "📄 原文内容"}}],
                }
            })

            # Split content into chunks (Notion rich_text limit is 2000 chars per block)
            content_blocks = self._split_content_to_blocks(gist.raw_markdown)

            # Add toggle block containing the content
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [{"type": "text", "text": {"content": "点击展开查看原文"}}],
                    "children": content_blocks,
                }
            })

        # Block 6: Metadata footer
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })

        metadata = f"📧 来源: {gist.sender or 'Unknown'}"
        if gist.original_id:
            metadata += f" | ID: {gist.original_id[:20]}"

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": metadata},
                    "annotations": {"color": "gray", "italic": True},
                }]
            }
        })

        return blocks

    def _split_content_to_blocks(self, content: str, max_length: int = 2000) -> list[dict]:
        """
        Split long content into multiple paragraph blocks.

        Args:
            content: The content to split.
            max_length: Maximum characters per block.

        Returns:
            List of paragraph block dictionaries.
        """
        blocks: list[dict] = []

        # Split by paragraphs first to avoid breaking mid-sentence
        paragraphs = content.split("\n\n")

        current_block = ""
        for para in paragraphs:
            if len(current_block) + len(para) + 2 <= max_length:
                current_block += ("\n\n" if current_block else "") + para
            else:
                # Save current block if not empty
                if current_block:
                    blocks.append(self._create_paragraph_block(current_block))
                # Start new block
                if len(para) <= max_length:
                    current_block = para
                else:
                    # Force split long paragraph
                    for i in range(0, len(para), max_length):
                        chunk = para[i:i + max_length]
                        blocks.append(self._create_paragraph_block(chunk))
                    current_block = ""

        # Add remaining content
        if current_block:
            blocks.append(self._create_paragraph_block(current_block))

        return blocks

    def _create_paragraph_block(self, text: str) -> dict:
        """
        Create a paragraph block from text.

        Args:
            text: The text content.

        Returns:
            Notion paragraph block dictionary.
        """
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": text[:2000]}
                }]
            }
        }

    def test_connection(self) -> bool:
        """
        Test the Notion API connection.

        Returns:
            True if connection works, False otherwise.
        """
        try:
            logger.info("Testing Notion connection...")

            # Try to retrieve the database
            database = self.client.databases.retrieve(database_id=self.database_id)

            title = database.get("title", [{}])
            title_text = title[0].get("plain_text", "Unknown") if title else "Unknown"
            logger.info(f"Notion connection successful: {title_text}")
            return True

        except APIResponseError as e:
            logger.error(f"Notion API connection failed: {e}")
            return False
        except HTTPResponseError as e:
            logger.error(f"Notion HTTP connection failed: {e}")
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((HTTPResponseError, APIResponseError)),
    )
    def get_database_properties(self) -> dict:
        """
        Get the properties of the target Notion database.

        Returns:
            Dictionary of database properties.
        """
        database = self.client.databases.retrieve(database_id=self.database_id)
        return database.get("properties", {})


# Property name constants for Notion database schema
NOTION_PROPERTIES = {
    "TITLE": "Name",
    "SCORE": "Score",
    "SUMMARY": "Summary",
    "TAGS": "Tags",
    "SENDER": "Sender",
    "DATE": "Date",
    "LINK": "Link",
    "STATUS": "Status",
}