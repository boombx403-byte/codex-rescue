"""E2E Test Suite for Codex Rescue (0.1.0a3)."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is in sys.path for test discovery and direct test execution
_src_dir = Path(__file__).resolve().parent.parent.parent / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
