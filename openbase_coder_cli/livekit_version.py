"""The livekit-server version Openbase Coder releases ship.

Single source of truth for the pinned LiveKit engine: the release workflow
refuses to package any other version (bump this constant deliberately when
upgrading), and dev installs — which resolve livekit-server from
Homebrew/PATH instead of a bundle — warn when their local version diverges,
so engine differences can't sail through development testing unnoticed.
"""

from __future__ import annotations

LIVEKIT_SERVER_PINNED_VERSION = "1.9.10"
