from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli import skills_autolink  # noqa: E402
from openbase_coder_cli.openbase_coder_cli_app import marketplace  # noqa: E402

SKILLS = [
    {
        "slug": "gmail-cli",
        "name": "Gmail CLI",
        "kind": "skill",
        "category": "email",
        "tagline": "Safe Gmail zzq",
        "repo_url": "https://example.com/gmail-cli-skill",
        "docs_url": "",
        "install_notes": "",
        "featured": True,
    },
    {
        "slug": "figma",
        "name": "Figma MCP",
        "kind": "mcp",
        "category": "design",
        "docs_url": "https://figma.example/docs",
        "install_notes": "Install the connector.",
    },
    {
        "slug": "notion-cli",
        "name": "Notion CLI",
        "kind": "cli",
        "category": "productivity",
        "docs_url": "https://notion.example/docs",
    },
]

ROUTINES = [
    {
        "slug": "daily-work-summary",
        "name": "Daily work summary",
        "kind": "agent",
        "category": "productivity",
        "prompt": "Summarize yesterday.",
        "schedule_type": "daily",
        "time": "08:30",
        "use_client_timezone": True,
        "required_skills": [],
    },
    {
        "slug": "morning-email-triage",
        "name": "Morning email triage",
        "kind": "agent",
        "category": "email",
        "prompt": "Triage my inbox.",
        "schedule_type": "daily",
        "time": "08:00",
        "use_client_timezone": True,
        "required_skills": ["gmail-cli"],
    },
]


class FakeManager:
    def __init__(self, routines=None):
        self._routines = list(routines or [])
        self.saved: list[dict] = []

    async def list_routines(self):
        return {"count": len(self._routines), "routines": self._routines}

    async def save_routine(self, payload):
        self.saved.append(payload)
        self._routines.append({"name": payload["name"]})
        return {"name": payload["name"], **payload}


