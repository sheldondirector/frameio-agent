"""Adobe IMS OAuth wizard with PKCE + local loopback capture.

This module implements the make-or-break flow described in the PRD's section 10:

  1. If no OAuth Web App credential is configured, print a numbered Adobe
     Developer Console walkthrough and (optionally) accept the values
     interactively, writing them to ``.env``.
  2. Generate a PKCE code verifier + S256 challenge.
  3. Open the user's browser to the Adobe IMS authorize URL with the
     configured scopes, redirect URI, state, and challenge.
  4. Run a single-shot HTTP server on the loopback that captures ``code``
     and ``state`` from the callback.
  5. POST to the IMS token endpoint to exchange ``code`` for tokens.
  6. Save the token cache to ``FRAMEIO_TOKEN_FILE`` with private perms where
     the OS supports it. Print ONLY the authenticated email — never tokens.

The same module also exposes :func:`load_tokens` and :func:`get_access_token`
for the REST client: refresh on demand, raise :class:`AuthError` when the
refresh token is gone so the CLI can prompt for ``auth login`` again.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

from .config import Config, load_config, write_env_values
from .errors import AuthError
from .redact import PLACEHOLDER


IMS_AUTHORIZE_URL = "https://ims-na1.adobelogin.com/ims/authorize/v2"
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_USERINFO_URL = "https://ims-na1.adobelogin.com/ims/userinfo/v2"

CALLBACK_TIMEOUT_SECONDS = 300
TOKEN_REFRESH_LEEWAY_SECONDS = 60


# ──────────────────────────────────────────────────────────────────────────────
# Token cache (on-disk JSON)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TokenCache:
    """On-disk token cache. Refresh fields are mandatory; the rest are best-effort."""

    access_token: str
    refresh_token: Optional[str]
    expires_at: float  # absolute unix timestamp
    token_type: str = "bearer"
    scope: str = ""
    email: Optional[str] = None
    user_id: Optional[str] = None
    obtained_at: float = 0.0

    def is_expired(self, leeway: float = TOKEN_REFRESH_LEEWAY_SECONDS) -> bool:
        return time.time() + leeway >= self.expires_at

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_token_response(
        cls,
        body: dict[str, Any],
        *,
        prior: Optional["TokenCache"] = None,
        email: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> "TokenCache":
        now = time.time()
        expires_in = float(body.get("expires_in") or 0)
        # IMS sometimes returns expires_in in milliseconds; normalize.
        if expires_in > 10_000_000:  # >115 days = definitely ms
            expires_in /= 1000.0
        return cls(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token") or (prior.refresh_token if prior else None),
            expires_at=now + (expires_in or 3600),
            token_type=body.get("token_type", "bearer"),
            scope=body.get("scope", "") or (prior.scope if prior else ""),
            email=email or (prior.email if prior else None),
            user_id=user_id or (prior.user_id if prior else None),
            obtained_at=now,
        )


def _save_token_cache(cache: TokenCache, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cache.to_json(), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # POSIX only; no-op on Windows
    except (OSError, NotImplementedError):
        pass


def load_tokens(cfg: Config) -> Optional[TokenCache]:
    """Read the on-disk token cache. Returns None if absent or unreadable."""
    if not cfg.token_file.exists():
        return None
    try:
        raw = json.loads(cfg.token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return TokenCache(**raw)
    except TypeError:
        return None


def _refresh_tokens(cfg: Config, cache: TokenCache) -> TokenCache:
    if not cache.refresh_token:
        raise AuthError(
            "No refresh token available.",
            remediation="Run: frameio-agent auth login",
        )
    cfg.require_oauth_app()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": cache.refresh_token,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    }
    try:
        resp = httpx.post(IMS_TOKEN_URL, data=data, timeout=30.0)
    except httpx.HTTPError as e:
        raise AuthError(
            f"Network error refreshing token: {type(e).__name__}",
            remediation="Check your connection, then re-run the command.",
        ) from None
    if resp.status_code != 200:
        # Don't leak any body that might echo the refresh token. IMS errors are JSON.
        try:
            err = resp.json()
            error_code = err.get("error", "unknown")
        except ValueError:
            error_code = f"HTTP {resp.status_code}"
        raise AuthError(
            f"Your Frame.io session expired (IMS error: {error_code}).",
            remediation="Run: frameio-agent auth login",
        )
    refreshed = TokenCache.from_token_response(resp.json(), prior=cache)
    _save_token_cache(refreshed, cfg.token_file)
    return refreshed


def get_access_token(cfg: Config) -> tuple[str, TokenCache]:
    """Return a usable access token, refreshing on the fly if needed."""
    cache = load_tokens(cfg)
    if cache is None:
        raise AuthError(
            "Frame.io is not authenticated.",
            remediation="Run: frameio-agent auth login",
        )
    if cache.is_expired():
        cache = _refresh_tokens(cfg, cache)
    return cache.access_token, cache


# ──────────────────────────────────────────────────────────────────────────────
# PKCE
# ──────────────────────────────────────────────────────────────────────────────

def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ──────────────────────────────────────────────────────────────────────────────
# Loopback callback server
# ──────────────────────────────────────────────────────────────────────────────

class _CallbackResult:
    """Thread-safe container for the one callback we expect."""

    def __init__(self) -> None:
        self.code: Optional[str] = None
        self.state: Optional[str] = None
        self.error: Optional[str] = None
        self.error_description: Optional[str] = None
        self.event = threading.Event()


def _build_handler(result: _CallbackResult, expected_path: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        # Suppress default request logging — could echo `code` to stderr otherwise.
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            if parts.path != expected_path:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not the callback endpoint.\n")
                return

            qs = parse_qs(parts.query, keep_blank_values=True)
            result.code = (qs.get("code") or [None])[0]
            result.state = (qs.get("state") or [None])[0]
            result.error = (qs.get("error") or [None])[0]
            result.error_description = (qs.get("error_description") or [None])[0]

            if result.error:
                self._respond_html(
                    title="Authentication failed",
                    body=f"<p>{result.error}</p><p>{result.error_description or ''}</p>",
                )
            else:
                self._respond_html(
                    title="Authentication complete",
                    body="<p>You can close this tab and return to your terminal.</p>",
                )
            result.event.set()

        def _respond_html(self, title: str, body: str) -> None:
            page = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title>"
                "<style>body{font-family:system-ui,sans-serif;max-width:520px;margin:64px auto;padding:0 24px;color:#222}"
                "h1{font-size:20px;margin:0 0 12px}p{margin:0 0 8px;color:#555}</style></head>"
                f"<body><h1>{title}</h1>{body}</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    return Handler


def _wait_for_callback(port: int, expected_path: str, timeout: float) -> _CallbackResult:
    result = _CallbackResult()
    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _build_handler(result, expected_path))
    except OSError as e:
        raise AuthError(
            f"Could not start loopback server on port {port}: {e}.",
            remediation=(
                "Another process may be using the port. "
                "Set FRAMEIO_REDIRECT_URI to a different port in .env, then re-run."
            ),
        ) from None

    def serve() -> None:
        # Handle requests until we see one that sets the event, then a few more
        # to flush, then quit. `serve_forever` would block; instead we poll.
        while not result.event.is_set():
            server.handle_request()
        server.server_close()

    t = threading.Thread(target=serve, name="frameio-oauth-loopback", daemon=True)
    t.start()

    ok = result.event.wait(timeout=timeout)
    if not ok:
        try:
            # Trigger one final handle_request so the worker thread exits.
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as s:
                s.sendall(b"GET / HTTP/1.0\r\n\r\n")
        except OSError:
            pass
        raise AuthError(
            f"Timed out waiting for OAuth callback after {int(timeout)}s.",
            remediation="Re-run: frameio-agent auth login",
        )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Walkthrough printed when credentials are missing
# ──────────────────────────────────────────────────────────────────────────────

WALKTHROUGH_TEMPLATE = """\
Frame.io uses Adobe IMS OAuth. You need an Adobe Developer Console OAuth Web App
credential. Follow these steps (one-time setup, ~5 minutes):

  1. Open the Adobe Developer Console:
       https://developer.adobe.com/console/projects

  2. Click "Create new project" (or open an existing project you want to use).

  3. In the project, click "+ Add to Project" -> "API".

  4. Search for "Frame.io" -> select "Frame.io API" -> click "Next".

  5. Choose credential type: "OAuth Web App".
       NOT "OAuth Server-to-Server" and NOT "OAuth Single Page App".

  6. Configure the redirect URI:
       Default Redirect URI:  {redirect_uri}
       Redirect URI Pattern:  {redirect_uri}

  7. Select all available Frame.io scopes (read-only is enforced in this CLI,
     not in OAuth scopes).

  8. Save. In the left sidebar under your workspace, click "OAuth Web App"
     to reveal:
         - Client ID
         - Client Secret  (click "Retrieve client secret")

