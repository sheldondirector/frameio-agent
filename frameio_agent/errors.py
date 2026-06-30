"""Friendly exceptions with remediation messages.

Every error the CLI surfaces should tell the user *exactly* what to run next.
The PRD treats error messages as a feature, not an afterthought.
"""
from __future__ import annotations


class FrameioAgentError(Exception):
    """Base class. Carries a `remediation` string the CLI prints verbatim."""

    def __init__(self, message: str, remediation: str = "") -> None:
        super().__init__(message)
        self.remediation = remediation

    def render(self) -> str:
        if self.remediation:
            return f"{self.args[0]}\n  > {self.remediation}"
        return str(self.args[0])


class ConfigError(FrameioAgentError):
    """Missing or invalid configuration in .env."""


class AuthError(FrameioAgentError):
    """Missing/expired/revoked credentials or a failed OAuth exchange."""


class ApiError(FrameioAgentError):
    """A Frame.io API call failed."""


class TraversalCapError(FrameioAgentError):
    """A search ran into the folder/asset traversal cap."""
