import os
import sys
from pathlib import Path

import shutil
import pytest


def _resolve_project_root() -> Path:
    """Trova una directory che contenga sia app/ sia data/ in ambienti host o container."""
    env_value = os.environ.get("PYTHONPATH", "")
    env_paths = [Path(p) for p in env_value.split(os.pathsep) if p]
    default_root = Path(__file__).resolve().parents[1]

    candidates = []
    for path in env_paths:
        candidates.append(path)
        candidates.append(path.parent)
    candidates.append(default_root)

    for candidate in candidates:
        if (candidate / "app").is_dir() and (candidate / "data").is_dir():
            return candidate
    return default_root


PROJECT_ROOT = _resolve_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture()
def tmp_campaign_dir(tmp_path, project_root):
    """Copia la campagna di esempio in una directory temporanea."""
    src = project_root / "data" / "campaigns" / "example"
    dst = tmp_path / "campaigns" / "example"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    yield dst
