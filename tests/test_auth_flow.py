"""Tests for the agent-friendly two-step auth flow (start / complete)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from frameio_agent import auth as auth_mod
from frameio_agent.config import Config


def _cfg(tmp_path: Path, **overrides: Any) -> Config:
    defaults: dict[str, Any] = dict(
        client_id="cid", client_secret="csecret", redirect_uri="https://localhost",
        scopes=("openid", "email"), token_file=tmp_path / ".frameio-agent" / "tokens.json",
        api_base="https://api.frame.io/v4",
        default_account_id=None, default_workspace_id=None,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestPendingAuthRoundtrip:
    def test_save_load_clear(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        auth_mod._save_pending_auth(cfg, {
            "state": "s1", "code_verifier": "v1",
            "redirect_uri": "https://localhost", "created_at": time.time(),
        })
        loaded = auth_mod._load_pending_auth(cfg)
        assert loaded is not None
        assert loaded["state"] == "s1"
        auth_mod._clear_pending_auth(cfg)
        assert auth_mod._load_pending_auth(cfg) is None

    def test_expired_pending_rejected(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        auth_mod._save_pending_auth(cfg, {
            "state": "s1", "code_verifier": "v1",
            "redirect_uri": "https://localhost",
            "created_at": time.time() - auth_mod.PENDING_AUTH_TTL_SECONDS - 5,
        })
        assert auth_mod._load_pending_auth(cfg) is None

    def test_malformed_pending_rejected(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        p = auth_mod._pending_auth_path(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{corrupt", encoding="utf-8")
        assert auth_mod._load_pending_auth(cfg) is None


class TestParseCallback:
    def test_full_url_with_matching_state(self) -> None:
        code, err = auth_mod._parse_callback(
            "https://localhost/?code=abc123&state=st", expected_state="st",
        )
        assert err is None
        assert code == "abc123"

    def test_state_mismatch_rejected(self) -> None:
        code, err = auth_mod._parse_callback(
            "https://localhost/?code=abc&state=WRONG", expected_state="st",
        )
        assert code is None
        assert "state mismatch" in (err or "").lower()

    def test_bare_code_accepted(self) -> None:
        code, err = auth_mod._parse_callback("just-a-code", expected_state="st")
        assert err is None
        assert code == "just-a-code"

    def test_adobe_error_surfaced(self) -> None:
        code, err = auth_mod._parse_callback(
            "https://localhost/?error=access_denied", expected_state="st",
        )
        assert code is None
        assert "access_denied" in (err or "")


class TestCmdCompleteGuards:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append((p, j))
        return emit

    def test_no_pending_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(tmp_path)
        monkeypatch.setattr(auth_mod, "load_config", lambda: cfg)
        rc = auth_mod.cmd_complete(
            redirect_or_code="https://localhost/?code=x&state=y",
            as_json=False, emit=self._emit([]),
        )
        assert rc == 2

    def test_state_mismatch_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(tmp_path)
        monkeypatch.setattr(auth_mod, "load_config", lambda: cfg)
        auth_mod._save_pending_auth(cfg, {
            "state": "expected", "code_verifier": "v",
            "redirect_uri": "https://localhost", "created_at": time.time(),
        })
        rc = auth_mod.cmd_complete(
            redirect_or_code="https://localhost/?code=x&state=attacker",
            as_json=False, emit=self._emit([]),
        )
        assert rc == 2
        # Pending survives a bad attempt so the user can paste the right URL.
        assert auth_mod._load_pending_auth(cfg) is not None


class TestCmdStart:
    def _emit(self, captured: list[Any]):
        def emit(p: Any, j: bool) -> None: captured.append(p)
        return emit

    def test_start_emits_url_and_persists_pending(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(tmp_path)
        monkeypatch.setattr(auth_mod, "load_config", lambda: cfg)
        captured: list[Any] = []
        rc = auth_mod.cmd_start(as_json=True, emit=self._emit(captured))
        assert rc == 0
        payload = captured[0]
        assert payload["authorize_url"].startswith(auth_mod.IMS_AUTHORIZE_URL)
        assert "code_challenge=" in payload["authorize_url"]
        pending = auth_mod._load_pending_auth(cfg)
        assert pending is not None
        assert pending["state"] in payload["authorize_url"]
        # Verifier stays on disk with owner-only perms and NEVER in the URL.
        assert pending["code_verifier"] not in payload["authorize_url"]

    def test_start_without_credentials_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _cfg(tmp_path, client_id=None, client_secret=None)
        monkeypatch.setattr(auth_mod, "load_config", lambda: cfg)
        rc = auth_mod.cmd_start(as_json=False, emit=self._emit([]))
        assert rc == 2
