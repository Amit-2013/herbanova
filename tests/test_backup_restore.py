"""MOD-09: the backup/restore test really runs, and it really can fail."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(
    subprocess.run(["which", "pg_dump"], capture_output=True).returncode != 0,
    reason="PostgreSQL client tools are not installed")


def test_restore_of_the_test_database_is_verified(database):
    done = subprocess.run([sys.executable, "backup_restore_test.py"], cwd=ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RESTORE TEST PASSED" in done.stdout


def test_a_difference_between_live_and_restored_copy_fails(database, monkeypatch, capsys):
    import backup_restore_test as tool
    real = tool._row_counts
    calls = {"n": 0}

    def tampered(engine):
        counts = dict(real(engine))
        calls["n"] += 1
        if calls["n"] == 2:                      # the restored copy loses a row
            counts["users"] = counts["users"] - 1
        return counts

    monkeypatch.setattr(tool, "_row_counts", tampered)
    monkeypatch.setattr(sys, "argv", ["backup_restore_test.py"])
    assert tool.main() == 1
    assert "RESTORE TEST FAILED" in capsys.readouterr().out
