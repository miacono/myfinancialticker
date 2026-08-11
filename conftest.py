import os
import sys

# Make sure `myfinancialticker` is importable from tests/ regardless of how
# pytest is invoked (bare `pytest`, `python -m pytest`, from another cwd, ...).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
