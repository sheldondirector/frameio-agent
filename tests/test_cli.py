"""CLI routing tests — exit codes and help behavior."""
from __future__ import annotations

import pytest

from frameio_agent.cli import main


class TestMissingSubcommand:
    @pytest.mark.parametrize("group", ["auth", "frames", "refs", "share"])
    def test_bare_group_exits_2(self, group: str, capsys) -> None:
        # Regression: parse_args([group, "--help"]) raised SystemExit(0),
        # so `frameio-agent frames` (no subcommand) exited 0. A missing
        # subcommand is user error and must exit nonzero.
        rc = main([group])
        assert rc == 2
        captured = capsys.readouterr()
        assert "usage:" in captured.err


class TestNoCommand:
    def test_bare_invocation_prints_help_exit_0(self, capsys) -> None:
        rc = main([])
        assert rc == 0
        assert "usage:" in capsys.readouterr().out
