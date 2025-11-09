import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES_SHEETS = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

def get_sheets_service(creds_dir: str):
    os.makedirs(creds_dir, exist_ok=True)
    token_path = os.path.join(creds_dir, "token_sheets.json")
    creds_path = os.path.join(creds_dir, "credentials.json")
    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"credentials.json non trovato in {creds_dir}")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES_SHEETS)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES_SHEETS)
            creds = flow.run_console()
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("sheets", "v4", credentials=creds)
