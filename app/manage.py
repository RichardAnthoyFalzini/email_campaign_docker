#!/usr/bin/env python3
import argparse, os, csv, time, uuid, json, random
from datetime import datetime
from typing import Dict, Any
from jinja2 import Template
import yaml
import pandas as pd

from gmail_utils import get_service, ensure_label, add_labels, search_messages, get_thread
from sheets_utils import get_sheets_service
from googleapiclient.errors import HttpError

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("DATA_ROOT", "/data")
CREDS_ROOT = os.environ.get("CREDS_ROOT", "/creds")
CAMPAIGNS_DIR = os.path.join(DATA_ROOT, "campaigns")
STATE_FILENAME = "state.json"
DEFAULT_JITTER_RATIO = 0.3


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def log_event(level: str, event: str, **fields: Any) -> None:
    """Stampa log strutturati JSON (stdout) per facile ingest."""
    payload = {
        "ts": _utc_now(),
        "level": level.upper(),
        "event": event,
    }
    if fields:
        payload["data"] = fields
    print(json.dumps(payload, ensure_ascii=False))


def _extract_status_code(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from googleapiclient errors."""
    if isinstance(exc, HttpError):
        if getattr(exc, "status_code", None):
            return exc.status_code
        resp = getattr(exc, "resp", None)
        if resp and getattr(resp, "status", None):
            return resp.status
    return getattr(exc, "status", None)


def _is_retryable_exception(exc: Exception) -> bool:
    status = _extract_status_code(exc)
    if status is not None:
        return status == 429 or 500 <= status < 600
    return isinstance(exc, (TimeoutError, ConnectionError))


def _sleep_with_jitter(base_seconds: float) -> None:
    jitter = base_seconds * DEFAULT_JITTER_RATIO
    time.sleep(base_seconds + random.uniform(0, jitter))


def _send_with_backoff(service, msg_body: Dict[str, Any], max_attempts: int, initial_delay: float,
                       multiplier: float, max_delay: float):
    """Invia il messaggio Gmail con retry exponential backoff."""
    attempt = 1
    current_delay = max(initial_delay, 1.0)
    max_delay = max(max_delay, current_delay)

    while attempt <= max_attempts:
        try:
            request = service.users().messages().send(userId="me", body=msg_body)
            return request.execute()
        except Exception as exc:
            if not _is_retryable_exception(exc) or attempt == max_attempts:
                raise
            sleep_for = min(current_delay, max_delay)
            log_event(
                "warning",
                "send_retry_scheduled",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(exc),
                sleep_seconds=round(sleep_for, 2),
            )
            _sleep_with_jitter(sleep_for)
            current_delay = min(current_delay * max(multiplier, 1.0), max_delay)
            attempt += 1

def load_config(campaign: str) -> Dict[str, Any]:
    cfg_path = os.path.join(CAMPAIGNS_DIR, campaign, "campaign_config.yaml")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"Config non trovato: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def render_template(tpl_path: str, ctx: Dict[str, Any]) -> str:
    with open(tpl_path, "r", encoding="utf-8") as f:
        tpl = Template(f.read())
    return tpl.render(**ctx)

def make_message(sender: str, to: str, subject: str, html_body: str, attachment_path: str | None):
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders
    import base64, os

    msg = MIMEMultipart()
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    if attachment_path:
        attachment_path = attachment_path.strip()
        if attachment_path and os.path.exists(attachment_path):
            part = MIMEBase("application", "octet-stream")
            with open(attachment_path, "rb") as f:
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(attachment_path)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)
        else:
            log_event("warning", "attachment_missing", attachment_path=attachment_path)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}

def load_send_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_send_state(path: str, state: Dict[str, Any]) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

def cmd_send(args):
    campaign = args.campaign
    cfg = load_config(campaign)

    creds_dir = os.path.join(CREDS_ROOT, cfg.get("account_name", "default"))
    service = get_service(creds_dir)

    from_email = cfg.get("send_as_email") or cfg["from_email"]
    subject_tpl = cfg.get("subject", "Campagna")
    label_name = cfg.get("label_for_sent") or f"campaign/{campaign}"
    label_id = ensure_label(service, label_name)

    recipients_csv = os.path.join(CAMPAIGNS_DIR, campaign, "recipients.csv")
    template_html = os.path.join(CAMPAIGNS_DIR, campaign, "template.html")

    track_opens = bool(cfg.get("track_opens", False))
    tracking_base = (cfg.get("tracking_base_url") or "").rstrip("/")
    unsubscribe_base = (cfg.get("unsubscribe_base_url") or "").rstrip("/")
    unsubscribe_enabled = bool(cfg.get("unsubscribe_enabled", False))

    daily_limit = int(cfg.get("daily_send_limit", 100))
    delay = int(cfg.get("delay_between_emails_seconds", 10))
    batch_size = int(cfg.get("batch_size", daily_limit))
    pause_between = int(cfg.get("pause_between_batches_seconds", 0))

    max_retry_attempts = int(cfg.get("max_retry_attempts", 3))
    retry_backoff_initial = float(cfg.get("retry_backoff_initial_seconds", 5))
    retry_backoff_multiplier = float(cfg.get("retry_backoff_multiplier", 2))
    retry_backoff_max = float(cfg.get("retry_backoff_max_seconds", 60))
    max_attempts_per_contact = int(cfg.get("max_attempts_per_contact", 5))
    global_error_threshold = int(cfg.get("global_error_threshold_for_cooldown", 5))
    global_error_cooldown = int(cfg.get("global_error_cooldown_seconds", 120))

    logs_dir = os.path.join(DATA_ROOT, "logs", campaign)
    os.makedirs(logs_dir, exist_ok=True)
    sent_log_path = os.path.join(logs_dir, "sent_log.csv")
    sent_threads_path = os.path.join(logs_dir, "sent_threads.csv")
    state_path = os.path.join(logs_dir, STATE_FILENAME)
    send_state = load_send_state(state_path)

    total_recipients = 0
    if os.path.exists(recipients_csv):
        with open(recipients_csv, newline="", encoding="utf-8") as csvfile:
            total_recipients = sum(1 for _ in csv.DictReader(csvfile))

    log_event(
        "info",
        "campaign_send_start",
        campaign=campaign,
        total_recipients=total_recipients,
        daily_limit=daily_limit,
        delay_seconds=delay,
        batch_size=batch_size,
    )

    sent_set = set()
    if os.path.exists(sent_log_path):
        with open(sent_log_path, "r", encoding="utf-8") as f:
            for line in f:
                sent_set.add(line.strip())

    sent_today = 0
    batch_counter = 0
    consecutive_errors = 0
    skipped_by_attempts = 0
    success_count = 0
    error_count = 0

    sent_threads = []
    if os.path.exists(sent_threads_path):
        with open(sent_threads_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            sent_threads = list(reader)

    with open(recipients_csv, newline="", encoding="utf-8") as csvfile, \
         open(sent_log_path, "a", encoding="utf-8") as logf:
        reader = csv.DictReader(csvfile)
        for row in reader:
            email = row.get("email", "").strip()
            if not email:
                continue

            state_entry = send_state.get(email)
            if not state_entry:
                send_state[email] = {"status": "pending", "attempts": 0}
            else:
                if state_entry.get("status") == "sent":
                    continue
                if state_entry.get("status") == "sending":
                    # Riporta a pending dopo crash
                    state_entry["status"] = "pending"

            if email in sent_set:
                continue

            entry = send_state[email]
            attempts_done = entry.get("attempts", 0)
            if entry.get("status") == "error" and attempts_done >= max_attempts_per_contact:
                log_event(
                    "warning",
                    "max_attempts_reached",
                    email=email,
                    attempts=attempts_done,
                    max_attempts=max_attempts_per_contact,
                )
                skipped_by_attempts += 1
                continue

            tracking_id = str(uuid.uuid4())
            tracking_pixel_url = ""
            if track_opens and tracking_base:
                # Apps Script: assumiamo che tracking_base contenga .../exec?mode=pixel
                tracking_pixel_url = f"{tracking_base}&cid={campaign}&to={email}"

            unsubscribe_url = ""
            if unsubscribe_enabled and unsubscribe_base:
                unsubscribe_url = f"{unsubscribe_base}&email={email}"

            ctx = {**row, "tracking_pixel_url": tracking_pixel_url, "unsubscribe_url": unsubscribe_url, "email": email}
            html_body = render_template(template_html, ctx)
            subject = Template(subject_tpl).render(**row)

            attachment_path = row.get("attachment_path", "").strip() or None
            if attachment_path and not os.path.isabs(attachment_path):
                attachment_path = os.path.join(DATA_ROOT, attachment_path)

            msg = make_message(from_email, email, subject, html_body, attachment_path)

            ts_now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            entry = send_state[email]
            entry["status"] = "sending"
            entry["last_attempt"] = ts_now
            entry["attempts"] = entry.get("attempts", 0) + 1
            entry.pop("error", None)
            save_send_state(state_path, send_state)

            log_event(
                "info",
                "send_attempt",
                email=email,
                campaign=campaign,
                attempt=entry["attempts"],
            )

            try:
                sent = _send_with_backoff(
                    service,
                    msg,
                    max_retry_attempts,
                    retry_backoff_initial,
                    retry_backoff_multiplier,
                    retry_backoff_max,
                )
            except Exception as exc:
                entry["status"] = "error"
                entry["error"] = str(exc)
                entry["last_error_ts"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                save_send_state(state_path, send_state)
                log_event(
                    "error",
                    "send_failed",
                    email=email,
                    campaign=campaign,
                    error=str(exc),
                    attempts=entry["attempts"],
                )
                error_count += 1
                consecutive_errors += 1
                if global_error_threshold > 0 and consecutive_errors >= global_error_threshold:
                    if global_error_cooldown > 0:
                        log_event(
                            "warning",
                            "global_cooldown",
                            consecutive_errors=consecutive_errors,
                            cooldown_seconds=global_error_cooldown,
                        )
                    time.sleep(global_error_cooldown)
                consecutive_errors = 0
                continue
            consecutive_errors = 0
            success_count += 1

            msg_id = sent.get("id")
            thread_id = sent.get("threadId")

            if label_id and msg_id:
                try:
                    add_labels(service, msg_id, [label_id])
                except Exception as e:
                    log_event(
                        "warning",
                        "label_apply_failed",
                        email=email,
                        label=label_name,
                        error=str(e),
                    )

            logf.write(email + "\n")
            logf.flush()
            sent_set.add(email)

            sent_threads.append({"email": email, "threadId": thread_id})
            with open(sent_threads_path, "w", encoding="utf-8", newline="") as tf:
                writer = csv.DictWriter(tf, fieldnames=["email", "threadId"])
                writer.writeheader()
                writer.writerows(sent_threads)

            entry["status"] = "sent"
            entry["message_id"] = msg_id
            entry["thread_id"] = thread_id
            entry["last_success_ts"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            save_send_state(state_path, send_state)

            log_event(
                "info",
                "send_success",
                email=email,
                campaign=campaign,
                message_id=msg_id,
                thread_id=thread_id,
                attempt=entry["attempts"],
            )

            sent_today += 1
            batch_counter += 1
            if sent_today >= daily_limit:
                log_event(
                    "info",
                    "daily_limit_reached",
                    campaign=campaign,
                    daily_limit=daily_limit,
                )
                break
            time.sleep(delay)
            if batch_counter >= batch_size:
                batch_counter = 0
                if pause_between > 0:
                    log_event(
                        "info",
                        "batch_pause",
                        campaign=campaign,
                        pause_seconds=pause_between,
                    )
                    time.sleep(pause_between)

    log_event(
        "info",
        "campaign_send_complete",
        campaign=campaign,
        sent=success_count,
        errors=error_count,
        skipped=skipped_by_attempts,
    )

def cmd_list(args):
    root = CAMPAIGNS_DIR
    if not os.path.isdir(root):
        print("Nessuna campagna trovata.")
        return
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            print(name)

def cmd_check_bounces(args):
    campaign = args.campaign
    cfg = load_config(campaign)
    creds_dir = os.path.join(CREDS_ROOT, cfg.get("account_name", "default"))
    service = get_service(creds_dir)

    bounce_label = cfg.get("bounce_label", f"campaign/{campaign}/bounce")
    query = f'label:"{bounce_label}" newer_than:30d'
    msgs = search_messages(service, query=query, max_results=500)

    logs_dir = os.path.join(DATA_ROOT, "logs", campaign)
    os.makedirs(logs_dir, exist_ok=True)
    bounces_csv = os.path.join(logs_dir, "bounces.csv")

    import re, base64
    rows = []
    for m in msgs:
        full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        payload = full.get("payload", {})
        parts = payload.get("parts", []) or []
        bodies = []
        if "body" in payload and payload["body"].get("data"):
            bodies.append(base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="ignore"))
        for p in parts:
            if p.get("mimeType", "").startswith("text/"):
                data = p.get("body", {}).get("data")
                if data:
                    bodies.append(base64.urlsafe_b64decode(data).decode(errors="ignore"))
        text = "\n".join(bodies)
        m_emails = re.findall(r"[Ff]inal-Recipient:\s*rfc822;\s*([^\s]+)", text)
        if m_emails:
            rows.append({"bounced_email": m_emails[0]})
    with open(bounces_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bounced_email"])
        w.writeheader()
        w.writerows(rows)
    print(f"Salvati bounce in {bounces_csv} ({len(rows)} trovati)")

def cmd_check_replies(args):
    campaign = args.campaign
    cfg = load_config(campaign)
    creds_dir = os.path.join(CREDS_ROOT, cfg.get("account_name", "default"))
    service = get_service(creds_dir)

    logs_dir = os.path.join(DATA_ROOT, "logs", campaign)
    sent_threads_path = os.path.join(logs_dir, "sent_threads.csv")
    if not os.path.exists(sent_threads_path):
        print("Nessun sent_threads.csv: invia prima la campagna.")
        return

    df = pd.read_csv(sent_threads_path)
    replies = []
    profile = service.users().getProfile(userId="me").execute()
    my_email = profile.get("emailAddress", "").lower()

    for _, row in df.iterrows():
        thread_id = str(row["threadId"])
        email = row["email"]
        th = get_thread(service, thread_id)
        messages = th.get("messages", [])
        someone_else = False
        for msg in messages[1:]:
            headers = msg.get("payload", {}).get("headers", [])
            frm = next((h["value"] for h in headers if h.get("name")=="From"), "")
            if my_email not in frm.lower():
                someone_else = True
                break
        if someone_else:
            replies.append({"email": email, "replied": True})
    replies_csv = os.path.join(logs_dir, "replies.csv")
    pd.DataFrame(replies).to_csv(replies_csv, index=False)
    print(f"Salvate risposte in {replies_csv} ({len(replies)} trovate)")

def cmd_fetch_opens(args):
    campaign = args.campaign
    cfg = load_config(campaign)
    creds_dir = os.path.join(CREDS_ROOT, cfg.get("account_name", "default"))
    service = get_sheets_service(creds_dir)

    sheet_id = cfg.get("sheet_id")
    sheet_name = cfg.get("sheet_opens_name", "opens")
    if not sheet_id:
        print("sheet_id non configurato in campaign_config.yaml")
        return

    rng = f"{sheet_name}!A:E"  # ts,cid,to,ua,ip
    resp = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute()
    values = resp.get("values", [])

    logs_dir = os.path.join(os.environ.get("DATA_ROOT", "/data"), "logs", campaign)
    os.makedirs(logs_dir, exist_ok=True)
    out_csv = os.path.join(logs_dir, "opens.csv")

    import csv
    if not values:
        print("Nessun dato di open trovato.")
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f); w.writerow(["ts","cid","to","ua","ip"])
        return

    header = values[0]
    rows = values[1:]
    target_header = ["ts","cid","to","ua","ip"]
    index_map = {name: (header.index(name) if name in header else i) for i, name in enumerate(target_header)}
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(target_header)
        for r in rows:
            out = []
            for k in target_header:
                idx = index_map[k]
                out.append(r[idx] if idx < len(r) else "")
            w.writerow(out)
    print(f"Open salvati in {out_csv} ({len(rows)} righe)")

def cmd_stats(args):
    campaign = args.campaign
    logs_dir = os.path.join(DATA_ROOT, "logs", campaign)
    sent_log = os.path.join(logs_dir, "sent_log.csv")
    b_csv = os.path.join(logs_dir, "bounces.csv")
    r_csv = os.path.join(logs_dir, "replies.csv")
    o_csv = os.path.join(logs_dir, "opens.csv")

    import csv
    sent = []
    if os.path.exists(sent_log):
        with open(sent_log, "r", encoding="utf-8") as f:
            sent = [line.strip() for line in f if line.strip()]

    bounces = set()
    if os.path.exists(b_csv):
        with open(b_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                bounces.add(r["bounced_email"].strip().lower())

    replies = set()
    if os.path.exists(r_csv):
        with open(r_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                replies.add(r["email"].strip().lower())

    opens = set()
    if os.path.exists(o_csv):
        with open(o_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                to = r.get("to","").strip().lower()
                if to:
                    opens.add(to)

    rows = []
    for e in sent:
        rows.append({
            "email": e,
            "sent": True,
            "bounced": e.lower() in bounces,
            "replied": e.lower() in replies,
            "opened": e.lower() in opens,
        })
    out_csv = os.path.join(logs_dir, "stats.csv")
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"Creato {out_csv}")
    if args.print:
        print(df.head(30).to_string(index=False))

def main():
    p = argparse.ArgumentParser(description="Email Campaign Manager (Docker)")
    sub = p.add_subparsers()

    s1 = sub.add_parser("send", help="Invia una campagna")
    s1.add_argument("--campaign", required=True)
    s1.set_defaults(func=cmd_send)

    s2 = sub.add_parser("list", help="Elenca campagne")
    s2.set_defaults(func=cmd_list)

    s3 = sub.add_parser("check-bounces", help="Legge i bounce (via filtro/etichetta)")
    s3.add_argument("--campaign", required=True)
    s3.set_defaults(func=cmd_check_bounces)

    s4 = sub.add_parser("check-replies", help="Legge risposte")
    s4.add_argument("--campaign", required=True)
    s4.set_defaults(func=cmd_check_replies)

    s5 = sub.add_parser("fetch-opens", help="Scarica gli open da Google Sheets")
    s5.add_argument("--campaign", required=True)
    s5.set_defaults(func=cmd_fetch_opens)

    s6 = sub.add_parser("stats", help="Crea stats.csv unendo sent/bounces/replies/opens")
    s6.add_argument("--campaign", required=True)
    s6.add_argument("--print", action="store_true")
    s6.set_defaults(func=cmd_stats)

    args = p.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
