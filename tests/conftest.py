# tests/conftest.py
"""Shared fixtures for data_generation tests."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so package imports work.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
