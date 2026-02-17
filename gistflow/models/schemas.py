"""
Data models and schemas for GistFlow.
Defines the contract for data flowing through the pipeline.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Gist(BaseModel):
    """
    Gist is the core knowledge unit extracted from an email.
    LLM must output JSON conforming to this structure.
    """

    # LLM-generated fields
    title: str = Field(..., description="Email title, or AI-optimized clearer title")
    summary: str = Field(..., description="Core summary in 100 characters or less (TL;DR)")
    score: int = Field(..., description="Value score (0-100), based on info density and relevance", ge=0, le=100)
    tags: list[str] = Field(default_factory=list, description="Auto-extracted category tags (e.g., AI, Dev, Finance)")
    key_insights: list[str] = Field(default_factory=list, description="3-5 core insight points")
    mentioned_links: list[str] = Field(
        default_factory=list, description="Important links/tools/repositories mentioned in the content"
    )
    is_spam_or_irrelevant: bool = Field(
        False, description="Mark as True if pure ad, receipt, or meaningless content"
    )

    # Metadata fields (filled by Ingestion layer, LLM doesn't generate these)
    original_id: Optional[str] = Field(None, description="Original email Message-ID")
    sender: Optional[str] = Field(None, description="Email sender/brand")
    sender_email: Optional[str] = Field(None, description="Sender email address")
    received_at: Optional[datetime] = Field(None, description="Email received timestamp")
    raw_markdown: Optional[str] = Field(None, description="Cleaned content in Markdown format")
    original_url: Optional[str] = Field(None, description="Original link if available")
    notion_page_id: Optional[str] = Field(None, description="Notion page ID after publishing")
    local_file_path: Optional[str] = Field(None, description="Local file path after saving")

    def is_valuable(self) -> bool:
        """Check if this gist is valuable enough to save to Notion."""
        return not self.is_spam_or_irrelevant and self.score >= 30


class RawEmail(BaseModel):
    """
    Raw email data fetched from Gmail.
    This is the input data structure for the processing pipeline.
    """

    message_id: str = Field(..., description="Gmail Message-ID (unique identifier)")
    thread_id: Optional[str] = Field(None, description="Gmail Thread-ID")
    subject: str = Field(default="(No Subject)", description="Email subject line")
    sender: str = Field(default="Unknown", description="Sender display name")
    sender_email: Optional[str] = Field(None, description="Sender email address")
    date: datetime = Field(..., description="Email received date/time")
    html_content: Optional[str] = Field(None, description="HTML body content")
    text_content: Optional[str] = Field(None, description="Plain text body content")
    labels: list[str] = Field(default_factory=list, description="Gmail labels attached to this email")
    urls: list[str] = Field(default_factory=list, description="Extracted URLs from email content")

    @property
    def content(self) -> str:
        """Get the best available content (HTML preferred, fall back to text)."""
        if self.html_content:
            return self.html_content
        return self.text_content or ""


class ProcessingResult(BaseModel):
    """Result of processing a single email."""

    success: bool = Field(..., description="Whether processing succeeded")
    gist: Optional[Gist] = Field(None, description="Extracted gist if successful")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    email_id: str = Field(..., description="Original email Message-ID")
    processing_time_seconds: Optional[float] = Field(None, description="Time taken to process")


class NotionPageContent(BaseModel):
    """Structured content for creating a Notion page."""

    title: str
    properties: dict
    children_blocks: list[dict]