"""MCP tools owned by the Openbase Coder CLI server."""

from __future__ import annotations

from typing import Any

from mcp_server.djangomcp import MCPToolset

from openbase_coder_cli import dispatcher_config

from .thread_import import (
    export_voice_codex_threads,
    import_normal_codex_threads,
    list_normal_codex_threads,
    list_voice_codex_threads,
)


class CodexThreadImportTools(MCPToolset):
    """Tools for copying threads between normal and voice Codex homes."""

    def list_normal_codex_threads(
        self,
        limit: int = 50,
        search: str | None = None,
        include_imported: bool = True,
    ) -> dict[str, Any]:
        """List normal non-voice Codex threads available for voice import."""
        threads = list_normal_codex_threads(
            limit=limit,
            search=search,
            include_imported=include_imported,
        )
        return {
            "threads": [thread.to_json() for thread in threads],
            "count": len(threads),
        }

    def import_normal_codex_threads(
        self,
        thread_ids: list[str],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Import normal Codex threads into the Openbase voice Codex home."""
        results = import_normal_codex_threads(thread_ids, overwrite=overwrite)
        return {
            "results": [result.to_json() for result in results],
            "imported_count": sum(1 for result in results if result.imported),
        }

    def list_voice_codex_threads(
        self,
        limit: int = 50,
        search: str | None = None,
        include_exported: bool = True,
    ) -> dict[str, Any]:
        """List voice Codex threads available for normal Codex export."""
        threads = list_voice_codex_threads(
            limit=limit,
            search=search,
            include_exported=include_exported,
        )
        return {
            "threads": [thread.to_json() for thread in threads],
            "count": len(threads),
        }

    def export_voice_codex_threads(
        self,
        thread_ids: list[str],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Export voice Codex threads into the normal Codex home."""
        results = export_voice_codex_threads(thread_ids, overwrite=overwrite)
        return {
            "results": [result.to_json() for result in results],
            "exported_count": sum(1 for result in results if result.exported),
        }

    def get_dispatcher_reasoning_effort(self) -> dict[str, Any]:
        """Show the default reasoning effort used by new dispatcher turns."""
        effort = dispatcher_config.dispatcher_reasoning_effort()
        return {
            "reasoning_effort": effort,
            "effective": effort or "app-server default",
            "config_path": str(dispatcher_config.CODEX_DISPATCHER_CONFIG_PATH),
        }

    def set_dispatcher_reasoning_effort(self, level: str) -> dict[str, Any]:
        """Set the default reasoning effort used by new dispatcher turns."""
        normalized = level.strip().lower()
        config_path = dispatcher_config.set_dispatcher_reasoning_effort(normalized)
        return {
            "reasoning_effort": normalized,
            "config_path": str(config_path),
            "applies_to": "next dispatcher turn",
        }

    def get_super_agents_reasoning_effort(self) -> dict[str, Any]:
        """Show the default reasoning effort used by new Super Agents turns."""
        effort = dispatcher_config.super_agents_reasoning_effort()
        return {
            "reasoning_effort": effort,
            "effective": effort or "high",
            "config_path": str(dispatcher_config.CODEX_DISPATCHER_CONFIG_PATH),
        }

    def set_super_agents_reasoning_effort(self, level: str) -> dict[str, Any]:
        """Set the default reasoning effort used by new Super Agents turns."""
        normalized = level.strip().lower()
        config_path = dispatcher_config.set_super_agents_reasoning_effort(normalized)
        return {
            "reasoning_effort": normalized,
            "config_path": str(config_path),
            "applies_to": "next Super Agents turn",
        }

    def get_super_agents_model(self) -> dict[str, Any]:
        """Show the default model used by new Super Agents turns."""
        model = dispatcher_config.super_agents_model()
        return {
            "model": model,
            "effective": model or "backend default",
            "config_path": str(dispatcher_config.CODEX_DISPATCHER_CONFIG_PATH),
        }

    def set_super_agents_model(self, model: str) -> dict[str, Any]:
        """Set the default model used by new Super Agents turns."""
        config_path = dispatcher_config.set_super_agents_model(model)
        normalized = dispatcher_config.super_agents_model(config_path)
        return {
            "model": normalized,
            "config_path": str(config_path),
            "applies_to": "next Super Agents turn",
        }


__all__ = ["CodexThreadImportTools"]
