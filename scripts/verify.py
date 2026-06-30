"""Sanity-check script. Equivalent to running ``frameio-agent verify``.

Run:  python scripts/verify.py
"""
from __future__ import annotations

import sys

from frameio_agent.cli import main


if __name__ == "__main__":
    sys.exit(main(["verify"]))
