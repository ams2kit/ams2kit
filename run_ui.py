"""Start the ams2kit UI (double-click, or `python run_ui.py [--port N] [--no-browser]`).

Errors stay on screen (and go to %LOCALAPPDATA%\\ams2kit\\ui.log) instead of closing the window.
"""
import os, sys, traceback
from pathlib import Path

LOG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ams2kit" / "ui.log"


def fail(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(msg, encoding="utf-8")
    print(msg)
    print(f"\n(also saved to {LOG})")
    if sys.stdin and sys.stdin.isatty():
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
    sys.exit(1)


if sys.version_info < (3, 11):
    fail(f"ams2kit needs Python 3.11 or newer; this is {sys.version.split()[0]} ({sys.executable}).")


def _add_user_site():
    """Some launch contexts don't add the per-user packages folder (where `pip install --user` puts
    pillow/numpy); add it explicitly."""
    import site
    user = site.getusersitepackages()
    if os.path.isdir(user) and user not in sys.path:
        site.addsitedir(user)


_add_user_site()


def _have_packages():
    try:
        import numpy, PIL  # noqa: F401
        return None
    except ImportError as e:
        return e.name


missing = _have_packages()
if missing:
    import subprocess
    cmd = [sys.executable, "-m", "pip", "install", "--user", "pillow", "numpy"]
    print(f"ams2kit needs the Python packages pillow and numpy ({missing} is missing for {sys.executable}).")
    try:
        answer = input("Install them now with pip? [Y/n] ").strip().lower() if sys.stdin and sys.stdin.isatty() else "n"
    except EOFError:
        answer = "n"
    if answer in ("", "y", "yes"):
        subprocess.run(cmd)
        import importlib, site
        importlib.invalidate_caches()
        site.addsitedir(site.getusersitepackages())
        missing = _have_packages()
    if missing:
        fail(f"Missing Python package: {missing}. Install it with:\n  \"{sys.executable}\" -m pip install --user pillow numpy\n"
             f"(user packages folder: {__import__('site').getusersitepackages()})")

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ams2kit.__main__ import main
    main(["ui", *sys.argv[1:]])
except SystemExit:
    raise
except BaseException:
    fail("ams2kit stopped with an error:\n\n" + traceback.format_exc())
