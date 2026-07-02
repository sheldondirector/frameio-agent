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
        # IMS sometimes returns expires_in in milliseconds; normalize. Real
        # access tokens live minutes-to-hours, so anything over 7 days is
        # milliseconds (e.g. a 1h token arriving as 3_600_000).
        if expires_in > 604_800:  # 7 days in seconds
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
    """Write the token cache atomically with owner-only permissions.

    The file is created 0600 from the first byte (no world-readable window)
    and swapped into place with os.replace, so a concurrent reader never
    sees a truncated JSON. Windows ignores the POSIX mode bits, as before.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cache.to_json())
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.replace(tmp, path)


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


# Serializes token refresh across ThreadPoolExecutor workers (frames pull,
# contact-sheet) and concurrent MCP tool calls, so only one refresh_token
# grant hits IMS and only one writer touches tokens.json at a time.
_refresh_lock = threading.Lock()


def get_access_token(cfg: Config, *, force_refresh: bool = False) -> tuple[str, TokenCache]:
    """Return a usable access token, refreshing on the fly if needed.

    ``force_refresh=True`` refreshes even when the local expiry looks fine —
    used by the HTTP client when Frame.io answers 401 for a token we thought
    was valid (server-side revocation, password change, clock skew).
    """
    cache = load_tokens(cfg)
    if cache is None:
        raise AuthError(
            "Frame.io is not authenticated.",
            remediation="Run: frameio-agent auth login",
        )
    if force_refresh or cache.is_expired():
        before = cache.obtained_at
        with _refresh_lock:
            # Another thread may have refreshed while we waited on the lock.
            latest = load_tokens(cfg) or cache
            if latest.obtained_at > before:
                cache = latest  # fresh enough — reuse it
            elif force_refresh or latest.is_expired():
                cache = _refresh_tokens(cfg, latest)
            else:
                cache = latest
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
One-time Adobe setup (~3 minutes). You need an OAuth Web App credential from
the Adobe Developer Console:

  1. Open https://developer.adobe.com/console/projects and create a project
     (or open one you already use).

  2. Add the Frame.io API: "+ Add to Project" -> "API" -> search "Frame.io"
     -> select "Frame.io API" -> Next.

  3. Pick credential type "OAuth Web App". Register the redirect URI as:
         {redirect_uri}
     (Adobe requires an HTTPS redirect; the login flow captures the code
      from your clipboard, so no local server is needed.)

  4. Open the new "OAuth Web App" card in the sidebar and copy the
     Client ID + Client Secret. Paste them at the prompts below.

The values go in a local .env file (gitignored). Nothing is logged or
sent anywhere except Adobe's token endpoint.
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
# Agent-friendly two-step flow: auth start / auth complete
#
# `auth login` is built for a human at a TTY (interactive prompts, clipboard
# watch). When a coding agent drives the CLI through a shell tool, stdin is
# not a TTY and long waits fight tool timeouts. The split flow is fully
# non-interactive:
#
#   1. `auth start --json`   -> emits the authorize URL; persists the PKCE
#                               verifier + state to a pending file (0600).
#   2. Human signs in, copies the https://localhost/?code=... redirect URL,
#      and hands it to the agent (pasting it in chat is fine: the code is
#      single-use, PKCE-bound, and useless without the client secret).
#   3. `auth complete "<url-or-code>"` -> exchanges and saves the tokens.
# ──────────────────────────────────────────────────────────────────────────────

PENDING_AUTH_TTL_SECONDS = 900  # 15 minutes


def _pending_auth_path(cfg: Config) -> Path:
    return cfg.token_file.parent / "pending_auth.json"


def _save_pending_auth(cfg: Config, data: dict[str, Any]) -> None:
    path = _pending_auth_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _load_pending_auth(cfg: Config) -> Optional[dict[str, Any]]:
    path = _pending_auth_path(cfg)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(data.get("created_at", 0)) > PENDING_AUTH_TTL_SECONDS:
        return None
    return data


def _clear_pending_auth(cfg: Config) -> None:
    try:
        _pending_auth_path(cfg).unlink()
    except OSError:
        pass


def _exchange_and_save(
    cfg: Config, *, code: str, code_verifier: str, redirect_uri: str,
) -> tuple[int, Optional[str]]:
    """Exchange an auth code for tokens and persist them.

    Returns (exit_code, email). Shared by `auth login` and `auth complete`.
    """
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
        return 2, None

    if resp.status_code != 200:
        try:
            err_code = resp.json().get("error", f"HTTP {resp.status_code}")
        except ValueError:
            err_code = f"HTTP {resp.status_code}"
        print(f"Error: token exchange failed ({err_code}).", file=sys.stderr)
        print("  > Start over: frameio-agent auth start", file=sys.stderr)
        return 2, None

    body = resp.json()
    email, user_id = _fetch_userinfo(body.get("access_token"))
    cache = TokenCache.from_token_response(body, email=email, user_id=user_id)
    _save_token_cache(cache, cfg.token_file)
    return 0, email


def cmd_start(*, as_json: bool, emit: Callable[[Any, bool], None]) -> int:
    """Begin the non-interactive OAuth flow: emit the authorize URL."""
    cfg = load_config()
    try:
        cfg.require_oauth_app()
    except Exception as e:  # ConfigError
        remediation = getattr(e, "remediation", "")
        print(f"Error: {e}", file=sys.stderr)
        print(
            "  > Set FRAMEIO_CLIENT_ID and FRAMEIO_CLIENT_SECRET in .env first "
            "(create an OAuth Web App in the Adobe Developer Console with "
            f"redirect URI {cfg.redirect_uri}).",
            file=sys.stderr,
        )
        return 2

    code_verifier, code_challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    authorize_url = IMS_AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "response_type": "code",
            "scope": " ".join(cfg.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    _save_pending_auth(cfg, {
        "state": state,
        "code_verifier": code_verifier,
        "redirect_uri": cfg.redirect_uri,
        "created_at": time.time(),
    })

    if as_json:
        emit({
            "authorize_url": authorize_url,
            "expires_in_seconds": PENDING_AUTH_TTL_SECONDS,
            "next": 'Have the user sign in at authorize_url, then run: frameio-agent auth complete "<redirect-url>"',
        }, True)
    else:
        print("Open this URL in a browser and sign in to Adobe:")
        print(f"  {authorize_url}")
        print()
        print('The browser will land on a "site can\'t be reached" page - that is expected.')
        print("Copy the full URL from the address bar, then run:")
        print('  frameio-agent auth complete "<that url>"')
        print(f"(This link expires in {PENDING_AUTH_TTL_SECONDS // 60} minutes.)")
    return 0


def cmd_complete(*, redirect_or_code: str, as_json: bool, emit: Callable[[Any, bool], None]) -> int:
    """Finish the non-interactive OAuth flow started by `auth start`."""
    cfg = load_config()
    pending = _load_pending_auth(cfg)
    if pending is None:
        print("Error: no pending login (or it expired).", file=sys.stderr)
        print("  > Run: frameio-agent auth start", file=sys.stderr)
        return 2

    code, err = _parse_callback(redirect_or_code, expected_state=pending["state"])
    if err or not code:
        print(f"Error: {err or 'no code found in input'}", file=sys.stderr)
        return 2

    rc, email = _exchange_and_save(
        cfg,
        code=code,
        code_verifier=pending["code_verifier"],
        redirect_uri=pending["redirect_uri"],
    )
    if rc != 0:
        return rc
    _clear_pending_auth(cfg)

    if as_json:
        emit({"ok": True, "authenticated": True, "email": email}, True)
    else:
        print(f"  Connected as {email or '(email unavailable)'}.")
        print("  Next: frameio-agent verify")
    return 0


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


def _parse_callback(value: str, expected_state: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a pasted redirect URL or bare code. Returns (code, error_message)."""
    value = (value or "").strip()
    if not value:
        return None, "No input received."
    if value.startswith(("http://", "https://")):
        qs = parse_qs(urlsplit(value).query, keep_blank_values=True)
        code = (qs.get("code") or [None])[0]
        state = (qs.get("state") or [None])[0]
        error = (qs.get("error") or [None])[0]
        if error:
            return None, f"Adobe returned error: {error}"
        if state and state != expected_state:
            return None, "OAuth state mismatch - possible CSRF. Aborting."
        if not code:
            return None, "Pasted URL did not contain a 'code' parameter."
        return code, None
    return value, None  # bare code; state not verifiable


