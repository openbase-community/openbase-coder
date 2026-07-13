# Sync Between Your Computers

Code sync keeps the same working directories on two or more of your machines
(for example a MacBook and a Mac mini, or a laptop and a Cloud DevSpace) in
near-realtime sync, so your secondary machine is always ready to take a voice
call. Files move on save — no commits, no pushes, no manual copying.

Under the hood, Openbase Coder runs a fully managed
[Syncthing](https://syncthing.net) instance as the `code-sync` service. You
never configure Syncthing yourself: device pairing comes from your Openbase
Cloud device registry, transport is pinned to your private Tailscale network,
and global discovery, relays, and NAT traversal are all disabled. Nothing
leaves your tailnet.

## What syncs

- Every directory you add with `openbase-coder sync add` (or from the console
  Sync settings). Folders are identified by their **home-relative path** —
  `~/Projects/myapp` on one machine maps to `~/Projects/myapp` on the other,
  even when the home directories differ.
- **Secrets sync deliberately.** `.env` files, keys, and other
  gitignored-but-needed files travel with the code. This is a core feature:
  git transports alone can never move them, and a second machine without its
  secrets cannot actually run your project. Only machines you own (they are
  all inside your tailnet) ever receive them.

## What never syncs

- **`.git` and all other VCS metadata (`.jj`, `.hg`) — categorically.** A git
  directory is a multi-file database mutated non-atomically; syncing it
  transfers refs from one moment and the index from another, which silently
  corrupts checkouts (this failure mode is why code sync exists in its
  current form). Each machine keeps its own private `.git`; branch pointers
  are reconciled through git's own transport instead (below).
- Dependency and build noise: `node_modules`, virtualenvs, `dist`/`build`
  outputs, `__pycache__`, `DerivedData`, caches, `*.sqlite3`.
- Machine-local state under `~/.openbase` (device identity, databases, logs).

Each synced folder gets a generated `.stignore` owned by openbase-coder; add
per-folder patterns via `extra_ignores` in the sync settings rather than
editing it.

## How git stays correct on both machines

Commits made on either machine propagate through a small reconciler that runs
every minute:

- When the peer committed and Syncthing has already delivered the resulting
  files, your local branch pointer is **fast-forwarded** to the same commit —
  status goes clean, nothing moves twice. This only happens when it is
  provably safe: no merge/rebase in progress, your head is an ancestor of the
  peer's, and your working tree already matches the peer's commit exactly.
- When both machines committed different things, nothing happens
  automatically: a **repo sync conflict** is recorded and surfaced in the
  console and iOS app (like thread sync conflicts), with *Keep Local* /
  *Use Remote* resolution. *Use Remote* safety-stashes your working tree
  first, so nothing is lost.
- Uncommitted work needs no reconciliation at all — it syncs as files and
  simply shows as a dirty tree on both sides.

Git **worktrees** under synced folders are first-class: the worktree's
files sync like any files, and each machine attaches its own local git
identity automatically (a small synced manifest tells the other machine
which repository and branch to attach). Run git commands in a worktree on
either computer; commits reconcile back through the same branch
fast-forward machinery as any repository.

Coding threads (Codex and Claude Code) also travel between your machines
over the same channel: each device exports snapshots of recent threads and
imports the other's automatically. Only threads active in the **last 15
days** are exchanged — after a long gap between machines, older threads
stay where they were created (they are never deleted, just not carried
across).

Machines fetch from each other directly over Tailscale (read-only git smart
HTTP served by the local API with your own credentials); no GitHub round-trip
is involved.

## The write lease

To make stale-machine echoes structurally impossible, code sync holds an
advisory write lease: the machine with recent voice/agent activity (last 15
minutes) keeps its folders send-receive, while an idle machine that can see
an active peer flips its own folders receive-only. When nobody is provably
active the lease is sticky with its last holder, so plain manual edits always
still propagate. Set `lease_mode` to `manual` in sync settings to disable
automatic flipping when you intentionally work on both machines at once.

## Versioning: the undo net

Synced work is often uncommitted, so it has no reflog. Every managed folder
has staggered file versioning enabled: whenever an incoming sync replaces or
deletes a file, the previous copy is kept under
`~/.openbase/sync-versions/<folder-id>/` for 30 days. A bad deletion that
propagates through sync is an undo, not data loss. Local edits never create
versions, and the storage-heavy patterns are excluded from sync entirely;
`openbase-coder doctor` warns when version history grows past 2 GiB, and the
console offers a purge control (`POST /api/sync/versions/purge/`).

## Eligibility

Code sync arms only when your Openbase Cloud device registry shows **two or
more non-phone devices with Tailscale identities**. Phones never participate
as sync peers; they only view sync state and conflicts. With a single
machine, the console shows an "add a second machine" nudge and
`openbase-coder sync enable` explains what is missing.

## Conflicts

Two kinds of conflicts are surfaced, never auto-resolved:

- **Repo conflicts** — both machines committed divergent work on the same
  branch (see above).
- **File conflicts** — Syncthing's last-resort `*.sync-conflict-*` copies
  from truly simultaneous edits of one file. The reconciler finds and lists
  them so they are cleaned up deliberately instead of discovered by grep.

List and resolve them with `openbase-coder sync conflicts` and
`openbase-coder sync resolve`, or from the console/iOS conflict pages.

See the [`sync` command reference](commands/sync.md) for the full CLI.
