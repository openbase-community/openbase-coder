# Brain Score Concurrency

This is documented as a plugin capability now, even though Brain Score Concurrency will become an optional plugin later.

The LiveKit Vibes brain readiness score is read from `~/.openbase/brain_score.json` and exposed by the CLI at `/api/brain-readiness/`.
If no brain score token is configured through `OPENBASE_BRAIN_SCORE_TOKEN` or `~/.openbase/brain_score_token`, the feature is disabled and `/api/brain-readiness/` reports no available score.

## Linking a Vibes AI account

The brain score upload uses the Vibes UAT score endpoint:

```text
http://uat.api.getvibes.ai/api/v1/score/hackathon
```

That endpoint requires HTTP Bearer authentication. Link a Vibes account from an
interactive terminal with:

```bash
openbase-coder vibes link
```

The command prompts for the Vibes username/email and password, calls the Vibes
UAT auth login endpoint, extracts the returned `access_token`, and stores it in
the existing brain score token file:

```text
~/.openbase/brain_score_token
```

The token file is created with mode `600` and should stay outside tracked repos.
At runtime, Openbase Coder also accepts `OPENBASE_BRAIN_SCORE_TOKEN` for systems
that prefer environment-based secret injection.

Important: this integration targets an early version of the Vibes AI app. Use a
Vibes-only password that you do not care about and do not reuse anywhere else.
Later Vibes AI app versions will block this case.

Concurrent agent threshold mapping:

| Brain readiness score | Concurrent agent threshold |
| --- | ---: |
| `< 25` | `1+` |
| `25` to `< 50` | `2+` |
| `50` to `< 75` | `4+` |
| `>= 75` | `7+` |

The backend computes the threshold from the exact `brs` value. The iOS app may display the score rounded to an integer, but it should use `parallel_voice_threshold` from `/api/brain-readiness/` for the concurrent-agent threshold whenever the score is available.

If no brain readiness score is available, iOS falls back to the locally stored muted-agent music threshold setting.
