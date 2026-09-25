"""Two independent auth mechanisms for the control tower.

- Dashboard sessions: a single shared password (``DASHBOARD_PASSWORD``)
  exchanged for a short-lived HMAC-signed token (HS256 JWT) via
  ``POST /auth/login``. No external JWT library — HS256 is just
  ``base64url(header).base64url(payload).base64url(hmac_sha256(...))``,
  which stdlib ``hmac``/``hashlib``/``base64`` cover directly.
- Agent API keys: bearer tokens issued via ``POST /applications``
  (api/main.py) and looked up by their sha256 hash. Enforcement of those
  lives in api/main.py, next to the ``app.state.applications`` store it
  checks against; this module only provides the shared hashing helper.

``AEGIS_DISABLE_AUTH=1`` bypasses both checks entirely. It exists so the
test suite (see tests/conftest.py) doesn't need every fixture to mint
tokens/keys — it must never be set outside tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import HTTPException

_JWT_ALG = "HS256"
DASHBOARD_TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12h dashboard session


def auth_disabled() -> bool:
    return os.environ.get("AEGIS_DISABLE_AUTH") == "1"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET is not configured — dashboard login is unavailable.",
        )
    return secret


def create_access_token(subject: str, *, ttl_seconds: int = DASHBOARD_TOKEN_TTL_SECONDS) -> str:
    header_b64 = _b64url_encode(
        json.dumps({"alg": _JWT_ALG, "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
    )
    now = int(time.time())
    payload_b64 = _b64url_encode(
        json.dumps(
            {"sub": subject, "iat": now, "exp": now + ttl_seconds},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        _jwt_secret().encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    """Verifies signature and expiry; raises HTTPException(401) on either."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="invalid session token")
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        _jwt_secret().encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
    ).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid session token") from exc
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(status_code=401, detail="invalid session token")
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid session token") from exc
    if float(payload.get("exp", 0)) < time.time():
        raise HTTPException(status_code=401, detail="session token expired")
    return payload
