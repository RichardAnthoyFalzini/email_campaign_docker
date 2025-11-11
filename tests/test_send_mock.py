import csv
import json
import os
import shutil
import types
from pathlib import Path

import yaml
from googleapiclient.errors import HttpError

import app.manage as manage

class DummyService:
    def __init__(self):
        self.sent = []

    # L'API finta replica la chain Google: service.users().messages().send(...)
    def users(self):
        return self

    def messages(self):
        return self

    def labels(self):
        return self

    def threads(self):
        return self

    def send(self, userId, body):
        self.sent.append(body)
        return types.SimpleNamespace(execute=lambda: {"id": "123", "threadId": "t1"})

    def create(self, userId, body):
        return types.SimpleNamespace(execute=lambda: {"id": "lbl"})

    def modify(self, userId, id, body):
        return types.SimpleNamespace(execute=lambda: None)

    def list(self, userId="me", **kw):
        return types.SimpleNamespace(execute=lambda: {"labels": [{"id": "lbl", "name": "campaign/example"}]})

    def get(self, **kw):
        return types.SimpleNamespace(execute=lambda: {"messages": []})

def test_cmd_send_creates_log(tmp_path, monkeypatch, tmp_campaign_dir):
    # Mock servizi
    dummy = DummyService()
    monkeypatch.setattr(manage, "get_service", lambda *_: dummy)
    monkeypatch.setattr(manage, "ensure_label", lambda *a, **kw: "lbl")
    monkeypatch.setattr(manage, "add_labels", lambda *a, **kw: None)

    # Prepara directory finta data/logs
    data_root = tmp_path / "data"
    (data_root / "campaigns").mkdir(parents=True)
    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    os.makedirs(os.environ["CREDS_ROOT"], exist_ok=True)
    manage.DATA_ROOT = os.environ["DATA_ROOT"]
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    manage.CAMPAIGNS_DIR = os.path.join(manage.DATA_ROOT, "campaigns")

    # Copia campagna esempio
    shutil.copytree(tmp_campaign_dir, data_root / "campaigns" / "example")

    args = types.SimpleNamespace(campaign="example")
    manage.cmd_send(args)

    logs_dir = data_root / "logs" / "example"
    log_file = logs_dir / "sent_log.csv"
    assert log_file.exists()
    lines = [l.strip() for l in open(log_file) if l.strip()]
    assert len(lines) >= 1
    assert any("alice@" in l or "bob@" in l for l in lines)

    state_file = logs_dir / manage.STATE_FILENAME
    assert state_file.exists()
    state = json.load(open(state_file))
    assert state["alice@example.com"]["status"] == "sent"
    assert state["bob@example.com"]["status"] == "sent"
    assert len(dummy.sent) == 2


def test_cmd_send_resumes_from_state(tmp_path, monkeypatch, tmp_campaign_dir):
    dummy = DummyService()
    monkeypatch.setattr(manage, "get_service", lambda *_: dummy)
    monkeypatch.setattr(manage, "ensure_label", lambda *a, **kw: "lbl")
    monkeypatch.setattr(manage, "add_labels", lambda *a, **kw: None)

    data_root = tmp_path / "data"
    (data_root / "campaigns").mkdir(parents=True)
    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    os.makedirs(os.environ["CREDS_ROOT"], exist_ok=True)
    manage.DATA_ROOT = os.environ["DATA_ROOT"]
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    manage.CAMPAIGNS_DIR = os.path.join(manage.DATA_ROOT, "campaigns")

    shutil.copytree(tmp_campaign_dir, data_root / "campaigns" / "example")

    logs_dir = data_root / "logs" / "example"
    logs_dir.mkdir(parents=True, exist_ok=True)
    # Simula stato precedente: alice già inviata, bob ancora pending
    state = {
        "alice@example.com": {"status": "sent", "attempts": 1},
        "bob@example.com": {"status": "pending", "attempts": 0},
    }
    with open(logs_dir / manage.STATE_FILENAME, "w", encoding="utf-8") as f:
        json.dump(state, f)
    with open(logs_dir / "sent_log.csv", "w", encoding="utf-8") as f:
        f.write("alice@example.com\n")

    args = types.SimpleNamespace(campaign="example")
    manage.cmd_send(args)

    # Solo Bob deve essere inviato in questa esecuzione
    assert len(dummy.sent) == 1
    state = json.load(open(logs_dir / manage.STATE_FILENAME))
    assert state["alice@example.com"]["status"] == "sent"
    assert state["bob@example.com"]["status"] == "sent"


