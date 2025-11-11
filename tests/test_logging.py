import json
import app.manage as manage


def test_log_event_outputs_json(capsys):
    manage.log_event("info", "demo_event", foo="bar", count=2)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["event"] == "demo_event"
    assert payload["level"] == "INFO"
    assert payload["data"]["foo"] == "bar"
    assert payload["data"]["count"] == 2
    assert "ts" in payload
