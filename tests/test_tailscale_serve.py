from __future__ import annotations

import subprocess

from openbase_coder_cli.services import tailscale_serve


def test_configure_tailscale_serve_installs_openbase_and_livekit_routes(monkeypatch):
    commands = []

    monkeypatch.setattr(tailscale_serve, "_tailscale_bin", lambda: "/usr/bin/tailscale")

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(tailscale_serve.subprocess, "run", fake_run)

    tailscale_serve.configure_tailscale_serve()

    assert [command for command, _kwargs in commands] == [
        [
            "/usr/bin/tailscale",
            "serve",
            "--bg",
            "--http=18080",
            "http://127.0.0.1:7999",
        ],
        [
            "/usr/bin/tailscale",
            "serve",
            "--bg",
            "--tcp=7880",
            "tcp://127.0.0.1:7880",
        ],
    ]


def test_tailscale_serve_health_requires_routes_and_external_health(monkeypatch):
    monkeypatch.setattr(tailscale_serve, "_tailscale_bin", lambda: "/usr/bin/tailscale")
    monkeypatch.setattr(
        tailscale_serve,
        "_tailscale_status",
        lambda _bin: {
            "Self": {
                "DNSName": "mac.tailnet.ts.net.",
            }
        },
    )
    monkeypatch.setattr(
        tailscale_serve,
        "_tailscale_serve_status",
        lambda _bin: {
            "TCP": {
                "18080": {"HTTP": True},
                "7880": {"TCPForward": "127.0.0.1:7880"},
            },
            "Web": {
                "mac.tailnet.ts.net:18080": {
                    "Handlers": {
                        "/": {"Proxy": "http://127.0.0.1:7999"},
                    }
                }
            },
        },
    )
    monkeypatch.setattr(
        tailscale_serve,
        "_openbase_reachable",
        lambda url: (url == "http://mac.tailnet.ts.net:18080", None),
    )

    health = tailscale_serve.tailscale_serve_health()

    assert health.healthy is True
    assert health.host == "mac.tailnet.ts.net"
    assert health.openbase_url == "http://mac.tailnet.ts.net:18080"
