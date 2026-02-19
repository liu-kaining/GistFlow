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

# Notion API 限制：单段 rich_text 的 text.content 长度 ≤ 2000
NOTION_RICH_TEXT_MAX = 2000


def _truncate_for_notion(text: str, max_len: int = NOTION_RICH_TEXT_MAX) -> str:
    """Ensure string length is within Notion rich_text limit (≤2000)."""
    if not text:
        return text
    return text[:max_len]


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
            # Track which block index starts the email content section
            email_content_start_index = self._find_email_content_start_index(blocks)
            self._append_blocks_in_chunks(page_id, blocks, email_content_start_index)

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

    def _find_email_content_start_index(self, blocks: list[dict]) -> Optional[int]:
        """
        Find the index of the block that starts the email content section.
        
        Args:
            blocks: List of block dictionaries.
            
        Returns:
            Index of the email content heading block, or None if not found.
        """
        for i, block in enumerate(blocks):
            if block.get("type") == "heading_2":
                heading = block.get("heading_2", {})
                rich_text = heading.get("rich_text", [])
                if rich_text and rich_text[0].get("text", {}).get("content") == "📧 邮件原文":
                    return i
        return None

    def _append_blocks_in_chunks(self, page_id: str, blocks: list[dict], email_content_start_index: Optional[int] = None) -> None:
        """
        Append content blocks in chunks to avoid Notion's limit.

        Args:
            page_id: The Notion page ID.
            blocks: List of block dictionaries to append.
            email_content_start_index: Index of the block that starts email content section (if any).
            
        Raises:
            APIResponseError: If critical chunks fail (e.g., first chunk, email content chunk, or all chunks fail).
        """
        if not blocks:
            return

        chunk_size = 100  # Notion has a limit of 100 blocks per request
        failed_chunks = []
        total_chunks = (len(blocks) + chunk_size - 1) // chunk_size
        last_exception = None
        
        # Calculate which chunk contains the email content
        email_content_chunk = None
        if email_content_start_index is not None:
            email_content_chunk = (email_content_start_index // chunk_size) + 1

        for i in range(0, len(blocks), chunk_size):
            chunk = blocks[i:i + chunk_size]
            chunk_num = i // chunk_size + 1
            try:
                self._append_blocks_with_retry(page_id, chunk)
            except (APIResponseError, HTTPResponseError) as e:
                # Escape braces in error message to avoid Loguru formatting issues with JSON strings
                error_msg = str(e).replace("{", "{{").replace("}", "}}")
                logger.error("Failed to append blocks chunk {} to page {}: {}", chunk_num, page_id, error_msg)
                failed_chunks.append(chunk_num)
                last_exception = e
                # If first chunk fails, this is critical - raise exception
                if chunk_num == 1:
                    logger.error("First chunk failed - this is critical, raising exception")
                    raise
                # If email content chunk fails, this is also critical - raise exception
                if email_content_chunk and chunk_num == email_content_chunk:
                    logger.error("Email content chunk failed - this is critical, raising exception")
                    raise
                # Continue with next chunk if not critical chunk
                continue
            except (ConnectionError, TimeoutError) as e:
                logger.error(f"Network error appending blocks chunk {chunk_num} to page {page_id}: {e}")
                failed_chunks.append(chunk_num)
                last_exception = e
                # If first chunk or email content chunk fails due to network, also raise
                if chunk_num == 1 or (email_content_chunk and chunk_num == email_content_chunk):
                    raise
                continue
        
        # If all chunks failed, raise the last exception
        if len(failed_chunks) == total_chunks and last_exception:
            logger.error("All {} chunks failed to append to page {}", total_chunks, page_id)
            raise last_exception

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
                            "content": _truncate_for_notion(gist.summary or "")
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

        # Block 1: Summary (if available, show in content area for better readability)
        if gist.summary:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "📋 摘要"}}],
                }
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": _truncate_for_notion(gist.summary)}}],
                }
            })
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })

        # Block 2: Key Insights (use proper bulleted list instead of Callout)
        if gist.key_insights:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "💡 核心要点"}}],
                }
            })
            
            # Use proper bulleted_list_item blocks for better structure
            for insight in gist.key_insights:
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": _truncate_for_notion(insight)}}],
                    }
                })
            
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })

        # Block 3: Mentioned Links (if any)
        if gist.mentioned_links:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
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
                                "content": _truncate_for_notion(link),
                                "link": {"url": _truncate_for_notion(link)} if link.startswith("http") else None,
                            }
                        }]
                    }
                })
            
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })

        # Block 4: Raw Email Content (displayed directly, styled like email)
        if gist.raw_markdown:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "📧 邮件原文"}}],
                }
            })
            
            # Add email header info (like email clients do)
            email_header_blocks = []
            if gist.sender:
                email_header_blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": "发件人: "},
                                "annotations": {"bold": True, "color": "gray"}
                            },
                            {"type": "text", "text": {"content": gist.sender[:100]}},
                        ]
                    }
                })
            
            if gist.received_at:
                from datetime import datetime
                date_str = gist.received_at.strftime("%Y年%m月%d日 %H:%M") if isinstance(gist.received_at, datetime) else str(gist.received_at)
                email_header_blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": "日期: "},
                                "annotations": {"bold": True, "color": "gray"}
                            },
                            {"type": "text", "text": {"content": date_str}},
                        ]
                    }
                })
            
            if gist.original_url:
                url_text = _truncate_for_notion(gist.original_url[:100])
                url_link = gist.original_url[:2000] if gist.original_url.startswith("http") else None
                email_header_blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": "链接: "},
                                "annotations": {"bold": True, "color": "gray"}
                            },
                            {
                                "type": "text",
                                "text": {"content": url_text, "link": {"url": url_link}} if url_link else {"content": url_text},
                                "annotations": {"color": "blue"}
                            },
                        ]
                    }
                })
            
            # Add divider after header
            if email_header_blocks:
                blocks.extend(email_header_blocks)
                blocks.append({
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                })
            
            # Split content into chunks and display directly (no toggle, fully visible)
            # This allows users to verify AI summary/classification/score accuracy
            content_blocks = self._split_content_to_blocks(gist.raw_markdown)
            
            # Add all content blocks directly - styled like email body
            # Use quote blocks for email-like indentation and styling
            for block in content_blocks:
                if block.get("type") == "paragraph":
                    # Convert to quote block for email-like appearance (indented, gray background)
                    quote_block = {
                        "object": "block",
                        "type": "quote",
                        "quote": {
                            "rich_text": block["paragraph"]["rich_text"],
                        }
                    }
                    blocks.append(quote_block)
                else:
                    # Keep other block types as-is (headings, lists, etc.)
                    blocks.append(block)

        # Block 5: Metadata footer (simplified, since sender is already in Properties)
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })

        # Only show ID if available, sender is redundant (already in Properties)
        if gist.original_id:
            metadata = f"📧 Message ID: {gist.original_id[:20]}"
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": _truncate_for_notion(metadata)},
                        "annotations": {"color": "gray", "italic": True}
                    }]
                }
            })

        return blocks

    def _split_content_to_blocks(self, content: str, max_length: int = NOTION_RICH_TEXT_MAX) -> list[dict]:
        """
        Split long content into multiple paragraph blocks.
        Notion requires rich_text content length ≤ 2000 per block.

        Args:
            content: The content to split.
            max_length: Maximum characters per block (default 2000).

        Returns:
            List of paragraph block dictionaries.
        """
        blocks: list[dict] = []

        # Split by paragraphs first to avoid breaking mid-sentence
        paragraphs = content.split("\n\n")

        current_block = ""
        for para in paragraphs:
            sep = "\n\n" if current_block else ""
            if len(current_block) + len(sep) + len(para) <= max_length:
                current_block += sep + para
            else:
                # Flush current block (guaranteed ≤ max_length)
                if current_block:
                    blocks.append(self._create_paragraph_block(current_block))
                # Start new block: cap single paragraph to max_length so we never exceed
                if len(para) <= max_length:
                    current_block = para
                else:
                    # Force split long paragraph into chunks of at most max_length
                    for i in range(0, len(para), max_length):
                        chunk = para[i : i + max_length]
                        blocks.append(self._create_paragraph_block(chunk))
                    current_block = ""

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
                    "text": {"content": _truncate_for_notion(text)}
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