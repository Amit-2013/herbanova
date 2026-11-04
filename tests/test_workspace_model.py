"""The workspace model is plain JavaScript; Node's test runner proves it.
This wrapper keeps `pytest` as the single entry point for the suite."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_workspace_model_contract():
    result = subprocess.run(["node", "--test", "tests/js/workspace.test.cjs"], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    output = (result.stdout + result.stderr).replace("\x1b[0m", "")
    assert result.returncode == 0, output
    assert "fail 0" in output, output
    # The model itself must run, not an empty glob that happens to exit zero.
    passed = re.search(r"pass (\d+)", output)
    assert passed and int(passed.group(1)) >= 18, output
