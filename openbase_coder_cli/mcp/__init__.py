"""Shared thread/session helpers for Openbase.

This package name is historical: the CLI no longer exposes its own MCP server.
Prefer agent skills for Openbase-specific agent-facing workflows. The separate
``super-agents-mcp`` server should stay general-purpose and Openbase-agnostic:
it is for managing AI agent threads, not for accumulating tools that only make
sense inside Openbase. Do not restore a CLI-owned MCP surface unless a
workflow genuinely needs MCP semantics.

To re-enable a CLI-owned MCP server intentionally:

1. Add ``django-mcp-server`` and any required MCP client/server dependency back
   to ``pyproject.toml`` and refresh ``uv.lock``.
2. Add ``mcp_server`` to ``INSTALLED_APPS`` in ``config/settings.py``.
3. Add ``openbase_coder_cli.mcp`` to ``INSTALLED_APPS`` only if the package has
   a Django app config that registers real tools.
4. Restore ``DJANGO_MCP_AUTHENTICATION_CLASSES`` using the existing JWT
   authentication backend, plus any required MCP server config.
5. Mount ``mcp_server.urls`` in ``config/urls.py``.
6. Add a new ``mcp.py`` with ``MCPToolset`` classes containing real tools, and
   cover registration and behavior with tests.
"""
