"""Compatibility entrypoint for the staged backend migration.

For now, the root-level ``main.py`` owns the live app and all route behavior.
This module intentionally re-exports that app so new import paths can be tested
without changing production startup or deleting the root reference file.
"""

from main import app

__all__ = ["app"]

