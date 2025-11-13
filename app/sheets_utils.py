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
            creds = _run_headless_flow(flow)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("sheets", "v4", credentials=creds)


def _run_headless_flow(flow: InstalledAppFlow):
    """Replica run_console mostrando URL + codice per ambienti headless."""
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    print("== Google OAuth (Sheets) ==")
    print("1) Apri questo URL in un browser e autorizza l'accesso:")
    print(auth_url)
    print("2) Copia il codice mostrato e incollalo qui sotto.")
    code = input("Codice di verifica: ").strip()
    flow.fetch_token(code=code)
    return flow.credentials
