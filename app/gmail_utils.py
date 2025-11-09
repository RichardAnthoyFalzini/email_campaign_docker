import os
from typing import Any, Dict, List, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]

def get_service(creds_dir: str) -> Any:
    os.makedirs(creds_dir, exist_ok=True)
    token_path = os.path.join(creds_dir, "token.json")
    creds_path = os.path.join(creds_dir, "credentials.json")
    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"credentials.json non trovato in {creds_dir}")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            # Console flow (compatibile con container/headless)
            creds = flow.run_console()
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def ensure_label(service, label_name: str) -> Optional[str]:
    if not label_name:
        return None
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"].lower() == label_name.lower():
            return l["id"]
    body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    created = service.users().labels().create(userId="me", body=body).execute()
    return created["id"]

def add_labels(service, message_id: str, label_ids: List[str]) -> None:
    if not label_ids:
        return
    service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": label_ids}).execute()

def search_messages(service, query: str, max_results: int = 100):
    res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return res.get("messages", []) or []

def get_thread(service, thread_id: str):
    return service.users().threads().get(userId="me", id=thread_id, format="full").execute()
