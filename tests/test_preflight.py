import json
import os
import shutil
import types
from pathlib import Path

import yaml

import app.manage as manage


def _setup_project(tmp_path, tmp_campaign_dir):
    data_root = tmp_path / "data"
    (data_root / "campaigns").mkdir(parents=True)
    shutil.copytree(tmp_campaign_dir, data_root / "campaigns" / "example")

    attachments_dir = data_root / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    default_attachment = attachments_dir / "default.pdf"
    default_attachment.write_text("dummy")

    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    os.makedirs(os.environ["CREDS_ROOT"], exist_ok=True)

    manage.DATA_ROOT = os.environ["DATA_ROOT"]
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    manage.CAMPAIGNS_DIR = os.path.join(manage.DATA_ROOT, "campaigns")

    cfg_path = data_root / "campaigns" / "example" / "campaign_config.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    cfg["default_attachment_path"] = "data/attachments/default.pdf"
    cfg["track_opens"] = False
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)
    return default_attachment


def _parse_logs(output: str):
    logs = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        logs.append(json.loads(line))
    return logs


def test_preflight_summary_counts(tmp_path, tmp_campaign_dir, capsys):
    default_attachment = _setup_project(tmp_path, tmp_campaign_dir)

    args = types.SimpleNamespace(campaign="example")
    manage.cmd_preflight(args)

    logs = _parse_logs(capsys.readouterr().out)
    summary = next(log for log in logs if log["event"] == "preflight_summary")
    data = summary["data"]
    assert data["total_recipients"] == 2
    assert data["attachment_missing"] == 0
    assert data["attachment_ok"] >= 1
    assert data["default_attachment_present"] is True
    assert data["template_exists"] is True
    assert data["sheet_status"] == "skipped"


def test_preflight_checks_sheet(tmp_path, tmp_campaign_dir, monkeypatch, capsys):
    default_attachment = _setup_project(tmp_path, tmp_campaign_dir)

    cfg_path = Path(manage.DATA_ROOT) / "campaigns" / "example" / "campaign_config.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    cfg["track_opens"] = True
    cfg["sheet_id"] = "sheet123"
    cfg["sheet_opens_name"] = "opens"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)

    class DummySheets:
        def __init__(self):
            self.called = False

        def spreadsheets(self):
            return self

        def values(self):
            return self

        def get(self, spreadsheetId, range):
            self.called = True
            assert spreadsheetId == "sheet123"
            return types.SimpleNamespace(execute=lambda: {"values": [["ts"]]})

    dummy = DummySheets()
    monkeypatch.setattr(manage, "get_sheets_service", lambda *_: dummy)

    args = types.SimpleNamespace(campaign="example")
    manage.cmd_preflight(args)

    logs = _parse_logs(capsys.readouterr().out)
    summary = next(log for log in logs if log["event"] == "preflight_summary")
    assert summary["data"]["sheet_status"] == "ok"
    assert dummy.called