def _request(method: str, path: str, data: dict | None = None):
    factory = APIRequestFactory()
    request = getattr(factory, method)(path, data or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def _patch_homes(monkeypatch, tmp_path: Path):
    home = tmp_path / "home-skills"
    codex = tmp_path / "codex" / "skills"
    claude = tmp_path / "claude" / "skills"
    monkeypatch.setattr(marketplace, "_home_skills_dir", lambda: home)
    monkeypatch.setattr(
        skills_autolink,
        "auto_link_target_dirs",
        lambda: {"openbase_codex": codex, "openbase_claude": claude},
    )
    monkeypatch.setattr(marketplace, "_bump_cloud_counter", lambda *a, **k: None)
    return home, codex, claude


def _patch_catalog(monkeypatch, skills=None, routines=None):
    data = {
        "skills": skills if skills is not None else SKILLS,
        "routines": routines if routines is not None else ROUTINES,
    }

    def fake_fetch(kind, *, force=False):
        return list(data[kind])

    monkeypatch.setattr(marketplace, "_fetch_catalog", fake_fetch)


def _fake_git_clone(clone_dir_factory):
    def run(cmd, *args, **kwargs):
        # cmd = ["git", "clone", "--depth", "1", repo, dest]
        dest = Path(cmd[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text("skill", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    return run


# --- skills catalog ---------------------------------------------------------


def test_skills_catalog_reports_installed_and_categories(tmp_path, monkeypatch):
    home, _, _ = _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    (home / "gmail-cli").mkdir(parents=True)
    (home / "gmail-cli" / "SKILL.md").write_text("x", encoding="utf-8")

    response = marketplace.marketplace_skills_catalog(
        _request("get", "/api/marketplace/skills/catalog/")
    )
    assert response.status_code == 200
    by_slug = {e["slug"]: e for e in response.data["entries"]}
    assert by_slug["gmail-cli"]["installed"] is True
    assert by_slug["figma"]["installed"] is False
    cats = {c["name"] for c in response.data["categories"]}
    assert {"email", "design", "productivity"} <= cats


def test_skills_catalog_query_filter(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    request = _request("get", "/api/marketplace/skills/catalog/?q=zzq")
    response = marketplace.marketplace_skills_catalog(request)
    assert {e["slug"] for e in response.data["entries"]} == {"gmail-cli"}


def test_skills_catalog_502_on_cloud_error(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise TimeoutError("down")

    monkeypatch.setattr(marketplace, "_fetch_catalog", boom)
    response = marketplace.marketplace_skills_catalog(
        _request("get", "/api/marketplace/skills/catalog/")
    )
    assert response.status_code == 502


def test_skill_install_co_installs_both_homes(tmp_path, monkeypatch):
    home, codex, claude = _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    monkeypatch.setattr(marketplace.subprocess, "run", _fake_git_clone(home))

    response = marketplace.marketplace_skills_install(
        _request("post", "/api/marketplace/skills/install/", {"slug": "gmail-cli"})
    )
    assert response.status_code == 201, response.data
    assert (home / "gmail-cli" / "SKILL.md").is_file()
    assert (codex / "gmail-cli").is_symlink()
    assert (claude / "gmail-cli").is_symlink()
    assert response.data["targets"]["openbase_codex"] == "created"
    assert response.data["targets"]["openbase_claude"] == "created"


def test_skill_install_idempotent_relinks(tmp_path, monkeypatch):
    home, codex, claude = _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    (home / "gmail-cli").mkdir(parents=True)
    (home / "gmail-cli" / "SKILL.md").write_text("x", encoding="utf-8")

    def fail_clone(*a, **k):
        raise AssertionError("should not clone when already present")

    monkeypatch.setattr(marketplace.subprocess, "run", fail_clone)
    response = marketplace.marketplace_skills_install(
        _request("post", "/api/marketplace/skills/install/", {"slug": "gmail-cli"})
    )
    assert response.status_code == 201
    assert (codex / "gmail-cli").is_symlink()


def test_skill_install_rejects_docs_only(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    response = marketplace.marketplace_skills_install(
        _request("post", "/api/marketplace/skills/install/", {"slug": "figma"})
    )
    assert response.status_code == 400
    assert response.data["docs_url"] == "https://figma.example/docs"


def test_skill_install_unknown_slug_404(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    response = marketplace.marketplace_skills_install(
        _request("post", "/api/marketplace/skills/install/", {"slug": "nope"})
    )
    assert response.status_code == 404


# --- routines catalog + install ---------------------------------------------


def test_routines_catalog_expands_required_skills(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: FakeManager())

    response = marketplace.marketplace_routines_catalog(
        _request("get", "/api/marketplace/routines/catalog/")
    )
    assert response.status_code == 200
    triage = next(
        e for e in response.data["entries"] if e["slug"] == "morning-email-triage"
    )
    assert triage["required_skills"][0]["slug"] == "gmail-cli"
    assert triage["schedule_summary"] == "Daily at 08:00"


def test_routine_install_happy_path_omits_timezone(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    manager = FakeManager()
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: manager)

    response = marketplace.marketplace_routines_install(
        _request(
            "post", "/api/marketplace/routines/install/", {"slug": "daily-work-summary"}
        )
    )
    assert response.status_code == 201, response.data
    assert response.data["installed_name"] == "Daily work summary"
    assert "timezone" not in manager.saved[0]


def test_routine_install_applies_timezone_override(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    manager = FakeManager()
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: manager)

    response = marketplace.marketplace_routines_install(
        _request(
            "post",
            "/api/marketplace/routines/install/",
            {
                "slug": "daily-work-summary",
                "overrides": {"timezone": "America/New_York"},
            },
        )
    )
    assert response.status_code == 201
    assert manager.saved[0]["timezone"] == "America/New_York"


def test_routine_install_co_installs_required_skill(tmp_path, monkeypatch):
    home, codex, claude = _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: FakeManager())
    monkeypatch.setattr(marketplace.subprocess, "run", _fake_git_clone(home))

    response = marketplace.marketplace_routines_install(
        _request(
            "post",
            "/api/marketplace/routines/install/",
            {"slug": "morning-email-triage"},
        )
    )
    assert response.status_code == 201, response.data
    assert response.data["installed_skills"] == ["gmail-cli"]
    assert (codex / "gmail-cli").is_symlink()
    assert (claude / "gmail-cli").is_symlink()


def test_routine_install_reports_manual_dependencies(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    routines = [
        {
            **ROUTINES[0],
            "slug": "figma-routine",
            "name": "Figma routine",
            "required_skills": ["figma"],
        }
    ]
    _patch_catalog(monkeypatch, routines=routines)
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: FakeManager())

    response = marketplace.marketplace_routines_install(
        _request(
            "post", "/api/marketplace/routines/install/", {"slug": "figma-routine"}
        )
    )
    assert response.status_code == 201
    assert response.data["manual_dependencies"][0]["slug"] == "figma"
    assert response.data["installed_skills"] == []


def test_routine_install_explicit_name_collision_409(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    manager = FakeManager(routines=[{"name": "Taken"}])
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: manager)

    response = marketplace.marketplace_routines_install(
        _request(
            "post",
            "/api/marketplace/routines/install/",
            {"slug": "daily-work-summary", "overrides": {"name": "Taken"}},
        )
    )
    assert response.status_code == 409


def test_routine_install_auto_suffixes_default_name(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)
    _patch_catalog(monkeypatch)
    manager = FakeManager(routines=[{"name": "Daily work summary"}])
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: manager)

    response = marketplace.marketplace_routines_install(
        _request(
            "post", "/api/marketplace/routines/install/", {"slug": "daily-work-summary"}
        )
    )
    assert response.status_code == 201
    assert response.data["installed_name"] == "Daily work summary-2"


def test_routine_install_502_on_cloud_error(tmp_path, monkeypatch):
    _patch_homes(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise TimeoutError("down")

    monkeypatch.setattr(marketplace, "_fetch_catalog", boom)
    monkeypatch.setattr(marketplace, "get_session_manager", lambda: FakeManager())
    response = marketplace.marketplace_routines_install(
        _request(
            "post", "/api/marketplace/routines/install/", {"slug": "daily-work-summary"}
        )
    )
    assert response.status_code == 502


# --- recommended prompt flag ------------------------------------------------


def test_recommended_prompt_get_and_patch(tmp_path, monkeypatch):
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(
        marketplace.dispatcher_config,
        "CODEX_DISPATCHER_CONFIG_PATH",
        config_path,
    )
    get1 = marketplace.marketplace_recommended_prompt(
        _request("get", "/api/marketplace/recommended-prompt/")
    )
    assert get1.data["dismissedAt"] is None

    patched = marketplace.marketplace_recommended_prompt(
        _request(
            "patch",
            "/api/marketplace/recommended-prompt/",
            {"dismissedAt": "2026-07-06T00:00:00Z"},
        )
    )
    assert patched.data["dismissedAt"] == "2026-07-06T00:00:00Z"

    get2 = marketplace.marketplace_recommended_prompt(
        _request("get", "/api/marketplace/recommended-prompt/")
    )
    assert get2.data["dismissedAt"] == "2026-07-06T00:00:00Z"
