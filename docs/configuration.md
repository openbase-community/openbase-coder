# Configuration

Openbase CLI reads configuration from environment variables (usually loaded from `~/.openbase/.env`).

## Core Variables

| Variable                                  | Required | Default                                          | Purpose                                     |
| ----------------------------------------- | -------- | ------------------------------------------------ | ------------------------------------------- |
| `OPENBASE_CODER_CLI_SECRET_KEY`           | Yes      | none                                             | Django secret key                           |
| `OPENBASE_CODER_CLI_API_TOKEN`            | Yes      | none                                             | Static bearer token auth                    |
| `OPENBASE_CODER_CLI_WEB_BACKEND_URL`      | No       | `https://app.openbase.cloud`                     | JWT/JWKS source + login endpoints           |
| `OPENBASE_CODER_CLI_JWT_JWKS_URL`         | No       | `<WEB_BACKEND_URL>/.well-known/jwks.json`        | JWKS URL for local JWT signature validation |
| `OPENBASE_CODER_CLI_JWT_AUTH_SESSION_URL` | No       | `<WEB_BACKEND_URL>/_allauth/app/v1/auth/session` | Fallback endpoint to validate JWTs remotely |
| `OPENBASE_CODER_CLI_JWT_ISSUER`           | No       | `WEB_BACKEND_URL`                                | Expected JWT issuer                         |
| `OPENBASE_CODER_CLI_JWT_AUDIENCE`         | No       | `openbase-coder-cli`                             | Expected JWT audience                       |
| `OPENBASE_CODER_CLI_ALLOWED_HOSTS`        | No       | `localhost,127.0.0.1`                            | Django allowed hosts                        |
| `OPENBASE_CODER_CLI_CORS_ORIGINS`         | No       | `http://localhost:8080,http://127.0.0.1:8080`    | CORS allowlist                              |
| `OPENBASE_CODER_CLI_DATA_DIR`             | No       | `~/.openbase`                                    | Data root (DB, static, logs, etc.)          |
| `OPENBASE_CODER_CLI_CONSOLE_BUILD_DIR`    | No       | inferred from install config                     | Console dist directory                      |
| `CODEX_MODEL`                             | No       | `gpt-5.5`                                        | Codex app-server model                      |
| `CODEX_MODEL_REASONING_EFFORT`            | No       | `high`                                           | Codex app-server reasoning effort           |
| `CODEX_SERVICE_TIER`                      | No       | `fast`                                           | Codex app-server service tier               |

## Agent/Voice Variables

| Variable                   | Required | Purpose                      |
| -------------------------- | -------- | ---------------------------- |
| `LIVEKIT_API_KEY`          | Yes      | LiveKit server auth          |
| `LIVEKIT_API_SECRET`       | Yes      | LiveKit server auth          |
| `LIVEKIT_URL`              | Yes      | LiveKit websocket URL        |
| `CODEX_APP_SERVER_URL`     | Yes      | Codex app-server websocket URL |
| `LIVEKIT_CODEX_THREAD_CWD` | Yes      | Shared Codex thread working directory |
| `ASSEMBLY_AI_API_KEY`      | Optional | Speech-to-text provider      |
| `CARTESIA_API_KEY`         | Optional | Text-to-speech provider      |
| `CARTESIA_VOICE_ID`        | Optional | Text-to-speech voice ID      |

## Auth Modes

All protected API routes support either:

1. Static token auth: `Authorization: Bearer <OPENBASE_CODER_CLI_API_TOKEN>`
2. JWT auth: RS256 JWT validated against `OPENBASE_CODER_CLI_JWT_JWKS_URL` (with fallback validation against `OPENBASE_CODER_CLI_JWT_AUTH_SESSION_URL`)

WebSocket auth accepts `?token=` in query string with either the static token or JWT.