def _watch_clipboard_for_callback(timeout_seconds: float = 180.0) -> Optional[str]:
    """Poll the system clipboard for a new URL matching our callback shape.

    Returns the URL the moment one appears, or None on timeout / no clipboard
    access. Uses tkinter (stdlib) so it works on Windows / macOS / Linux with
    a display. Headless systems silently fall through to manual paste.
    """
    try:
        import tkinter as tk
    except ImportError:
        return None
    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    try:
        try:
            initial = root.clipboard_get()
        except tk.TclError:
            initial = ""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                root.update()  # keep tk event loop responsive
                current = root.clipboard_get()
            except tk.TclError:
                current = ""
            if (
                current
                and current != initial
                and current.startswith(("http://localhost", "https://localhost"))
                and "code=" in current
            ):
                return current.strip()
            time.sleep(0.5)
        return None
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _manual_paste_flow(authorize_url: str, expected_state: str) -> tuple[Optional[str], Optional[str]]:
    """Capture the OAuth code via clipboard watch + manual paste fallback.

    Adobe Web App credentials require an HTTPS redirect, so we can't auto-
    catch the callback over a local HTTP loopback. Instead, we watch the
    user's clipboard: the moment they copy the redirect URL from their
    browser's address bar (a natural Ctrl-L Ctrl-C after the page errors
    out), we detect it and continue. Ctrl-C falls back to a paste prompt.
    """
    print()
    print("In your browser:")
    print("  1. Sign in to Adobe and click Allow.")
    print("  2. The page will show \"site can't be reached\" - that is correct.")
    print("  3. Copy the URL from the address bar (Ctrl+L, Ctrl+C).")
    print()
    print(f"  If the browser didn't open, visit:\n    {authorize_url}")
    print()
    print("Watching clipboard... (Ctrl+C to paste manually instead)")

    try:
        url = _watch_clipboard_for_callback(timeout_seconds=180.0)
    except KeyboardInterrupt:
        url = None
        print()  # newline after ^C
    if url:
        print("  Got it from clipboard.")
        return _parse_callback(url, expected_state)

    # Clipboard timeout or interrupted — fall back to typed paste.
    print()
    try:
        pasted = input("Paste the URL (or just the code value): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None, "No input received."
    return _parse_callback(pasted, expected_state)


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
        # Preserve the registered hostname — Adobe matches the redirect URI
        # exactly, so rewriting localhost to 127.0.0.1 would break the match.
        redirect_uri = parts._replace(netloc=f"{parts.hostname}:{port}").geturl()
    expected_path = urlsplit(redirect_uri).path or "/callback"

    # Auto-switch to manual mode when the redirect URI cannot host an
    # http loopback (Adobe Web App credentials require HTTPS).
    if not manual and not _is_loopback_capturable(redirect_uri):
        manual = True

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
        print()
        print("Opening Adobe to sign in...")
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
                f"Error from Adobe: {result.error} - {result.error_description or ''}",
                file=sys.stderr,
            )
            return 2
        if result.state != state:
            print("Error: OAuth state mismatch - possible CSRF. Aborting.", file=sys.stderr)
            return 2
        if not result.code:
            print("Error: no authorization code received.", file=sys.stderr)
            return 2
        code = result.code

    # Exchange code for tokens (shared with `auth complete`).
    rc, email = _exchange_and_save(
        cfg, code=code, code_verifier=code_verifier, redirect_uri=redirect_uri,
    )
    if rc != 0:
        return rc

    print()
    print(f"  Connected as {email or '(email unavailable)'}.")
    print(f"  Next: frameio-agent verify")
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
