"""
LLM Engine module for intelligent content extraction.
Uses LangChain to interact with LLM and force structured JSON output.
"""

import time
from pathlib import Path
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_openai import ChatOpenAI
from loguru import logger
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gistflow.config import Settings
from gistflow.models import Gist


# Default system prompt (fallback if file not found)
DEFAULT_SYSTEM_PROMPT = """You are an expert Tech Information Analyst. Your goal is to process incoming emails (newsletters, technical updates, blogs) and extract high-value knowledge.

Input: Raw email content (Markdown format).
Output: A valid JSON object strictly following the `Gist` schema.

Rules:
1. **Filtering**: If the email is a receipt, pure marketing spam, verification code, or extremely low value, set `is_spam_or_irrelevant` to true.
2. **Scoring**: Score from 0-100.
   - >80: High density technical deep dives, tutorials, breaking news.
   - 40-60: General updates, weekly links without context.
   - <30: Marketing fluff.
3. **Language**: Summarize and extract insights in **Chinese (Simplified)**, unless the content is strictly code or proper nouns.
4. **Formatting**: Keep `key_insights` concise (bullet points style, 3-5 items max).
5. **Tags**: Extract 2-5 relevant category tags (e.g., AI, Dev, Finance, Product, Career).
6. **Links**: Extract any mentioned tools, GitHub repos, articles, or resources.

Remember: Output MUST be a valid JSON object matching the schema exactly."""


# Default user prompt template (fallback if file not found)
DEFAULT_USER_PROMPT_TEMPLATE = """Here is the email content:
---
{email_content}
---

Email metadata:
- Sender: {sender}
- Subject: {subject}
- Date: {date}

Extract the gist now. Output strictly JSON following the schema."""


