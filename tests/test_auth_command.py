import json
import os
import shutil
import types

import yaml

import app.manage as manage


class DummyProfileService:
    def users(self):
        return self

    def getProfile(self, userId="me"):
        return types.SimpleNamespace(execute=lambda: {"emailAddress": "tester@example.com"})


def test_cmd_auth_with_explicit_account(tmp_path, monkeypatch, capsys):
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    os.makedirs(manage.CREDS_ROOT, exist_ok=True)

    captured = {}

    def fake_get_service(creds_dir):
        captured["creds_dir"] = creds_dir
        return DummyProfileService()

    monkeypatch.setattr(manage, "get_service", fake_get_service)

    args = types.SimpleNamespace(account="custom", campaign=None)
    manage.cmd_auth(args)

    assert captured["creds_dir"].endswith(os.path.join("creds", "custom"))
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["event"] == "auth_success"
    assert payload["data"]["account"] == "custom"


def test_cmd_auth_uses_campaign_account(tmp_path, tmp_campaign_dir, monkeypatch):
    data_root = tmp_path / "data"
    campaigns_dir = data_root / "campaigns"
    shutil.copytree(tmp_campaign_dir, campaigns_dir / "example")

    cfg_path = campaigns_dir / "example" / "campaign_config.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    cfg["account_name"] = "campaign-account"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)

    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    manage.DATA_ROOT = os.environ["DATA_ROOT"]
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    manage.CAMPAIGNS_DIR = os.path.join(manage.DATA_ROOT, "campaigns")

    os.makedirs(manage.CREDS_ROOT, exist_ok=True)

    captured = {}

    def fake_get_service(creds_dir):
        captured["creds_dir"] = creds_dir
        return DummyProfileService()

    monkeypatch.setattr(manage, "get_service", fake_get_service)

    args = types.SimpleNamespace(account=None, campaign="example")
    manage.cmd_auth(args)

    assert captured["creds_dir"].endswith(os.path.join("creds", "campaign-account"))
