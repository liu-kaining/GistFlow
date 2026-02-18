#!/usr/bin/env python3
"""
GistFlow Main Entry Point.
Orchestrates the complete email processing pipeline with scheduling.
Supports dual publishing: Notion and local Markdown/JSON files.
"""

import signal
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from imap_tools.errors import ImapToolsError
from loguru import logger
from notion_client.errors import APIResponseError, HTTPResponseError
from openai import APIError

from gistflow.config import get_settings
from gistflow.core import ContentCleaner, EmailFetcher, GistEngine, LocalPublisher, NotionPublisher
from gistflow.database import LocalStore
from gistflow.models import Gist, RawEmail
from gistflow.utils import setup_logger
from gistflow.web import create_app


class GistFlowPipeline:
    """
    Main pipeline orchestrator for GistFlow.
    Coordinates email fetching, LLM processing, and dual publishing (Notion + Local).
    """

    def __init__(self) -> None:
        """Initialize the pipeline with all required components."""
        try:
            logger.info("Loading settings...")
            self.settings = get_settings()
            logger.info("Setting up logger...")
            setup_logger(
                log_level=self.settings.LOG_LEVEL,
                log_dir=Path(__file__).parent / "logs",
            )

            logger.info("Initializing LocalStore...")
            self.local_store = LocalStore()
            logger.info("Initializing ContentCleaner...")
            self.cleaner = ContentCleaner(self.settings)
            logger.info("Initializing GistEngine...")
            self.llm_engine = GistEngine(self.settings)
        except Exception as e:
            logger.exception(f"Failed to initialize pipeline components: {e}")
            raise

        # Dual publishers
        self.notion_publisher: Optional[NotionPublisher] = None
        self.local_publisher: Optional[LocalPublisher] = None
        self._init_publishers()

        self._shutdown_requested = False
        self.scheduler: Optional[BackgroundScheduler] = None
        self._web_thread: Optional[threading.Thread] = None
        self._setup_signal_handlers()

        # Log publisher status
        publishers = []
        if self.notion_publisher:
            publishers.append("Notion")
        if self.local_publisher:
            publishers.append(f"Local({self.settings.LOCAL_STORAGE_FORMAT})")
        logger.info(f"GistFlow Pipeline initialized | Publishers: {', '.join(publishers) or 'None'}")

    def _init_publishers(self) -> None:
        """Initialize publishers based on configuration."""
        # Notion publisher
        try:
            if self.settings.NOTION_API_KEY and self.settings.NOTION_DATABASE_ID:
                self.notion_publisher = NotionPublisher(self.settings)
        except Exception as e:
            logger.warning(f"Failed to initialize Notion publisher: {e}")

        # Local publisher
        if self.settings.ENABLE_LOCAL_STORAGE:
            self.local_publisher = LocalPublisher(self.settings)

    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown signal handlers."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        """
        Handle shutdown signals gracefully.

        Args:
            signum: Signal number.
            frame: Current stack frame.
        """
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._shutdown_requested = True

    def process_single_email(self, email: RawEmail) -> Optional[Gist]:
        """
        Process a single email through the complete pipeline.

        Args:
            email: RawEmail object to process.

        Returns:
            Gist object if successful, None otherwise.
        """
        logger.info(f"Processing email: {email.subject[:50]}...")

        try:
            # Step 1: Clean content
            logger.debug("Step 1: Cleaning content...")
            cleaned_content = self.cleaner.clean(email.content)

            if not cleaned_content or len(cleaned_content) < 50:
                logger.warning(f"Email content too short or empty, skipping")
                return None

            # Step 2: Extract Gist using LLM
            logger.debug("Step 2: Extracting gist with LLM...")
            gist = self.llm_engine.extract_gist_with_fallback(
                content=cleaned_content,
                sender=email.sender,
                subject=email.subject,
                date=email.date.isoformat() if email.date else "",
                original_id=email.message_id,
                original_url=email.urls[0] if email.urls else None,
            )

            # Fill metadata
            gist.raw_markdown = cleaned_content
            gist.sender_email = email.sender_email
            gist.received_at = email.date

            # Step 3: Publish (if valuable)
            if gist.is_valuable(min_score=self.settings.MIN_VALUE_SCORE):
                self._publish_gist(gist)
            else:
                logger.info(f"Skipping publish (score={gist.score}, threshold={self.settings.MIN_VALUE_SCORE}, spam={gist.is_spam_or_irrelevant})")

            return gist

        except APIError as e:
            error_msg = f"LLM API error: {str(e)}"
            logger.error(f"LLM API error processing email {email.message_id}: {e}")
            self.local_store.record_error(email.message_id, error_msg)
            return None
        except (APIResponseError, HTTPResponseError) as e:
            error_msg = f"Notion API error: {str(e)}"
            logger.error(f"Notion API error processing email {email.message_id}: {e}")
            self.local_store.record_error(email.message_id, error_msg)
            return None
        except ValueError as e:
            error_msg = f"Data validation error: {str(e)}"
            logger.error(f"Data validation error processing email {email.message_id}: {e}")
            self.local_store.record_error(email.message_id, error_msg)
            return None
        except Exception as e:
            # Catch-all for any unexpected errors
            error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
            logger.exception(f"Unexpected error processing email {email.message_id}: {e}")
            self.local_store.record_error(email.message_id, error_msg)
            return None

    def _publish_gist(self, gist: Gist) -> None:
        """
        Publish gist to configured destinations.

        Args:
            gist: The Gist object to publish.
        """
        # Publish to Notion
        if self.notion_publisher:
            logger.debug("Publishing to Notion...")
            try:
                page_id = self.notion_publisher.push(gist)
                if page_id:
                    gist.notion_page_id = page_id
                    logger.success(f"Published to Notion: {page_id}")
                else:
                    logger.warning("Failed to publish to Notion")
            except (APIResponseError, HTTPResponseError) as e:
                logger.error(f"Notion publish error: {e}")

        # Publish to Local
        if self.local_publisher:
            logger.debug("Publishing to local storage...")
            try:
                file_path = self.local_publisher.push(gist)
                if file_path:
                    gist.local_file_path = file_path  # type: ignore
                    logger.success(f"Saved locally: {file_path}")
                else:
                    logger.warning("Failed to save locally")
            except OSError as e:
                logger.error(f"Local publish error: {e}")

    def run_once(self) -> dict:
        """
        Run the pipeline once (single execution).

        Returns:
            Dictionary with execution statistics.
        """
        logger.info("=" * 60)
        logger.info(f"GistFlow Pipeline Run: {datetime.now().isoformat()}")
        logger.info("=" * 60)

        stats = {
            "started_at": datetime.now().isoformat(),
            "emails_found": 0,
            "emails_processed": 0,
            "emails_skipped": 0,
            "gists_created": 0,
            "notion_published": 0,
            "local_saved": 0,
            "errors": 0,
        }

        try:
            # Fetch unprocessed emails
            with EmailFetcher(self.settings, self.local_store) as fetcher:
                emails = fetcher.fetch_unprocessed()
                stats["emails_found"] = len(emails)

                logger.info(f"Found {len(emails)} unprocessed emails")

                for email in emails:
                    if self._shutdown_requested:
                        logger.info("Shutdown requested, stopping processing")
                        break

                    try:
                        gist = self.process_single_email(email)

                        if gist:
                            stats["emails_processed"] += 1

                            # Mark as processed in local store
                            try:
                                self.local_store.mark_processed(
                                    message_id=email.message_id,
                                    subject=email.subject,
                                    sender=email.sender,
                                    score=gist.score,
                                    is_spam=gist.is_spam_or_irrelevant,
                                    notion_page_id=gist.notion_page_id,
                                )
                            except Exception as e:
                                logger.error(f"Failed to mark email as processed in database: {e}")
                                # Continue processing other emails even if DB write fails

                            # Mark as processed in Gmail (only after successful processing)
                            try:
                                fetcher.mark_as_processed(email.message_id)
                            except ImapToolsError as e:
                                logger.warning(f"Failed to mark email as processed in Gmail: {e}")
                                # Don't fail the whole pipeline if Gmail marking fails

                            if gist.is_valuable(min_score=self.settings.MIN_VALUE_SCORE):
                                stats["gists_created"] += 1
                                if gist.notion_page_id:
                                    stats["notion_published"] += 1
                                if hasattr(gist, 'local_file_path') and gist.local_file_path:
                                    stats["local_saved"] += 1
                        else:
                            stats["emails_skipped"] += 1
                    except Exception as e:
                        # Catch any unexpected errors during email processing
                        logger.exception(f"Unexpected error processing email {email.message_id}: {e}")
                        self.local_store.record_error(email.message_id, f"Unexpected error: {type(e).__name__}: {str(e)}")
                        stats["emails_skipped"] += 1
                        stats["errors"] += 1
                        # Continue processing next email
                        continue

        except ImapToolsError as e:
            logger.error(f"IMAP error during pipeline execution: {e}")
            stats["errors"] += 1
        except sqlite3.Error as e:
            logger.error(f"Database error during pipeline execution: {e}")
            stats["errors"] += 1

        stats["finished_at"] = datetime.now().isoformat()

        # Log summary
        logger.info("=" * 60)
        logger.info("Pipeline Run Summary:")
        logger.info(f"  Emails Found: {stats['emails_found']}")
        logger.info(f"  Emails Processed: {stats['emails_processed']}")
        logger.info(f"  Emails Skipped: {stats['emails_skipped']}")
        logger.info(f"  Gists Created: {stats['gists_created']}")
        logger.info(f"  Notion Published: {stats['notion_published']}")
        logger.info(f"  Local Saved: {stats['local_saved']}")
        logger.info("=" * 60)

        return stats

    def start_web_server(self) -> None:
        """
        Start Flask web server in a separate thread.
        """
        try:
            app = create_app(pipeline_instance=self, local_store=self.local_store)
            host = self.settings.WEB_SERVER_HOST
            port = self.settings.WEB_SERVER_PORT

            def run_server():
                try:
                    logger.info(f"Starting web server on {host}:{port}")
                    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
                except Exception as e:
                    logger.exception(f"Web server error: {e}")
                    raise

            self._web_thread = threading.Thread(target=run_server, daemon=True)
            self._web_thread.start()
            # Give the server a moment to start
            import time
            time.sleep(0.5)
            logger.info(f"Web management interface available at http://{host}:{port}")
        except Exception as e:
            logger.exception(f"Failed to start web server: {e}")
            raise

    def run_scheduled(self) -> None:
        """
        Run the pipeline with scheduling.
        Uses APScheduler to run at configured intervals.
        Also starts the web management interface.
        """
        scheduler = BackgroundScheduler()

        # Add job with interval trigger
        scheduler.add_job(
            self.run_once,
            trigger=IntervalTrigger(minutes=self.settings.CHECK_INTERVAL_MINUTES),
            id="gistflow_pipeline",
            name="GistFlow Email Processing Pipeline",
            max_instances=1,
            misfire_grace_time=300,
        )

        logger.info(f"Starting scheduler with {self.settings.CHECK_INTERVAL_MINUTES} minute interval")

        scheduler.start()
        self.scheduler = scheduler

        # Start web server
        self.start_web_server()

        try:
            # Run once immediately on startup
            logger.info("Running initial pipeline execution...")
            self.run_once()

            # Keep the main thread alive
            logger.info("Scheduler started. Press Ctrl+C to stop.")
            import time
            while not self._shutdown_requested:
                time.sleep(1)  # Sleep for 1 second and check shutdown flag

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down scheduler...")
        finally:
            scheduler.shutdown(wait=True)
            self.local_store.close()
            logger.info("GistFlow stopped gracefully")

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.local_store.close()


def main() -> None:
    """
    Main entry point for GistFlow.
    """
    logger.info("=" * 60)
    logger.info("  GistFlow - Newsletter Knowledge Pipeline")
    logger.info("=" * 60)

    try:
        logger.info("Initializing GistFlow pipeline...")
        pipeline = GistFlowPipeline()
        logger.info("Pipeline initialized successfully")

        # Check if running in one-shot mode
        if len(sys.argv) > 1 and sys.argv[1] == "--once":
            logger.info("Running in one-shot mode")
            stats = pipeline.run_once()
            pipeline.cleanup()

            # Exit with appropriate code
            sys.exit(0 if stats["errors"] == 0 else 1)
        else:
            # Run with scheduler
            logger.info("Starting scheduled mode with web interface...")
            pipeline.run_scheduled()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except ValueError as e:
        logger.exception(f"Configuration error: {e}")
        sys.exit(1)
    except sqlite3.Error as e:
        logger.exception(f"Database error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error during startup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()