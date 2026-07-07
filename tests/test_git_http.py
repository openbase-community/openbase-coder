from __future__ import annotations

# ruff: noqa: E402, I001

import os
import subprocess
from pathlib import Path

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django
from django.test import RequestFactory

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import git_http
from openbase_coder_cli.sync_config import SyncFolder, folder_id_for_relpath

FOLDER_RELPATH = "Projects/demo"
FOLDER_ID = folder_id_for_relpath(FOLDER_RELPATH)


def _setup_folder(monkeypatch, tmp_path: Path) -> Path:
    """A synced folder under a fake $HOME containing one real git repo."""
    monkeypatch.setenv("HOME", str(tmp_path))
    folder_root = tmp_path / FOLDER_RELPATH
    repo = folder_root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)], capture_output=True, check=True
    )
    (repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=T",
            "add",
            "-A",
        ],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=T",
            "commit",
            "-m",
            "initial",
        ],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    monkeypatch.setattr(
        git_http,
        "folder_for_id",
        lambda folder_id: (
            SyncFolder(relpath=FOLDER_RELPATH) if folder_id == FOLDER_ID else None
        ),
    )
    monkeypatch.setattr(git_http, "_authenticate", lambda request: None)
    return repo


def _info_refs_request(folder_id: str, subpath: str):
    return RequestFactory().get(
        f"/api/sync/git/{folder_id}/{subpath}",
        {"service": "git-upload-pack"},
    )


def test_info_refs_serves_upload_pack_advertisement(
    monkeypatch, tmp_path: Path
) -> None:
    _setup_folder(monkeypatch, tmp_path)

    response = git_http.git_http_backend(
        _info_refs_request(FOLDER_ID, "repo/info/refs"),
        folder_id=FOLDER_ID,
        subpath="repo/info/refs",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-git-upload-pack-advertisement"
    assert b"git-upload-pack" in response.content
    assert b"refs/heads/main" in response.content


def test_unknown_folder_returns_404(monkeypatch, tmp_path: Path) -> None:
    _setup_folder(monkeypatch, tmp_path)

    response = git_http.git_http_backend(
        _info_refs_request("cs-unknown", "repo/info/refs"),
        folder_id="cs-unknown",
        subpath="repo/info/refs",
    )

    assert response.status_code == 404


def test_traversal_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _setup_folder(monkeypatch, tmp_path)
    # A repo outside the synced folder that traversal would otherwise reach.
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(outside)],
        capture_output=True,
        check=True,
    )

    subpath = "../../outside-repo/info/refs"
    response = git_http.git_http_backend(
        _info_refs_request(FOLDER_ID, subpath),
        folder_id=FOLDER_ID,
        subpath=subpath,
    )

    assert response.status_code == 400


def test_non_repo_path_returns_404(monkeypatch, tmp_path: Path) -> None:
    _setup_folder(monkeypatch, tmp_path)

    response = git_http.git_http_backend(
        _info_refs_request(FOLDER_ID, "not-a-repo/info/refs"),
        folder_id=FOLDER_ID,
        subpath="not-a-repo/info/refs",
    )

    assert response.status_code == 404


def test_receive_pack_service_is_refused(monkeypatch, tmp_path: Path) -> None:
    _setup_folder(monkeypatch, tmp_path)

    request = RequestFactory().get(
        f"/api/sync/git/{FOLDER_ID}/repo/info/refs",
        {"service": "git-receive-pack"},
    )
    response = git_http.git_http_backend(
        request, folder_id=FOLDER_ID, subpath="repo/info/refs"
    )

    assert response.status_code == 403


def test_unsupported_endpoint_returns_404(monkeypatch, tmp_path: Path) -> None:
    _setup_folder(monkeypatch, tmp_path)

    request = RequestFactory().post(f"/api/sync/git/{FOLDER_ID}/repo/git-receive-pack")
    response = git_http.git_http_backend(
        request, folder_id=FOLDER_ID, subpath="repo/git-receive-pack"
    )

    assert response.status_code == 404


def test_unauthenticated_requests_are_refused() -> None:
    # No Authorization header and the real authenticator: refused up front.
    response = git_http.git_http_backend(
        _info_refs_request(FOLDER_ID, "repo/info/refs"),
        folder_id=FOLDER_ID,
        subpath="repo/info/refs",
    )
    assert response.status_code == 401


def test_end_to_end_fetch_over_smart_http(monkeypatch, tmp_path: Path) -> None:
    """A real `git fetch` against the view via a throwaway HTTP server."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    repo = _setup_folder(monkeypatch, tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    factory = RequestFactory()

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self):
            path, _, query = self.path.partition("?")
            prefix = f"/api/sync/git/{FOLDER_ID}/"
            assert path.startswith(prefix)
            subpath = path[len(prefix) :]
            body = b""
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                body = self.rfile.read(length)
            if self.command == "GET":
                request = factory.get(path + ("?" + query if query else ""))
            else:
                request = factory.post(
                    path + ("?" + query if query else ""),
                    data=body,
                    content_type=self.headers.get("Content-Type", ""),
                )
            response = git_http.git_http_backend(
                request, folder_id=FOLDER_ID, subpath=subpath
            )
            self.send_response(response.status_code)
            self.send_header("Content-Type", response["Content-Type"])
            self.end_headers()
            self.wfile.write(response.content)

        def do_GET(self):
            self._dispatch()

        def do_POST(self):
            self._dispatch()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "init", "-b", "main", str(clone)],
            capture_output=True,
            check=True,
        )
        fetch = subprocess.run(
            [
                "git",
                "fetch",
                f"http://127.0.0.1:{port}/api/sync/git/{FOLDER_ID}/repo",
                "main",
            ],
            cwd=clone,
            capture_output=True,
            text=True,
        )
        assert fetch.returncode == 0, fetch.stderr
        fetched = subprocess.run(
            ["git", "rev-parse", "FETCH_HEAD"],
            cwd=clone,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert fetched == head
    finally:
        server.shutdown()
        server.server_close()
