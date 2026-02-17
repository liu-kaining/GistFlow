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
        settings = get_settings()
        config_dict = settings.model_dump()

        # Mask sensitive fields
        sensitive_fields = [
            "GMAIL_APP_PASSWORD",
            "OPENAI_API_KEY",
            "NOTION_API_KEY",
        ]
        for field in sensitive_fields:
            if field in config_dict and config_dict[field]:
                config_dict[field] = "****" + config_dict[field][-4:] if len(config_dict[field]) > 4 else "****"

        return jsonify(config_dict)

    @app.route("/api/config", methods=["POST"])
    def update_config() -> dict:
        """Update configuration by writing to .env file."""
        try:
            data = request.json
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            env_path = Path(".env")
            if not env_path.exists():
                return jsonify({"success": False, "error": ".env file not found"}), 404

            # Read existing .env
            env_lines = env_path.read_text(encoding="utf-8").splitlines()

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
            for key, value in data.items():
                if key in env_dict:
                    env_dict[key] = str(value)
                else:
                    # Add new key
                    env_dict[key] = str(value)

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

            env_path.write_text("\n".join(env_content), encoding="utf-8")

            # Reload settings
            reload_settings()

            return jsonify({"success": True, "message": "Configuration updated"})

        except Exception as e:
            logger.error(f"Failed to update config: {e}")
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
            system_content = data.get("system_prompt", "")
            user_content = data.get("user_prompt_template", "")

            # Save to files
            if system_content:
                system_path = Path(settings.PROMPT_SYSTEM_PATH)
                system_path.parent.mkdir(parents=True, exist_ok=True)
                system_path.write_text(system_content, encoding="utf-8")

                # Save to history
                local_store = app.config.get("local_store")
                if local_store:
                    local_store.save_prompt_version("system", system_content, "web")

            if user_content:
                user_path = Path(settings.PROMPT_USER_PATH)
                user_path.parent.mkdir(parents=True, exist_ok=True)
                user_path.write_text(user_content, encoding="utf-8")

                # Save to history
                local_store = app.config.get("local_store")
                if local_store:
                    local_store.save_prompt_version("user", user_content, "web")

            # Reload prompts in engine
            pipeline = app.config.get("pipeline")
            if pipeline and hasattr(pipeline, "llm_engine"):
                pipeline.llm_engine.reload_prompts()

            return jsonify({"success": True, "message": "Prompts updated and reloaded"})

        except Exception as e:
            logger.error(f"Failed to update prompts: {e}")
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
                return jsonify({"error": "No data provided"}), 400

            test_content = data.get("content", "")
            sender = data.get("sender", "Test Sender")
            subject = data.get("subject", "Test Subject")
            date = data.get("date", "")

            pipeline = app.config.get("pipeline")
            if not pipeline or not hasattr(pipeline, "llm_engine"):
                return jsonify({"error": "Pipeline not available"}), 503

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

            # Extract gist
            gist = test_engine.extract_gist(
                content=test_content,
                sender=sender,
                subject=subject,
                date=date,
            )

            if gist:
                return jsonify({"success": True, "gist": gist.model_dump()})
            else:
                return jsonify({"success": False, "error": "Failed to extract gist"}), 500

        except Exception as e:
            logger.error(f"Failed to test prompt: {e}")
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
            return jsonify({"history": history})

        except Exception as e:
            logger.error(f"Failed to get prompt history: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/tasks/status", methods=["GET"])
    def get_task_status() -> dict:
        """Get task scheduler status."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"error": "Pipeline not available"}), 503

            scheduler = getattr(pipeline, "scheduler", None)
            if scheduler and scheduler.running:
                jobs = scheduler.get_jobs()
                return jsonify({
                    "running": True,
                    "jobs": [{"id": job.id, "name": job.name, "next_run": str(job.next_run_time)} for job in jobs],
                })
            else:
                return jsonify({"running": False, "jobs": []})

        except Exception as e:
            logger.error(f"Failed to get task status: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/tasks/run", methods=["POST"])
    def run_task() -> dict:
        """Manually trigger a single pipeline run."""
        try:
            pipeline = app.config.get("pipeline")
            if not pipeline:
                return jsonify({"error": "Pipeline not available"}), 503

            stats = pipeline.run_once()
            return jsonify({"success": True, "stats": stats})

        except Exception as e:
            logger.error(f"Failed to run task: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/tasks/history", methods=["GET"])
    def get_task_history() -> dict:
        """Get task processing history."""
        try:
            local_store = app.config.get("local_store")
            if not local_store:
                return jsonify({"error": "LocalStore not available"}), 503

            limit = int(request.args.get("limit", 50))
            history = local_store.get_recent_history(limit=limit)
            return jsonify({"history": history})

        except Exception as e:
            logger.error(f"Failed to get task history: {e}")
            return jsonify({"error": str(e)}), 500

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

            cursor.execute("SELECT COUNT(*) FROM processed_emails")
            total_processed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM processed_emails WHERE is_spam = 1")
            total_spam = cursor.fetchone()[0]

            cursor.execute("SELECT AVG(score) FROM processed_emails WHERE score IS NOT NULL")
            avg_score_row = cursor.fetchone()
            avg_score = float(avg_score_row[0]) if avg_score_row[0] else 0.0

            cursor.execute("SELECT COUNT(*) FROM processing_errors")
            total_errors = cursor.fetchone()[0]

            return jsonify({
                "total_processed": total_processed,
                "total_spam": total_spam,
                "avg_score": round(avg_score, 2),
                "total_errors": total_errors,
            })

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/", methods=["GET"])
    def index() -> str:
        """Serve web UI."""
        ui_path = Path(__file__).parent / "static" / "index.html"
        if ui_path.exists():
            return ui_path.read_text(encoding="utf-8")
        return "<h1>GistFlow Web Interface</h1><p>UI not found. Please check static/index.html</p>"

    return app
