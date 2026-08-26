"""Source-checkout wrapper for the dependency-free production smoke client."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging" / "mcp_smoke_runtime.py"), run_name="__main__")
