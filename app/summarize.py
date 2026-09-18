"""הפקת סיכום + משימות מתוך תמלול, באמצעות מודל שפה מקומי דרך Ollama (ללא ענן).

כולל הגנה מפני "המצאת" סיכום כשהתמלול קצר מדי / לא מכיל תוכן אמיתי
(למשל בדיקת מיקרופון: "בדיקה בדיקה 1 2 3"), וגם פיצול לקטעים (chunking) לפגישות
ארוכות מאוד שעלולות לחרוג מחלון ההקשר של המודל."""
import requests

from .i18n import t
from .logger import get_logger

logger = get_logger(__name__)

MIN_WORDS_FOR_SUMMARY = 12
MAX_WORDS_PER_CHUNK = 3000
NO_CONTENT_MARKER = "NO_REAL_CONTENT"

SYSTEM_PROMPT = """אתה עוזר שמסכם פגישות עסקיות בעברית עבור צוות מכירות/שירות.
קיבלת תמלול גולמי של שיחה או פגישה. ייתכן שהתמלול מכיל שגיאות תמלול קלות - התעלם מהן והתמקד בתוכן.

אם התמלול קצר מדי, לא מכיל שיחה עסקית אמיתית, או נראה כמו בדיקת מיקרופון/סאונד גרידא
(למשל חזרות על מילים כמו "בדיקה", "טסט", ספירת מספרים, או משפט בודד ללא הקשר עסקי) -
אסור לך בשום אופן להמציא פגישה, החלטות או משימות שלא נאמרו בפועל.
במקרה כזה החזר אך ורק את המילה הבאה ותו לא, בלי שום טקסט נוסף: NO_REAL_CONTENT

אחרת, הפק פלט בפורמט Markdown עם הכותרות הבאות בדיוק:

## תקציר
פסקה קצרה (2-4 משפטים) שמסכמת על מה דיברו ומה הוחלט.

## נקודות מרכזיות
רשימת תבליטים של הנושאים והנקודות החשובות שעלו.

## משימות ומעקב
רשימת תבליטים של כל משימה/מטלה/הבטחה שעלתה בשיחה. לכל משימה ציין (אם ידוע מהתמלול):
- מה יש לעשות
- מי אחראי
- עד מתי (אם צוין תאריך/מסגרת זמן)
אם לא עלו משימות כלל, כתוב "לא זוהו משימות בשיחה זו".

כתוב הכל בעברית תקנית וברורה. אל תמציא מידע שלא נאמר בתמלול."""

CHUNK_SYSTEM_PROMPT = """אתה עוזר שמנתח קטע אחד מתוך תמלול ארוך יותר של פגישה עסקית בעברית.
זהו רק חלק מתוך שיחה ארוכה יותר - אל תתייחס אליו כאילו הוא כל הפגישה, ואל תכתוב "תקציר פגישה" מלא.
החזר רשימת תבליטים קצרה בעברית: נקודות מרכזיות שעלו בקטע הזה, ומשימות/החלטות/הבטחות שהוזכרו
(עם מי אחראי ועד מתי, אם צוין). אל תמציא מידע שלא נאמר. אם הקטע לא מכיל תוכן משמעותי, החזר שורה אחת:
"אין תוכן משמעותי בקטע זה."."""

ROLLUP_SYSTEM_PROMPT = """קיבלת רשימות הערות שחולצו בנפרד מקטעים עוקבים של פגישה עסקית ארוכה אחת בעברית.
מזג את כל ההערות לסיכום קוהרנטי אחד של הפגישה כולה, בפורמט Markdown עם הכותרות הבאות בדיוק:

## תקציר
פסקה קצרה (2-4 משפטים) שמסכמת על מה דיברו ומה הוחלט לאורך כל הפגישה.

## נקודות מרכזיות
רשימת תבליטים של הנושאים והנקודות החשובות, ממוזגות מכל הקטעים (בלי כפילויות).

## משימות ומעקב
רשימת תבליטים של כל המשימות שעלו לאורך הפגישה (מי אחראי, עד מתי - אם ידוע). מזג משימות
כפולות שחוזרות בכמה קטעים. אם לא עלו משימות כלל, כתוב "לא זוהו משימות בשיחה זו".

אל תמציא מידע שלא מופיע בהערות שקיבלת."""


