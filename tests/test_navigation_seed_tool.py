"""The seed generator must never rewrite an applied migration.

Migration 0031 is already applied to development; Alembic does not checksum
applied revisions, so a silent rewrite would go undetected. `--check` may read
the active file, but `--write` must refuse it and leave the bytes untouched.
"""
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "generate_navigation_seed.py"
MIGRATION = ROOT / "alembic" / "versions" / "0031_navigation_registry.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def _module():
    spec = importlib.util.spec_from_file_location("generate_navigation_seed", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_reads_the_active_migration():
    before = _sha256(MIGRATION)
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "seed block is current" in result.stdout
    assert _sha256(MIGRATION) == before


def test_write_refuses_the_active_migration():
    before = _sha256(MIGRATION)
    result = _run("--write")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "refusing to rewrite the active migration" in result.stderr
    assert _sha256(MIGRATION) == before


def test_only_the_active_path_is_protected():
    module = _module()
    draft = module.ACTIVE.with_name(module.ACTIVE.name + ".draft")
    assert module.is_active(module.ACTIVE)
    assert not module.is_active(draft)
