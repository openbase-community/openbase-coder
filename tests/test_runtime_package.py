from __future__ import annotations

import json
from pathlib import Path

from openbase_coder_cli import runtime
from openbase_coder_cli.services.installation import InstallationConfig


def test_runtime_package_resolves_from_explicit_env(monkeypatch, tmp_path: Path):
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / runtime.PACKAGE_METADATA_FILENAME).write_text(
        json.dumps({"version": "1.2.3", "target": "aarch64-apple-darwin"}),
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENBASE_CODER_PACKAGE_DIR", str(package_dir))

    package = runtime.current_runtime_package()

    assert package is not None
    assert package.root == package_dir
    assert package.version == "1.2.3"
    assert package.console_build_dir == package_dir / "console"


def test_installation_config_load_ignores_unknown_keys(monkeypatch, tmp_path: Path):
    install_path = tmp_path / "installation.json"
    install_path.write_text(
        json.dumps(
            {
                "workspace_path": "",
                "env_file": "/tmp/.env",
                "standalone": True,
                "unknown": "ignored",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openbase_coder_cli.services.installation.INSTALLATION_JSON_PATH",
        install_path,
    )

    config = InstallationConfig.load()

    assert config.workspace_path == ""
    assert config.env_file == "/tmp/.env"
    assert config.standalone is True