When you have those two values, paste them at the prompts below. They will be
written to your local .env file (which is gitignored). No values are echoed
back, logged, or sent anywhere except Adobe's token endpoint.
"""


def _interactive_credential_capture(cfg: Config) -> Config:
    """Prompt for client_id + client_secret if missing, write to .env, reload."""
    print()
    print(WALKTHROUGH_TEMPLATE.format(redirect_uri=cfg.redirect_uri))
    if not sys.stdin.isatty():
        raise AuthError(
            "Missing FRAMEIO_CLIENT_ID / FRAMEIO_CLIENT_SECRET and stdin is not a TTY.",
            remediation="Edit .env to set both values, then re-run: frameio-agent auth login",
        )

    updates: dict[str, str] = {}
    if not cfg.client_id:
        cid = input("Paste your Client ID: ").strip()
        if not cid:
            raise AuthError("Client ID is required.", remediation="Re-run: frameio-agent auth login")
        updates["FRAMEIO_CLIENT_ID"] = cid
    if not cfg.client_secret:
        # getpass hides the secret from the terminal as the user types.
        csec = getpass.getpass("Paste your Client Secret (hidden): ").strip()
        if not csec:
            raise AuthError("Client Secret is required.", remediation="Re-run: frameio-agent auth login")
        updates["FRAMEIO_CLIENT_SECRET"] = csec

    write_env_values(updates)
    print(f"Wrote credentials to .env. (Values not echoed; '.env' is gitignored.)")
    return load_config()


# ──────────────────────────────────────────────────────────────────────────────
# Public entry points: cmd_login / cmd_status
# ──────────────────────────────────────────────────────────────────────────────

def _is_loopback_capturable(redirect_uri: str) -> bool:
    """True if our HTTP loopback server can plausibly catch the callback.

    Adobe Web App credentials require HTTPS redirects and reject plain
    http://localhost:<port>/callback. When the redirect URI is the
    HTTPS-default ``https://localhost`` (no port, no path) we cannot bind
    or terminate TLS without admin + a cert, so we force manual paste.
    """
    parts = urlsplit(redirect_uri)
    if parts.scheme != "http":
        return False
    if parts.hostname not in ("localhost", "127.0.0.1"):
        return False
    return bool(parts.port)


def _manual_paste_flow(authorize_url: str, expected_state: str) -> tuple[Optional[str], Optional[str]]:
    """Print the authorize URL, accept a pasted redirect URL or bare code.

    Returns (code, error_message). On state mismatch or missing code,
    returns (None, error_message).
    """
    print()
    print("Manual paste mode — your browser will land on a 'site can't be reached' page.")
    print("That is expected; the URL bar contains the OAuth code we need.")
    print()
    print("1. Open this URL in your browser and sign in to Adobe:")
    print(f"   {authorize_url}")
    print()
    print("2. After signing in, copy the ENTIRE redirect URL from the browser's")
    print("   address bar (it will start with https://localhost/?code=...) and paste below.")
    print("   You can also paste just the code value if you prefer.")
    print()
    try:
        pasted = input("Paste redirect URL or code: ").strip()
    except EOFError:
        return None, "No input received."

    if not pasted:
        return None, "No input received."

    if pasted.startswith(("http://", "https://")):
        qs = parse_qs(urlsplit(pasted).query, keep_blank_values=True)
        code = (qs.get("code") or [None])[0]
        state = (qs.get("state") or [None])[0]
        error = (qs.get("error") or [None])[0]
        if error:
            return None, f"Adobe returned error: {error}"
        if state and state != expected_state:
            return None, "OAuth state mismatch — possible CSRF. Aborting."
        if not code:
            return None, "Pasted URL did not contain a 'code' parameter."
        return code, None
    return pasted, None  # bare code; state not verifiable


def cmd_login(*, port: Optional[int] = None, no_browser: bool = False, manual: bool = False) -> int:
    cfg = load_config()

    if not cfg.client_id or not cfg.client_secret:
        try:
            cfg = _interactive_credential_capture(cfg)
        except AuthError as e:
            print(f"Error: {e.render()}", file=sys.stderr)
            return 2

    # Honor --port override; otherwise use the port encoded in the redirect URI.
    actual_port = port or cfg.loopback_port
    redirect_uri = cfg.redirect_uri
    if port and port != cfg.loopback_port:
        parts = urlsplit(cfg.redirect_uri)
        redirect_uri = parts._replace(netloc=f"127.0.0.1:{port}").geturl()
    expected_path = urlsplit(redirect_uri).path or "/callback"

    # Auto-switch to manual mode when the redirect URI cannot host an
    # http loopback (e.g. Adobe's required https://localhost).
    if not manual and not _is_loopback_capturable(redirect_uri):
        manual = True
        print()
        print(
            "Note: FRAMEIO_REDIRECT_URI is "
            f"{redirect_uri!r} — switching to manual paste mode "
            "since we can't host an HTTP loopback at that address."
        )

    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    authorize_url = IMS_AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": cfg.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(cfg.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )

    if manual:
        if not no_browser:
            try:
                webbrowser.open(authorize_url)
            except Exception:
                pass
        code, err = _manual_paste_flow(authorize_url, expected_state=state)
        if err or not code:
            print(f"Error: {err or 'no code received'}", file=sys.stderr)
            return 2
    else:
        print()
        print(f"Starting local callback server on http://127.0.0.1:{actual_port}{expected_path}")
        print("Opening browser to Adobe to sign in...")
        print("(If the browser does not open, copy this URL and paste it into a browser:)")
        print(f"  {authorize_url}")
        print()

        if not no_browser:
            try:
                webbrowser.open(authorize_url)
            except Exception:
                pass

        try:
            result = _wait_for_callback(actual_port, expected_path, CALLBACK_TIMEOUT_SECONDS)
        except AuthError as e:
            print(f"Error: {e.render()}", file=sys.stderr)
            return 2

        if result.error:
            print(
                f"Error from Adobe: {result.error} — {result.error_description or ''}",
                file=sys.stderr,
            )
            return 2
        if result.state != state:
            print("Error: OAuth state mismatch — possible CSRF. Aborting.", file=sys.stderr)
            return 2
        if not result.code:
            print("Error: no authorization code received.", file=sys.stderr)
            return 2
        code = result.code

    # Exchange code for tokens.
    try:
        resp = httpx.post(
            IMS_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        print(f"Error: network failure during token exchange: {type(e).__name__}", file=sys.stderr)
        return 2

    if resp.status_code != 200:
        try:
            err_code = resp.json().get("error", f"HTTP {resp.status_code}")
        except ValueError:
            err_code = f"HTTP {resp.status_code}"
        print(f"Error: token exchange failed ({err_code}).", file=sys.stderr)
        print("  > Run: frameio-agent auth login", file=sys.stderr)
        return 2

    body = resp.json()
    # Fetch userinfo so we can show "Connected as <email>".
    email, user_id = _fetch_userinfo(body.get("access_token"))
    cache = TokenCache.from_token_response(body, email=email, user_id=user_id)
    _save_token_cache(cache, cfg.token_file)

    print()
    print(f"Authenticated as {email or '(email unavailable)'}.")
    print(f"Token cache saved: {cfg.token_file}")
    return 0


def _fetch_userinfo(access_token: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not access_token:
        return None, None
    try:
        resp = httpx.get(
            IMS_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return None, None
        body = resp.json()
        return body.get("email"), body.get("sub")
    except (httpx.HTTPError, ValueError):
        return None, None


def cmd_status(*, as_json: bool, emit: Callable[[Any, bool], None]) -> int:
    cfg = load_config()
    cache = load_tokens(cfg)
    if cache is None:
        payload = {
            "ok": False,
            "authenticated": False,
            "token_file_exists": False,
            "has_refresh_token": False,
            "remediation": "Run: frameio-agent auth login",
        }
        if as_json:
            emit(payload, True)
        else:
            print("Not authenticated.")
            print("  > Run: frameio-agent auth login")
        return 1

    expires_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cache.expires_at))
    payload = {
        "ok": True,
        "authenticated": True,
        "email": cache.email,
        "user_id": cache.user_id,
        "token_file_exists": True,
        "has_refresh_token": bool(cache.refresh_token),
        "expires_at": expires_at_iso,
        "expired": cache.is_expired(leeway=0),
        # Never include token values.
        "access_token": PLACEHOLDER,
        "refresh_token": PLACEHOLDER if cache.refresh_token else None,
    }
    if as_json:
        emit(payload, True)
    else:
        print(f"Authenticated as {cache.email or '(email unavailable)'}")
        print(f"Token cache: {cfg.token_file}")
        print(f"Expires at:  {expires_at_iso} ({'expired' if cache.is_expired(0) else 'valid'})")
        print(f"Refresh token: {'present' if cache.refresh_token else 'missing'}")
    return 0
