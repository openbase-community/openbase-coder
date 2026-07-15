from __future__ import annotations

from openbase_coder_cli.code_sync import eligibility


def _device(
    device_id: str,
    kind: str = "desktop",
    magic_dns: str = "host.tail1234.ts.net.",
    syncthing_device_id: str | None = "AAAAAAA-BBBBBBB",
    name: str = "Machine",
) -> dict:
    device = {
        "device_id": device_id,
        "kind": kind,
        "display_name": name,
        "tailscale_magic_dns": magic_dns,
        "capabilities": {},
    }
    if syncthing_device_id:
        device["capabilities"]["syncthing_device_id"] = syncthing_device_id
    return device


def test_two_desktops_with_tailscale_are_eligible() -> None:
    state = {
        "devices": [
            _device("desktop-self"),
            _device("desktop-peer", name="Mac mini"),
        ]
    }
    result = eligibility.evaluate_state(state, "desktop-self")

    assert result.eligible is True
    assert result.reason == ""
    assert [peer.device_id for peer in result.peers] == ["desktop-peer"]
    assert result.peers[0].name == "Mac mini"
    assert result.peers[0].tailscale_magic_dns == "host.tail1234.ts.net."


def test_single_desktop_is_not_eligible() -> None:
    state = {"devices": [_device("desktop-self")]}
    result = eligibility.evaluate_state(state, "desktop-self")

    assert result.eligible is False
    assert "two non-phone devices" in result.reason
    assert result.peers == ()


def test_mobiles_and_tailscaleless_devices_do_not_count() -> None:
    state = {
        "devices": [
            _device("desktop-self"),
            _device("phone-1", kind="mobile"),
            _device("desktop-stale", magic_dns=""),
        ]
    }
    result = eligibility.evaluate_state(state, "desktop-self")

    assert result.eligible is False
    assert result.peers == ()


def test_syncable_peers_require_syncthing_identity() -> None:
    state = {
        "devices": [
            _device("desktop-self"),
            _device("desktop-ready", name="Ready"),
            _device("desktop-not-ready", syncthing_device_id=None),
        ]
    }
    result = eligibility.evaluate_state(state, "desktop-self")

    assert result.eligible is True
    assert len(result.peers) == 2
    syncable = eligibility.syncable_peers(result)
    assert [peer.name for peer in syncable] == ["Ready"]


def test_missing_devices_payload_is_not_eligible() -> None:
    result = eligibility.evaluate_state({}, "desktop-self")
    assert result.eligible is False


def test_syncable_peers_dedupes_and_excludes_self(monkeypatch) -> None:
    from openbase_coder_cli.code_sync import eligibility

    monkeypatch.setattr(
        "openbase_coder_cli.code_sync.syncthing.stored_device_id",
        lambda *a, **k: "SELF-ENGINE-ID",
    )
    peers = (
        eligibility.SyncPeer(
            device_id="d1", name="mini", kind="desktop", tailscale_magic_dns="mini.ts.net",
            syncthing_device_id="MINI-ENGINE-ID",
        ),
        eligibility.SyncPeer(
            device_id="d2", name="mini-stale", kind="desktop", tailscale_magic_dns="mini.ts.net",
            syncthing_device_id="MINI-ENGINE-ID",
        ),
        eligibility.SyncPeer(
            device_id="d3", name="old-self", kind="desktop", tailscale_magic_dns="self.ts.net",
            syncthing_device_id="SELF-ENGINE-ID",
        ),
        eligibility.SyncPeer(
            device_id="d4", name="no-engine", kind="desktop", tailscale_magic_dns="x.ts.net",
            syncthing_device_id="",
        ),
    )
    result = eligibility.EligibilityResult(eligible=True, reason="", peers=peers)

    kept = eligibility.syncable_peers(result)

    assert [p.device_id for p in kept] == ["d1"]
