"""Config loader: reads ``.env`` and exposes a typed :class:`Config` view.

Resolution order for each key:
  1. Explicit environment variable.
  2. ``.env`` file — searched in the current working directory first, then
     the package checkout root (which only matters for editable/dev
     installs; under a normal ``pip install`` that path is site-packages
     and must never receive user secrets).
  3. Built-in default (only for non-secret values).

Relative token-cache paths resolve against the directory of the ``.env``
that was actually loaded; with no ``.env`` at all, secrets live under
``~/.frameio-agent/``. Secret-bearing keys never have built-in defaults.
Missing required values raise :class:`ConfigError` with a remediation
message.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from dotenv import load_dotenv

from .errors import ConfigError


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

DEFAULT_API_BASE = "https://api.frame.io/v4"
# Adobe Web App OAuth credentials require an HTTPS redirect and reject the
# http loopback form — https://localhost is what the Console accepts and
# what the clipboard-capture login flow expects.
DEFAULT_REDIRECT_URI = "https://localhost"
DEFAULT_TOKEN_FILE = ".frameio-agent/tokens.json"
DEFAULT_SCOPES = "openid,profile,email,offline_access,additional_info.roles"


def find_env_file() -> Optional[Path]:
    """Locate the .env to load: cwd first, then the dev-checkout root."""
    for cand in (Path.cwd() / ".env", DEFAULT_ENV_FILE):
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return None


@dataclass(frozen=True)
class Config:
    """Resolved configuration. Never contains raw secrets in repr (see __repr__)."""

    client_id: Optional[str]
    client_secret: Optional[str]
    redirect_uri: str
    scopes: tuple[str, ...]
    token_file: Path
    api_base: str
    default_account_id: Optional[str]
    default_workspace_id: Optional[str]

    @property
    def loopback_port(self) -> int:
        """Port extracted from the redirect URI, used by the OAuth wizard."""
        parts = urlsplit(self.redirect_uri)
        if parts.port:
            return parts.port
        return 443 if parts.scheme == "https" else 80

    def require_oauth_app(self) -> None:
        """Raise ConfigError if no OAuth Web App credential is configured."""
        if not self.client_id:
            raise ConfigError(
                "Missing FRAMEIO_CLIENT_ID.",
                remediation="Run: frameio-agent auth login",
            )
        if not self.client_secret:
            raise ConfigError(
                "Missing FRAMEIO_CLIENT_SECRET.",
                remediation="Run: frameio-agent auth login",
            )

    def __repr__(self) -> str:  # pragma: no cover — defensive
        has_id = "set" if self.client_id else "missing"
        has_secret = "set" if self.client_secret else "missing"
        return (
            f"Config(client_id=<{has_id}>, client_secret=<{has_secret}>, "
            f"redirect_uri={self.redirect_uri!r}, token_file={str(self.token_file)!r}, "
            f"api_base={self.api_base!r})"
        )


def _split_scopes(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.replace(" ", ",").split(",")]
    return tuple(p for p in parts if p)


def _resolve_token_path(raw: Optional[str], env_dir: Optional[Path]) -> Path:
    """Resolve the token-cache path.

    Relative paths anchor to the directory of the loaded ``.env`` (keeps
    dev checkouts self-contained). With no ``.env``, secrets default to the
    user's home — never to the installed package directory, which under a
    non-editable install is site-packages.
    """
    base = env_dir if env_dir is not None else Path.home()
    p = Path(raw).expanduser() if raw else Path(DEFAULT_TOKEN_FILE)
    if not p.is_absolute():
        p = base / p
    return p


def load_config(env_file: Optional[Path] = None) -> Config:
    """Load configuration from environment + .env file.

    An explicit ``env_file`` argument is honored verbatim (no discovery),
    which keeps tests hermetic. Otherwise :func:`find_env_file` searches
    cwd, then the dev checkout root.

    Does NOT validate that OAuth credentials are present; commands that need
    them call :meth:`Config.require_oauth_app` themselves so e.g. ``auth login``
    can run with a missing client_id (and print the walkthrough).
    """
    if env_file is not None:
        path: Optional[Path] = env_file if env_file.exists() else None
    else:
        path = find_env_file()
    if path is not None:
        load_dotenv(path, override=False)
    env_dir = path.parent if path is not None else None

    return Config(
        client_id=_clean(os.environ.get("FRAMEIO_CLIENT_ID")),
        client_secret=_clean(os.environ.get("FRAMEIO_CLIENT_SECRET")),
        redirect_uri=os.environ.get("FRAMEIO_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
        scopes=_split_scopes(os.environ.get("FRAMEIO_SCOPES") or DEFAULT_SCOPES),
        token_file=_resolve_token_path(os.environ.get("FRAMEIO_TOKEN_FILE"), env_dir),
        api_base=(os.environ.get("FRAMEIO_API_BASE") or DEFAULT_API_BASE).rstrip("/"),
        default_account_id=_clean(os.environ.get("FRAMEIO_ACCOUNT_ID")),
        default_workspace_id=_clean(os.environ.get("FRAMEIO_WORKSPACE_ID")),
    )


def _clean(value: Optional[str]) -> Optional[str]:
    """Drop placeholders and blanks. `your_client_id_here` etc. count as unset."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if v.lower().startswith(("your_", "<", "changeme", "placeholder")):
        return None
    return v


def write_env_values(updates: dict[str, str], env_file: Optional[Path] = None) -> Path:
    """Update or append KEY=VALUE lines in .env, preserving comments and order.

    Used by the ``auth login`` wizard when the user pastes their client_id /
    client_secret. Lines are NOT logged or echoed elsewhere. Targets the
    discovered .env, or creates one in the current working directory —
    never inside the installed package (site-packages).
    """
    path = env_file or find_env_file() or (Path.cwd() / ".env")
    if not path.exists():
        example = REPO_ROOT / ".env.example"
        path.write_text(example.read_text(encoding="utf-8") if example.exists() else "", encoding="utf-8")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, _, _rest = line.partition("=")
        key_clean = key.strip()
        if key_clean in updates:
            out.append(f"{key_clean}={updates[key_clean]}")
            seen.add(key_clean)
        else:
            out.append(line)

    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")

    path.write_text("\n".join(out) + ("\n" if not text.endswith("\n") and out else ""), encoding="utf-8")
    return path
