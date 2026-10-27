import os
import subprocess
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE_SCRIPT = REPOSITORY_ROOT / "deploy" / "database-maintenance.sh"


def test_backup_pruning_only_removes_old_generated_backup_files(tmp_path):
    old_backup = tmp_path / "sps-dashboard-old.dump.age"
    recent_backup = tmp_path / "sps-dashboard-recent.dump.age"
    custom_file = tmp_path / "manual-export.dump.age"
    nested_backup = tmp_path / "nested" / "sps-dashboard-nested.dump.age"
    nested_backup.parent.mkdir()
    for path in (old_backup, recent_backup, custom_file, nested_backup):
        path.write_bytes(b"encrypted")

    old_timestamp = time.time() - 40 * 24 * 60 * 60
    os.utime(old_backup, (old_timestamp, old_timestamp))
    os.utime(custom_file, (old_timestamp, old_timestamp))
    os.utime(nested_backup, (old_timestamp, old_timestamp))

    result = subprocess.run(
        ["bash", str(MAINTENANCE_SCRIPT), "prune"],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "BACKUP_DIRECTORY": str(tmp_path), "BACKUP_RETENTION_DAYS": "30"},
        check=True,
        capture_output=True,
        text=True,
    )

    assert not old_backup.exists()
    assert recent_backup.exists()
    assert custom_file.exists()
    assert nested_backup.exists()
    assert old_backup.name in result.stdout
