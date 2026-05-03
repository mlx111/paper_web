"""Shared test configuration — add app/ to sys.path for bare imports like models.factory."""
import sys
from pathlib import Path

# Ensure the app/ directory is on sys.path so that bare imports
# (from tools.xxx, from services.xxx, from models.factory, etc.) work.
_app_dir = Path(__file__).resolve().parent / "app"
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))
