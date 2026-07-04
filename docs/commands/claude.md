# claude

Manage Claude Code auth for Openbase's managed `CLAUDE_CONFIG_DIR`.

## Usage

```bash
openbase-coder claude status
openbase-coder claude login
openbase-coder claude sync-state
```

`status` and `login` run Claude Code with
`CLAUDE_CONFIG_DIR=~/.openbase/claude_config`. This is separate from a normal
Claude Code login because Claude Code stores usable OAuth credentials in a
config-dir-scoped credential store.

`sync-state` merges normal Claude Code state from `~/.claude.json` into
`~/.openbase/claude_config/.claude.json` — the file Claude Code reads under
Openbase's `CLAUDE_CONFIG_DIR` — preserving existing Openbase values and
unioning `mcpServers` entries. On macOS, when the Openbase config dir is not
already logged in, it also copies the normal "Claude Code-credentials"
keychain item to Openbase's config-dir-specific keychain service so managed
Claude sessions inherit your normal Claude login without a second browser
OAuth. If no login can be bridged, run `openbase-coder claude login`.
