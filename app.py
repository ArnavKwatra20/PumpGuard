"""Vercel serverless entrypoint (ASGI) for the PumpGuard API.

Vercel's Python runtime auto-detects an ``app`` instance in this file at the
project root and routes every backend request to it. Local development keeps
using ``uvicorn apps.api.main:app``; this module exists only so the src-layout
``pumpguard`` package resolves inside Vercel's function bundle, where the
project itself is not pip-installed (requirements.txt lists runtime
dependencies only).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _path in (str(_ROOT), str(_ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from pumpguard.api.app import create_app  # noqa: E402  (sys.path setup must run first)

app = create_app()
