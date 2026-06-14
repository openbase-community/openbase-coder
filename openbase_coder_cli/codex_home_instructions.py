from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from openbase_coder_cli.paths import CODEX_HOME_DIR
from openbase_coder_cli.services.installation import InstallationConfig

CODEX_HOME_DEFAULT_SOURCE_DIR = "instructions"
MANAGED_AGENTS_HEADING = "## Openbase Coder Instructions"


def refresh_openbase_agents_md_from_installation() -> bool:
    """Refresh the editable Openbase Codex home AGENTS.md on CLI launch."""
    try:
        if not InstallationConfig.exists():
            return False
        workspace_dir = Path(InstallationConfig.load().workspace_path)
        return ensure_openbase_agents_md(workspace_dir)
    except Exception:
        return False


def ensure_openbase_agents_md(
    workspace_dir: str | Path,
    *,
    codex_home_dir: Path | None = None,
    report: Callable[[str], None] | None = None,
) -> bool:
    """Maintain an editable AGENTS.md with a replaceable Openbase section."""
    source_path = Path(workspace_dir) / CODEX_HOME_DEFAULT_SOURCE_DIR / "AGENTS.md"
    target_path = (codex_home_dir or CODEX_HOME_DIR) / "AGENTS.md"
    if not source_path.is_file():
        _report(report, f"Codex home AGENTS.md source not found at {source_path}")
        return False

    source_text = source_path.read_text(encoding="utf-8")
    generated_section = _managed_agents_md_section(source_text, source_path)
    existing = ""
    if target_path.exists() or target_path.is_symlink():
        try:
            existing = target_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    if existing.strip() == source_text.strip():
        existing = ""

    updated = _replace_managed_agents_md_section(existing, generated_section)
    if target_path.is_symlink():
        target_path.unlink()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not target_path.is_file():
        _report(
            report,
            f"Codex home AGENTS.md already exists at {target_path}; "
            "leaving it unchanged.",
        )
        return False

    if target_path.exists() and target_path.read_text(encoding="utf-8") == updated:
        _report(report, f"Codex home AGENTS.md already configured at {target_path}")
        return False

    target_path.write_text(updated, encoding="utf-8")
    _report(report, f"Updated editable Codex home AGENTS.md at {target_path}")
    return True


def _managed_agents_md_section(source_text: str, source_path: Path) -> str:
    body = _without_h2_headings(source_text).strip()
    note = f"- These instructions are auto generated from {source_path}."
    if body:
        return f"{MANAGED_AGENTS_HEADING}\n\n{note}\n\n{body}\n"
    return f"{MANAGED_AGENTS_HEADING}\n\n{note}\n"


def _without_h2_headings(text: str) -> str:
    return "".join(
        f"#{line}" if line.startswith("## ") else line
        for line in text.splitlines(keepends=True)
    )


def _replace_managed_agents_md_section(existing: str, generated_section: str) -> str:
    lines = existing.splitlines(keepends=True)
    start_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == MANAGED_AGENTS_HEADING
        ),
        None,
    )

    if start_index is None:
        prefix = existing.rstrip()
        if not prefix:
            return generated_section
        return f"{prefix}\n\n{generated_section}"

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        if line.startswith("## ") and line.strip() != MANAGED_AGENTS_HEADING:
            end_index = index
            break

    prefix = "".join(lines[:start_index]).rstrip()
    suffix = "".join(lines[end_index:]).lstrip()

    if prefix and suffix:
        return f"{prefix}\n\n{generated_section}\n{suffix}"
    if prefix:
        return f"{prefix}\n\n{generated_section}"
    if suffix:
        return f"{generated_section}\n{suffix}"
    return generated_section


def _report(report: Callable[[str], None] | None, message: str) -> None:
    if report is not None:
        report(message)
