"""Line-based TOML table editing for config files Openbase Coder manages.

These helpers deliberately treat the file as text rather than parsing it:
user config like the Codex ``config.toml`` may hold comments and formatting a
parse/serialize round-trip would destroy.
"""

from __future__ import annotations


def remove_toml_table(text: str, table_name: str) -> str:
    """Drop one ``[table_name]`` table (header plus body) from ``text``."""
    target_header = f"[{table_name}]"
    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        if lines[index].strip() == target_header:
            index += 1
            while index < len(lines):
                stripped = lines[index].strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    break
                index += 1
            while output and not output[-1].strip():
                output.pop()
            continue

        output.append(lines[index])
        index += 1

    while output and not output[-1].strip():
        output.pop()

    return "\n".join(output) + ("\n" if output else "")


def replace_toml_table(text: str, table_name: str, block: str) -> str:
    """Replace (or append) one ``[table_name]`` table with ``block``."""
    updated = remove_toml_table(text, table_name).rstrip()
    if updated:
        return f"{updated}\n\n{block}"
    return block
