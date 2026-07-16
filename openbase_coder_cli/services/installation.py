from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

from openbase_coder_cli.paths import INSTALLATION_JSON_PATH

# Bump alongside a forward-only migration; see the workspace AUTO_UPDATE.md.
INSTALLATION_SCHEMA_VERSION = 1


@dataclass
class InstallationConfig:
    """Install-mode record; never a cache of package paths.

    Standalone package paths (python, livekit-server, console build, package
    root) are deliberately not persisted here: the single source of truth is
    the ``packages/standalone/current`` symlink, resolved at use time via
    ``openbase_coder_cli.runtime``. Legacy files may still contain those keys;
    ``load()`` ignores unknown keys, so they are dead on read.
    """

    schema_version: int = INSTALLATION_SCHEMA_VERSION
    workspace_path: str = ""
    env_file: str = ""
    standalone: bool = False

    def save(self) -> None:
        self.schema_version = INSTALLATION_SCHEMA_VERSION
        INSTALLATION_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        INSTALLATION_JSON_PATH.write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls) -> InstallationConfig:
        data = json.loads(INSTALLATION_JSON_PATH.read_text())
        found_version = int(data.get("schema_version", 1))
        if found_version > INSTALLATION_SCHEMA_VERSION:
            raise ValueError(
                f"installation.json schema {found_version} was written by a "
                "newer Openbase Coder; update the CLI."
            )
        field_names = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in field_names})

    @classmethod
    def exists(cls) -> bool:
        return INSTALLATION_JSON_PATH.is_file()
