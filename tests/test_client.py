"""Tests for HTTP-client helpers (Retry-After parsing, URL resolution)."""
from __future__ import annotations

import time
from email.utils import formatdate
from pathlib import Path

import pytest

from frameio_agent.client import FrameioClient, _parse_retry_after
from frameio_agent.config import Config


class TestParseRetryAfter:
    def test_delta_seconds(self) -> None:
        assert _parse_retry_after("30") == 30.0

    def test_float_seconds(self) -> None:
        assert _parse_retry_after("1.5") == 1.5

    def test_http_date_future(self) -> None:
        # RFC 9110 permits an HTTP-date; a bare float() used to raise here.
        future = formatdate(time.time() + 60, usegmt=True)
        got = _parse_retry_after(future)
        assert 0.0 < got <= 61.0

    def test_http_date_past_clamps_to_zero(self) -> None:
        past = formatdate(time.time() - 120, usegmt=True)
        assert _parse_retry_after(past) == 0.0

    def test_garbage_falls_back_to_zero(self) -> None:
        assert _parse_retry_after("soon-ish") == 0.0

    def test_empty_and_negative(self) -> None:
        assert _parse_retry_after("") == 0.0
        assert _parse_retry_after("-5") == 0.0


class TestAbsoluteUrl:
    def _client(self) -> FrameioClient:
        cfg = Config(
            client_id="x", client_secret="y", redirect_uri="https://localhost",
            scopes=("openid",), token_file=Path("/tmp/t.json"),
            api_base="https://api.frame.io/v4",
            default_account_id=None, default_workspace_id=None,
        )
        return FrameioClient(cfg)

    def test_v4_relative_path(self) -> None:
        c = self._client()
        try:
            assert c._absolute("/me") == "https://api.frame.io/v4/me"
        finally:
            c.close()

    def test_host_absolute_v4_path_not_doubled(self) -> None:
        # links.next cursors arrive as /v4/... — must not become /v4/v4/...
        c = self._client()
        try:
            out = c._absolute("/v4/accounts/a/folders/f/children?after=xyz")
            assert out.startswith("https://api.frame.io/v4/accounts/")
            assert "/v4/v4/" not in out
        finally:
            c.close()

    def test_full_url_passthrough(self) -> None:
        c = self._client()
        try:
            url = "https://elsewhere.example.com/x"
            assert c._absolute(url) == url
        finally:
            c.close()
