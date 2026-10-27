"""Make the integration in this repo loadable by the Home Assistant test harness."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))  # fixtures.py

import custom_components  # noqa: E402

if str(ROOT / "custom_components") not in list(custom_components.__path__):
    custom_components.__path__.append(str(ROOT / "custom_components"))
