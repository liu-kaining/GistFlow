"""
Gmail IMAP email fetcher module.
Handles connecting to Gmail, searching for labeled emails, and fetching content.
"""

import imaplib
from datetime import datetime
from email.utils import parseaddr
from typing import Optional

from imap_tools import AND, MailBox, MailMessage
from imap_tools.errors import ImapToolsError
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gistflow.config import Settings
from gistflow.core.cleaner import ContentCleaner
from gistflow.database import LocalStore
from gistflow.models import RawEmail


class EmailFetcher:
    """
    Gmail IMAP email fetcher with deduplication support.
    Fetches emails with specific labels and filters already processed ones.

    Label matching is case-insensitive and supports variants:
    - Newsletter, newsletter, NEWSLETTER
    - News, news, NEWS
    - Any label containing the configured TARGET_LABEL (case-insensitive)
    """

    IMAP_SERVER = "imap.gmail.com"
    PROCESSED_LABEL = "GistFlow-Processed"

    # Common newsletter label variants to match (case-insensitive)
    LABEL_VARIANTS = [
        "newsletter",
        "news",
        "newsletters",
    ]

    def __init__(self, settings: Settings, local_store: Optional[LocalStore] = None) -> None:
        """
        Initialize the email fetcher.

        Args:
            settings: Application settings containing Gmail credentials.
            local_store: Optional LocalStore for deduplication. If None, creates new instance.
        """
        self.settings = settings
        self.local_store = local_store or LocalStore()
        self.cleaner = ContentCleaner(settings)
        self._mailbox: Optional[MailBox] = None
        self._matched_labels: Optional[list[str]] = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((imaplib.IMAP4.error, ConnectionError)),
        reraise=True,
    )
    def connect(self) -> None:
        """
        Establish IMAP connection to Gmail.

        Raises:
            imaplib.IMAP4.error: If connection or authentication fails.
        """
        try:
            self._mailbox = MailBox(self.IMAP_SERVER)
            self._mailbox.login(
                self.settings.GMAIL_USER,
                self.settings.GMAIL_APP_PASSWORD,
            )
            logger.info(f"Connected to Gmail as: {self.settings.GMAIL_USER}")
        except imaplib.IMAP4.error as e:
            logger.error(f"Failed to connect to Gmail: {e}")
            raise

    def disconnect(self) -> None:
        """Close IMAP connection."""
        if self._mailbox:
            try:
                self._mailbox.logout()
                logger.info("Disconnected from Gmail")
            except ImapToolsError as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._mailbox = None
                self._matched_labels = None

    def _ensure_connected(self) -> MailBox:
        """
        Ensure mailbox is connected, reconnect if necessary.

        Returns:
            Connected MailBox instance.

        Raises:
            imaplib.IMAP4.error: If reconnection fails.
        """
        if self._mailbox is None:
            self.connect()
        return self._mailbox  # type: ignore

    def _get_matching_labels(self) -> list[str]:
        """
        Get list of labels that match the target label (case-insensitive).
        Also matches common variants like 'news', 'newsletter', etc.

        Returns:
            List of matching label names from Gmail.
        """
        if self._matched_labels is not None:
            return self._matched_labels

        mailbox = self._ensure_connected()
        target_label_lower = self.settings.TARGET_LABEL.lower()

        try:
            # Get all available labels from Gmail using folder.list()
            all_folders = list(mailbox.folder.list())
            matching_labels: list[str] = []

            for folder_info in all_folders:
                # folder_info is FolderInfo object with 'name' attribute
                label_name = folder_info.name

                if not label_name:
                    continue

                # Skip Gmail system folders
                if label_name.startswith('[Gmail]'):
                    continue

                label_lower = label_name.lower()

                # Check if label matches target label (case-insensitive)
                if label_lower == target_label_lower:
                    matching_labels.append(label_name)
                    continue

                # Check if label matches any variant
                for variant in self.LABEL_VARIANTS:
                    if label_lower == variant:
                        matching_labels.append(label_name)
                        break

            if matching_labels:
                logger.info(f"Found matching labels: {matching_labels}")
            else:
                # Fallback to configured label if no matches found
                logger.warning(f"No matching labels found for '{self.settings.TARGET_LABEL}', using as-is")
                matching_labels = [self.settings.TARGET_LABEL]

            self._matched_labels = matching_labels
            return matching_labels

        except ImapToolsError as e:
            logger.warning(f"Failed to list folders, using configured label: {e}")
            return [self.settings.TARGET_LABEL]

    def fetch_unprocessed(self, limit: Optional[int] = None) -> tuple[list[RawEmail], int]:
        """
        Fetch unprocessed emails with the target label.
        First counts total available emails, then fetches up to the limit.

        Label matching is case-insensitive and supports variants.

        Args:
            limit: Maximum number of emails to fetch. Defaults to MAX_EMAILS_PER_RUN from settings.

        Returns:
            Tuple of (list of RawEmail objects, total_count).
            - List contains up to 'limit' emails that haven't been processed yet.
            - total_count is the total number of unprocessed emails available (may be > limit).

        Raises:
            ImapToolsError: If IMAP operation fails.
        """
        if limit is None:
            limit = self.settings.MAX_EMAILS_PER_RUN

        mailbox = self._ensure_connected()
        raw_emails: list[RawEmail] = []
        processed_ids: set[str] = set()
        total_count = 0  # Total unprocessed emails available

        try:
            # Get matching labels (case-insensitive)
            matching_labels = self._get_matching_labels()

            logger.info(f"Searching for unseen emails with labels: {matching_labels}")

            # First pass: Count total unprocessed emails
            all_unprocessed_uids: set[str] = set()
            for label in matching_labels:
                search_criteria = AND(seen=False, gmail_label=label)
                messages = list(mailbox.fetch(
                    criteria=search_criteria,
                    mark_seen=False,
                    reverse=True,
                ))
                
                for msg in messages:
                    # Skip if already counted from another label
                    if msg.uid in all_unprocessed_uids:
                        continue
                    
                    # Check if already processed (deduplication)
                    if self.local_store.is_processed(msg.uid):
                        continue
                    
                    all_unprocessed_uids.add(msg.uid)
            
            total_count = len(all_unprocessed_uids)
            logger.info(f"Found {total_count} total unprocessed emails (will fetch up to {limit})")

            # Second pass: Fetch emails up to limit
            for label in matching_labels:
                # Optimized search: only unseen emails with this label
                search_criteria = AND(seen=False, gmail_label=label)

                # Fetch emails (newest first)
                messages = list(mailbox.fetch(
                    criteria=search_criteria,
                    mark_seen=False,
                    reverse=True,
                ))

                logger.debug(f"Found {len(messages)} unseen emails with label '{label}'")

                for msg in messages:
                    # Skip if already added from another label
                    if msg.uid in processed_ids:
                        continue

                    # Check if already processed (deduplication)
                    if self.local_store.is_processed(msg.uid):
                        continue

                    # Convert to RawEmail
                    raw_email = self._convert_to_raw_email(msg)

                    if raw_email:
                        raw_emails.append(raw_email)
                        processed_ids.add(msg.uid)

                        if len(raw_emails) >= limit:
                            break

                if len(raw_emails) >= limit:
                    break

            remaining = max(0, total_count - len(raw_emails))
            if remaining > 0:
                logger.info(f"Returning {len(raw_emails)} unprocessed emails (total: {total_count}, remaining: {remaining})")
            else:
                logger.info(f"Returning {len(raw_emails)} unprocessed emails (all {total_count} emails will be processed)")

        except ImapToolsError as e:
            logger.error(f"IMAP error fetching emails: {e}")
            raise
        except imaplib.IMAP4.error as e:
            logger.error(f"Gmail IMAP error: {e}")
            raise

        return raw_emails, total_count

    def _convert_to_raw_email(self, msg: MailMessage) -> Optional[RawEmail]:
        """
        Convert imap_tools MailMessage to RawEmail model.

        Args:
            msg: MailMessage from imap_tools.

        Returns:
            RawEmail object or None if conversion fails.
        """
        try:
            # Parse sender info
            sender_name, sender_email = parseaddr(msg.from_)
            if not sender_name:
                sender_name = sender_email or "Unknown"

            # Get content (prefer HTML)
            html_content = msg.html or None
            text_content = msg.text or None

            # Extract URLs from HTML if available
            urls: list[str] = []
            if html_content:
                urls = self.cleaner.extract_urls(html_content)

            # Parse date
            received_date = msg.date or datetime.now()

            return RawEmail(
                message_id=msg.uid or f"no-id-{datetime.now().timestamp()}",
                thread_id=getattr(msg, "thread_id", None),
                subject=msg.subject or "(No Subject)",
                sender=sender_name,
                sender_email=sender_email,
                date=received_date,
                html_content=html_content,
                text_content=text_content,
                labels=list(msg.flags) if hasattr(msg, "flags") else [],
                urls=urls,
            )

        except (ValueError, AttributeError) as e:
            logger.error(f"Failed to convert message: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((imaplib.IMAP4.error, ImapToolsError)),
    )
    def mark_as_processed(self, email_id: str) -> None:
        """
        Mark an email as processed in Gmail.
        Removes all matching labels and marks as read (only after successful Notion write).

        Args:
            email_id: Gmail Message-ID to mark as processed.

        Raises:
            ImapToolsError: If IMAP operation fails.
        """
        mailbox = self._ensure_connected()

        try:
            # Get matching labels
            matching_labels = self._get_matching_labels()

            # Remove all matching labels
            for label in matching_labels:
                try:
                    mailbox.flag(email_id, [label], False)
                    logger.debug(f"Removed label '{label}' from email {email_id}")
                except ImapToolsError as e:
                    logger.warning(f"Could not remove label '{label}': {e}")

            # Mark email as read (\\Seen flag)
            try:
                mailbox.flag(email_id, ['\\Seen'], True)
                logger.debug(f"Marked email {email_id} as read")
            except ImapToolsError as e:
                logger.warning(f"Could not mark email as read: {e}")

            logger.info(f"Email {email_id} marked as processed in Gmail (removed labels: {matching_labels}, marked as read)")

        except ImapToolsError as e:
            logger.error(f"Failed to mark email as processed: {e}")
            raise

    def get_label_stats(self) -> dict:
        """
        Get statistics about emails with the target label.

        Returns:
            Dictionary with stats: total_with_label, unread_with_label
        """
        mailbox = self._ensure_connected()

        try:
            matching_labels = self._get_matching_labels()

            total_count = 0
            unread_count = 0

            for label in matching_labels:
                # Get unread count
                try:
                    unread_criteria = AND(seen=False, label=label)
                    unread_messages = list(mailbox.fetch(criteria=unread_criteria, mark_seen=False))
                    unread_count += len(unread_messages)

                    # Get total count
                    total_criteria = AND(label=label)
                    total_messages = list(mailbox.fetch(criteria=total_criteria, mark_seen=False))
                    total_count += len(total_messages)
                except ImapToolsError as e:
                    logger.warning(f"Error getting stats for label '{label}': {e}")

            return {
                "matched_labels": matching_labels,
                "target_label": self.settings.TARGET_LABEL,
                "total_with_label": total_count,
                "unread_with_label": unread_count,
            }

        except ImapToolsError as e:
            logger.error(f"Failed to get label stats: {e}")
            return {
                "matched_labels": [self.settings.TARGET_LABEL],
                "target_label": self.settings.TARGET_LABEL,
                "total_with_label": 0,
                "unread_with_label": 0,
                "error": str(e),
            }

    def __enter__(self) -> "EmailFetcher":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.disconnect()

    def __del__(self) -> None:
        """Destructor to ensure cleanup."""
        self.disconnect()