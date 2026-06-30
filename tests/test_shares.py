"""Tests for the share-creation command — payload, confirmation, no-TTY guard."""
from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

import pytest

from frameio_agent import shares


def _emit_capture(captured: list[Any]):
    def _emit(payload: Any, as_json: bool) -> None:
        captured.append((payload, as_json))
    return _emit


class _FakeTTY(io.StringIO):
    def __init__(self, text: str = "", tty: bool = True) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestBuildPayload:
    def test_minimum_fields(self) -> None:
        body = shares.build_payload(
            name="Test", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True,
        )
        assert body == {
            "name": "Test",
            "asset_ids": ["f1"],
            "allow_comments": True,
            "allow_download": False,
            "access": "public",
        }

    def test_restricted_visibility(self) -> None:
        body = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=False,
        )
        assert body["access"] == "restricted"

    def test_expires_and_password_included_when_set(self) -> None:
        body = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=True,
            expires_at="2026-07-15", password="hunter2", public=True,
        )
        assert body["expires_at"] == "2026-07-15"
        assert body["password"] == "hunter2"

    def test_multiple_assets(self) -> None:
        body = shares.build_payload(
            name="x", asset_ids=["a", "b", "c"], allow_comments=True,
            allow_download=False, expires_at=None, password=None, public=True,
        )
        assert body["asset_ids"] == ["a", "b", "c"]


class TestRenderConfirmation:
    def test_public_label(self) -> None:
        payload = shares.build_payload(
            name="Demo", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True,
        )
        text = shares._render_confirmation(payload)
        assert "public link" in text
        assert "anyone with URL" in text
        assert "Demo" in text

    def test_restricted_label(self) -> None:
        payload = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=False,
        )
        text = shares._render_confirmation(payload)
        assert "restricted" in text
        assert "signed-in" in text

    def test_password_never_echoed(self) -> None:
        payload = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password="hunter2-very-secret", public=True,
        )
        text = shares._render_confirmation(payload)
        assert "hunter2" not in text
        assert "Password:     set" in text

    def test_no_password_shown_as_none(self) -> None:
        payload = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True,
        )
        text = shares._render_confirmation(payload)
        assert "Password:     none" in text

    def test_download_default_no(self) -> None:
        payload = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True,
        )
        text = shares._render_confirmation(payload)
        assert "Download:     not allowed" in text


class TestNormalizeResponse:
    def test_minimal_response(self) -> None:
        raw = {"id": "share_xxx", "url": "https://f.io/p/xxx", "created_at": "2026-06-30T13:00:00Z"}
        request = shares.build_payload(
            name="Demo", asset_ids=["f1", "f2"], allow_comments=True,
            allow_download=False, expires_at=None, password=None, public=True,
        )
        out = shares._normalize_share_response(raw, request)
        assert out["share_id"] == "share_xxx"
        assert out["url"] == "https://f.io/p/xxx"
        assert out["asset_count"] == 2
        assert out["asset_ids"] == ["f1", "f2"]
        assert out["visibility"] == "public"
        assert out["password_protected"] is False

    def test_password_protected_marker(self) -> None:
        raw = {"id": "s1", "url": "https://f.io/p/x"}
        request = shares.build_payload(
            name="x", asset_ids=["f1"], allow_comments=True, allow_download=False,
            expires_at=None, password="hunter2", public=True,
        )
        out = shares._normalize_share_response(raw, request)
        assert out["password_protected"] is True


class TestCmdShareCreateGuards:
    def test_no_file_ids_refused(self) -> None:
        captured: list[Any] = []
        rc = shares.cmd_share_create(
            file_ids=[], name="x", allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True, yes=True,
            as_json=False, emit=_emit_capture(captured),
        )
        assert rc == 2
        assert captured == []

    def test_empty_name_refused(self) -> None:
        captured: list[Any] = []
        rc = shares.cmd_share_create(
            file_ids=["f1"], name="  ", allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True, yes=True,
            as_json=False, emit=_emit_capture(captured),
        )
        assert rc == 2

    def test_non_tty_without_yes_refused(self) -> None:
        captured: list[Any] = []
        rc = shares.cmd_share_create(
            file_ids=["f1"], name="x", allow_comments=True, allow_download=False,
            expires_at=None, password=None, public=True, yes=False,
            as_json=False, emit=_emit_capture(captured),
            stdin=_FakeTTY(tty=False),
        )
        assert rc == 2
        assert captured == []  # never reached the API

    def test_tty_with_n_aborts(self) -> None:
        captured: list[Any] = []
        with patch("builtins.input", return_value="n"):
            rc = shares.cmd_share_create(
                file_ids=["f1"], name="x", allow_comments=True, allow_download=False,
                expires_at=None, password=None, public=True, yes=False,
                as_json=False, emit=_emit_capture(captured),
                stdin=_FakeTTY(tty=True),
            )
        assert rc == 1
        assert captured == []

    def test_tty_with_empty_input_aborts(self) -> None:
        # Default-N: empty input means No.
        captured: list[Any] = []
        with patch("builtins.input", return_value=""):
            rc = shares.cmd_share_create(
                file_ids=["f1"], name="x", allow_comments=True, allow_download=False,
                expires_at=None, password=None, public=True, yes=False,
                as_json=False, emit=_emit_capture(captured),
                stdin=_FakeTTY(tty=True),
            )
        assert rc == 1


class TestPromptConfirm:
    @pytest.mark.parametrize("answer,expected", [
        ("y", True), ("Y", True), ("yes", True), ("YES", True),
        ("n", False), ("N", False), ("no", False),
        ("", False), ("maybe", False), ("yeah", False),  # only y/yes are yes
    ])
    def test_parsing(self, answer: str, expected: bool) -> None:
        with patch("builtins.input", return_value=answer):
            assert shares._prompt_confirm() is expected

    def test_eof_is_no(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            assert shares._prompt_confirm() is False
