"""Entry point for the frozen backend (PyInstaller). Same as `python -m claw.main`."""

from claw.main import main

if __name__ == "__main__":
    raise SystemExit(main())