class GistEngine:
    """
    LLM-powered content analysis engine.
    Extracts structured Gist from raw email content.
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the GistEngine with LangChain ChatOpenAI.

        Args:
            settings: Application settings containing LLM configuration.
        """
        self.settings = settings
        self.llm = self._init_llm()
        self._system_prompt: str = ""
        self._user_prompt_template: str = ""
        self._load_prompts()
        self.prompt = self._build_prompt()

        logger.info(
            f"GistEngine initialized with model: {settings.LLM_MODEL_NAME} "
            f"(base_url: {settings.OPENAI_BASE_URL})"
        )

    def _init_llm(self) -> ChatOpenAI:
        """
        Initialize LangChain ChatOpenAI with settings.

        Returns:
            Configured ChatOpenAI instance.
        """
        return ChatOpenAI(
            model=self.settings.LLM_MODEL_NAME,
            api_key=self.settings.OPENAI_API_KEY,
            base_url=self.settings.OPENAI_BASE_URL,
            temperature=self.settings.LLM_TEMPERATURE,
            max_tokens=self.settings.LLM_MAX_TOKENS,
            timeout=60,
        )

    def _load_prompts(self) -> None:
        """
        Load prompts from files specified in settings.
        Falls back to default prompts if files are not found.
        """
        # Load system prompt
        system_path = Path(self.settings.PROMPT_SYSTEM_PATH)
        if system_path.exists():
            try:
                self._system_prompt = system_path.read_text(encoding="utf-8").strip()
                logger.debug(f"Loaded system prompt from: {system_path}")
            except Exception as e:
                logger.warning(f"Failed to load system prompt from {system_path}: {e}, using default")
                self._system_prompt = DEFAULT_SYSTEM_PROMPT
        else:
            logger.warning(f"System prompt file not found: {system_path}, using default")
            self._system_prompt = DEFAULT_SYSTEM_PROMPT

        # Load user prompt template
        user_path = Path(self.settings.PROMPT_USER_PATH)
        if user_path.exists():
            try:
                self._user_prompt_template = user_path.read_text(encoding="utf-8").strip()
                logger.debug(f"Loaded user prompt template from: {user_path}")
            except Exception as e:
                logger.warning(f"Failed to load user prompt template from {user_path}: {e}, using default")
                self._user_prompt_template = DEFAULT_USER_PROMPT_TEMPLATE
        else:
            logger.warning(f"User prompt template file not found: {user_path}, using default")
            self._user_prompt_template = DEFAULT_USER_PROMPT_TEMPLATE

    def reload_prompts(self) -> None:
        """
        Reload prompts from files.
        Useful for hot-reloading prompts without restarting the service.
        """
        logger.info("Reloading prompts from files...")
        self._load_prompts()
        self.prompt = self._build_prompt()
        logger.info("Prompts reloaded successfully")

    def _build_prompt(self) -> ChatPromptTemplate:
        """
        Build the chat prompt template from loaded prompts.

        Returns:
            ChatPromptTemplate for the LLM.
        """
        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(self._system_prompt),
            HumanMessagePromptTemplate.from_template(self._user_prompt_template),
        ])

    def get_prompts(self) -> dict[str, str]:
        """
        Get current prompt contents.

        Returns:
            Dictionary with 'system_prompt' and 'user_prompt_template'.
        """
        return {
            "system_prompt": self._system_prompt,
            "user_prompt_template": self._user_prompt_template,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError)),
        reraise=True,
    )
    def _call_llm(self, messages: list) -> Gist:
        """
        Call the LLM with retry mechanism.

        Args:
            messages: Formatted messages for the LLM.

        Returns:
            Gist object extracted from LLM response.

        Raises:
            APIError: If all retries fail due to API issues.
        """
        import json
        import re

        # Try structured output first
        try:
            structured_llm = self.llm.with_structured_output(Gist)
            gist = structured_llm.invoke(messages)
            # Normalize mentioned_links in case LLM returns objects
            gist = self._normalize_gist_links(gist)
            return gist
        except Exception as e:
            # If structured output fails (e.g., validation error), fall back to manual parsing
            logger.debug(f"Structured output failed, falling back to manual parsing: {e}")
            pass  # Fall through to manual parsing

        # Fallback: invoke directly and parse JSON manually
        response = self.llm.invoke(messages)
        raw_content = response.content if hasattr(response, 'content') else str(response)

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try raw JSON
            json_str = raw_content.strip()

        # Parse JSON and create Gist
        try:
            data = json.loads(json_str)
            
            # Normalize mentioned_links: handle both string list and object list
            data = self._normalize_data_links(data)
            
            return Gist(**data)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Failed to parse LLM output as Gist: {e}")

    def _normalize_gist_links(self, gist: Gist) -> Gist:
        """
        Normalize mentioned_links in Gist object.
        Handles cases where LLM returns objects instead of strings.
        
        Args:
            gist: Gist object to normalize.
            
        Returns:
            Normalized Gist object.
        """
        if not gist.mentioned_links:
            return gist
        
        normalized_links = []
        for link in gist.mentioned_links:
            if isinstance(link, str):
                normalized_links.append(link)
            elif isinstance(link, dict):
                # Extract URL from object
                url = link.get("url") or link.get("link") or link.get("href") or link.get("value")
                if url and isinstance(url, str):
                    normalized_links.append(url)
                else:
                    logger.warning(f"Skipping link object without valid URL: {link}")
        
        gist.mentioned_links = normalized_links
        return gist
    
    def _normalize_data_links(self, data: dict) -> dict:
        """
        Normalize mentioned_links in data dictionary.
        
        Args:
            data: Dictionary containing Gist data.
            
        Returns:
            Normalized dictionary.
        """
        if "mentioned_links" in data and data["mentioned_links"]:
            normalized_links = []
            for link in data["mentioned_links"]:
                if isinstance(link, str):
                    normalized_links.append(link)
                elif isinstance(link, dict):
                    # Extract URL from object (could be 'url', 'link', 'href', etc.)
                    url = link.get("url") or link.get("link") or link.get("href") or link.get("value")
                    if url and isinstance(url, str):
                        normalized_links.append(url)
                    else:
                        logger.warning(f"Skipping link object without valid URL: {link}")
            data["mentioned_links"] = normalized_links
        return data

    def extract_gist(
        self,
        content: str,
        sender: str = "Unknown",
        subject: str = "(No Subject)",
        date: str = "",
        original_id: Optional[str] = None,
        original_url: Optional[str] = None,
    ) -> Optional[Gist]:
        """
        Extract a Gist from email content using LLM.

        Args:
            content: Cleaned markdown content of the email.
            sender: Email sender name.
            subject: Email subject line.
            date: Email received date string.
            original_id: Original email Message-ID.
            original_url: Original URL if available.

        Returns:
            Gist object if extraction succeeds, None otherwise.
        """
        try:
            logger.info(f"Extracting gist for: {subject[:30]}...")

            # Build messages
            messages = self.prompt.format_messages(
                email_content=content,
                sender=sender,
                subject=subject,
                date=date,
            )

            # Invoke LLM with retry
            start_time = time.time()
            gist = self._call_llm(messages)
            elapsed = time.time() - start_time

            # Fill metadata fields
            gist.original_id = original_id
            gist.sender = sender
            gist.original_url = original_url

            logger.info(
                f"Successfully extracted gist: score={gist.score}, "
                f"spam={gist.is_spam_or_irrelevant}, "
                f"elapsed={elapsed:.2f}s"
            )

            return gist

        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            logger.error(f"LLM API error after retries for {original_id}: {e}")
            return None
        except APIError as e:
            logger.error(f"LLM API error for {original_id}: {e}")
            return None
        except ValueError as e:
            logger.error(f"LLM output parsing error for {original_id}: {e}")
            return None

    def extract_gist_with_fallback(
        self,
        content: str,
        sender: str = "Unknown",
        subject: str = "(No Subject)",
        date: str = "",
        original_id: Optional[str] = None,
        original_url: Optional[str] = None,
    ) -> Gist:
        """
        Extract a Gist with fallback to minimal valid Gist on failure.

        This method guarantees a valid Gist object is returned,
        even if LLM extraction fails. The fallback Gist will have
        minimal information extracted without LLM.

        Args:
            content: Cleaned markdown content of the email.
            sender: Email sender name.
            subject: Email subject line.
            date: Email received date string.
            original_id: Original email Message-ID.
            original_url: Original URL if available.

        Returns:
            Gist object (real extracted or fallback minimal).
        """
        gist = self.extract_gist(
            content=content,
            sender=sender,
            subject=subject,
            date=date,
            original_id=original_id,
            original_url=original_url,
        )

        if gist:
            return gist

        # Fallback: create minimal Gist without LLM
        logger.warning(f"Using fallback Gist generation for {original_id}")

        return Gist(
            title=subject,
            summary="内容处理失败，请手动查看原文。" if content else "无内容",
            score=30,
            tags=["待处理"],
            key_insights=["LLM 处理失败，需人工审核"],
            mentioned_links=[],
            is_spam_or_irrelevant=False,
            original_id=original_id,
            sender=sender,
            original_url=original_url,
            raw_markdown=content[:500] if content else None,
        )

    def test_connection(self) -> bool:
        """
        Test the LLM connection with a simple prompt.

        Returns:
            True if connection works, False otherwise.
        """
        try:
            logger.info("Testing LLM connection...")

            response = self.llm.invoke("Reply with 'OK' to confirm connection.")

            if response and response.content:
                logger.info(f"LLM connection successful: {response.content[:50]}")
                return True

            return False

        except (APIConnectionError, APITimeoutError, RateLimitError, APIError) as e:
            logger.error(f"LLM connection test failed: {e}")
            return False

    def get_model_info(self) -> dict:
        """
        Get information about the configured LLM model.

        Returns:
            Dictionary with model information.
        """
        return {
            "model_name": self.settings.LLM_MODEL_NAME,
            "base_url": self.settings.OPENAI_BASE_URL,
            "temperature": self.settings.LLM_TEMPERATURE,
            "max_tokens": self.settings.LLM_MAX_TOKENS,
        }