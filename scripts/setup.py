"""One-shot setup script: install deps and create the local config directory.

Run:  python scripts/setup.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def install_deps() -> None:
    print("Installing dependencies (this may take a moment)...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", str(REPO)])
    except subprocess.CalledProcessError as e:
        print(f"\npip install failed (exit {e.returncode}).", file=sys.stderr)
        print(
            "  > Editable installs of pyproject-only packages need pip >= 21.3.\n"
            f"  > Try: {sys.executable} -m pip install --upgrade pip\n"
            "  > Then re-run: python scripts/setup.py",
            file=sys.stderr,
        )
        raise SystemExit(1)


def ensure_env_file() -> None:
    env = REPO / ".env"
    example = REPO / ".env.example"
    if env.exists():
        print(".env already exists — leaving it alone.")
        return
    if example.exists():
        shutil.copy(example, env)
        print(f"Created {env.name} from .env.example. Edit it, then run: frameio-agent auth login")
    else:
        print("WARNING: .env.example missing; cannot seed .env.", file=sys.stderr)


def ensure_token_dir() -> None:
    token_dir = REPO / ".frameio-agent"
    token_dir.mkdir(exist_ok=True)
    print(f"Token cache directory ready: {token_dir.name}/ (gitignored)")


def main() -> int:
    install_deps()
    ensure_env_file()
    ensure_token_dir()
    print()
    print("Setup complete.")
    print("Next: frameio-agent auth login")
    return 0


if __name__ == "__main__":
    sys.exit(main())
