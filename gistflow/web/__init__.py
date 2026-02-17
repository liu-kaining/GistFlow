"""
Web management interface for GistFlow.
Provides REST API and web UI for configuration, task control, and prompt management.
"""

from gistflow.web.api import create_app

__all__ = ["create_app"]
