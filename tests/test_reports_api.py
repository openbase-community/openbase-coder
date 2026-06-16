from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import reports as report_views, views  # noqa: E402,I001


def _delete_report(project_path: Path, relative_path: str):
    factory = APIRequestFactory()
    query = urlencode({"path": str(project_path), "file": relative_path})
    request = factory.delete(
        f"/api/projects/reports/file/?{query}",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return views.project_reports_file(request)


def _patch_report(project_path: Path, relative_path: str, content):
    factory = APIRequestFactory()
    query = urlencode({"path": str(project_path), "file": relative_path})
    request = factory.patch(
        f"/api/projects/reports/file/?{query}",
        {"content": content},
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return views.project_reports_file(request)


def _download_report(project_path: Path, relative_path: str):
    factory = APIRequestFactory()
    query = urlencode({"path": str(project_path), "file": relative_path})
    request = factory.get(
        f"/api/projects/reports/download/?{query}",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return views.project_reports_download(request)


def _set_report_tags(project_path: Path, relative_path: str, tags: list[str]):
    factory = APIRequestFactory()
    query = urlencode({"path": str(project_path), "file": relative_path})
    request = factory.patch(
        f"/api/projects/reports/tags/?{query}",
        {"tags": tags},
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return views.project_reports_tags(request)


def _get_global_reports_projects():
    factory = APIRequestFactory()
    request = factory.get("/api/projects/reports/global/")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return views.global_reports_projects(request)


def _get_all_project_reports():
    factory = APIRequestFactory()
    request = factory.get("/api/projects/reports/all/")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return views.all_project_reports(request)


def test_global_reports_projects_lists_untracked_report_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    openbase_codex_home = tmp_path / "openbase" / "codex_home"
    normal_codex_home = tmp_path / ".codex"
    home = tmp_path / "home"
    for source, report_name in (
        (openbase_codex_home, "voice.md"),
        (normal_codex_home, "normal.md"),
        (home, "home.md"),
    ):
        reports = source / ".reports"
        reports.mkdir(parents=True)
        (reports / report_name).write_text("done", encoding="utf-8")

    monkeypatch.setattr(report_views, "CODEX_HOME_DIR", openbase_codex_home)
    monkeypatch.setattr(report_views, "NORMAL_CODEX_HOME_DIR", normal_codex_home)
    monkeypatch.setattr(report_views, "HOME_REPORTS_PROJECT_DIR", home)

    response = _get_global_reports_projects()

    assert response.status_code == 200
    projects = response.data["projects"]
    assert [project["path"] for project in projects] == [
        str(openbase_codex_home.resolve()),
        str(normal_codex_home.resolve()),
        str(home.resolve()),
    ]
    assert all(project["global_reports"] is True for project in projects)
    assert all(project["reports_count"] == 1 for project in projects)


def test_global_reports_projects_skips_missing_reports_dirs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    openbase_codex_home = tmp_path / "openbase" / "codex_home"
    normal_codex_home = tmp_path / ".codex"
    home = tmp_path / "home"
    (normal_codex_home / ".reports").mkdir(parents=True)
    (normal_codex_home / ".reports" / "normal.md").write_text(
        "done",
        encoding="utf-8",
    )

    monkeypatch.setattr(report_views, "CODEX_HOME_DIR", openbase_codex_home)
    monkeypatch.setattr(report_views, "NORMAL_CODEX_HOME_DIR", normal_codex_home)
    monkeypatch.setattr(report_views, "HOME_REPORTS_PROJECT_DIR", home)

    response = _get_global_reports_projects()

    assert response.status_code == 200
    assert [project["path"] for project in response.data["projects"]] == [
        str(normal_codex_home.resolve()),
    ]


def test_all_project_reports_lists_recent_and_global_reports(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recent_project = tmp_path / "project"
    global_project = tmp_path / "global"
    duplicate_global_project = tmp_path / "duplicate"
    for project, report_name in (
        (recent_project, "recent.md"),
        (global_project, "global.md"),
        (duplicate_global_project, "duplicate.md"),
    ):
        reports = project / ".reports"
        reports.mkdir(parents=True)
        (reports / report_name).write_text("done", encoding="utf-8")

    monkeypatch.setattr(
        report_views,
        "_get_recent_projects",
        lambda: [
            {"path": str(recent_project), "name": "Recent"},
            {"path": str(duplicate_global_project), "name": "Duplicate"},
        ],
    )
    monkeypatch.setattr(report_views, "CODEX_HOME_DIR", global_project)
    monkeypatch.setattr(report_views, "NORMAL_CODEX_HOME_DIR", duplicate_global_project)
    monkeypatch.setattr(report_views, "HOME_REPORTS_PROJECT_DIR", tmp_path / "missing")

    response = _get_all_project_reports()

    assert response.status_code == 200
    items = response.data["items"]
    item_paths = {(item["project"]["path"], item["file"]["path"]) for item in items}
    assert item_paths == {
        (str(global_project.resolve()), "global.md"),
        (str(duplicate_global_project.resolve()), "duplicate.md"),
        (str(recent_project.resolve()), "recent.md"),
    }
    assert all(item["id"] == f"{item['project']['path']}:{item['file']['path']}" for item in items)


def test_project_reports_file_delete_removes_report_inside_reports_dir(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    report = reports / "summary.md"
    report.write_text("done", encoding="utf-8")

    response = _delete_report(project, "summary.md")

    assert response.status_code == 200
    assert response.data["deleted"] is True
    assert response.data["file"]["path"] == "summary.md"
    assert not report.exists()


def test_project_reports_file_delete_rejects_path_traversal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    outside = project / "outside.md"
    outside.write_text("keep", encoding="utf-8")

    response = _delete_report(project, "../outside.md")

    assert response.status_code == 400
    assert response.data["error"] == "file must be inside .reports"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_project_reports_file_delete_rejects_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / ".reports" / "nested"
    nested.mkdir(parents=True)

    response = _delete_report(project, "nested")

    assert response.status_code == 400
    assert response.data["error"] == "Report path must be a file"
    assert nested.is_dir()


def test_project_reports_file_delete_reports_missing_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".reports").mkdir(parents=True)

    response = _delete_report(project, "missing.md")

    assert response.status_code == 404
    assert response.data["error"] == "File not found: missing.md"


def test_project_reports_file_patch_updates_markdown_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    report = reports / "summary.md"
    report.write_text("# Old", encoding="utf-8")

    response = _patch_report(project, "summary.md", "# New\n\nUpdated.")

    assert response.status_code == 200
    assert response.data["file"]["path"] == "summary.md"
    assert response.data["file"]["kind"] == "markdown"
    assert response.data["content"] == "# New\n\nUpdated."
    assert report.read_text(encoding="utf-8") == "# New\n\nUpdated."


def test_project_reports_file_patch_rejects_path_traversal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".reports").mkdir(parents=True)
    outside = project / "outside.md"
    outside.write_text("keep", encoding="utf-8")

    response = _patch_report(project, "../outside.md", "replace")

    assert response.status_code == 400
    assert response.data["error"] == "file must be inside .reports"
    assert outside.read_text(encoding="utf-8") == "keep"


def test_project_reports_file_patch_rejects_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / ".reports" / "nested"
    nested.mkdir(parents=True)

    response = _patch_report(project, "nested", "replace")

    assert response.status_code == 400
    assert response.data["error"] == "Report path must be a file"


def test_project_reports_file_patch_rejects_image_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    image = reports / "preview.png"
    image.write_bytes(b"png")

    response = _patch_report(project, "preview.png", "replace")

    assert response.status_code == 415
    assert response.data["error"] == "Only markdown and text reports can be edited."
    assert image.read_bytes() == b"png"


def test_project_reports_file_patch_requires_string_content(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    report = reports / "summary.md"
    report.write_text("# Old", encoding="utf-8")

    response = _patch_report(project, "summary.md", 42)

    assert response.status_code == 400
    assert response.data["error"] == "content must be a string"
    assert report.read_text(encoding="utf-8") == "# Old"


def test_project_reports_download_returns_raw_report_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reports = project / ".reports" / "nested"
    reports.mkdir(parents=True)
    report = reports / "artifact.pdf"
    report.write_bytes(b"%PDF-1.4\ncontent")

    response = _download_report(project, "nested/artifact.pdf")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "artifact.pdf" in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == b"%PDF-1.4\ncontent"


def test_project_reports_download_rejects_path_traversal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".reports").mkdir(parents=True)
    outside = project / "outside.pdf"
    outside.write_bytes(b"keep")

    response = _download_report(project, "../outside.pdf")

    assert response.status_code == 400
    assert response.data["error"] == "file must be inside .reports"


def test_project_reports_download_reports_missing_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".reports").mkdir(parents=True)

    response = _download_report(project, "missing.pdf")

    assert response.status_code == 404
    assert response.data["error"] == "File not found: missing.pdf"


def test_project_reports_includes_shared_tags(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENBASE_CODER_CLI_DATA_DIR", str(tmp_path / "data"))
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    (reports / "summary.md").write_text("# Summary", encoding="utf-8")

    tag_response = _set_report_tags(project, "summary.md", ["Needs Review"])
    assert tag_response.status_code == 200
    assert tag_response.data["tags"] == ["Needs Review"]

    factory = APIRequestFactory()
    request = factory.get(f"/api/projects/reports/?{urlencode({'path': str(project)})}")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = views.project_reports(request)

    assert response.status_code == 200
    assert response.data["files"][0]["tags"] == ["Needs Review"]


def test_report_tags_endpoint_reuses_thread_tag_options(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENBASE_CODER_CLI_DATA_DIR", str(tmp_path / "data"))
    project = tmp_path / "project"
    reports = project / ".reports"
    reports.mkdir(parents=True)
    (reports / "summary.md").write_text("# Summary", encoding="utf-8")

    from openbase_coder_cli.openbase_coder_cli_app.item_tags import set_thread_tags

    set_thread_tags("thread-1", ["Client"])
    response = _set_report_tags(project, "summary.md", ["client"])

    assert response.status_code == 200
    assert response.data["tags"] == ["Client"]
    assert [tag["label"] for tag in response.data["tag_options"]] == ["Client"]


def test_report_tags_endpoint_rejects_missing_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENBASE_CODER_CLI_DATA_DIR", str(tmp_path / "data"))
    project = tmp_path / "project"
    (project / ".reports").mkdir(parents=True)

    response = _set_report_tags(project, "missing.md", ["Client"])

    assert response.status_code == 404
    assert response.data["error"] == "File not found: missing.md"
