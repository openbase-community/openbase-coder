from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from openbase_coder_cli.services.ec2_identity import presign_get_caller_identity_url


def test_presign_get_caller_identity_url_uses_regional_sts_and_short_expiry():
    url = presign_get_caller_identity_url(
        {
            "AccessKeyId": "AKIAEXAMPLE",
            "SecretAccessKey": "secret",
            "Token": "session/token",
        },
        region="us-east-1",
        now=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        expires=60,
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.hostname == "sts.us-east-1.amazonaws.com"
    assert params["Action"] == ["GetCallerIdentity"]
    assert params["Version"] == ["2011-06-15"]
    assert params["X-Amz-Expires"] == ["60"]
    assert params["X-Amz-SignedHeaders"] == ["host"]
    assert params["X-Amz-Signature"][0]
