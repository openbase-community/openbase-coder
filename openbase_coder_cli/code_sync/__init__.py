"""Managed Syncthing file sync between a user's computers (code-sync).

Layer 1 syncs working trees over Tailscale with Syncthing while categorically
excluding VCS metadata; layer 2 reconciles git branch pointers through git's
own transport (see the reconciler module).
"""

from __future__ import annotations


class CodeSyncError(Exception):
    """Raised when a code-sync operation cannot be completed."""
