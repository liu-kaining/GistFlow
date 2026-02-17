"""
Local SQLite storage for deduplication and state management.
Records processed Message-IDs to prevent duplicate processing.
"""

import sqlite3
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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        """Initialize database schema."""
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

        conn.commit()
        logger.info(f"Database initialized at: {self.db_path}")

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
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("Database connection closed")

    def __enter__(self) -> "LocalStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()