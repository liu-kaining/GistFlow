"""
Notion Publisher module for writing processed gists to Notion database.
Handles page creation, property mapping, and content block generation.
"""

import re
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
        stop=stop_after_attempt(5),  # Increased from 3 to 5 for better success rate
        wait=wait_exponential(multiplier=2, min=2, max=30),  # Longer wait times: 2s, 4s, 8s, 16s, 30s
        retry=retry_if_exception_type((HTTPResponseError, APIResponseError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    def _create_page_with_retry(self, properties: dict) -> dict:
        """
        Create a Notion page with retry mechanism.
        Uses aggressive retry strategy to maximize success rate.

        Args:
            properties: Notion page properties.

        Returns:
            Created page object from Notion API.

        Raises:
            APIResponseError: If all retries fail (after 5 attempts).
        """
        return self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=properties,
        )

    @retry(
        stop=stop_after_attempt(5),  # Increased from 3 to 5 for better success rate
        wait=wait_exponential(multiplier=2, min=2, max=30),  # Longer wait times: 2s, 4s, 8s, 16s, 30s
        retry=retry_if_exception_type((HTTPResponseError, APIResponseError, ConnectionError, TimeoutError)),
        reraise=True,
    )
    def _append_blocks_with_retry(self, page_id: str, blocks: list[dict]) -> dict:
        """
        Append content blocks to a Notion page with retry mechanism.
        Uses aggressive retry strategy to maximize success rate.

        Args:
            page_id: The Notion page ID.
            blocks: List of block dictionaries to append.

        Returns:
            API response.

        Raises:
            APIResponseError: If all retries fail (after 5 attempts).
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
        Uses aggressive retry strategy to maximize success rate - only fails if all retries are exhausted.

        Args:
            page_id: The Notion page ID.
            blocks: List of block dictionaries to append.
            email_content_start_index: Index of the block that starts email content section (if any).
            
        Raises:
            APIResponseError: Only if all retries are exhausted for critical chunks (first chunk or email content chunk).
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
                # _append_blocks_with_retry already has retry mechanism (5 attempts with exponential backoff)
                # If it raises an exception, all retries have been exhausted
                self._append_blocks_with_retry(page_id, chunk)
                logger.debug("Successfully appended chunk {}/{} to page {}", chunk_num, total_chunks, page_id)
            except (APIResponseError, HTTPResponseError, ConnectionError, TimeoutError) as e:
                # All retries have been exhausted at this point
                error_msg = str(e).replace("{", "{{").replace("}", "}}")
                logger.error("Failed to append blocks chunk {} to page {} after all retries: {}", chunk_num, page_id, error_msg)
                failed_chunks.append(chunk_num)
                last_exception = e
                
                # Only raise exception for critical chunks (first chunk or email content chunk)
                # These are essential for the page to be meaningful
                is_critical = (chunk_num == 1) or (email_content_chunk and chunk_num == email_content_chunk)
                
                if is_critical:
                    logger.error("Critical chunk {} failed after all retries - cannot continue", chunk_num)
                    raise
                else:
                    # Non-critical chunk failed - log warning but continue
                    logger.warning("Non-critical chunk {} failed after all retries - continuing with remaining chunks", chunk_num)
                    continue
        
        # If all chunks failed, raise the last exception
        if len(failed_chunks) == total_chunks and last_exception:
            logger.error("All {} chunks failed to append to page {} after all retries", total_chunks, page_id)
            raise last_exception
        
        # Log summary if some chunks failed but not all
        if failed_chunks:
            logger.warning("Some chunks failed but page was created: failed chunks: {}/{}", len(failed_chunks), total_chunks)

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

        # Block 4: Raw Email Content (collapsed in toggle, preserving original email appearance)
        if gist.raw_markdown:
            # Parse Markdown and convert to Notion blocks, preserving original email structure
            content_blocks = self._parse_markdown_to_blocks(gist.raw_markdown)
            
            # Wrap email content in a toggle block (collapsed by default)
            toggle_children = []
            
            # Add email header info inside toggle
            if gist.sender:
                toggle_children.append({
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
                toggle_children.append({
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
                toggle_children.append({
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
            
            if toggle_children:
                toggle_children.append({
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                })
            
            # Add content blocks inside toggle, preserving original structure
            # Don't convert to quote blocks - keep original formatting for authenticity
            toggle_children.extend(content_blocks)
            
            # Create toggle block with email content (collapsed by default)
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": "📧 邮件原文（点击展开）"},
                        "annotations": {"color": "gray", "italic": True}
                    }],
                    "children": toggle_children
                }
            })

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

    def _extract_important_links(self, content: str, original_url: Optional[str] = None) -> list[tuple[str, str]]:
        """
        Extract important links from email content for prominent display.
        Filters out common noise links (unsubscribe, social media, etc.).

        Args:
            content: Email content to extract links from.
            original_url: Original email URL (if any).

        Returns:
            List of tuples (url, text) for important links.
        """
        if not content:
            return []
        
        links: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        
        # Noise patterns to exclude
        noise_patterns = [
            r'unsubscribe',
            r'取消订阅',
            r'退订',
            r'view.*browser',
            r'在浏览器中查看',
            r'twitter\.com',
            r'facebook\.com',
            r'linkedin\.com',
            r'instagram\.com',
            r'substack\.com/redirect',  # Substack redirect links
            r'email.*settings',
            r'privacy.*policy',
            r'terms.*service',
        ]
        
        # Extract Markdown links: [text](url)
        markdown_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
        for link_text, link_url in markdown_links:
            # Skip noise links
            if any(re.search(pattern, link_url, re.IGNORECASE) for pattern in noise_patterns):
                continue
            
            # Skip if already seen
            if link_url in seen_urls:
                continue
            
            # Only include HTTP(S) links
            if link_url.startswith(('http://', 'https://')):
                links.append((link_url, link_text))
                seen_urls.add(link_url)
        
        # Extract plain URLs
        url_pattern = r'https?://[^\s\)]+'
        plain_urls = re.findall(url_pattern, content)
        for url in plain_urls:
            # Clean URL (remove trailing punctuation)
            url = url.rstrip('.,;:!?)')
            
            # Skip noise URLs
            if any(re.search(pattern, url, re.IGNORECASE) for pattern in noise_patterns):
                continue
            
            # Skip if already seen
            if url in seen_urls:
                continue
            
            # Skip if it's the original URL (already shown)
            if original_url and url == original_url:
                continue
            
            links.append((url, url[:60] + '...' if len(url) > 60 else url))
            seen_urls.add(url)
        
        # Prioritize: original URL first, then others
        if original_url and original_url not in seen_urls:
            links.insert(0, (original_url, "原始链接"))
        
        return links[:10]  # Return top 10 links
    
    def _parse_markdown_to_blocks(self, content: str) -> list[dict]:
        """
        Parse Markdown content and convert to Notion blocks with proper formatting.
        Handles links, bold, italic, tables, headings, and code blocks.

        Args:
            content: Markdown content to parse.

        Returns:
            List of Notion block dictionaries.
        """
        if not content:
            return []
        
        blocks: list[dict] = []
        
        # Minimal cleaning: only remove obvious table separator lines
        # Preserve original email structure as much as possible
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Only skip lines that are purely table separators (no actual content)
            # Pattern: only contains |, -, :, spaces, and very few other characters
            if re.match(r'^[\s|:\-]+$', stripped) and len(stripped) > 3:
                # This is a table separator line, skip it
                continue
            cleaned_lines.append(line)
        content = '\n'.join(cleaned_lines)
        
        # Only clean up excessive consecutive separators that break readability
        # But preserve single | characters and normal text
        # Replace patterns like "|||||" (5+ consecutive pipes) with single space
        content = re.sub(r'\|{5,}', ' ', content)
        # Replace patterns like "|---|---|" (table separator patterns) with single space
        content = re.sub(r'\|[\s\-:]{3,}\|', ' ', content)
        
        # Split by double newlines (paragraphs)
        paragraphs = content.split('\n\n')
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # Handle headings
            if para.startswith('#'):
                level = len(para) - len(para.lstrip('#'))
                text = para.lstrip('#').strip()
                if text:
                    blocks.append({
                        "object": "block",
                        "type": f"heading_{min(level, 3)}",
                        f"heading_{min(level, 3)}": {
                            "rich_text": self._parse_markdown_inline(text)
                        }
                    })
                continue
            
            # Handle code blocks
            if para.startswith('```'):
                lines_in_para = para.split('\n')
                if len(lines_in_para) > 1:
                    code_content = '\n'.join(lines_in_para[1:-1]) if lines_in_para[-1].strip() == '```' else '\n'.join(lines_in_para[1:])
                    blocks.append({
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [{"type": "text", "text": {"content": _truncate_for_notion(code_content)}}],
                            "language": "plain text"
                        }
                    })
                continue
            
            # Handle bullet lists
            if para.strip().startswith('- ') or para.strip().startswith('* '):
                list_items = [line.strip() for line in para.split('\n') if line.strip().startswith(('- ', '* '))]
                for item in list_items:
                    item_text = item.lstrip('-* ').strip()
                    if item_text:
                        blocks.append({
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": self._parse_markdown_inline(item_text)
                            }
                        })
                continue
            
            # Handle numbered lists
            if re.match(r'^\d+\.\s', para.strip()):
                list_items = [line.strip() for line in para.split('\n') if re.match(r'^\d+\.\s', line.strip())]
                for item in list_items:
                    item_text = re.sub(r'^\d+\.\s+', '', item)
                    if item_text:
                        blocks.append({
                            "object": "block",
                            "type": "numbered_list_item",
                            "numbered_list_item": {
                                "rich_text": self._parse_markdown_inline(item_text)
                            }
                        })
                continue
            
            # Regular paragraph - parse inline Markdown
            rich_text = self._parse_markdown_inline(para)
            if rich_text:
                # Split into chunks if too long
                current_chunk = []
                current_length = 0
                
                for item in rich_text:
                    item_text = item.get("text", {}).get("content", "")
                    item_length = len(item_text)
                    
                    if current_length + item_length <= NOTION_RICH_TEXT_MAX:
                        current_chunk.append(item)
                        current_length += item_length
                    else:
                        # Flush current chunk
                        if current_chunk:
                            blocks.append({
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {"rich_text": current_chunk}
                            })
                        # Start new chunk
                        if item_length <= NOTION_RICH_TEXT_MAX:
                            current_chunk = [item]
                            current_length = item_length
                        else:
                            # Item itself is too long, split it
                            for i in range(0, item_length, NOTION_RICH_TEXT_MAX):
                                chunk_text = item_text[i:i + NOTION_RICH_TEXT_MAX]
                                current_chunk = [{
                                    "type": "text",
                                    "text": {"content": chunk_text},
                                    "annotations": item.get("annotations", {})
                                }]
                                blocks.append({
                                    "object": "block",
                                    "type": "paragraph",
                                    "paragraph": {"rich_text": current_chunk}
                                })
                                current_chunk = []
                                current_length = 0
                
                if current_chunk:
                    blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": current_chunk}
                    })
        
        return blocks
    
    def _parse_markdown_inline(self, text: str) -> list[dict]:
        """
        Parse inline Markdown formatting (bold, italic, links) into Notion rich_text format.
        Processes links first, then bold/italic within remaining text.
        
        Args:
            text: Text with Markdown formatting.
            
        Returns:
            List of Notion rich_text items.
        """
        if not text:
            return []
        
        rich_text_items: list[dict] = []
        i = 0
        
        while i < len(text):
            # Match links: [text](url) - process links first
            link_match = re.search(r'\[([^\]]+)\]\(([^)]+)\)', text[i:])
            if link_match:
                # Add text before link (may contain bold/italic)
                before_link = text[i:i + link_match.start()]
                if before_link:
                    rich_text_items.extend(self._parse_bold_italic(before_link))
                
                # Add link (link text itself may contain formatting, but we'll keep it simple)
                link_text = link_match.group(1)
                link_url = link_match.group(2)
                
                # Parse formatting within link text
                link_rich_text = self._parse_bold_italic(link_text)
                # Apply link to each item
                for item in link_rich_text:
                    if item.get("text", {}).get("content"):
                        item["text"]["link"] = {"url": link_url[:2000]} if link_url.startswith("http") else None
                        if not item.get("annotations"):
                            item["annotations"] = {}
                        item["annotations"]["color"] = "blue"
                        rich_text_items.append(item)
                
                i += link_match.end()
                continue
            
            # No more links, parse remaining text for bold/italic
            remaining = text[i:]
            if remaining:
                rich_text_items.extend(self._parse_bold_italic(remaining))
            break
        
        return rich_text_items if rich_text_items else [{"type": "text", "text": {"content": _truncate_for_notion(text)}}]
    
    def _parse_bold_italic(self, text: str) -> list[dict]:
        """
        Parse bold (**text**) and italic (*text*) formatting.
        
        Args:
            text: Text with bold/italic formatting.
            
        Returns:
            List of Notion rich_text items.
        """
        if not text:
            return []
        
        items: list[dict] = []
        i = 0
        
        while i < len(text):
            # Match bold: **text**
            bold_match = re.search(r'\*\*([^*]+)\*\*', text[i:])
            # Match italic: *text* (but not **text**)
            italic_match = re.search(r'(?<!\*)\*([^*]+)\*(?!\*)', text[i:])
            
            # Choose the earliest match
            matches = []
            if bold_match:
                matches.append((bold_match.start(), bold_match.end(), 'bold', bold_match.group(1)))
            if italic_match:
                matches.append((italic_match.start(), italic_match.end(), 'italic', italic_match.group(1)))
            
            if not matches:
                # No more formatting, add remaining text
                remaining = text[i:]
                if remaining:
                    items.append({"type": "text", "text": {"content": _truncate_for_notion(remaining)}})
                break
            
            # Sort by position
            matches.sort(key=lambda x: x[0])
            match_start, match_end, match_type, match_content = matches[0]
            
            # Add text before match
            before_match = text[i:i + match_start]
            if before_match:
                items.append({"type": "text", "text": {"content": _truncate_for_notion(before_match)}})
            
            # Add formatted text
            annotations = {}
            if match_type == 'bold':
                annotations["bold"] = True
            elif match_type == 'italic':
                annotations["italic"] = True
            
            items.append({
                "type": "text",
                "text": {"content": _truncate_for_notion(match_content)},
                "annotations": annotations
            })
            
            i += match_end
        
        return items if items else [{"type": "text", "text": {"content": _truncate_for_notion(text)}}]
    
    def _split_content_to_blocks(self, content: str, max_length: int = NOTION_RICH_TEXT_MAX) -> list[dict]:
        """
        Split long content into multiple paragraph blocks.
        Notion requires rich_text content length ≤ 2000 per block.
        
        DEPRECATED: Use _parse_markdown_to_blocks instead for proper Markdown parsing.

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