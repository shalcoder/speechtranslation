"""Compatibility patch for Streamlit Cloud builds.

Some Streamlit Cloud environments may not ship with setuptools, which provides
pkg_resources. Older imageio-ffmpeg versions import pkg_resources at import time,
causing the app to crash before requirements are fully resolved.

This module ensures pkg_resources is importable by trying to install/set up
setuptools at runtime if needed.
"""

from __future__ import annotations

import importlib
import subprocess
import sys


def ensure_pkg_resources() -> None:
    try:
        importlib.import_module("pkg_resources")
        return
    except ModuleNotFoundError:
        pass

    # Best-effort: install/upgrade setuptools into the current environment.
    # If this fails, we re-raise the original error.
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", "setuptools"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        importlib.invalidate_caches()
        importlib.import_module("pkg_resources")
    except Exception as e:
        raise ModuleNotFoundError(
            "pkg_resources is missing (setuptools not installed). "
            "Tried to install setuptools at runtime but failed."
        ) from e
