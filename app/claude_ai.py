"""ניתוח פגישה מלא דרך Claude (Anthropic Messages API) - אופציונלי, כבוי כברירת מחדל.

קריאה אחת מחזירה הכל במבנה מוגדר: תקציר, סוג פגישה, מסקנות והחלטות, משימות, תוצאות,
טיפים והמלצות, שאלות פתוחות, טון ותגיות. התמלול עצמו (אודיו->טקסט) נשאר תמיד מקומי;
רק טקסט התמלול נשלח ל-Anthropic, ורק אם המשתמש הפעיל והסכים במפורש בהגדרות.
כל כשל (אין מפתח / אין רשת / שגיאת API) מחזיר None והקורא נופל חזרה ל-Ollama המקומי."""
import os
import time

import requests

from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
MODELS = ["claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5"]
# ~ מעל זה נשארים עם הנתיב המקומי המפוצל במקום לשלוח הכל בבקשה אחת
MAX_WORDS_SINGLE_CALL = 60000

MEETING_TYPES = [
    "sales_call", "support_call", "team_sync", "planning", "client_meeting",
    "one_on_one", "interview", "brainstorm", "negotiation", "training", "other",
]
TONES = ["positive", "neutral", "tense"]

_TOOL_NAME = "record_meeting_analysis"
_TOOL = {
    "name": _TOOL_NAME,
    "description": "Record the structured analysis of the meeting transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "no_real_content": {
                "type": "boolean",
                "description": "True only if the transcript is too short / a mic test / has no real conversation. Then leave everything else empty.",
            },
            "title": {"type": "string", "description": "2-5 word title, e.g. 'Renewal call - Dana'."},
            "meeting_type": {"type": "string", "enum": MEETING_TYPES},
            "tone": {"type": "string", "enum": TONES},
            "tldr": {"type": "string", "description": "2-4 sentence summary: what was discussed and what was decided."},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "decisions": {
                "type": "array", "items": {"type": "string"},
                "description": "Conclusions and decisions actually reached.",
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "owner": {"type": "string", "description": "Empty if not stated."},
                        "due": {"type": "string", "description": "Empty if not stated."},
                    },
                    "required": ["task"],
                },
            },
            "results": {
                "type": "array", "items": {"type": "string"},
                "description": "Outcomes/results/numbers/agreements achieved in the meeting.",
            },
            "tips": {
                "type": "array", "items": {"type": "string"},
                "description": "Practical recommendations / coaching tips for the user's next step, grounded in what was said.",
            },
            "open_questions": {
                "type": "array", "items": {"type": "string"},
                "description": "Unresolved questions or risks that need follow-up.",
            },
            "tags": {"type": "array", "items": {"type": "string"}, "description": "2-4 short topic tags, no names/dates."},
        },
        "required": ["no_real_content"],
    },
}

_SYSTEM = (
    "You analyze a raw transcript of a business meeting or call (often Hebrew, may contain "
    "transcription errors - ignore them and focus on content; speaker labels may be present). "
    "Write every text field in the SAME LANGUAGE as the transcript. Never invent facts, decisions, "
    "tasks, owners or dates that were not said. If the transcript is a mic test or has no real "
    "conversation, set no_real_content=true and leave the rest empty. Tips must be concrete and "
    "tied to the conversation, not generic advice."
)


def get_api_key(config: dict) -> str:
    return (config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def is_enabled(config: dict) -> bool:
    return config.get("ai_provider") == "claude" and bool(get_api_key(config))


def _post(config: dict, payload: dict) -> dict:
    headers = {
        "x-api-key": get_api_key(config),
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    last_exc = None
    for attempt in range(2):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=180)
            if resp.status_code in (429, 500, 502, 503, 529) and attempt == 0:
                time.sleep(3)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(2)
    raise last_exc


def test_connection(config: dict) -> tuple:
    """(ok, message) - קריאה זעירה לבדיקת מפתח/רשת מתוך מסך ההגדרות."""
    if not get_api_key(config):
        return False, t("claude_status_no_key")
    try:
        _post(config, {
            "model": config.get("claude_model") or DEFAULT_MODEL,
            "max_tokens": 8,
            "messages": [{"role": "user", "content": "ping"}],
        })
        return True, t("claude_status_ok")
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code in (401, 403):
            return False, t("claude_status_bad_key")
        return False, t("claude_status_failed", code=code)
    except Exception as exc:
        logger.warning("claude connection test failed: %s", exc)
        return False, t("claude_status_network")


def analyze(transcript: str, config: dict):
    """מחזיר dict לפי הסכמה, או None אם כבוי/נכשל (הקורא ימשיך ל-Ollama)."""
    if not is_enabled(config):
        return None
    if len(transcript.split()) > MAX_WORDS_SINGLE_CALL:
        logger.info("transcript too long for single Claude call - using local chunked path")
        return None
    try:
        data = _post(config, {
            "model": config.get("claude_model") or DEFAULT_MODEL,
            "max_tokens": 4096,
            "system": _SYSTEM,
            "tools": [_TOOL],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
            "messages": [{
                "role": "user",
                "content": f"<transcript>\n{transcript}\n</transcript>",
            }],
        })
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == _TOOL_NAME:
                return block.get("input") or {}
        logger.warning("claude response had no tool_use block")
    except Exception as exc:
        logger.warning("claude analysis failed - falling back to local model: %s", exc)
    return None


def _bullets(items) -> str:
    return "\n".join(f"- {s.strip()}" for s in items if isinstance(s, str) and s.strip())


def _task_line(item) -> str:
    if isinstance(item, str):
        return f"- {item.strip()}"
    parts = [str(item.get("task", "")).strip()]
    if item.get("owner"):
        parts.append(f"**{t('claude_owner')}:** {item['owner'].strip()}")
    if item.get("due"):
        parts.append(f"**{t('claude_due')}:** {item['due'].strip()}")
    return "- " + " | ".join(p for p in parts if p)


def to_markdown(a: dict) -> str:
    """ממיר את הניתוח ל-Markdown באותה מתכונת כמו הנתיב המקומי, עם כותרות נוספות. הכותרת
    של המשימות זהה ל-t('tasks_header') כדי ש-tasks.py ימשיך לחלץ אותן ללא שינוי."""
    mtype = a.get("meeting_type")
    if mtype not in MEETING_TYPES:
        mtype = "other"
    out = [f"## {t('ai_summary_header')}", a.get("tldr", "").strip()]
    out.append(f"\n**{t('meeting_type_label')}:** {t(f"meeting_type_{mtype}")}")
    sections = [
        ("key_points_header", _bullets(a.get("key_points", []))),
        ("ai_decisions_header", _bullets(a.get("decisions", []))),
        ("tasks_header", "\n".join(_task_line(x) for x in a.get("tasks", []) if x) or t("summary_no_tasks")),
        ("ai_results_header", _bullets(a.get("results", []))),
        ("ai_tips_header", _bullets(a.get("tips", []))),
        ("ai_open_header", _bullets(a.get("open_questions", []))),
    ]
    for key, body in sections:
        if body:
            out.append(f"\n## {t(key)}\n{body}")
    return "\n".join(out).strip()
