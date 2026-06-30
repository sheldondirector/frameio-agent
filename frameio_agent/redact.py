"""Redaction utilities — keep secrets out of stdout/stderr/logs.

The CLI never prints raw token values, client secrets, or OAuth `code`
parameters. This module is the single source of truth for what counts as
sensitive and how it is replaced.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PLACEHOLDER = "***redacted***"

# Env-var key fragments that mark a value as sensitive.
SECRET_KEY_FRAGMENTS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "PRIVATE",
    "CODE_VERIFIER",
    "REFRESH",
    "AUTH_CODE",
)

# URL query parameter names whose values must be redacted.
SECRET_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "code",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "code_verifier",
        "Signature",
        "X-Amz-Signature",
        "AWSAccessKeyId",
        "Authorization",
    }
)

# JWT-ish: three base64url segments separated by dots, generous length.
_JWT_RE = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b")

# Bearer / Token headers in serialized strings.
_BEARER_RE = re.compile(r"(?i)(Bearer|Token)\s+[A-Za-z0-9._\-+/=]{12,}")

# Long opaque hex/alphanumeric strings that look like client secrets or
# access tokens but aren't JWTs. Conservative: only triggers on >= 32 chars.
_OPAQUE_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def is_secret_key(key: str) -> bool:
    """True if an env var key should be treated as secret."""
    upper = key.upper()
    return any(fragment in upper for fragment in SECRET_KEY_FRAGMENTS) or upper in {
        "FRAMEIO_CLIENT_SECRET",
    }


def redact_value(value: str) -> str:
    """Redact JWT-ish tokens, Bearer headers, and long opaque strings inside text."""
    if not value:
        return value
    out = _JWT_RE.sub(PLACEHOLDER, value)
    out = _BEARER_RE.sub(f"Bearer {PLACEHOLDER}", out)
    out = _OPAQUE_RE.sub(PLACEHOLDER, out)
    return out


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of an env-like mapping with secret values replaced."""
    return {k: (PLACEHOLDER if is_secret_key(k) and v else v) for k, v in env.items()}


def redact_url(url: str) -> str:
    """Strip secret query params from a URL while preserving structure."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    redacted = [
        (k, PLACEHOLDER if k in SECRET_QUERY_PARAMS else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(redacted)))


def redact_mapping(data: Any) -> Any:
    """Recursively redact a JSON-like structure.

    - Dict keys matching :func:`is_secret_key` get :data:`PLACEHOLDER` as value.
    - Strings are passed through :func:`redact_value` (URL-aware when applicable).
    - Lists/tuples are walked element-wise.
    """
    if isinstance(data, dict):
        out: dict[Any, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and is_secret_key(k):
                out[k] = PLACEHOLDER
            else:
                out[k] = redact_mapping(v)
        return out
    if isinstance(data, (list, tuple)):
        cls = type(data)
        return cls(redact_mapping(v) for v in data)  # type: ignore[call-arg]
    if isinstance(data, str):
        looks_like_url = data.startswith(("http://", "https://"))
        return redact_url(data) if looks_like_url else redact_value(data)
    return data


def safe_format_exception(exc: BaseException) -> str:
    """Format an exception's message with redaction applied."""
    return redact_value(str(exc))


__all__: Iterable[str] = (
    "PLACEHOLDER",
    "SECRET_KEY_FRAGMENTS",
    "SECRET_QUERY_PARAMS",
    "is_secret_key",
    "redact_value",
    "redact_env",
    "redact_url",
    "redact_mapping",
    "safe_format_exception",
)