def _http_error(status):
    resp = types.SimpleNamespace(status=status, reason="boom")
    return HttpError(resp=resp, content=b"{}")


def test_cmd_send_retries_on_retryable_error(tmp_path, monkeypatch, tmp_campaign_dir):
    class FlakyService(DummyService):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def send(self, userId, body):
            def _execute():
                self.attempts += 1
                if self.attempts == 1:
                    raise _http_error(429)
                self.sent.append(body)
                return {"id": "ok", "threadId": "t1"}
            return types.SimpleNamespace(execute=_execute)

    dummy = FlakyService()
    monkeypatch.setattr(manage, "get_service", lambda *_: dummy)
    monkeypatch.setattr(manage, "ensure_label", lambda *a, **kw: "lbl")
    monkeypatch.setattr(manage, "add_labels", lambda *a, **kw: None)

    data_root = tmp_path / "data"
    (data_root / "campaigns").mkdir(parents=True)
    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    os.makedirs(os.environ["CREDS_ROOT"], exist_ok=True)
    manage.DATA_ROOT = os.environ["DATA_ROOT"]
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    manage.CAMPAIGNS_DIR = os.path.join(manage.DATA_ROOT, "campaigns")

    shutil.copytree(tmp_campaign_dir, data_root / "campaigns" / "example")

    args = types.SimpleNamespace(campaign="example")
    manage.cmd_send(args)

    assert len(dummy.sent) == 2  # entrambi i destinatari spediti
    assert dummy.attempts >= 3  # primo tentativo fallito, poi retry


def test_cmd_send_stops_after_max_attempts(tmp_path, monkeypatch, tmp_campaign_dir):
    dummy = DummyService()
    monkeypatch.setattr(manage, "get_service", lambda *_: dummy)
    monkeypatch.setattr(manage, "ensure_label", lambda *a, **kw: "lbl")
    monkeypatch.setattr(manage, "add_labels", lambda *a, **kw: None)

    data_root = tmp_path / "data"
    (data_root / "campaigns").mkdir(parents=True)
    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["CREDS_ROOT"] = str(tmp_path / "creds")
    os.makedirs(os.environ["CREDS_ROOT"], exist_ok=True)
    manage.DATA_ROOT = os.environ["DATA_ROOT"]
    manage.CREDS_ROOT = os.environ["CREDS_ROOT"]
    manage.CAMPAIGNS_DIR = os.path.join(manage.DATA_ROOT, "campaigns")

    shutil.copytree(tmp_campaign_dir, data_root / "campaigns" / "example")

    cfg_path = data_root / "campaigns" / "example" / "campaign_config.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    cfg["max_attempts_per_contact"] = 1
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f)

    logs_dir = data_root / "logs" / "example"
    logs_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "alice@example.com": {"status": "error", "attempts": 1},
        "bob@example.com": {"status": "pending", "attempts": 0},
    }
    with open(logs_dir / manage.STATE_FILENAME, "w", encoding="utf-8") as f:
        json.dump(state, f)

    args = types.SimpleNamespace(campaign="example")
    manage.cmd_send(args)

    # Alice ha raggiunto il limite: nessun invio, Bob procede.
    assert len(dummy.sent) == 1
    lines = [l.strip() for l in open(logs_dir / "sent_log.csv") if l.strip()]
    assert "bob@example.com" in lines
    assert "alice@example.com" not in lines
