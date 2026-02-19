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
from apscheduler.schedulers.base import STATE_PAUSED, STATE_RUNNING, STATE_STOPPED
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
            db_path = Path(self.settings.DATA_DIR) / "gistflow.db"
            self.local_store = LocalStore(db_path=db_path)
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
        self._last_run: Optional[dict] = None  # 最近一次执行的详情，供 Web 展示
        self._is_running: bool = False  # 防止并发执行 run_once
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

            # Step 3: Publish (if valuable and not LLM-fallback)
            if gist.is_fallback():
                logger.warning(f"Skipping publish for LLM-fallback gist (content processing failed): {email.message_id}")
            elif gist.is_valuable(min_score=self.settings.MIN_VALUE_SCORE):
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
        # 防止并发执行
        if self._is_running:
            logger.warning("Pipeline is already running, skipping this request")
            return {
                "started_at": datetime.now().isoformat(),
                "emails_found": 0,
                "emails_processed": 0,
                "emails_skipped": 0,
                "gists_created": 0,
                "notion_published": 0,
                "local_saved": 0,
                "errors": 1,
                "finished_at": datetime.now().isoformat(),
                "error_message": "任务正在执行中，请稍后再试",
            }
        
        self._is_running = True
        try:
            logger.info("=" * 60)
            logger.info(f"GistFlow Pipeline Run: {datetime.now().isoformat()}")
            logger.info("=" * 60)

            started_at = datetime.now().isoformat()
            stats = {
                "started_at": started_at,
                "emails_found": 0,
                "emails_processed": 0,
                "emails_skipped": 0,
                "gists_created": 0,
                "notion_published": 0,
                "local_saved": 0,
                "errors": 0,
            }
            self._last_run = {"started_at": started_at, "running": True, "finished_at": None, "stats": stats, "phase": "正在连接邮箱…"}

            try:
                # Fetch unprocessed emails
                emails = []  # 初始化为空列表
                with EmailFetcher(self.settings, self.local_store) as fetcher:
                    # 检查是否已被请求停止
                    if self._shutdown_requested:
                        logger.info("Shutdown requested before fetching emails")
                        if self._last_run and self._last_run.get("running"):
                            self._last_run["phase"] = "已中断"
                        emails = []  # 设置为空列表，跳过后续处理
                    else:
                        self._last_run["phase"] = "正在获取邮件列表…"
                        emails = fetcher.fetch_unprocessed()
                        
                        # 再次检查是否已被请求停止（可能在 fetch 过程中被停止）
                        if self._shutdown_requested:
                            logger.info("Shutdown requested after fetching emails")
                            if self._last_run and self._last_run.get("running"):
                                self._last_run["phase"] = "已中断"
                            # 即使已获取邮件，也跳过处理
                            emails = []
                    
                    stats["emails_found"] = len(emails)
                    # 同步到 _last_run，便于前端轮询时看到进度
                    if self._last_run:
                        self._last_run["stats"] = dict(stats)

                    logger.info(f"Found {len(emails)} unprocessed emails")

                    for i, email in enumerate(emails):
                        if self._last_run and self._last_run.get("running"):
                            self._last_run["phase"] = f"正在处理第 {i + 1}/{len(emails)} 封…"
                            self._last_run["stats"] = dict(stats)
                        if self._shutdown_requested:
                            logger.info("Shutdown requested, stopping processing")
                            # 更新 phase 为已中断
                            if self._last_run and self._last_run.get("running"):
                                self._last_run["phase"] = "已中断"
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
                        finally:
                            # 同步进度，便于任务页轮询时看到最新数字
                            if self._last_run and self._last_run.get("running"):
                                self._last_run["stats"] = dict(stats)

            except ImapToolsError as e:
                logger.error(f"IMAP error during pipeline execution: {e}")
                stats["errors"] += 1
            except sqlite3.Error as e:
                logger.error(f"Database error during pipeline execution: {e}")
                stats["errors"] += 1
            except Exception as e:
                logger.exception(f"Unexpected error in run_once: {e}")
                stats["errors"] += 1

            stats["finished_at"] = datetime.now().isoformat()
            if self._last_run:
                self._last_run["running"] = False
                self._last_run["finished_at"] = stats["finished_at"]
                self._last_run["stats"] = stats
                # 根据错误情况和 shutdown 状态设置不同的 phase
                if self._shutdown_requested and self._last_run.get("phase") != "已中断":
                    # 如果是因为 shutdown 中断的，确保 phase 是已中断
                    self._last_run["phase"] = "已中断"
                elif stats.get("errors", 0) > 0:
                    self._last_run["phase"] = "已完成（有错误）"
                else:
                    self._last_run["phase"] = "已完成"

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
        finally:
            self._is_running = False

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
        Initialize the pipeline with scheduler (but don't start it automatically).
        Scheduler must be started manually via API.
        Also starts the web management interface.
        """
        scheduler = BackgroundScheduler()

        # Add job with interval trigger (but don't start scheduler yet)
        scheduler.add_job(
            self.run_once,
            trigger=IntervalTrigger(minutes=self.settings.CHECK_INTERVAL_MINUTES),
            id="gistflow_pipeline",
            name="GistFlow Email Processing Pipeline",
            max_instances=1,
            misfire_grace_time=300,
        )

        # 不自动启动调度器，必须通过 API 手动启动
        self.scheduler = scheduler
        logger.info(f"Scheduler initialized (not started). Interval: {self.settings.CHECK_INTERVAL_MINUTES} minutes. Use API to start.")

        # Start web server
        self.start_web_server()

        try:
            # Keep the main thread alive
            logger.info("Web interface ready. Use API to start scheduler. Press Ctrl+C to stop.")
            import time
            while not self._shutdown_requested:
                time.sleep(1)  # Sleep for 1 second and check shutdown flag

        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down...")
        finally:
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown(wait=True)
            self.local_store.close()
            logger.info("GistFlow stopped gracefully")

    def start_scheduler(self) -> bool:
        """
        Start the scheduler (if not already running).

        Returns:
            True if scheduler was started, False if it was already running or not initialized.
        """
        if not self.scheduler:
            logger.warning("Cannot start scheduler: scheduler not initialized")
            return False
        
        if self.scheduler.running:
            logger.info("Scheduler already running")
            return True
        
        try:
            self.scheduler.start()
            logger.info(f"Scheduler started with {self.settings.CHECK_INTERVAL_MINUTES} minute interval")
            return True
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            return False

    def stop_scheduler(self) -> bool:
        """
        Stop the scheduler (shutdown).

        Returns:
            True if scheduler was stopped, False if it wasn't running.
        """
        if not self.scheduler:
            logger.warning("Cannot stop scheduler: scheduler not initialized")
            return False
        
        if not self.scheduler.running:
            logger.info("Scheduler already stopped")
            return True
        
        try:
            logger.info("Stopping scheduler...")
            # If there's a running execution, mark it as finished (interrupted)
            if self._last_run and self._last_run.get("running"):
                self._last_run["running"] = False
                if not self._last_run.get("finished_at"):
                    self._last_run["finished_at"] = datetime.now().isoformat()
                self._last_run["phase"] = "已中断"
                if self._last_run.get("stats"):
                    self._last_run["stats"] = dict(self._last_run["stats"])
                logger.info("Marked running execution as finished (interrupted by scheduler stop)")
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
            return True
        except Exception as e:
            logger.error(f"Failed to stop scheduler: {e}")
            return False

    def pause_scheduler(self) -> bool:
        """
        Pause the scheduler (jobs won't run, but scheduler stays alive).

        Returns:
            True if scheduler was paused, False if it wasn't running or already paused.
        """
        if not self.scheduler:
            return False
        
        if not self.scheduler.running:
            logger.warning("Cannot pause scheduler: scheduler is not running")
            return False
        
        try:
            # Check if already paused
            if self.scheduler.state == STATE_PAUSED:
                logger.info("Scheduler already paused")
                return True
            
            # Only pause if running
            if self.scheduler.state == STATE_RUNNING:
                self.scheduler.pause()
                logger.info("Scheduler paused")
                return True
            else:
                logger.warning(f"Cannot pause scheduler: invalid state ({self.scheduler.state})")
                return False
        except Exception as e:
            logger.error(f"Failed to pause scheduler: {e}")
            return False

    def resume_scheduler(self) -> bool:
        """
        Resume the scheduler (if paused).

        Returns:
            True if scheduler was resumed, False if it wasn't paused or not running.
        """
        if not self.scheduler:
            logger.warning("Cannot resume scheduler: scheduler not initialized")
            return False
        
        if not self.scheduler.running:
            logger.warning("Cannot resume scheduler: scheduler is not running (must be started first)")
            return False
        
        try:
            if self.scheduler.state == STATE_PAUSED:
                self.scheduler.resume()
                logger.info("Scheduler resumed")
                return True
            elif self.scheduler.state == STATE_RUNNING:
                logger.info("Scheduler already running")
                return True
            elif self.scheduler.state == STATE_STOPPED:
                logger.warning("Cannot resume scheduler: scheduler is stopped (must be started first)")
                return False
            else:
                logger.warning(f"Scheduler is not in a resumable state (state={self.scheduler.state})")
                return False
        except Exception as e:
            logger.error(f"Failed to resume scheduler: {e}")
            return False

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