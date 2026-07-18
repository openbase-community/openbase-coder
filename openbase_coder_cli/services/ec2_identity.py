"""EC2 instance identity helpers for Cloud workspace self-repair."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from openbase_coder_cli.services.cloud_workspace import cloud_workspace_id

IMDS_BASE_URL = "http://169.254.169.254/latest"
STS_VERSION = "2011-06-15"
STS_ACTION = "GetCallerIdentity"


class EC2IdentityError(RuntimeError):
    """The EC2 identity material required for auth rehydration was unavailable."""


def build_instance_rehydrate_payload() -> dict[str, Any]:
    workspace_id = cloud_workspace_id()
    if not workspace_id:
        raise EC2IdentityError("This machine is not marked as an Openbase Cloud workspace.")

    token = _imds_token()
    document = _imds_json("/dynamic/instance-identity/document", token=token)
    instance_id = str(document.get("instanceId") or "")
    region = str(document.get("region") or "")
    if not instance_id or not region:
        raise EC2IdentityError("EC2 identity document did not include instanceId/region.")

    role_name = _imds_text("/meta-data/iam/security-credentials/", token=token).strip()
    if not role_name:
        raise EC2IdentityError("EC2 instance profile role was not available from IMDS.")
    credentials = _imds_json(
        f"/meta-data/iam/security-credentials/{role_name}",
        token=token,
    )
    sts_url = presign_get_caller_identity_url(credentials, region=region)
    return {
        "workspace_id": workspace_id,
        "instance_identity_document": document,
        "sts_get_caller_identity_url": sts_url,
    }


def _imds_token() -> str:
    try:
        response = httpx.put(
            f"{IMDS_BASE_URL}/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"},
            timeout=5,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EC2IdentityError("Could not get an IMDSv2 token.") from exc
    return response.text


def _imds_text(path: str, *, token: str) -> str:
    try:
        response = httpx.get(
            f"{IMDS_BASE_URL}{path}",
            headers={"X-aws-ec2-metadata-token": token},
            timeout=5,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EC2IdentityError(f"Could not read EC2 metadata at {path}.") from exc
    return response.text


def _imds_json(path: str, *, token: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_imds_text(path, token=token))
    except json.JSONDecodeError as exc:
        raise EC2IdentityError(f"EC2 metadata at {path} was not JSON.") from exc
    if not isinstance(parsed, dict):
        raise EC2IdentityError(f"EC2 metadata at {path} was not a JSON object.")
    return parsed


def presign_get_caller_identity_url(
    credentials: dict[str, Any],
    *,
    region: str,
    now: datetime | None = None,
    expires: int = 60,
) -> str:
    access_key = str(credentials.get("AccessKeyId") or "")
    secret_key = str(credentials.get("SecretAccessKey") or "")
    session_token = str(credentials.get("Token") or "")
    if not access_key or not secret_key or not session_token:
        raise EC2IdentityError("Instance profile credentials were incomplete.")
    if expires < 1 or expires > 300:
        raise EC2IdentityError("STS presign expiration must be between 1 and 300 seconds.")

    signed_at = now or datetime.now(UTC)
    amz_date = signed_at.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = signed_at.strftime("%Y%m%d")
    host = f"sts.{region}.amazonaws.com"
    credential_scope = f"{date_stamp}/{region}/sts/aws4_request"
    params = {
        "Action": STS_ACTION,
        "Version": STS_VERSION,
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-Security-Token": session_token,
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = _canonical_query(params)
    canonical_request = "\n".join(
        [
            "GET",
            "/",
            canonical_query,
            f"host:{host}\n",
            "host",
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"https://{host}/?{canonical_query}&X-Amz-Signature={signature}"


def _canonical_query(params: dict[str, str]) -> str:
    pairs = sorted((_aws_quote(key), _aws_quote(value)) for key, value in params.items())
    return "&".join(f"{key}={value}" for key, value in pairs)


def _aws_quote(value: str) -> str:
    return quote(value, safe="-_.~")


def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    date_key = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    date_region_key = _sign(date_key, region)
    date_region_service_key = _sign(date_region_key, "sts")
    return _sign(date_region_service_key, "aws4_request")


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()
