"""Thin authenticated HTTP client for the Frame.io V4 REST API.

Responsibilities:
  * Inject the Adobe IMS bearer token and the x-api-key header.
  * Refresh tokens on 401.
  * Apply a small retry on 429 / 5xx with backoff.
  * Walk paginated list endpoints transparently via :meth:`paginate`.
  * Redact secrets from any error message that escapes to the user.

Endpoint paths and query parameter names live in :mod:`api`. This module is
deliberately dumb about Frame.io's URL shapes so that future API revisions
need only edit one file.
"""
from __future__ import annotations

import time
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .auth import get_access_token
from .config import Config
from .errors import ApiError
from .redact import redact_url, safe_format_exception


DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
BACKOFF_BASE = 0.5  # seconds


class FrameioClient:
    """Authenticated REST client over httpx."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._http = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self._cached_token: Optional[str] = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "FrameioClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ──────────────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        token = self._cached_token
        if token is None:
            token, _ = get_access_token(self.cfg)
            self._cached_token = token
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": self.cfg.client_id or "",
            "Accept": "application/json",
            "User-Agent": "frameio-agent-starter/0.1",
        }

    def _absolute(self, path_or_url: str) -> str:
        """Resolve a path or URL against the API base.

        Handles three cases:
          * full URL  -> returned as-is
          * V4-relative path (e.g. ``/me``)  -> append to api_base
          * host-absolute path that already includes the api_base path
            (e.g. ``/v4/accounts/...?after=...`` from a ``links.next`` cursor)
            -> resolve against the host root to avoid doubling ``/v4/v4/``
        """
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        base = urlsplit(self.cfg.api_base)
        base_path = base.path or ""
        if base_path and (path_or_url == base_path or path_or_url.startswith(base_path + "/")):
            return urlunsplit((base.scheme, base.netloc, path_or_url, "", ""))
        return f"{self.cfg.api_base.rstrip('/')}/{path_or_url.lstrip('/')}"

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        accept_status: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        """Issue one request with retry + token-refresh handling. Returns parsed JSON."""
        url = self._absolute(path_or_url)
        last_error: Optional[str] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._http.request(
                    method, url, params=params, json=json_body, headers=self._headers()
                )
            except httpx.HTTPError as e:
                last_error = f"{type(e).__name__}: {safe_format_exception(e)}"
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue
                raise ApiError(
                    f"Network error calling Frame.io: {last_error}",
                    remediation="Check your connection and try again.",
                ) from None

            if resp.status_code == 401:
                # Token may be stale; force a refresh and retry once.
                self._cached_token = None
                if attempt < MAX_RETRIES:
                    continue
                raise ApiError(
                    "Frame.io rejected the access token (HTTP 401).",
                    remediation="Run: frameio-agent auth login",
                )

            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                if attempt < MAX_RETRIES:
                    retry_after = float(resp.headers.get("Retry-After", "0") or 0)
                    time.sleep(max(retry_after, BACKOFF_BASE * (2 ** attempt)))
                    continue

            if resp.status_code in accept_status:
                if resp.status_code == 204 or not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError:
                    raise ApiError(
                        f"Unexpected non-JSON response from {redact_url(url)} (HTTP {resp.status_code}).",
                        remediation="Re-run with the latest version, or report a bug.",
                    )

            # Non-recoverable error path.
            try:
                body = resp.json()
                detail = body.get("message") or body.get("error") or body.get("detail") or ""
            except ValueError:
                detail = (resp.text or "").strip()[:300]
            raise ApiError(
                f"Frame.io API error {resp.status_code} on {method} {redact_url(url)}"
                + (f": {detail}" if detail else ""),
                remediation=(
                    "Run `frameio-agent verify` to confirm auth. "
                    "If the path looks wrong, the V4 endpoint may have changed."
                ),
            )

        # Should never reach here.
        raise ApiError(
            "Exhausted retries calling Frame.io.",
            remediation="Try again later.",
        )

    def get(self, path_or_url: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", path_or_url, **kwargs)

    def paginate(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        items_key: str = "data",
        max_pages: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """Yield items from a paginated V4 list endpoint.

        Frame.io V4 rejects ``page``/``page_size`` query params (HTTP 422).
        Two pagination shapes have been observed against live V4:

          * ``{"data":[...], "meta": {"next_cursor": "..."}}``
            (followed with ``?cursor=...``)
          * ``{"data":[...], "links": {"next": "https://...absolute-url..."}}``
            (followed with the absolute next URL verbatim)

        We start with no params, then follow whichever cursor shape is
        present until exhausted.
        """
        url: Optional[str] = path
        cursor: Optional[str] = None
        for _ in range(max_pages):
            q = dict(params or {})
            if cursor:
                q["cursor"] = cursor
            payload = self.get(url, params=q) if url is not None else {}
            items = payload.get(items_key) or payload.get("results") or []
            for item in items:
                yield item
            meta = payload.get("meta") or {}
            links = payload.get("links") or {}
            next_link = links.get("next")
            next_cursor = meta.get("next_cursor") or meta.get("next")
            if next_link:
                url = next_link
                cursor = None
                params = None  # next_link already encodes its own query string
            elif next_cursor:
                cursor = next_cursor
                # url stays the same; cursor is appended to params on next loop
            else:
                return
