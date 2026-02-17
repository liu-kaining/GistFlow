"""
Content cleaner module for processing email HTML content.
Converts HTML to Markdown and performs noise removal and truncation.
"""

import re
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger
from markdownify import markdownify as md

from gistflow.config import Settings


class ContentCleaner:
    """
    Cleans email HTML content for LLM processing.
    Handles HTML to Markdown conversion, noise removal, and truncation.
    """

    # Common noise patterns to remove
    NOISE_PATTERNS = [
        # Unsubscribe links
        r'\[?unsubscribe\]?\s*',
        r'click here to unsubscribe',
        r'取消订阅',
        r'退订',
        # View in browser
        r'\[?view in browser\]?\s*',
        r'\[?view online\]?\s*',
        r'在浏览器中查看',
        # Social media links
        r'\[?(twitter|facebook|linkedin|instagram)\]?\s*',
        # Copyright footers
        r'copyright\s*©?\s*\d{4}.*$',
        r'©\s*\d{4}.*$',
        r'all rights reserved\.?',
        r'版权所有',
        # Email footer noise
        r'sent from my\s+\w+',
        r'get the app',
        r'download our app',
        # Forward/share prompts
        r'forward to a friend',
        r'share this email',
        r'发送给朋友',
        # Privacy/legal
        r'privacy policy',
        r'terms of service',
        r'隐私政策',
    ]

    # Regex patterns compiled for efficiency
    _compiled_noise_patterns: list[re.Pattern] = []

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the content cleaner.

        Args:
            settings: Application settings containing truncation parameters.
        """
        self.settings = settings
        self.max_length = settings.MAX_CONTENT_LENGTH
        self.truncation_head = settings.CONTENT_TRUNCATION_HEAD
        self.truncation_tail = settings.CONTENT_TRUNCATION_TAIL

        # Compile noise patterns once
        if not self._compiled_noise_patterns:
            self._compiled_noise_patterns = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in self.NOISE_PATTERNS
            ]

    def clean(self, html_content: str) -> str:
        """
        Clean HTML content and convert to Markdown.

        Args:
            html_content: Raw HTML content from email.

        Returns:
            Cleaned Markdown content ready for LLM processing.
        """
        if not html_content:
            return ""

        # Step 1: Remove tracking pixels and hidden elements
        html_content = self._remove_tracking_elements(html_content)

        # Step 2: Parse and clean HTML (BeautifulSoup is very forgiving)
        soup = self._parse_html(html_content)

        # Remove unwanted tags
        self._remove_unwanted_tags(soup)

        # Extract text content
        cleaned_html = str(soup)

        # Step 3: Convert to Markdown with fallback
        markdown = self._html_to_markdown(cleaned_html)

        # Step 4: Remove noise patterns
        markdown = self._remove_noise(markdown)

        # Step 5: Normalize whitespace
        markdown = self._normalize_whitespace(markdown)

        # Step 6: Truncate if necessary
        markdown = self._truncate(markdown)

        logger.debug(f"Cleaned content: {len(html_content)} chars -> {len(markdown)} chars")

        return markdown

    def _parse_html(self, html: str) -> BeautifulSoup:
        """
        Parse HTML content using BeautifulSoup.
        Falls back to html.parser if lxml fails.

        Args:
            html: Raw HTML content.

        Returns:
            BeautifulSoup object.
        """
        # Try lxml first (faster), fall back to html.parser (more forgiving)
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:
            return BeautifulSoup(html, "html.parser")

    def _remove_tracking_elements(self, html: str) -> str:
        """
        Remove tracking pixels and hidden elements.

        Args:
            html: Raw HTML content.

        Returns:
            HTML with tracking elements removed.
        """
        soup = self._parse_html(html)

        # Remove tracking pixels (1x1 images)
        for img in soup.find_all("img"):
            width = img.get("width", "")
            height = img.get("height", "")
            if width in ["1", "0"] or height in ["1", "0"]:
                img.decompose()

        # Remove hidden elements
        for tag in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
            tag.decompose()

        return str(soup)

    def _remove_unwanted_tags(self, soup: BeautifulSoup) -> None:
        """
        Remove script, style, and other non-content tags.

        Args:
            soup: BeautifulSoup object to clean.
        """
        unwanted_tags = ["script", "style", "noscript", "iframe", "object", "embed"]

        for tag_name in unwanted_tags:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, str) and text.strip().startswith("<!--")):
            comment.extract()

    def _html_to_markdown(self, html: str) -> str:
        """
        Convert HTML to Markdown using markdownify.
        Falls back to plain text extraction if conversion fails.

        Args:
            html: HTML content to convert.

        Returns:
            Markdown formatted text.
        """
        try:
            markdown = md(
                html,
                heading_style="atx",
                bullets="-",
                strip=["img"],
                escape_asterisks=False,
                escape_underscores=False,
            )

            # Check if markdownify produced meaningful output
            if markdown and len(markdown.strip()) > 10:
                return markdown

            # Fallback to plain text extraction
            logger.warning("Markdownify produced empty/short output, falling back to plain text")
            return self._extract_plain_text(html)

        except (ValueError, TypeError) as e:
            logger.warning(f"Markdown conversion error: {e}, falling back to plain text")
            return self._extract_plain_text(html)

    def _extract_plain_text(self, html: str) -> str:
        """
        Extract plain text from HTML as fallback.

        Args:
            html: HTML content.

        Returns:
            Plain text extracted from HTML.
        """
        soup = self._parse_html(html)
        return soup.get_text(separator="\n", strip=True)

    def _remove_noise(self, text: str) -> str:
        """
        Remove common noise patterns from text.

        Args:
            text: Text to clean.

        Returns:
            Text with noise patterns removed.
        """
        for pattern in self._compiled_noise_patterns:
            text = pattern.sub("", text)

        # Remove excessive empty lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace and line breaks.

        Args:
            text: Text to normalize.

        Returns:
            Normalized text.
        """
        # Replace multiple spaces with single space
        text = re.sub(r"[ \t]+", " ", text)

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove trailing whitespace from each line
        lines = [line.rstrip() for line in text.split("\n")]

        return "\n".join(lines)

    def _truncate(self, text: str) -> str:
        """
        Truncate text if it exceeds maximum length.
        Uses head + tail strategy to preserve important content.

        Args:
            text: Text to potentially truncate.

        Returns:
            Truncated text with marker if truncation occurred.
        """
        if len(text) <= self.max_length:
            return text

        # Truncate to head + ... + tail
        truncated = (
            text[:self.truncation_head]
            + "\n\n--- [Content Truncated for AI Processing] ---\n\n"
            + text[-self.truncation_tail:]
        )

        logger.warning(
            f"Content truncated: {len(text)} -> {len(truncated)} chars"
        )

        return truncated

    def extract_urls(self, html_content: str) -> list[str]:
        """
        Extract URLs from HTML content.

        Args:
            html_content: Raw HTML content.

        Returns:
            List of unique URLs found in the content.
        """
        soup = self._parse_html(html_content)
        urls: set[str] = set()

        # Extract from anchor tags
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(("http://", "https://")):
                # Skip common tracking and unsubscribe links
                skip_keywords = ["unsubscribe", "tracking", "mailto:", "opt-out"]
                if not any(skip in href.lower() for skip in skip_keywords):
                    urls.add(href)

        return list(urls)