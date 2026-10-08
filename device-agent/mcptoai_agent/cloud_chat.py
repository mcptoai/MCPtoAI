"""Backwards-compatible bridge for conversation history IPC.

The implementation moved to :mod:`mcptoai_agent.history` so chat persistence
can be local, MCPtoAI-managed, or later customer-hosted without coupling it to
device execution or application updates.
"""
from .history import handle_cloud_chat_request, handle_history_request

__all__ = ["handle_cloud_chat_request", "handle_history_request"]
