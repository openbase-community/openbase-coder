from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import views  # noqa: E402


def _request(method: str, path: str, data: dict | None = None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def _write_skill(root: Path, name: str, content: str = "instructions") -> Path:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def _patch_skill_homes(
    monkeypatch,
    normal_home: Path,
    openbase_home: Path,
    claude_home: Path | None = None,
) -> None:
    from openbase_coder_cli import skills_autolink

    resolved_claude_home = claude_home or normal_home.parent / "openbase-claude"
    monkeypatch.setattr(views, "_home_skills_dir", lambda: normal_home / "skills")
    monkeypatch.setattr(views, "CODEX_HOME_DIR", openbase_home)
    monkeypatch.setattr(views, "OPENBASE_CLAUDE_CONFIG_DIR", resolved_claude_home)
    monkeypatch.setattr(
        skills_autolink, "home_skills_dir", lambda: normal_home / "skills"
    )
    monkeypatch.setattr(skills_autolink, "CODEX_HOME_DIR", openbase_home)
    monkeypatch.setattr(
        skills_autolink, "OPENBASE_CLAUDE_CONFIG_DIR", resolved_claude_home
    )
    monkeypatch.setattr(
        views._skills.dispatcher_config,
        "CODEX_DISPATCHER_CONFIG_PATH",
        normal_home.parent / "dispatcher-config.json",
    )


def test_skills_list_uses_normal_and_openbase_codex_homes(tmp_path: Path, monkeypatch):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    claude_home = tmp_path / "openbase-claude"
    _write_skill(normal_home, "normal-skill")
    _write_skill(openbase_home, "openbase-skill")
    _write_skill(claude_home, "claude-skill")

    _patch_skill_homes(monkeypatch, normal_home, openbase_home, claude_home)

    response = views.skills_list(_request("get", "/api/skills/"))

    assert response.status_code == 200
    sections = {section["key"]: section for section in response.data["sections"]}
    assert sections["home"]["label"] == "Personal skills"
    assert sections["home"]["skills_dir"] == str(normal_home / "skills")
    assert [skill["name"] for skill in sections["home"]["skills"]] == ["normal-skill"]
    assert sections["openbase_codex"]["label"] == "Openbase Codex skills"
    assert sections["openbase_codex"]["skills_dir"] == str(openbase_home / "skills")
    assert [skill["name"] for skill in sections["openbase_codex"]["skills"]] == [
        "openbase-skill"
    ]
    assert sections["openbase_claude"]["label"] == "Openbase Claude skills"
    assert sections["openbase_claude"]["skills_dir"] == str(claude_home / "skills")
    assert [skill["name"] for skill in sections["openbase_claude"]["skills"]] == [
        "claude-skill"
    ]


def test_skills_symlink_links_normal_skill_to_openbase_codex(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    source_dir = _write_skill(normal_home, "shared-skill")

    _patch_skill_homes(monkeypatch, normal_home, openbase_home)

    response = views.skills_symlink(
        _request(
            "post",
            "/api/skills/symlink/",
            {
                "name": "shared-skill",
                "source_scope": "home",
                "target_scope": "openbase_codex",
            },
        )
    )

    target_dir = openbase_home / "skills" / "shared-skill"
    assert response.status_code == 201
    assert response.data["created"] is True
    assert response.data["source_dir"] == str(source_dir.resolve())
    assert target_dir.is_symlink()
    assert target_dir.resolve() == source_dir.resolve()
    assert (target_dir / "SKILL.md").read_text(encoding="utf-8") == "instructions"


def test_skills_symlink_links_normal_skill_to_openbase_claude(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    claude_home = tmp_path / "openbase-claude"
    source_dir = _write_skill(normal_home, "shared-skill")

    _patch_skill_homes(monkeypatch, normal_home, openbase_home, claude_home)

    response = views.skills_symlink(
        _request(
            "post",
            "/api/skills/symlink/",
            {
                "name": "shared-skill",
                "source_scope": "home",
                "target_scope": "openbase_claude",
            },
        )
    )

    target_dir = claude_home / "skills" / "shared-skill"
    assert response.status_code == 201
    assert response.data["created"] is True
    assert response.data["target_scope"] == "openbase_claude"
    assert target_dir.is_symlink()
    assert target_dir.resolve() == source_dir.resolve()


def test_skills_symlink_returns_ok_when_link_already_exists(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    source_dir = _write_skill(normal_home, "shared-skill")
    target_dir = openbase_home / "skills" / "shared-skill"
    target_dir.parent.mkdir(parents=True)
    target_dir.symlink_to(source_dir, target_is_directory=True)

    _patch_skill_homes(monkeypatch, normal_home, openbase_home)

    response = views.skills_symlink(
        _request(
            "post",
            "/api/skills/symlink/",
            {
                "name": "shared-skill",
                "source_scope": "home",
                "target_scope": "openbase_codex",
            },
        )
    )

    assert response.status_code == 200
    assert response.data["created"] is False


def test_skills_symlink_rejects_existing_non_link_target(tmp_path: Path, monkeypatch):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    _write_skill(normal_home, "shared-skill", "normal")
    _write_skill(openbase_home, "shared-skill", "openbase")

    _patch_skill_homes(monkeypatch, normal_home, openbase_home)

    response = views.skills_symlink(
        _request(
            "post",
            "/api/skills/symlink/",
            {
                "name": "shared-skill",
                "source_scope": "home",
                "target_scope": "openbase_codex",
            },
        )
    )

    assert response.status_code == 409
    assert "already exists" in response.data["error"]
    assert not (openbase_home / "skills" / "shared-skill").is_symlink()


def test_skills_auto_link_setting_defaults_disabled(tmp_path: Path, monkeypatch):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    config_path = tmp_path / "dispatcher-config.json"
    _write_skill(normal_home, "shared-skill")
    _patch_skill_homes(monkeypatch, normal_home, openbase_home)
    monkeypatch.setattr(
        views._skills.dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path
    )

    response = views.skills_list(_request("get", "/api/skills/"))

    assert response.status_code == 200
    assert (
        response.data["auto_link_personal_skills"]["auto_link_personal_skills"] is False
    )
    assert response.data["auto_link_personal_skills_sync"] is None
    assert not (openbase_home / "skills" / "shared-skill").exists()


def test_skills_auto_link_setting_enables_and_links_normal_skills(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    config_path = tmp_path / "dispatcher-config.json"
    source_dir = _write_skill(normal_home, "shared-skill")
    _patch_skill_homes(monkeypatch, normal_home, openbase_home)
    monkeypatch.setattr(
        views._skills.dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path
    )

    response = views.skills_auto_link_settings(
        _request(
            "patch",
            "/api/skills/auto-link-personal/",
            {"auto_link_personal_skills": True},
        )
    )

    target_dir = openbase_home / "skills" / "shared-skill"
    assert response.status_code == 200
    assert response.data["auto_link_personal_skills"] is True
    # One link per target scope (openbase codex home + claude config dir).
    assert response.data["sync"]["created"] == 2
    assert target_dir.is_symlink()
    assert target_dir.resolve() == source_dir.resolve()

    list_response = views.skills_list(_request("get", "/api/skills/"))
    assert list_response.data["auto_link_personal_skills_sync"]["already_linked"] == 2


def test_skills_auto_link_reports_conflict_without_overwriting(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    config_path = tmp_path / "dispatcher-config.json"
    _write_skill(normal_home, "shared-skill", "normal")
    _write_skill(openbase_home, "shared-skill", "openbase")
    _patch_skill_homes(monkeypatch, normal_home, openbase_home)
    monkeypatch.setattr(
        views._skills.dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path
    )

    response = views.skills_auto_link_settings(
        _request(
            "patch",
            "/api/skills/auto-link-personal/",
            {"auto_link_personal_skills": True},
        )
    )

    assert response.status_code == 200
    assert response.data["sync"]["conflicts"] == 1
    assert response.data["sync"]["results"][0]["status"] == "conflict"
    target_dir = openbase_home / "skills" / "shared-skill"
    assert not target_dir.is_symlink()
    assert (target_dir / "SKILL.md").read_text(encoding="utf-8") == "openbase"


def test_skill_delete_unlinks_symlink_without_deleting_source(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    source_dir = _write_skill(normal_home, "shared-skill")
    target_dir = openbase_home / "skills" / "shared-skill"
    target_dir.parent.mkdir(parents=True)
    target_dir.symlink_to(source_dir, target_is_directory=True)

    _patch_skill_homes(monkeypatch, normal_home, openbase_home)

    request = _request(
        "delete",
        "/api/skills/shared-skill/?scope=openbase_codex",
    )
    response = views.skill_detail(request, "shared-skill")

    assert response.status_code == 200
    assert not target_dir.exists()
    assert source_dir.is_dir()
    assert (source_dir / "SKILL.md").read_text(encoding="utf-8") == "instructions"


def test_skills_symlink_preserves_existing_source_symlink_chain(
    tmp_path: Path, monkeypatch
):
    normal_home = tmp_path / "normal-codex"
    openbase_home = tmp_path / "openbase-codex"
    real_skill = tmp_path / "Developer" / "skills" / "shared-skill"
    real_skill.mkdir(parents=True)
    (real_skill / "SKILL.md").write_text("real instructions", encoding="utf-8")
    source_dir = normal_home / "skills" / "shared-skill"
    source_dir.parent.mkdir(parents=True)
    source_dir.symlink_to(real_skill, target_is_directory=True)
    _patch_skill_homes(monkeypatch, normal_home, openbase_home)

    response = views.skills_symlink(
        _request(
            "post",
            "/api/skills/symlink/",
            {
                "name": "shared-skill",
                "source_scope": "home",
                "target_scope": "openbase_codex",
            },
        )
    )

    target_dir = openbase_home / "skills" / "shared-skill"
    assert response.status_code == 201
    assert response.data["source_dir"] == str(source_dir)
    assert target_dir.is_symlink()
    assert os.readlink(target_dir) == str(source_dir)
    assert target_dir.resolve() == real_skill.resolve()
