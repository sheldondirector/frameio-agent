"""Redaction tests — the safety net that prevents accidental secret leaks."""
from __future__ import annotations

import json

import pytest

from frameio_agent import redact


SAMPLE_JWT = (
    "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NSIsIm5hbWUiOiJUZXN0IiwiaWF0IjoxNTE2MjM5MDIyfQ"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
SAMPLE_OPAQUE = "p8e-Vh5ef-O0TBd-lvzeI3SKoSwvSwewN42p_extralongtoreach32chars"
SAMPLE_SHORT = "abc123"  # below the 32-char threshold


class TestIsSecretKey:
    @pytest.mark.parametrize(
        "key",
        [
            "FRAMEIO_CLIENT_SECRET",
            "FRAMEIO_ACCESS_TOKEN",
            "FRAMEIO_REFRESH_TOKEN",
            "MY_PASSWORD",
            "SOMETHING_PRIVATE",
            "AUTH_CODE",
            "ID_TOKEN",
        ],
    )
    def test_secret_keys_detected(self, key: str) -> None:
        assert redact.is_secret_key(key) is True

    @pytest.mark.parametrize(
        "key",
        ["FRAMEIO_CLIENT_ID", "FRAMEIO_API_BASE", "FRAMEIO_REDIRECT_URI", "FRAMEIO_ACCOUNT_ID"],
    )
    def test_nonsecret_keys_pass_through(self, key: str) -> None:
        assert redact.is_secret_key(key) is False


class TestRedactValue:
    def test_jwt_token_redacted(self) -> None:
        out = redact.redact_value(f"Got token: {SAMPLE_JWT}")
        assert SAMPLE_JWT not in out
        assert redact.PLACEHOLDER in out

    def test_bearer_header_redacted(self) -> None:
        out = redact.redact_value(f"Authorization: Bearer {SAMPLE_JWT}")
        assert SAMPLE_JWT not in out
        assert "Bearer" in out

    def test_opaque_long_string_redacted(self) -> None:
        out = redact.redact_value(SAMPLE_OPAQUE)
        assert SAMPLE_OPAQUE not in out

    def test_short_strings_pass_through(self) -> None:
        assert redact.redact_value(SAMPLE_SHORT) == SAMPLE_SHORT
        assert redact.redact_value("hello world") == "hello world"

    def test_empty_string_ok(self) -> None:
        assert redact.redact_value("") == ""


class TestRedactUrl:
    def test_code_param_stripped(self) -> None:
        url = "http://localhost:8722/callback?code=abc.def.ghi&state=xyz"
        out = redact.redact_url(url)
        assert "abc.def.ghi" not in out
        assert "state=xyz" in out

    def test_signed_s3_url(self) -> None:
        url = (
            "https://example.s3.amazonaws.com/asset.mov"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            "&X-Amz-Signature=deadbeefcafebabe1234567890abcdef"
        )
        out = redact.redact_url(url)
        assert "deadbeefcafebabe" not in out
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in out

    def test_no_query_unchanged(self) -> None:
        url = "https://api.frame.io/v4/me"
        assert redact.redact_url(url) == url


class TestRedactEnv:
    def test_replaces_secret_values(self) -> None:
        env = {
            "FRAMEIO_CLIENT_ID": "id_value",
            "FRAMEIO_CLIENT_SECRET": "secret_value",
            "FRAMEIO_REFRESH_TOKEN": "refresh_value",
        }
        out = redact.redact_env(env)
        assert out["FRAMEIO_CLIENT_ID"] == "id_value"
        assert "secret_value" not in json.dumps(out)
        assert "refresh_value" not in json.dumps(out)


class TestRedactMapping:
    def test_nested_dict_keys_redacted(self) -> None:
        data = {
            "user": "alice",
            "tokens": {"access_token": SAMPLE_JWT, "refresh_token": "long" * 10},
            "history": [{"client_secret": "p8e-secret-value-that-is-very-long-indeed"}],
        }
        out = redact.redact_mapping(data)
        serialized = json.dumps(out)
        assert SAMPLE_JWT not in serialized
        assert "p8e-secret-value-that-is-very-long-indeed" not in serialized
        assert out["user"] == "alice"

    def test_redacts_jwt_in_string_values(self) -> None:
        data = {"log_line": f"saved token={SAMPLE_JWT}"}
        out = redact.redact_mapping(data)
        assert SAMPLE_JWT not in out["log_line"]

    def test_redacts_url_query_in_string_values(self) -> None:
        data = {"redirect": "http://localhost:8722/callback?code=abc.def.ghi"}
        out = redact.redact_mapping(data)
        assert "abc.def.ghi" not in out["redirect"]


class TestSafeFormatException:
    def test_exception_message_redacted(self) -> None:
        try:
            raise ValueError(f"failed with token {SAMPLE_JWT}")
        except ValueError as e:
            out = redact.safe_format_exception(e)
            assert SAMPLE_JWT not in out
            assert "failed with token" in out
