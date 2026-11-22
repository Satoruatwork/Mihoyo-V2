#!/usr/bin/env python3
"""Deprecated shim — use scripts/check_db.py instead.

Kept for backwards compatibility so old docs/scripts don't break.
"""

import pathlib
import runpy
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
print("⚠ scripts/check_redis.py is deprecated — running scripts/check_db.py instead.\n")
runpy.run_path(str(pathlib.Path(__file__).with_name("check_db.py")), run_name="__main__")
