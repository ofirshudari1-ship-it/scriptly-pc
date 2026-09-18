"""חיבור אופציונלי לחשבון Google - כדי לשלוח משימה בודדת (רק הטקסט שלה, לא כל התמלול)
ל-Google Tasks או Google Calendar בלחיצת כפתור. הכל opt-in: שום דבר לא נשלח אוטומטית,
ושום דבר לא נשלח החוצה כלל אם הפיצ'ר לא הוגדר ב-Settings.

כדי להשתמש בזה המשתמש חייב ליצור OAuth Client ID (סוג Desktop app) ב-Google Cloud Console
ולהדביק את ה-Client ID / Client Secret בהגדרות - זה השלב היחיד שדורש פעולה מחוץ לתוכנה."""
from datetime import date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import APPDATA_DIR
from .logger import get_logger

logger = get_logger(__name__)

TOKEN_PATH = APPDATA_DIR / "google_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.events",
]


def is_configured(config: dict) -> bool:
    return bool(config.get("google_client_id", "").strip()) and bool(config.get("google_client_secret", "").strip())


def is_connected() -> bool:
    return TOKEN_PATH.exists()


def disconnect() -> None:
    TOKEN_PATH.unlink(missing_ok=True)


def _client_config(config: dict) -> dict:
    return {
        "installed": {
            "client_id": config["google_client_id"].strip(),
            "client_secret": config["google_client_secret"].strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def get_credentials(config: dict) -> Credentials:
    """Credentials תקפים - מהקאש המקומי, מרוענן אם פג תוקף, או זרימת התחברות חדשה (פותחת דפדפן)."""
    creds = None
    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except (ValueError, OSError):
            creds = None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_config(_client_config(config), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def connect(config: dict) -> None:
    """מפעיל את זרימת ההתחברות (חוסם עד שהמשתמש מאשר בדפדפן) - קרא מ-thread נפרד."""
    get_credentials(config)


def send_task_to_google_tasks(text: str, config: dict) -> None:
    creds = get_credentials(config)
    service = build("tasks", "v1", credentials=creds)
    service.tasks().insert(tasklist="@default", body={"title": text}).execute()


def send_task_to_calendar(text: str, config: dict) -> None:
    creds = get_credentials(config)
    service = build("calendar", "v3", credentials=creds)
    today = date.today().isoformat()
    service.events().insert(
        calendarId="primary",
        body={"summary": text, "start": {"date": today}, "end": {"date": today}},
    ).execute()
