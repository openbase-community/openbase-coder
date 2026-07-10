# lockdown

Manage locked-down mode: while enabled, Super Agents launches cannot use
permission bypasses (Codex `approvalPolicy: never` or `danger-full-access`
sandboxes, Claude Code `bypassPermissions`) unless your safe phrase has been
heard in the current voice session.

Locked-down mode is off by default; the onboarding skill offers to enable it
as its final step.

## How It Works

- With locked-down mode on, a machine-wide permission guard keeps every
  coding-agent launch gated: agents ask for approval before running commands
  and work in a workspace-limited sandbox. Approvals arrive in the iOS app,
  console, and desktop app as usual.
- Saying your **safe phrase** during a call unlocks full-access launches for
  the rest of that voice session. Only the direct speech transcript counts —
  text produced or relayed by an agent can never unlock, so a prompt-injected
  agent cannot talk its way past the guard.
- Every new voice session starts locked again.

## Usage

```bash
# Show mode, whether a safe phrase is set, and the live guard state
openbase-coder lockdown status [--json]

# Enable (the safe phrase is required once)
openbase-coder lockdown enable --safe-phrase "purple elephant sunrise"

# Re-arm immediately after an unlock, without waiting for a new session
openbase-coder lockdown relock

# Disable
openbase-coder lockdown disable
```

Pick a safe phrase you would not say by accident; matching ignores casing and
punctuation.

## API

The console and apps use `GET/PATCH /api/settings/lockdown/` with
`locked_down_mode` and `lockdown_safe_phrase` fields; the payload also
reports `restricted`, the live guard state.