def _no_content_message() -> str:
    return (
        f"## {t('summary_no_content_title')}\n"
        f"{t('summary_no_content_body')}\n\n"
        f"## {t('key_points_header')}\n\n"
        f"## {t('tasks_header')}\n"
        f"{t('summary_no_tasks')}"
    )


def _error_message() -> str:
    return (
        f"## {t('summary_error_title')}\n"
        f"{t('summary_error_body')}\n\n"
        f"## {t('key_points_header')}\n\n"
        f"## {t('tasks_header')}\n"
        f"{t('summary_error_tasks')}"
    )


def _call_ollama(prompt: str, ollama_model: str, ollama_url: str) -> str:
    resp = requests.post(
        f"{ollama_url}/api/generate",
        json={"model": ollama_model, "prompt": prompt, "stream": False},
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _split_into_chunks(transcript: str, max_words: int) -> list:
    """מפצל תמלול ארוך לקטעים, על גבולות שורה (כדי לא לחתוך משפט/דובר באמצע)."""
    lines = transcript.splitlines()
    chunks, current, count = [], [], 0
    for line in lines:
        words_in_line = len(line.split())
        if count + words_in_line > max_words and current:
            chunks.append("\n".join(current))
            current, count = [], 0
        current.append(line)
        count += words_in_line
    if current:
        chunks.append("\n".join(current))
    return chunks or [transcript]


def _summarize_long_transcript(transcript: str, ollama_model: str, ollama_url: str) -> str:
    chunks = _split_into_chunks(transcript, MAX_WORDS_PER_CHUNK)
    logger.info("long transcript (%d words) - summarizing in %d chunks", len(transcript.split()), len(chunks))
    notes = []
    for i, chunk in enumerate(chunks, 1):
        prompt = f"{CHUNK_SYSTEM_PROMPT}\n\n--- קטע {i}/{len(chunks)} ---\n{chunk}\n--- סוף הקטע ---"
        notes.append(f"[קטע {i}/{len(chunks)}]\n{_call_ollama(prompt, ollama_model, ollama_url)}")
    combined_notes = "\n\n".join(notes)
    prompt = f"{ROLLUP_SYSTEM_PROMPT}\n\n--- הערות מהקטעים ---\n{combined_notes}\n--- סוף ההערות ---"
    return _call_ollama(prompt, ollama_model, ollama_url)


TITLE_SYSTEM_PROMPT = """קיבלת סיכום של פגישה או שיחה עסקית בעברית. תן לה כותרת קצרה שתעזור לזהות אותה
ברשימה מבין הקלטות אחרות - 2 עד 5 מילים, כמו כותרת אימייל. ציין את סוג השיחה ואת מי שמעורב אם ידוע
(למשל "שיחת חידוש עם דנה", "בירור תמיכה - בעיית חיוב", "פגישת צוות שבועית").
החזר את הכותרת בלבד, בלי מרכאות, בלי נקודה בסוף, בלי שום טקסט נוסף."""


TONE_SYSTEM_PROMPT = """קיבלת סיכום של פגישה או שיחה עסקית בעברית. סווג את הטון הכללי של השיחה
למילה אחת בדיוק מתוך הרשימה הבאה (ותו לא, בלי הסבר):
positive - שיחה חיובית, ידידותית, הסתיימה בהסכמה או שביעות רצון
neutral - שיחה עניינית/רגילה, בלי טון בולט לכאן או לכאן
tense - שיחה עם מתח, אי הסכמה, תלונה, או חוסר שביעות רצון

החזר אך ורק אחת מהמילים: positive / neutral / tense"""


TAGS_SYSTEM_PROMPT = """קיבלת סיכום של פגישה או שיחה עסקית בעברית. הצע 2 עד 4 תגיות נושא קצרות
שיעזרו לסווג ולחפש את ההקלטה הזו מול הקלטות אחרות (כמו תגיות בדואר אלקטרוני) - נושא כללי
(למשל "חיוב", "חידוש מנוי", "תמיכה טכנית", "מכירות", "צוות"), לא שמות אנשים ולא תאריכים.
מילה אחת או שתיים לכל תגית, בעברית, בלי סולמית (#) ובלי מרכאות.
החזר רשימה מופרדת בפסיקים בלבד, בלי שום טקסט נוסף, למשל: חיוב, חידוש מנוי"""


def generate_tone(summary: str, ollama_model: str, ollama_url: str) -> str:
    """מתייג טון כללי לשיחה (positive/neutral/tense) על בסיס הסיכום, לצורך תובנות מצטברות."""
    try:
        prompt = f"{TONE_SYSTEM_PROMPT}\n\n--- סיכום ---\n{summary}\n--- סוף הסיכום ---"
        raw = _call_ollama(prompt, ollama_model, ollama_url).strip().lower()
        for candidate in ("positive", "neutral", "tense"):
            if candidate in raw:
                return candidate
        return ""
    except Exception as exc:
        logger.warning("tone generation failed: %s", exc)
        return ""


def generate_tags(summary: str, ollama_model: str, ollama_url: str) -> list:
    """מציע 2-4 תגיות נושא קצרות אוטומטית, על בסיס הסיכום - כדי שהקלטות יסווגו וייחפשו
    גם בלי שהמשתמש יטרח להוסיף תגיות ידנית (נקרא רק אם עדיין אין תגיות ידניות, ראו controller.py)."""
    try:
        prompt = f"{TAGS_SYSTEM_PROMPT}\n\n--- סיכום ---\n{summary}\n--- סוף הסיכום ---"
        raw = _call_ollama(prompt, ollama_model, ollama_url)
        tags = []
        for part in raw.replace("\n", ",").split(","):
            tag = part.strip().strip("#").strip().strip('"').strip("'").strip()
            if tag and len(tag) <= 30 and tag not in tags:
                tags.append(tag)
        return tags[:4]
    except Exception as exc:
        logger.warning("tag generation failed: %s", exc)
        return []


def generate_title(summary: str, ollama_model: str, ollama_url: str) -> str:
    """כותרת קצרה שנוצרת אוטומטית מהסיכום, כדי שרשימת ההקלטות תהיה קריאה יותר מסתם תאריך/שעה."""
    try:
        prompt = f"{TITLE_SYSTEM_PROMPT}\n\n--- סיכום ---\n{summary}\n--- סוף הסיכום ---"
        title = _call_ollama(prompt, ollama_model, ollama_url)
        title = title.strip().strip('"').strip("'").strip()
        if len(title) > 60:
            title = title[:60].rsplit(" ", 1)[0]
        return title
    except Exception as exc:
        logger.warning("title generation failed: %s", exc)
        return ""


def summarize(transcript: str, ollama_model: str, ollama_url: str) -> str:
    if not transcript.strip() or len(transcript.split()) < MIN_WORDS_FOR_SUMMARY:
        return _no_content_message()

    try:
        if len(transcript.split()) > MAX_WORDS_PER_CHUNK:
            result = _summarize_long_transcript(transcript, ollama_model, ollama_url)
        else:
            prompt = f"{SYSTEM_PROMPT}\n\n--- תמלול השיחה ---\n{transcript}\n--- סוף התמלול ---"
            result = _call_ollama(prompt, ollama_model, ollama_url)
        if not result or NO_CONTENT_MARKER in result:
            return _no_content_message()
        return result
    except Exception as exc:
        logger.error("summarization failed: %s", exc)
        return _error_message()
