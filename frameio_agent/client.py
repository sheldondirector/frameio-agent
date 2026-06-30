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
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return f"{self.cfg.api_base}{path_or_url}"

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
        page_param: str = "page",
        page_size_param: str = "page_size",
        page_size: int = 50,
        max_pages: int = 200,
    ) -> Iterator[dict[str, Any]]:
        """Yield items from a paginated list endpoint.

        Frame.io V4 returns a top-level ``data`` array. Pagination is
        typically ``page`` + ``page_size`` query params; if a future schema
        change moves to cursors or links, this is the single place to fix it.
        """
        page = 1
        seen = 0
        while page <= max_pages:
            q = dict(params or {})
            q[page_param] = page
            q[page_size_param] = page_size
            payload = self.get(path, params=q)
            items = payload.get(items_key) or payload.get("results") or []
            if not items:
                return
            for item in items:
                yield item
                seen += 1
            # Heuristic stop: if we got fewer than page_size items, we're done.
            if len(items) < page_size:
                return
            page += 1
