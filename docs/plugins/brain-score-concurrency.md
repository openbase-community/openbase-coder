# Brain Score Concurrency

This is documented as a plugin capability now, even though Brain Score Concurrency will become an optional plugin later.

The LiveKit Vibes brain readiness score is read from `~/.openbase/brain_score.json` and exposed by the CLI at `/api/brain-readiness/`.
If no brain score token is configured through `OPENBASE_BRAIN_SCORE_TOKEN` or `~/.openbase/brain_score_token`, the feature is disabled and `/api/brain-readiness/` reports no available score.

## Vibes access token

The brain score upload uses the Vibes UAT score endpoint:

```text
https://uat.api.getvibes.ai/api/v1/score/hackathon
```

That endpoint requires HTTP Bearer authentication. The token is usually obtained from the Vibes UAT auth API:

```bash
curl -X POST https://uat.api.getvibes.ai/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"your-password"}'
```

If the user does not have an account yet, sign up first:

```bash
curl -X POST https://uat.api.getvibes.ai/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"password-at-least-8-chars","name":"Your Name"}'
```

The response includes `access_token`. Store that value outside git:

```bash
mkdir -p ~/.openbase
printf '%s\n' '<access_token>' > ~/.openbase/brain_score_token
chmod 600 ~/.openbase/brain_score_token
```

Users can copy-paste this prompt into Codex or Claude Code to get and install the token:

```text
Use the Vibes UAT API docs at https://uat.api.getvibes.ai/docs. Help me obtain a Vibes access token for Openbase brain readiness scoring. If I already have a Vibes account, ask me for my email and password and call POST https://uat.api.getvibes.ai/api/v1/auth/login with JSON {"email":"...","password":"..."}. If I do not have an account, ask me for name, email, and password and call POST https://uat.api.getvibes.ai/api/v1/auth/signup with JSON {"name":"...","email":"...","password":"..."}. Extract access_token from the JSON response, write it to ~/.openbase/brain_score_token with mode 600, and do not print the token or write it into any tracked repository file.
```

Concurrent agent threshold mapping:

| Brain readiness score | Concurrent agent threshold |
| --- | ---: |
| `< 25` | `1+` |
| `25` to `< 50` | `2+` |
| `50` to `< 75` | `4+` |
| `>= 75` | `7+` |

The backend computes the threshold from the exact `brs` value. The iOS app may display the score rounded to an integer, but it should use `parallel_voice_threshold` from `/api/brain-readiness/` for the concurrent-agent threshold whenever the score is available.

If no brain readiness score is available, iOS falls back to the locally stored muted-agent music threshold setting.
