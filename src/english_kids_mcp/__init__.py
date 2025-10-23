"""English Kids MCP service package."""

from .config import Settings
from .server import KidEnglishMCPServer, SYSTEM_PROMPT
from .sse_server import main as serve_sse, run_sse_server

__all__ = ["Settings", "KidEnglishMCPServer", "SYSTEM_PROMPT", "run_sse_server", "serve_sse"]
