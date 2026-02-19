"""
Flask REST API for GistFlow web management interface.
"""

import json
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request
from loguru import logger

from gistflow.config import get_settings, reload_settings
from gistflow.database import LocalStore


def create_app(pipeline_instance=None, local_store: Optional[LocalStore] = None) -> Flask:
    """
    Create Flask application instance.

    Args:
        pipeline_instance: GistFlowPipeline instance for task control.
        local_store: LocalStore instance for database access.

    Returns:
        Configured Flask application.
    """
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config["pipeline"] = pipeline_instance
    app.config["local_store"] = local_store

    @app.route("/api/health", methods=["GET"])
    def health() -> dict:
        """Health check endpoint."""
        return jsonify({"status": "ok", "service": "GistFlow"})

    @app.route("/api/config", methods=["GET"])
    def get_config() -> dict:
        """Get current configuration (with sensitive fields masked)."""
        try:
            # Ensure .env file exists
            from gistflow.config import ensure_env_file
            ensure_env_file()
            
            settings = get_settings()
            config_dict = settings.model_dump()

            # Mask sensitive fields (but keep original for editing)
            sensitive_fields = [
                "GMAIL_APP_PASSWORD",
                "OPENAI_API_KEY",
                "NOTION_API_KEY",
            ]
            masked_dict = config_dict.copy()
            for field in sensitive_fields:
                if field in masked_dict and masked_dict[field]:
                    masked_dict[field] = "****" + masked_dict[field][-4:] if len(masked_dict[field]) > 4 else "****"

            return jsonify({
                "config": masked_dict,
                "has_env_file": Path(".env").exists(),
                "sensitive_fields": sensitive_fields,  # List of fields that are masked
            })
        except Exception as e:
            logger.exception(f"Failed to get config: {e}")
            return jsonify({"error": str(e), "config": {}, "has_env_file": False}), 500

    @app.route("/api/config", methods=["POST"])
    def update_config() -> dict:
        """Update configuration by writing to .env file."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            # Ensure .env file exists
            from gistflow.config import ensure_env_file
            ensure_env_file()

            env_path = Path(".env")
            if not env_path.exists():
                return jsonify({"success": False, "error": ".env file not found and could not be created"}), 500

            # Validate required fields are not empty
            required_fields = ["GMAIL_USER", "GMAIL_APP_PASSWORD", "OPENAI_API_KEY", "NOTION_API_KEY", "NOTION_DATABASE_ID"]
            missing_fields = [field for field in required_fields if not data.get(field)]
            if missing_fields:
                return jsonify({
                    "success": False,
                    "error": f"Required fields cannot be empty: {', '.join(missing_fields)}"
                }), 400

            # Read existing .env
            try:
                env_lines = env_path.read_text(encoding="utf-8").splitlines()
            except Exception as e:
                logger.error(f"Failed to read .env file: {e}")
                return jsonify({"success": False, "error": f"Failed to read .env file: {e}"}), 500

            # Update values
            env_dict = {}
            for line in env_lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_dict[key.strip()] = value.strip()

            # Update with new values
            # Handle masked passwords: if value is masked (starts with ****), keep original value
            for key, value in data.items():
                str_value = str(value)
                # If the value is masked (starts with ****), don't update it
                if str_value.startswith("****") and key in env_dict:
                    continue
                if key in env_dict:
                    env_dict[key] = str_value
                else:
                    # Add new key
                    env_dict[key] = str_value

            # Write back to .env
            env_content = []
            for line in env_lines:
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#"):
                    env_content.append(line)
                elif "=" in line_stripped:
                    key = line_stripped.split("=", 1)[0].strip()
                    if key in env_dict:
                        env_content.append(f"{key}={env_dict[key]}")
                        del env_dict[key]
                    else:
                        env_content.append(line)

            # Add any new keys
            for key, value in env_dict.items():
                env_content.append(f"{key}={value}")

            # Write with error handling
            try:
                env_path.write_text("\n".join(env_content), encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to write .env file: {e}")
                return jsonify({"success": False, "error": f"Failed to write .env file: {e}"}), 500

            # Reload settings with validation
            try:
                reload_settings()
            except Exception as e:
                logger.error(f"Failed to reload settings: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Configuration saved but validation failed: {e}. Please check your configuration."
                }), 400

            return jsonify({"success": True, "message": "Configuration updated"})

        except Exception as e:
            logger.exception(f"Failed to update config: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/prompts", methods=["GET"])
    def get_prompts() -> dict:
        """Get current prompts."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline or not hasattr(pipeline, "llm_engine"):
                return jsonify({"error": "Pipeline not available"}), 503

            prompts = pipeline.llm_engine.get_prompts()
            return jsonify(prompts)

        except Exception as e:
            logger.error(f"Failed to get prompts: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/prompts", methods=["POST"])
    def update_prompts() -> dict:
        """Update prompts and save to files."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            settings = get_settings()
            system_content = data.get("system_prompt", "").strip()
            user_content = data.get("user_prompt_template", "").strip()

            # Validate content is not empty
            if not system_content:
                return jsonify({"success": False, "error": "System prompt cannot be empty"}), 400
            if not user_content:
                return jsonify({"success": False, "error": "User prompt template cannot be empty"}), 400

            # Validate content length
            if len(system_content) > 100000:
                return jsonify({"success": False, "error": "System prompt too long (max 100000 characters)"}), 400
            if len(user_content) > 100000:
                return jsonify({"success": False, "error": "User prompt template too long (max 100000 characters)"}), 400

            local_store = app.config.get("local_store")

            # Save system prompt
            try:
                system_path = Path(settings.PROMPT_SYSTEM_PATH)
                system_path.parent.mkdir(parents=True, exist_ok=True)
                system_path.write_text(system_content, encoding="utf-8")

                # Save to history
                if local_store:
                    local_store.save_prompt_version("system", system_content, "web")
            except Exception as e:
                logger.error(f"Failed to save system prompt: {e}")
                return jsonify({"success": False, "error": f"Failed to save system prompt: {e}"}), 500

            # Save user prompt
            try:
                user_path = Path(settings.PROMPT_USER_PATH)
                user_path.parent.mkdir(parents=True, exist_ok=True)
                user_path.write_text(user_content, encoding="utf-8")

                # Save to history
                if local_store:
                    local_store.save_prompt_version("user", user_content, "web")
            except Exception as e:
                logger.error(f"Failed to save user prompt: {e}")
                return jsonify({"success": False, "error": f"Failed to save user prompt: {e}"}), 500

            # Reload prompts in engine
            pipeline = app.config.get("pipeline")
            if pipeline and hasattr(pipeline, "llm_engine"):
                try:
                    pipeline.llm_engine.reload_prompts()
                except Exception as e:
                    logger.error(f"Failed to reload prompts: {e}")
                    return jsonify({
                        "success": False,
                        "error": f"Prompts saved but reload failed: {e}. Please restart the service."
                    }), 500

            return jsonify({"success": True, "message": "Prompts updated and reloaded"})

        except Exception as e:
            logger.exception(f"Failed to update prompts: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/prompts/reload", methods=["POST"])
    def reload_prompts() -> dict:
        """Reload prompts from files."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline or not hasattr(pipeline, "llm_engine"):
                return jsonify({"error": "Pipeline not available"}), 503

            pipeline.llm_engine.reload_prompts()
            return jsonify({"success": True, "message": "Prompts reloaded"})

        except Exception as e:
            logger.error(f"Failed to reload prompts: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/prompts/test", methods=["POST"])
    def test_prompt() -> dict:
        """Test prompt with sample content."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            test_content = data.get("content", "").strip()
            if not test_content:
                return jsonify({"success": False, "error": "Test content cannot be empty"}), 400

            if len(test_content) > 50000:
                return jsonify({"success": False, "error": "Test content too long (max 50000 characters)"}), 400

            sender = data.get("sender", "Test Sender")
            subject = data.get("subject", "Test Subject")
            date = data.get("date", "")

            pipeline = app.config.get("pipeline")
            if not pipeline or not hasattr(pipeline, "llm_engine"):
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            # Use temporary prompt if provided
            temp_system = data.get("system_prompt")
            temp_user = data.get("user_prompt_template")

            if temp_system or temp_user:
                # Create temporary engine for testing
                from gistflow.core import GistEngine
                from gistflow.config import get_settings

                test_settings = get_settings()
                test_engine = GistEngine(test_settings)
                if temp_system:
                    test_engine._system_prompt = temp_system
                if temp_user:
                    test_engine._user_prompt_template = temp_user
                test_engine.prompt = test_engine._build_prompt()
            else:
                test_engine = pipeline.llm_engine

            # Extract gist with timeout protection
            try:
                gist = test_engine.extract_gist(
                    content=test_content,
                    sender=sender,
                    subject=subject,
                    date=date,
                )

                if gist:
                    return jsonify({"success": True, "gist": gist.model_dump()})
                else:
                    return jsonify({"success": False, "error": "Failed to extract gist (LLM returned None)"}), 500

            except Exception as e:
                logger.exception(f"Error during prompt test: {e}")
                return jsonify({"success": False, "error": f"Test failed: {str(e)}"}), 500

        except Exception as e:
            logger.exception(f"Failed to test prompt: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/prompts/history", methods=["GET"])
    def get_prompt_history() -> dict:
        """Get prompt history."""
        try:
            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"error": "LocalStore not available"}), 503

            prompt_type = request.args.get("type")  # 'system' or 'user'
            limit = int(request.args.get("limit", 50))

            history = local_store.get_prompt_history(prompt_type=prompt_type, limit=limit)
            # Convert datetime objects to strings for JSON serialization
            for item in history:
                if "created_at" in item and item["created_at"]:
                    created_at = item["created_at"]
                    if hasattr(created_at, "isoformat"):
                        item["created_at"] = created_at.isoformat()
                    elif not isinstance(created_at, str):
                        item["created_at"] = str(created_at)
                # Ensure all values are JSON serializable
                for key, value in list(item.items()):
                    if value is None:
                        item[key] = None
                    elif isinstance(value, (int, float, str, bool)):
                        pass  # Already serializable
                    else:
                        try:
                            item[key] = str(value)
                        except Exception:
                            item[key] = None
            return jsonify({"history": history})

        except Exception as e:
            logger.error(f"Failed to get prompt history: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/prompts/restore", methods=["POST"])
    def restore_prompt() -> dict:
        """Restore a prompt version from history."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            version_id = data.get("version_id")
            if not version_id:
                return jsonify({"success": False, "error": "version_id required"}), 400

            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"success": False, "error": "LocalStore not available"}), 503

            # Get prompt version
            prompt_version = local_store.get_prompt_version(version_id)
            if not prompt_version:
                return jsonify({"success": False, "error": "Prompt version not found"}), 404

            settings = get_settings()
            prompt_type = prompt_version.get("prompt_type")
            content = prompt_version.get("content", "")

            if not prompt_type or not content:
                return jsonify({"success": False, "error": "Invalid prompt version data"}), 400

            # Save to file
            try:
                if prompt_type == "system":
                    system_path = Path(settings.PROMPT_SYSTEM_PATH)
                    system_path.parent.mkdir(parents=True, exist_ok=True)
                    system_path.write_text(content, encoding="utf-8")
                elif prompt_type == "user":
                    user_path = Path(settings.PROMPT_USER_PATH)
                    user_path.parent.mkdir(parents=True, exist_ok=True)
                    user_path.write_text(content, encoding="utf-8")
                else:
                    return jsonify({"success": False, "error": f"Unknown prompt type: {prompt_type}"}), 400
            except Exception as e:
                logger.error(f"Failed to save restored prompt to file: {e}")
                return jsonify({"success": False, "error": f"Failed to save prompt: {e}"}), 500

            # Reload prompts in engine
            pipeline = app.config.get("pipeline")
            if pipeline and hasattr(pipeline, "llm_engine"):
                try:
                    pipeline.llm_engine.reload_prompts()
                except Exception as e:
                    logger.error(f"Failed to reload prompts after restore: {e}")
                    return jsonify({
                        "success": False,
                        "error": f"Prompt restored but reload failed: {e}. Please restart the service."
                    }), 500

            return jsonify({"success": True, "message": f"{prompt_type} prompt restored"})

        except Exception as e:
            logger.exception(f"Failed to restore prompt: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/status", methods=["GET"])
    def get_task_status() -> dict:
        """Get task scheduler status and last run details."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"error": "Pipeline not available"}), 503

            scheduler = getattr(pipeline, "scheduler", None)
            if scheduler:
                if scheduler.running:
                    try:
                        jobs = scheduler.get_jobs()
                        # APScheduler state: STATE_STOPPED=0, STATE_PAUSED=1, STATE_RUNNING=2
                        scheduler_state = getattr(scheduler, "state", 0)
                        is_paused = scheduler_state == 1  # STATE_PAUSED
                        next_run_time = None
                        if jobs and jobs[0].next_run_time:
                            next_run_time = jobs[0].next_run_time.isoformat() if hasattr(jobs[0].next_run_time, 'isoformat') else str(jobs[0].next_run_time)
                        status = {
                            "running": True,
                            "paused": is_paused,
                            "next_run_time": next_run_time,
                            "interval_minutes": getattr(pipeline, "settings", None) and getattr(pipeline.settings, "CHECK_INTERVAL_MINUTES", None) or None,
                            "jobs": [{"id": job.id, "name": job.name, "next_run": str(job.next_run_time)} for job in jobs],
                        }
                    except Exception as e:
                        logger.warning(f"Failed to get scheduler status: {e}")
                        status = {"running": False, "paused": False, "next_run_time": None, "jobs": []}
                else:
                    # 调度器已初始化但未启动，仍返回间隔供前端展示
                    status = {
                        "running": False,
                        "paused": False,
                        "next_run_time": None,
                        "interval_minutes": getattr(pipeline, "settings", None) and getattr(pipeline.settings, "CHECK_INTERVAL_MINUTES", None) or None,
                        "jobs": [],
                    }
            else:
                status = {
                    "running": False,
                    "paused": False,
                    "next_run_time": None,
                    "interval_minutes": getattr(pipeline, "settings", None) and getattr(pipeline.settings, "CHECK_INTERVAL_MINUTES", None) or None,
                    "jobs": [],
                }

            last_run = getattr(pipeline, "_last_run", None)
            if last_run is not None:
                status["last_run"] = last_run
            return jsonify(status)

        except Exception as e:
            logger.error(f"Failed to get task status: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/tasks/run", methods=["POST"])
    def run_task() -> dict:
        """Manually trigger a single pipeline run."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            # 检查是否已有任务在执行
            is_running = getattr(pipeline, "_is_running", False)
            last_run = getattr(pipeline, "_last_run", None)
            
            # 如果 _is_running 为 True，但 _last_run 显示任务已完成，说明状态不一致，强制重置
            if is_running and last_run:
                if not last_run.get("running") and last_run.get("finished_at"):
                    logger.warning(f"Detected inconsistent state: _is_running=True but _last_run indicates finished. Resetting _is_running.")
                    pipeline._is_running = False
                    is_running = False
            
            if is_running:
                return jsonify({
                    "success": False,
                    "error": "任务正在执行中，请等待当前任务完成后再试",
                }), 409  # Conflict

            # 在后台线程中异步执行，避免阻塞 Flask 请求
            import threading
            def run_in_background():
                try:
                    pipeline.run_once()
                except Exception as e:
                    logger.exception(f"Background task execution failed: {e}")
                    # 确保即使异常也重置运行标志
                    if hasattr(pipeline, "_is_running"):
                        pipeline._is_running = False
                    # 更新 _last_run 状态，如果不存在则创建
                    from datetime import datetime
                    if not hasattr(pipeline, "_last_run") or not pipeline._last_run:
                        # 如果 _last_run 不存在，创建一个基本的记录
                        pipeline._last_run = {
                            "started_at": datetime.now().isoformat(),
                            "running": False,
                            "finished_at": datetime.now().isoformat(),
                            "stats": {
                                "emails_found": 0,
                                "emails_processed": 0,
                                "emails_skipped": 0,
                                "gists_created": 0,
                                "notion_published": 0,
                                "local_saved": 0,
                                "errors": 1,
                            },
                            "phase": "执行失败",
                        }
                    else:
                        # 更新现有的 _last_run
                        pipeline._last_run["running"] = False
                        if not pipeline._last_run.get("finished_at"):
                            pipeline._last_run["finished_at"] = datetime.now().isoformat()
                        pipeline._last_run["phase"] = "执行失败"
                        # 确保 stats 中有错误计数
                        if pipeline._last_run.get("stats"):
                            pipeline._last_run["stats"]["errors"] = pipeline._last_run["stats"].get("errors", 0) + 1

            thread = threading.Thread(target=run_in_background, daemon=True)
            thread.start()

            return jsonify({
                "success": True,
                "message": "任务已启动，正在后台执行。请查看任务页的执行详情了解进度。",
            })

        except Exception as e:
            logger.exception(f"Failed to run task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/stop", methods=["POST"])
    def stop_task() -> dict:
        """Stop the scheduler (shutdown)."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            if pipeline.stop_scheduler():
                return jsonify({"success": True, "message": "调度器已停止"})
            return jsonify({"success": False, "error": "调度器未运行"}), 400

        except Exception as e:
            logger.exception(f"Failed to stop task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/pause", methods=["POST"])
    def pause_task() -> dict:
        """Pause the scheduler (jobs won't run, but scheduler stays alive)."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            if pipeline.pause_scheduler():
                return jsonify({"success": True, "message": "调度器已暂停"})
            return jsonify({"success": False, "error": "调度器未运行或已暂停"}), 400

        except Exception as e:
            logger.exception(f"Failed to pause task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/resume", methods=["POST"])
    def resume_task() -> dict:
        """Resume the scheduler (if paused)."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            if pipeline.resume_scheduler():
                return jsonify({"success": True, "message": "调度器已恢复"})
            return jsonify({"success": False, "error": "调度器未暂停或未运行"}), 400

        except Exception as e:
            logger.exception(f"Failed to resume task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/start", methods=["POST"])
    def start_task() -> dict:
        """Start the scheduler (if not already running)."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            if pipeline.start_scheduler():
                return jsonify({"success": True, "message": "调度器已启动，将按配置的间隔自动执行任务"})
            return jsonify({"success": False, "error": "调度器已在运行"}), 400

        except Exception as e:
            logger.exception(f"Failed to start scheduler: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/history", methods=["GET"])
    def get_task_history() -> dict:
        """Get task processing history."""
        try:
            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"error": "LocalStore not available"}), 503

            try:
                limit = int(request.args.get("limit", 50))
            except (ValueError, TypeError):
                limit = 50

            history = local_store.get_recent_processed(limit=limit)
            # Convert datetime objects to strings for JSON serialization
            for item in history:
                if "processed_at" in item and item["processed_at"]:
                    processed_at = item["processed_at"]
                    if hasattr(processed_at, "isoformat"):
                        item["processed_at"] = processed_at.isoformat()
                    elif isinstance(processed_at, str):
                        # Already a string, keep as is
                        pass
                    else:
                        # Try to convert to string
                        item["processed_at"] = str(processed_at)
                # Ensure all values are JSON serializable
                for key, value in list(item.items()):
                    if value is None:
                        item[key] = None
                    elif isinstance(value, (int, float, str, bool)):
                        pass  # Already serializable
                    else:
                        try:
                            # Try to convert to string
                            item[key] = str(value)
                        except Exception:
                            # If conversion fails, set to None
                            item[key] = None
            return jsonify({"history": history})

        except Exception as e:
            logger.exception(f"Failed to get task history: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/tasks/errors", methods=["GET"])
    def get_task_errors() -> dict:
        """Get failed task errors."""
        try:
            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"error": "LocalStore not available"}), 503

            conn = local_store._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    SELECT message_id, error_message, error_time
                    FROM processing_errors
                    ORDER BY error_time DESC
                    LIMIT 100
                """)
                rows = cursor.fetchall()
            except Exception as e:
                logger.warning(f"Failed to query processing_errors table: {e}")
                # Table might not exist yet, return empty list
                return jsonify({"errors": []})

            errors = []
            for row in rows:
                try:
                    error_dict = {key: row[key] for key in row.keys()}
                    # Convert datetime to string if present
                    if "error_time" in error_dict and error_dict["error_time"]:
                        error_time = error_dict["error_time"]
                        if hasattr(error_time, "isoformat"):
                            error_dict["error_time"] = error_time.isoformat()
                        elif not isinstance(error_time, str):
                            error_dict["error_time"] = str(error_time)
                    # Ensure all values are JSON serializable
                    for key, value in list(error_dict.items()):
                        if value is None:
                            error_dict[key] = None
                        elif not isinstance(value, (int, float, str, bool)):
                            try:
                                error_dict[key] = str(value)
                            except Exception:
                                error_dict[key] = None
                    errors.append(error_dict)
                except Exception as e:
                    logger.warning(f"Failed to process error row: {e}")
                    continue

            return jsonify({"errors": errors})

        except Exception as e:
            logger.exception(f"Failed to get task errors: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/tasks/retry", methods=["POST"])
    def retry_task() -> dict:
        """Retry a failed task: unmark so it will be re-fetched and reprocessed on next run."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            message_id = data.get("message_id")
            if not message_id:
                return jsonify({"success": False, "error": "message_id required"}), 400

            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"success": False, "error": "LocalStore not available"}), 503

            if local_store.unmark_processed(message_id):
                return jsonify({
                    "success": True,
                    "message": "已移除失败记录，下次运行将重新拉取并处理该邮件。",
                })
            return jsonify({
                "success": False,
                "error": "未找到该 message_id 的失败记录",
            }), 404

        except Exception as e:
            logger.error(f"Failed to retry task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/reset", methods=["POST"])
    def reset_task_state() -> dict:
        """Force reset task running state (for recovery from stuck tasks)."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"success": False, "error": "Pipeline not available"}), 503

            was_running = getattr(pipeline, "_is_running", False)
            
            # 如果任务正在运行，设置 shutdown_requested 来中断它
            if was_running:
                pipeline._shutdown_requested = True
                logger.warning("Setting _shutdown_requested=True to interrupt running task")
            
            pipeline._is_running = False
            
            # Also update _last_run if it's stuck
            last_run = getattr(pipeline, "_last_run", None)
            if last_run and last_run.get("running"):
                if not last_run.get("finished_at"):
                    from datetime import datetime
                    last_run["finished_at"] = datetime.now().isoformat()
                last_run["running"] = False
                last_run["phase"] = "已强制重置"
            
            logger.warning(f"Task state forcefully reset (was_running={was_running})")
            return jsonify({
                "success": True,
                "message": "任务状态已重置，正在执行的任务将被中断。现在可以重新启动任务了",
            })

        except Exception as e:
            logger.error(f"Failed to reset task state: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/reprocess", methods=["POST"])
    def reprocess_task() -> dict:
        """Remove a task from processed_emails so it will be re-fetched and reprocessed in the next run."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            message_id = data.get("message_id")
            if not message_id:
                return jsonify({"success": False, "error": "message_id required"}), 400

            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"success": False, "error": "LocalStore not available"}), 503

            if local_store.unmark_processed(message_id):
                return jsonify({
                    "success": True,
                    "message": "已移除处理记录，下次运行将重新拉取并处理该邮件。",
                })
            return jsonify({
                "success": False,
                "error": "未找到该 message_id 的处理记录",
            }), 404

        except Exception as e:
            logger.error(f"Failed to reprocess task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/stats", methods=["GET"])
    def get_stats() -> dict:
        """Get overall statistics."""
        try:
            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"error": "LocalStore not available"}), 503

            # Get basic stats from database
            conn = local_store._get_connection()
            cursor = conn.cursor()

            # Initialize default values
            total_processed = 0
            total_spam = 0
            avg_score = 0.0
            total_errors = 0

            # Check if tables exist first
            try:
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name IN ('processed_emails', 'processing_errors')
                """)
                existing_tables = {row[0] for row in cursor.fetchall()}
            except Exception as e:
                logger.warning(f"Failed to check tables: {e}")
                existing_tables = set()

            # Get total processed
            if 'processed_emails' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) FROM processed_emails")
                    result = cursor.fetchone()
                    total_processed = int(result[0]) if result and result[0] is not None else 0
                except Exception as e:
                    logger.warning(f"Failed to get total_processed: {e}")
                    total_processed = 0
            else:
                logger.debug("processed_emails table does not exist yet")

            # Get total spam
            if 'processed_emails' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) FROM processed_emails WHERE is_spam = 1")
                    result = cursor.fetchone()
                    total_spam = int(result[0]) if result and result[0] is not None else 0
                except Exception as e:
                    logger.warning(f"Failed to get total_spam: {e}")
                    total_spam = 0

            # Get average score
            if 'processed_emails' in existing_tables:
                try:
                    cursor.execute("SELECT AVG(score) FROM processed_emails WHERE score IS NOT NULL")
                    result = cursor.fetchone()
                    if result and result[0] is not None:
                        try:
                            avg_score = float(result[0])
                        except (ValueError, TypeError):
                            avg_score = 0.0
                    else:
                        avg_score = 0.0
                except Exception as e:
                    logger.warning(f"Failed to get avg_score: {e}")
                    avg_score = 0.0

            # Get total errors
            if 'processing_errors' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) FROM processing_errors")
                    result = cursor.fetchone()
                    total_errors = int(result[0]) if result and result[0] is not None else 0
                except Exception as e:
                    logger.warning(f"Failed to get total_errors: {e}")
                    total_errors = 0
            else:
                logger.debug("processing_errors table does not exist yet")

            return jsonify({
                "total_processed": total_processed,
                "total_spam": total_spam,
                "avg_score": round(avg_score, 2),
                "total_errors": total_errors,
            })

        except Exception as e:
            logger.exception(f"Failed to get stats: {e}")
            # Return default values instead of error to prevent UI breakage
            return jsonify({
                "total_processed": 0,
                "total_spam": 0,
                "avg_score": 0.0,
                "total_errors": 0,
                "error": str(e)
            }), 200  # Return 200 with error message instead of 500

    @app.route("/", methods=["GET"])
    def index() -> str:
        """Serve web UI."""
        ui_path = Path(__file__).parent / "static" / "index.html"
        if ui_path.exists():
            return ui_path.read_text(encoding="utf-8")
        return "<h1>GistFlow Web Interface</h1><p>UI not found. Please check static/index.html</p>"

    return app
