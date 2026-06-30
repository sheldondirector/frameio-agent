"""Config loader tests — verify .env parsing, placeholders, and path resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from frameio_agent import config as config_mod
from frameio_agent.config import Config, load_config, write_env_values
from frameio_agent.errors import ConfigError


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip Frame.io env vars so tests are deterministic."""
    for k in [
        "FRAMEIO_CLIENT_ID",
        "FRAMEIO_CLIENT_SECRET",
        "FRAMEIO_REDIRECT_URI",
        "FRAMEIO_SCOPES",
        "FRAMEIO_TOKEN_FILE",
        "FRAMEIO_API_BASE",
        "FRAMEIO_ACCOUNT_ID",
        "FRAMEIO_WORKSPACE_ID",
    ]:
        monkeypatch.delenv(k, raising=False)


def _write_env(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".env"
    p.write_text(content, encoding="utf-8")
    return p


class TestLoadConfig:
    def test_defaults_when_env_missing(self, tmp_path: Path) -> None:
        cfg = load_config(env_file=tmp_path / "missing.env")
        assert cfg.client_id is None
        assert cfg.client_secret is None
        assert cfg.redirect_uri == "http://localhost:8722/callback"
        assert cfg.api_base == "https://api.frame.io/v4"
        assert cfg.loopback_port == 8722

    def test_reads_values_from_env_file(self, tmp_path: Path) -> None:
        env = _write_env(
            tmp_path,
            "FRAMEIO_CLIENT_ID=abc123\nFRAMEIO_CLIENT_SECRET=p8e-supersecret-burner-value-1234567890\n",
        )
        cfg = load_config(env_file=env)
        assert cfg.client_id == "abc123"
        assert cfg.client_secret == "p8e-supersecret-burner-value-1234567890"

    def test_placeholder_values_treated_as_unset(self, tmp_path: Path) -> None:
        env = _write_env(
            tmp_path,
            "FRAMEIO_CLIENT_ID=your_client_id_here\nFRAMEIO_CLIENT_SECRET=changeme\n",
        )
        cfg = load_config(env_file=env)
        assert cfg.client_id is None
        assert cfg.client_secret is None

    def test_custom_redirect_uri_extracts_port(self, tmp_path: Path) -> None:
        env = _write_env(tmp_path, "FRAMEIO_REDIRECT_URI=http://localhost:9000/callback\n")
        cfg = load_config(env_file=env)
        assert cfg.redirect_uri == "http://localhost:9000/callback"
        assert cfg.loopback_port == 9000

    def test_scopes_parsed(self, tmp_path: Path) -> None:
        env = _write_env(tmp_path, "FRAMEIO_SCOPES=openid, profile, offline_access\n")
        cfg = load_config(env_file=env)
        assert cfg.scopes == ("openid", "profile", "offline_access")

    def test_token_file_relative_resolves_under_repo(self, tmp_path: Path) -> None:
        env = _write_env(tmp_path, "FRAMEIO_TOKEN_FILE=.frameio-agent/tokens.json\n")
        cfg = load_config(env_file=env)
        assert cfg.token_file.is_absolute()
        assert cfg.token_file.name == "tokens.json"

    def test_token_file_absolute_preserved(self, tmp_path: Path) -> None:
        abs_target = tmp_path / "abs_tokens.json"
        env = _write_env(tmp_path, f"FRAMEIO_TOKEN_FILE={abs_target}\n")
        cfg = load_config(env_file=env)
        assert cfg.token_file == abs_target


class TestRequireOauthApp:
    def test_raises_when_client_id_missing(self) -> None:
        cfg = Config(
            client_id=None, client_secret=None, redirect_uri="http://localhost:8722/callback",
            scopes=("openid",), token_file=Path("/tmp/t.json"), api_base="https://api.frame.io/v4",
            default_account_id=None, default_workspace_id=None,
        )
        with pytest.raises(ConfigError) as ei:
            cfg.require_oauth_app()
        assert "auth login" in ei.value.remediation

    def test_passes_when_both_present(self) -> None:
        cfg = Config(
            client_id="x", client_secret="y", redirect_uri="http://localhost:8722/callback",
            scopes=("openid",), token_file=Path("/tmp/t.json"), api_base="https://api.frame.io/v4",
            default_account_id=None, default_workspace_id=None,
        )
        cfg.require_oauth_app()  # no raise


class TestConfigRepr:
    def test_repr_never_contains_secret(self) -> None:
        cfg = Config(
            client_id="abc", client_secret="p8e-very-secret-burner-value-xyz",
            redirect_uri="http://localhost:8722/callback", scopes=("openid",),
            token_file=Path("/tmp/t.json"), api_base="https://api.frame.io/v4",
            default_account_id=None, default_workspace_id=None,
        )
        text = repr(cfg)
        assert "p8e-very-secret-burner-value-xyz" not in text
        assert "abc" not in text
        assert "<set>" in text


class TestWriteEnvValues:
    def test_updates_existing_key(self, tmp_path: Path) -> None:
        env = _write_env(
            tmp_path,
            "# header\nFRAMEIO_CLIENT_ID=old\nFRAMEIO_API_BASE=https://x\n",
        )
        write_env_values({"FRAMEIO_CLIENT_ID": "new123"}, env_file=env)
        out = env.read_text(encoding="utf-8")
        assert "FRAMEIO_CLIENT_ID=new123" in out
        assert "FRAMEIO_API_BASE=https://x" in out
        assert "# header" in out

    def test_appends_missing_key(self, tmp_path: Path) -> None:
        env = _write_env(tmp_path, "FRAMEIO_CLIENT_ID=abc\n")
        write_env_values({"FRAMEIO_NEW_KEY": "val"}, env_file=env)
        out = env.read_text(encoding="utf-8")
        assert "FRAMEIO_NEW_KEY=val" in out

    def test_creates_file_from_example_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point REPO_ROOT at a tmp dir with no .env.example, so we just write fresh.
        monkeypatch.setattr(config_mod, "REPO_ROOT", tmp_path)
        env = tmp_path / ".env"
        write_env_values({"FRAMEIO_CLIENT_ID": "new"}, env_file=env)
        assert env.exists()
        assert "FRAMEIO_CLIENT_ID=new" in env.read_text(encoding="utf-8")
