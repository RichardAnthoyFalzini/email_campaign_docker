import os
import subprocess
import sys
from pathlib import Path

def test_cli_list_runs(project_root):
    script = (project_root / "app" / "manage.py").resolve()
    env = os.environ.copy()
    env.setdefault("DATA_ROOT", str(project_root / "data"))
    env.setdefault("CREDS_ROOT", str(project_root / "creds"))
    result = subprocess.run(
        [sys.executable, str(script), "list"],
        cwd=str(script.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "example" in result.stdout.lower()
