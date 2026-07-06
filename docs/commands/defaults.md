# defaults

Manage default dispatcher and Super Agents model/reasoning settings.

## Usage

```bash
openbase-coder defaults COMMAND [ARGS]
```

## Commands

| Command | Description |
|---|---|
| `dispatcher-reasoning [LEVEL]` | Show or set the default dispatcher reasoning effort |
| `dispatcher-model [MODEL]` | Show or set the default dispatcher model |
| `super-agents-reasoning [LEVEL]` | Show or set the default Super Agents reasoning effort |
| `super-agents-model [MODEL]` | Show or set the default Super Agents model |

## Examples

```bash
openbase-coder defaults dispatcher-reasoning low
openbase-coder defaults dispatcher-model gpt-5.5
openbase-coder defaults super-agents-reasoning high
openbase-coder defaults super-agents-model opus
```
