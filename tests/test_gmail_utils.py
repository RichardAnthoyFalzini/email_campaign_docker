import base64
import email
from app.manage import make_message  # <-- cambia qui

def test_make_message_without_attachment(tmp_path):
    msg = make_message(
        "me@example.com",
        "you@example.com",
        "Test",
        "<p>Hello</p>",
        None
    )
    raw = base64.urlsafe_b64decode(msg["raw"])
    parsed = email.message_from_bytes(raw)
    assert parsed["To"] == "you@example.com"
    assert parsed["From"] == "me@example.com"
    assert parsed["Subject"] == "Test"

def test_make_message_with_attachment(tmp_path):
    f = tmp_path / "allegato.txt"
    f.write_text("test data")
    msg = make_message(
        "a@example.com",
        "b@example.com",
        "Subject",
        "<p>Body</p>",
        str(f)
    )
    raw = base64.urlsafe_b64decode(msg["raw"])
    parsed = email.message_from_bytes(raw)
    parts = [p for p in parsed.walk() if p.get_content_maintype() != "multipart"]
    filenames = [p.get_filename() for p in parts if p.get_filename()]
    assert "allegato.txt" in filenames
