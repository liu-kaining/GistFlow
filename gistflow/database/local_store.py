"""
Local SQLite storage for deduplication and state management.
Records processed Message-IDs to prevent duplicate processing.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


class LocalStore:
    """
    SQLite-based local storage for tracking processed emails.
    Provides deduplication by Message-ID.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the local store.

        Args:
            db_path: Path to SQLite database file. Defaults to data/gistflow.db
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "gistflow.db"

        self.db_path = Path(db_path)
        # Ensure parent directory exists
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create database directory {self.db_path.parent}: {e}")
            raise

        self._conn: Optional[sqlite3.Connection] = None
        # Initialize thread-local storage
        self._thread_local = threading.local()
        
        # Initialize database schema
        try:
            self._init_db()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _get_connection(self) -> sqlite3.Connection:
        """
        Get or create database connection.
        Uses thread-local storage to ensure each thread has its own connection,
        preventing SQLite threading issues.
        """
        # Check if this thread already has a connection
        # Use getattr with default None to safely check for connection attribute
        conn = getattr(self._thread_local, 'connection', None)
        
        if conn is None:
            # Create a new connection for this thread with check_same_thread=False
            # This allows the connection to be used across threads safely
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                self._thread_local.connection = conn
                thread_id = threading.get_ident()
                logger.debug(f"Created database connection for thread {thread_id}")
            except Exception as e:
                logger.error(f"Failed to create database connection: {e}")
                raise
        
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE NOT NULL,
                    subject TEXT,
                    sender TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    score INTEGER,
                    is_spam BOOLEAN DEFAULT FALSE,
                    notion_page_id TEXT
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_message_id ON processed_emails(message_id)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processing_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    error_message TEXT,
                    error_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prompt_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT 'system'
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prompt_type ON prompt_history(prompt_type)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prompt_created_at ON prompt_history(created_at DESC)
            """)

            conn.commit()
            logger.info(f"Database initialized at: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database at {self.db_path}: {e}")
            raise

    def is_processed(self, message_id: str) -> bool:
        """
        Check if an email has already been processed.

        Args:
            message_id: Gmail Message-ID to check.

        Returns:
            True if already processed, False otherwise.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM processed_emails WHERE message_id = ?",
            (message_id,)
        )

        exists = cursor.fetchone() is not None
        if exists:
            logger.debug(f"Email {message_id} already processed, skipping")
        return exists

    def mark_processed(
        self,
        message_id: str,
        subject: str = "",
        sender: str = "",
        score: Optional[int] = None,
        is_spam: bool = False,
        notion_page_id: Optional[str] = None,
    ) -> None:
        """
        Mark an email as processed.

        Args:
            message_id: Gmail Message-ID.
            subject: Email subject (for reference).
            sender: Email sender (for reference).
            score: Value score assigned by LLM.
            is_spam: Whether the email was classified as spam.
            notion_page_id: Notion page ID if created.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO processed_emails
                (message_id, subject, sender, score, is_spam, notion_page_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (message_id, subject, sender, score, is_spam, notion_page_id))

            conn.commit()
            logger.debug(f"Marked email {message_id} as processed (score={score}, spam={is_spam})")
        except sqlite3.Error as e:
            logger.error(f"Failed to mark email as processed: {e}")

    def unmark_processed(self, message_id: str) -> bool:
        """
        Remove an email from processed_emails and processing_errors so it can be
        re-fetched and reprocessed in the next pipeline run.

        Args:
            message_id: Gmail Message-ID to clear.

        Returns:
            True if at least one row was deleted (processed_emails or processing_errors).
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM processed_emails WHERE message_id = ?", (message_id,))
            deleted_pe = cursor.rowcount
            cursor.execute("DELETE FROM processing_errors WHERE message_id = ?", (message_id,))
            deleted_err = cursor.rowcount
            conn.commit()
            if deleted_pe or deleted_err:
                logger.info(f"Unmarked {message_id} for reprocess (processed_emails={deleted_pe}, errors={deleted_err})")
            return deleted_pe > 0 or deleted_err > 0
        except sqlite3.Error as e:
            logger.error(f"Failed to unmark processed: {e}")
            return False

    def record_error(self, message_id: str, error_message: str) -> None:
        """
        Record a processing error for an email.

        Args:
            message_id: Gmail Message-ID.
            error_message: Error description.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO processing_errors (message_id, error_message)
                VALUES (?, ?)
            """, (message_id, error_message))

            conn.commit()
            logger.warning(f"Recorded error for email {message_id}: {error_message}")
        except sqlite3.Error as e:
            logger.error(f"Failed to record error: {e}")

    def get_stats(self) -> dict:
        """
        Get processing statistics.

        Returns:
            Dictionary with stats: total_processed, total_spam, total_errors, avg_score
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM processed_emails")
        total_processed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM processed_emails WHERE is_spam = 1")
        total_spam = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM processing_errors")
        total_errors = cursor.fetchone()[0]

        cursor.execute("SELECT AVG(score) FROM processed_emails WHERE score IS NOT NULL")
        avg_score_row = cursor.fetchone()
        avg_score = round(avg_score_row[0], 1) if avg_score_row[0] else 0.0

        return {
            "total_processed": total_processed,
            "total_spam": total_spam,
            "total_errors": total_errors,
            "avg_score": avg_score,
        }

    def get_recent_processed(self, limit: int = 10) -> list[dict]:
        """
        Get recently processed emails.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of recent processing records.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT message_id, subject, sender, processed_at, score, is_spam
            FROM processed_emails
            ORDER BY processed_at DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def close(self) -> None:
        """Close database connection(s)."""
        # Close thread-local connections
        # Note: We can't iterate over all threads, so we only close the current thread's connection
        if hasattr(self, '_thread_local'):
            try:
                if hasattr(self._thread_local, 'connection') and self._thread_local.connection:
                    try:
                        self._thread_local.connection.close()
                        self._thread_local.connection = None
                        logger.debug("Thread-local database connection closed")
                    except Exception as e:
                        logger.warning(f"Error closing thread-local connection: {e}")
            except AttributeError:
                # thread_local may not have connection attribute in this thread
                pass
        
        # Close main connection if exists (for backward compatibility)
        if self._conn:
            try:
                self._conn.close()
                self._conn = None
                logger.debug("Main database connection closed")
            except Exception as e:
                logger.warning(f"Error closing main connection: {e}")

    def __enter__(self) -> "LocalStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def save_prompt_version(
        self,
        prompt_type: str,
        content: str,
        created_by: str = "system",
    ) -> int:
        """
        Save a prompt version to history.

        Args:
            prompt_type: Type of prompt ('system' or 'user').
            content: Prompt content.
            created_by: Creator identifier (default: 'system').

        Returns:
            ID of the saved prompt version.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO prompt_history (prompt_type, content, created_by)
            VALUES (?, ?, ?)
        """, (prompt_type, content, created_by))

        conn.commit()
        prompt_id = cursor.lastrowid
        logger.debug(f"Saved prompt version: {prompt_type} (id: {prompt_id})")
        return prompt_id

    def get_prompt_history(
        self,
        prompt_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get prompt history.

        Args:
            prompt_type: Filter by prompt type ('system' or 'user'). None for all.
            limit: Maximum number of records to return.

        Returns:
            List of prompt history records.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if prompt_type:
            cursor.execute("""
                SELECT id, prompt_type, content, created_at, created_by
                FROM prompt_history
                WHERE prompt_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (prompt_type, limit))
        else:
            cursor.execute("""
                SELECT id, prompt_type, content, created_at, created_by
                FROM prompt_history
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def get_prompt_version(self, prompt_id: int) -> Optional[dict]:
        """
        Get a specific prompt version by ID.

        Args:
            prompt_id: Prompt version ID.

        Returns:
            Prompt version record or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, prompt_type, content, created_at, created_by
            FROM prompt_history
            WHERE id = ?
        """, (prompt_id,))

        row = cursor.fetchone()
        return {key: row[key] for key in row.keys()} if row else None