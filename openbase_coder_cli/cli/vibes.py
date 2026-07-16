"""CLI helpers for linking Vibes AI to Openbase Coder."""

from __future__ import annotations

import click
import httpx

from openbase_coder_cli.brain_score import save_brain_score_token

VIBES_UAT_AUTH_LOGIN_URL = "http://uat.api.getvibes.ai/api/v1/auth/login"


def _extract_access_token(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""

    direct = payload.get("access_token")
    if isinstance(direct, str):
        return direct.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("access_token")
        if isinstance(nested, str):
            return nested.strip()

    return ""


@click.group()
def vibes() -> None:
    """Vibes AI account helpers."""


@vibes.command("link")
def link_vibes_account() -> None:
    """Interactively link a Vibes AI account for brain score uploads."""
    click.echo("This will link your Vibes AI account for brain score uploads.")
    click.echo()
    click.echo("WARNING: The Vibes UAT auth endpoint is HTTP only.")
    click.echo("Your password will be sent without HTTPS/TLS encryption.")
    click.echo("Do not use an important password or a password reused elsewhere.")
    click.echo()
    if not click.confirm("Continue with HTTP login?", default=False):
        click.echo("Canceled. No credentials were sent.")
        return

    email = click.prompt("Vibes username/email").strip()
    if not email:
        raise click.ClickException("Vibes username/email is required.")
    password = click.prompt("Vibes password", hide_input=True)
    if not password:
        raise click.ClickException("Vibes password is required.")

    try:
        response = httpx.post(
            VIBES_UAT_AUTH_LOGIN_URL,
            json={"email": email, "password": password},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(
            f"Vibes login failed with HTTP {exc.response.status_code}."
        ) from None
    except httpx.RequestError as exc:
        raise click.ClickException(f"Vibes login request failed: {exc}") from None
    except ValueError:
        raise click.ClickException(
            "Vibes login failed: response was not JSON."
        ) from None

    access_token = _extract_access_token(payload)
    if not access_token:
        raise click.ClickException(
            "Vibes login succeeded but no access token was returned."
        )

    token_path = save_brain_score_token(access_token)
    click.echo(f"Vibes account linked. Brain score token saved to {token_path}.")
